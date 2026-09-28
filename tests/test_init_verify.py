"""`init verify` (D3, phase 6): the invented-component check, and verify over the staging tree
as if it were in place — lint (clean: no error, no warning), invented components, the routing
hit rate; `verify.json` and the exit rule."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from modsys.init_verify import invented
from modsys.workspace import Workspace
from tests.helpers import run
from tests.init_helpers import WORK, executor, ok, protected_sha, shop, state


class InventedTest(unittest.TestCase):  # P5B-AC-021 (SI-12)
    DOC = """# Catalog

## Purpose

The books, in `packages/catalog/src/books.ts`, see `packages/catalog/src/books.ts:12` and
`packages/catalog/src/books.ts#L10`; not `packages/catalog/src/missing.ts`.
The cart's doc: `modules/cart/MODULE.md`. Not paths: `packages/*/src`, `https://x.org/a/b`,
`<module>/x`, `@scope/pkg`, `word`.

```ts
import x from `packages/catalog/src/fenced.ts`;
```

<!-- `packages/catalog/src/commented.ts` -->
<!-- a comment over
`packages/catalog/src/two-lines.ts` two lines -->

## EXISTING Components - DO NOT CREATE NEW

| Name | Path | Purpose |
|------|------|---------|
| `searchBooks` | `packages/catalog/src/books.ts` | finds books |
| `searchBook` | `packages/catalog/src/books.ts` | a near miss |
| `SearchBooks` | `packages/catalog/src/books.ts` | the case differs |
| `lookup` | | no path |
| `lookup` | `packages/catalog/src/gone.ts` | a missing file |
| Book search | `packages/catalog/src/books.ts` | prose |
| `listing` | `packages/catalog/src` | a directory |
"""

    def test_the_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "repo"
            (root / "packages/catalog/src").mkdir(parents=True)
            (root / "packages/catalog/src/books.ts").write_text(
                "export function searchBooks() {}\n")
            doc = Path(tmp) / "MODULE.md"
            doc.write_text(self.DOC)
            ws = Workspace.load(root)
            ws.overlay = {"modules/catalog/MODULE.md": doc,
                          "modules/cart/MODULE.md": Path(tmp) / "other.md"}
            found = invented(ws, {"modules/catalog/MODULE.md": doc})
        lines = self.DOC.splitlines()

        def at(needle: str) -> int:
            return next(i for i, line in enumerate(lines, 1) if needle in line)

        rows = [(at("not `packages/catalog/src/missing.ts`"), "path",
                 "packages/catalog/src/missing.ts"),
                (at("| `searchBook` |"), "symbol", "searchBook"),
                (at("| `SearchBooks` |"), "symbol", "SearchBooks"),
                (at("| no path |"), "no-file", "lookup"),
                (at("| a missing file |"), "path", "packages/catalog/src/gone.ts"),
                (at("| a directory |"), "no-file", "listing")]
        self.assertEqual(found, [{"doc": "modules/catalog/MODULE.md", "line": n, "kind": kind,
                                  "token": token} for n, kind, token in rows])


class VerifyRepo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.template = shop(Path(cls._tmp.name).resolve(), name="template")
        ok(cls.template, "init", "fanout")
        ok(cls.template, "init", "run", "--executor", executor())
        ok(cls.template, "init", "reconcile")
        ok(cls.template, "init", "eval-tasks", "--executor", executor())

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(dir=self._tmp.name)).resolve()
        self.root = self.base / "shop"
        shutil.copytree(self.template, self.root, symlinks=True)
        self.registry = self.root / WORK / "staging/registry.json"

    def edit(self, fn) -> None:
        doc = json.loads(self.registry.read_text())
        fn(doc["modules"])
        self.registry.write_text(json.dumps(doc, indent=2) + "\n")

    def verify(self) -> tuple[int, dict, str]:
        code, out, err = run("init", "verify", "--json", "--root", str(self.root))
        self.assertEqual(err, "")
        return code, json.loads(out)["data"], out


class VerifyTest(VerifyRepo):  # P5B-AC-022 (SI-16, SI-17)
    def test_a_clean_verify(self):
        before = protected_sha(self.root)
        code, data, _ = self.verify()
        self.assertEqual(code, 0)
        self.assertEqual(set(data), {"action", "verify", "lint", "invented", "routing",
                                     "staging_sha256", "passed", "next"})
        self.assertEqual((data["lint"]["summary"], data["invented"], data["passed"]),
                         ({"error": 0, "warning": 0, "info": 0}, [], True))
        self.assertEqual((data["routing"]["hit_rate"], data["routing"]["passed"]), (1.0, True))
        written = json.loads((self.root / WORK / "verify.json").read_text())
        self.assertEqual(list(written), ["lint", "invented", "routing", "staging_sha256",
                                         "passed"])
        self.assertEqual(protected_sha(self.root), before)  # nothing moved (P5B-AC-011)
        self.assertFalse((self.root / "modules/cart").exists())
        self.assertEqual(state(self.root)["phases"]["verify"]["status"], "done")
        self.assertIn("gate 7", data["next"])

    def test_the_exit_rule(self):
        rows = [
            ("a warning", lambda m: m["cart"]["context_files"]["roles"].update(
                reviewer="modules/cart/roles/developer.md"), 1, "MS015"),
            ("an error", lambda m: m["cart"].update(status="bogus"), 1, "MS003"),
            ("info only", lambda m: [m[x]["keywords"].append("shelfmark")
                                     for x in ("cart", "catalog", "payments", "ui-kit")], 0,
             "MS021")]
        for label, change, code, lint_code in rows:
            with self.subTest(row=label):
                self.setUp()
                self.edit(change)
                got, data, _ = self.verify()
                self.assertEqual((got, data["passed"]), (code, code == 0))
                self.assertIn(lint_code, [f["code"] for f in data["lint"]["findings"]])

    def test_an_invented_component_and_a_low_hit_rate(self):
        doc = self.root / WORK / "staging/cart/MODULE.md"
        doc.write_text(doc.read_text() + "\nSee `packages/cart/src/nowhere.ts`.\n")
        code, data, _ = self.verify()
        self.assertEqual((code, [f["token"] for f in data["invented"]]),
                         (1, ["packages/cart/src/nowhere.ts"]))
        self.setUp()
        tasks = [{"task": "change how the cart and the basket work", "module": "cart"}] * 3 + \
            [{"task": "nothing relevant", "module": "cart"}]
        (self.root / WORK / "routing-tasks.json").write_text(json.dumps(tasks))
        code, data, _ = self.verify()
        self.assertEqual((code, data["routing"]["hit_rate"], data["passed"]), (1, 0.75, False))
        self.assertIn("verify failed", data["next"])

    def test_no_tasks_file(self):
        (self.root / WORK / "routing-tasks.json").unlink()
        code, data, _ = self.verify()
        self.assertEqual((code, data["routing"], data["passed"]), (0, None, True))
        code, out, err = run("init", "verify", "--root", str(self.root))
        self.assertEqual((code, err), (0, ""))
        self.assertIn("routing: not measured", out.splitlines())

    def test_before_reconcile(self):
        s = state(self.root)
        s["phases"]["reconcile"]["status"] = "pending"
        (self.root / WORK / "state.json").write_text(json.dumps(s))
        code, out, err = run("init", "verify", "--json", "--root", str(self.root))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("modsys init reconcile", err)


class OverlayEqualsFinalTest(VerifyRepo):  # P5B-AC-022 (verify reads what finish writes)
    def test_the_same_lint_and_routing_after_finish(self):
        for shared in (False, True):
            with self.subTest(shared_keyword=shared):
                self.setUp()
                if shared:  # a finding to compare: MS021 (info) needs 4 modules
                    self.edit(lambda m: [m[x]["keywords"].append("shelfmark")
                                         for x in ("cart", "catalog", "payments", "ui-kit")])
                code, data, _ = self.verify()
                self.assertEqual(code, 0)
                ok(self.root, "init", "finish")
                lint = ok(self.root, "lint")
                self.assertEqual((lint["findings"], lint["summary"]),
                                 (data["lint"]["findings"], data["lint"]["summary"]))
                routed = ok(self.root, "eval", "routing", "--tasks",
                            str(self.root / WORK / "routing-tasks.json"))
                self.assertEqual(routed, data["routing"])


if __name__ == "__main__":
    unittest.main()
