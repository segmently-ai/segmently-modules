"""`init verify` (D3, phase 6): the invented-component check, and verify over the staging tree
as if it were in place — lint (clean: no error, no warning), invented components, the routing
hit rate; `verify.json` and the exit rule."""
import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from segmently_modules.init_verify import invented
from segmently_modules.workspace import Workspace
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

    def check(self, text: str) -> list[tuple[int, str, str]]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "repo"
            (root / "packages/catalog/src").mkdir(parents=True)
            (root / "packages/catalog/src/books.ts").write_text(
                "export function searchBooks() {}\n")
            doc = Path(tmp) / "developer.md"
            doc.write_text(text.replace("<root>", str(root)))
            found = invented(Workspace.load(root), {"modules/catalog/roles/developer.md": doc})
        return [(f["line"], f["kind"], f["token"].replace(str(root), "<root>")) for f in found]

    def test_a_table_without_a_path_column(self):  # PR-19 (I-5): not a components table
        text = ("| Name | Kind | Purpose |\n|---|---|---|\n| `searchBooks` | function | finds "
                "books |\n| `pytest` | tool | runs the tests |\n\n| Symbol | Type |\n|---|---|\n"
                "| `maxItems` | int |\n\n| Path | Purpose |\n|---|---|\n| `nowhere` | x |\n")
        self.assertEqual(self.check(text), [])
        text += "\n| Name | File |\n|---|---|\n| `nowhere` | `packages/catalog/src/books.ts` |\n"
        self.assertEqual(self.check(text), [(16, "symbol", "nowhere")])

    def test_paths_outside_the_root(self):  # M-15: they exist on the machine, not in the root
        text = ("See `<root>/packages/catalog/src/books.ts` and "
                "`../repo/packages/catalog/src/books.ts`, not `packages/../../x/y`.\n\n"
                "| Name | Path |\n|---|---|\n"
                "| `searchBooks` | `../repo/packages/catalog/src/books.ts` |\n"
                "| `searchBooks` | `packages/catalog/src/books.ts` |\n")
        self.assertEqual(self.check(text), [
            (1, "path", "../repo/packages/catalog/src/books.ts"),
            (1, "path", "<root>/packages/catalog/src/books.ts"),
            (1, "path", "packages/../../x/y"),
            (5, "no-file", "searchBooks"),
            (5, "path", "../repo/packages/catalog/src/books.ts")])

    def test_the_text_lines(self):  # final review M-7: the words init done uses (SI-2)
        from segmently_modules.init_cmd import _render_verify
        data = {"lint": {"summary": {"error": 0, "warning": 0, "info": 0}, "findings": []},
                "invented": [{"doc": "modules/cart/MODULE.md", "line": n, "kind": k, "token": t}
                             for n, k, t in ((12, "path", "src/lines.ts"),
                                             (20, "symbol", "lineTotals"),
                                             (21, "no-file", "lineTotal"))],
                "routing": None, "passed": False, "verify": f"{WORK}/verify.json", "next": "x",
                "keywords": [{"module": "cart", "words": 45, "max_keywords": 40,
                              "generic": ["deletes", "user"]},
                             {"module": "catalog", "words": 12, "max_keywords": 40,
                              "generic": ["save"]}]}
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            _render_verify(data)
        self.assertEqual(out.getvalue().splitlines()[1:5], [
            "invented      3 component(s)",
            "  modules/cart/MODULE.md:12: path does not exist: src/lines.ts",
            "  modules/cart/MODULE.md:20: symbol not found in its row's file: lineTotals",
            "  modules/cart/MODULE.md:21: no file to check: lineTotal"])
        self.assertEqual(out.getvalue().splitlines()[6:9], [  # FoodMate init, 2026-10-14
            "keywords      2 module(s) with too many words or a generic word",
            "  cart: 45 words > max_keywords 40; generic: deletes, user",
            "  catalog: generic: save"])


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


class KeywordsTest(VerifyRepo):  # a new module's keywords (FoodMate init, 2026-10-14)
    def test_too_many_words_or_a_generic_word_fails(self):
        many = [f"basket{chr(97 + i // 26)}{chr(97 + i % 26)}" for i in range(41)]
        self.edit(lambda m: (m["cart"].update(keywords=many),
                             m["catalog"]["keywords"].extend(["Deletes", "users"])))
        code, data, _ = self.verify()
        self.assertEqual((code, data["passed"]), (1, False))
        cart, catalog = data["keywords"]
        self.assertEqual(cart, {"module": "cart", "words": 41, "max_keywords": 40,
                                "generic": []})
        self.assertEqual((catalog["module"], catalog["generic"]), ("catalog",
                                                                  ["Deletes", "users"]))
        self.assertLess(catalog["words"], 40)
        self.edit(lambda m: (m["cart"].update(keywords=many[:38] + ["checkout", "checkouts"]),
                             m["catalog"].update(keywords=[k for k in m["catalog"]["keywords"]
                                                           if k not in ("Deletes", "users")])))
        code, data, _ = self.verify()
        self.assertEqual((code, data["keywords"], data["passed"]), (0, [], True))


class VerifyTest(VerifyRepo):  # P5B-AC-022 (SI-16, SI-17)
    def test_a_clean_verify(self):
        before = protected_sha(self.root)
        code, data, _ = self.verify()
        self.assertEqual(code, 0)
        self.assertEqual(set(data), {"action", "verify", "lint", "invented", "routing",
                                     "keywords", "staging_sha256", "passed", "next"})
        self.assertEqual(data["keywords"], [])
        self.assertEqual((data["lint"]["summary"], data["invented"], data["passed"]),
                         ({"error": 0, "warning": 0, "info": 0}, [], True))
        self.assertEqual((data["routing"]["hit_rate"], data["routing"]["passed"]), (1.0, True))
        written = json.loads((self.root / WORK / "verify.json").read_text())
        self.assertEqual(list(written), ["lint", "invented", "routing", "keywords",
                                         "staging_sha256", "passed"])
        r = data["routing"]  # how precise, never a gate
        self.assertEqual(set(r) - {"hit_rate", "top", "tasks", "per_module", "hits",
                                   "min_hit_rate", "passed"},
                         {"top1_hit_rate", "mean_matched"})
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
        self.assertIn("segmently-modules init reconcile", err)

    def refused(self, *argv: str) -> str:
        code, out, err = run(*argv, "--json", "--root", str(self.root))
        self.assertEqual((code, out), (2, ""), err)
        self.assertNotIn("internal error", err)
        self.assertNotIn(str(self.root), err)  # root-relative (M-12)
        return err

    def test_a_hand_written_tasks_file_that_is_not_valid(self):  # Task 9 review I1
        tasks = self.root / WORK / "routing-tasks.json"
        for text, problem in (("{not json", f"{WORK}/routing-tasks.json: invalid JSON"),
                              ('[{"task": "the isbn", "module": "nosuch"}]',
                               f"unknown module 'nosuch' in {WORK}/routing-tasks.json")):
            with self.subTest(problem=problem[:20]):
                tasks.write_text(text)
                err = self.refused("init", "verify")
                self.assertIn(problem, err)
                self.assertIn("— fix it, or segmently-modules init eval-tasks --force", err)

    def test_a_broken_staging_registry(self):  # M-1: a hand edit gone wrong
        for text in ('{"modules": {,', '{"modules": []}'):
            self.registry.write_text(text)
            for argv in (("init", "verify"), ("eval", "routing", "--prompt")):
                with self.subTest(text=text, argv=argv):
                    err = self.refused(*argv)
                    self.assertIn(f"{WORK}/staging/registry.json", err)
                    self.assertIn("fix it, or rebuild it from the entry.json files: segmently-modules init "
                                  "reconcile --force", err)

    def test_a_symlink_added_to_staging_after_verify(self):  # Task 9 review C1 (M-8)
        from segmently_modules.init_verify import tree_sha
        self.assertEqual(self.verify()[0], 0)
        staging = self.root / WORK / "staging"
        before = tree_sha(staging)
        (staging / "cart/roles/extra.md").symlink_to(self.root / "README.md")
        self.assertNotEqual(tree_sha(staging), before)
        code, out, err = run("init", "finish", "--root", str(self.root))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("staging changed since verify", err)

    def test_a_symlinked_staging_module_dir(self):  # re-review out-of-scope 2: never read
        self.assertEqual(self.verify()[0], 0)
        staging = self.root / WORK / "staging"
        shutil.move(staging / "cart", self.base / "cart-elsewhere")
        (staging / "cart").symlink_to(self.base / "cart-elsewhere")
        before = protected_sha(self.root)
        for argv in (("init", "verify"), ("init", "finish"), ("init", "finish", "--force")):
            with self.subTest(argv=argv):
                err = self.refused(*argv)
                self.assertIn(f"the staging dir {WORK}/staging/cart is a symlink (write the "
                              f"files into a real directory)", err)
        self.assertEqual(protected_sha(self.root), before)
        self.assertEqual(state(self.root)["phases"]["finish"]["status"], "pending")


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
