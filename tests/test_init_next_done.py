"""The sequential driver (D1, driver 2): `init next` claims the next pending module and returns
its work item; `init done MODULE` checks the files written into its staging directory (SI-8)."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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

    def test_a_symlinked_staging_dir_is_refused(self):  # Task 5 review I1 (Work.clear)
        target = self.base / "elsewhere"
        target.mkdir()
        (target / "keep.md").write_text("keep\n")
        staging = self.root / WORK / "staging"
        staging.mkdir(parents=True, exist_ok=True)
        (staging / "cart").symlink_to(target)
        before = (self.root / WORK / "state.json").read_bytes()
        code, out, err = text(self.root, "init", "next", "--json")
        self.assertEqual((code, out), (2, ""))
        self.assertIn(f"{WORK}/staging/cart is a symlink — remove it (its target is left alone)",
                      err)
        self.assertEqual((target / "keep.md").read_text(), "keep\n")
        self.assertEqual((self.root / WORK / "state.json").read_bytes(), before)


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

    def test_the_text_of_a_check_with_problems(self):  # Task 5 review M1 (_render_done)
        write_docs(self.root, self.item)
        (self.staging / "roles/qa.md").unlink()
        self.entry(keywords=["one"])
        code, out, err = text(self.root, "init", "done", "cart")
        self.assertEqual((code, out), (1, "not done      cart (2 problem(s) on stderr)\n"))
        self.assertEqual(err.splitlines(), [
            "modsys: cart: missing roles/qa.md",
            "modsys: cart: at least 5 distinct keywords (a list of non-empty strings)"])

    def test_a_failed_item_that_still_has_problems(self):  # Task 5 review M2
        s = state(self.root)
        s["modules"]["cart"].update(status="failed", error="exit 3: gave up")
        (self.root / WORK / "state.json").write_text(json.dumps(s))
        write_docs(self.root, self.item)
        (self.staging / "MODULE.md").write_text("")
        code, out, err = text(self.root, "init", "done", "cart", "--json")
        data = json.loads(out)["data"]
        self.assertEqual((code, data["status"], data["problems"]),
                         (1, "failed", ["MODULE.md is empty"]))
        self.assertEqual(state(self.root)["modules"]["cart"]["status"], "failed")

    def test_a_symlinked_staging_dir_is_one_problem(self):  # M-8: its target is never read
        elsewhere = self.base / "elsewhere"
        shutil.rmtree(self.staging)
        elsewhere.mkdir()
        self.staging.symlink_to(elsewhere)
        write_docs(self.root, self.item, staging=elsewhere)
        code, out, err = text(self.root, "init", "done", "cart", "--json")
        self.assertEqual((code, json.loads(out)["data"]["problems"]),
                         (1, [f"the staging dir {WORK}/staging/cart is a symlink (write the "
                              f"files into a real directory)"]))

    def test_claimed_again_while_it_was_checked(self):  # M-10: the same attempt only
        from modsys.init_work import Work
        write_docs(self.root, self.item)
        real = Work.problems

        def meanwhile(work, module):  # another driver resets and claims it during the check
            found = real(work, module)
            s = state(self.root)
            s["modules"][module]["attempts"] += 1
            (self.root / WORK / "state.json").write_text(json.dumps(s))
            return found

        with mock.patch("modsys.init_work.Work.problems", autospec=True, side_effect=meanwhile):
            code, out, err = text(self.root, "init", "done", "cart", "--json")
        data = json.loads(out)["data"]
        self.assertEqual((code, data["status"]), (1, "running"))
        self.assertEqual(data["problems"], ["changed while it was checked (now running, attempt "
                                            "2): nothing marked — check it again once it is "
                                            "written"])
        self.assertEqual(state(self.root)["modules"]["cart"]["status"], "running")
        self.assertEqual(ok(self.root, "init", "done", "cart")["status"], "done")

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
