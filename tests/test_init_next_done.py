"""The sequential driver (D1, driver 2): `init next` claims the next pending module and returns
its work item; `init done MODULE` checks the files written into its staging directory (SI-8)."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.init_fake_executor import write_docs
from tests.init_helpers import WORK, ok, shop, state, text


class DriverRepo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.template = shop(Path(cls._tmp.name).resolve(), name="template")
        ok(cls.template, "init", "fanout")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(dir=self._tmp.name))
        self.root = self.base / "shop"
        shutil.copytree(self.template, self.root, symlinks=True)

    def claim(self) -> dict:
        return ok(self.root, "init", "next")


class NextTest(DriverRepo):  # P5B-AC-005 (init next)
    def test_the_first_pending_module_in_name_order(self):
        data = self.claim()
        self.assertEqual(set(data), {"action", "item", "path", "counts"})
        self.assertEqual((data["item"]["module"], data["path"]),
                         ("cart", f"{WORK}/work/cart.json"))
        self.assertEqual(data["counts"], {"pending": 5, "running": 1, "done": 0, "failed": 0})
        self.assertEqual(state(self.root)["modules"]["cart"],
                         {"status": "running", "attempts": 1, "error": None})
        self.assertEqual(self.claim()["item"]["module"], "catalog")

    def test_text_output(self):
        code, out, err = text(self.root, "init", "next")
        self.assertEqual((code, err), (0, ""))
        item = json.loads((self.root / WORK / "work/cart.json").read_text())
        self.assertEqual(out, f"claimed       cart  (work item {WORK}/work/cart.json)\n"
                              + item["prompt"])


class DoneTest(DriverRepo):  # P5B-AC-005 (init done, the table)
    def setUp(self):
        super().setUp()
        self.claim()
        self.item = json.loads((self.root / WORK / "work/cart.json").read_text())
        self.staging = self.root / self.item["staging_dir"]

    def entry(self, **changes) -> None:
        path = self.staging / "entry.json"
        entry = json.loads(path.read_text())
        entry.update(changes)
        path.write_text(json.dumps({k: v for k, v in entry.items() if v is not None}))

    def outcome(self, change=None) -> tuple[int, list[str]]:
        shutil.rmtree(self.staging, ignore_errors=True)
        write_docs(self.root, self.item)
        if change:
            change()
        before = json.dumps(state(self.root)["modules"]["cart"])
        code, out, err = text(self.root, "init", "done", "cart", "--json")
        data = json.loads(out)["data"]
        lines = err.splitlines()
        if code == 1:
            self.assertEqual(json.dumps(state(self.root)["modules"]["cart"]), before)
            self.assertEqual(lines, [f"modsys: cart: {p}" for p in data["problems"]])
            self.assertEqual(data["status"], "running")
        return code, data["problems"]

    def test_the_table(self):
        twenty = "x" * 20
        rows = [
            (lambda: self.entry(description=twenty), []),
            (lambda: self.entry(description="y" * 200), []),
            (lambda: self.entry(description="y" * 19), ["description must be 20–200 characters"]),
            (lambda: self.entry(description="y" * 201), ["description must be 20–200 characters"]),
            (lambda: self.entry(keywords=["a", "b", "c", "d"]),
             ["at least 5 distinct keywords (a list of non-empty strings)"]),
            (lambda: self.entry(keywords=["a", "b", "c", "d", "d"]),
             ["at least 5 distinct keywords (a list of non-empty strings)"]),
            (lambda: (self.staging / "roles/qa.md").unlink(), ["missing roles/qa.md"]),
            (lambda: (self.staging / "MODULE.md").write_text("  \n\n "), ["MODULE.md is empty"]),
            (lambda: (self.staging / "MODULE.md").write_text("# ${title}\n"),
             ["MODULE.md: unfilled placeholder ${title}"]),
            (lambda: (self.staging / "notes.txt").write_text("n\n"),
             ["unexpected file notes.txt"]),
            (lambda: (self.staging / "entry.json").write_text("{not json"),
             ["entry.json: invalid JSON"]),
            (lambda: (self.staging / "entry.json").write_text("[]"), ["entry.json: not an object"]),
            (lambda: self.entry(status="active"), ["entry.json: unknown key 'status'"]),
            (lambda: self.entry(related_modules=[
                {"module": "nosuch", "relation": "depends-on", "description": "d"},
                {"module": "catalog", "relation": "uses", "description": "d"},
                {"module": "catalog", "relation": "depends-on"}]),
             ["related_modules[0]: 'nosuch' is not a confirmed module",
              "related_modules[1]: relation 'uses' is not in the relations (depends-on, "
              "complements, implemented-in, shares-contract, superseded-by)",
              "related_modules[2]: missing description"]),
        ]
        for change, problems in rows:
            with self.subTest(problems=problems):
                code, got = self.outcome(change)
                self.assertEqual((code, got), (1 if problems else 0, problems))
                if not problems:  # back to running for the next row
                    s = state(self.root)
                    s["modules"]["cart"]["status"] = "running"
                    (self.root / WORK / "state.json").write_text(json.dumps(s))
        code, got = self.outcome(lambda: self.entry(related_modules=[
            {"module": "catalog", "relation": "depends-on", "description": "imports the books"}]))
        self.assertEqual((code, got, state(self.root)["modules"]["cart"]["status"]),
                         (0, [], "done"))

    def test_several_problems_at_once_and_a_symlink(self):
        def change():
            (self.staging / "roles/po.md").unlink()
            (self.staging / "roles/po.md").symlink_to(self.staging / "MODULE.md")
            (self.staging / "roles/qa.md").unlink()
            self.entry(description="short", keywords=["one"])
        code, got = self.outcome(change)
        self.assertEqual((code, got), (1, [
            "missing roles/qa.md", "roles/po.md is a symlink (write the file itself)",
            "description must be 20–200 characters",
            "at least 5 distinct keywords (a list of non-empty strings)"]))


if __name__ == "__main__":
    unittest.main()
