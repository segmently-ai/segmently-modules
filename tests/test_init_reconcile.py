"""`init reconcile` (D2, phase 5): the staging registry and its edges, keyword collisions,
duplicate names and the judgement items; the phase's order, determinism and a re-run over hand
edits."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import run
from tests.init_helpers import SIX, WORK, executor, ok, shop, state

ROLES = {"developer": "developer", "qa": "qa", "po": "po", "architect": "architect"}


class ReconcileRepo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.template = shop(Path(cls._tmp.name).resolve(), name="template")
        ok(cls.template, "init", "fanout")
        ok(cls.template, "init", "run", "--executor", executor())

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(dir=self._tmp.name)).resolve()
        self.root = self.base / "shop"
        shutil.copytree(self.template, self.root, symlinks=True)
        self.staging = self.root / WORK / "staging"

    def reconcile(self, *flags: str, code: int = 0):
        return ok(self.root, "init", "reconcile", *flags, code=code)

    def registry(self) -> dict:
        return json.loads((self.staging / "registry.json").read_text())

    def report(self) -> dict:
        return json.loads((self.root / WORK / "reconcile.json").read_text())

    def keywords(self, module: str, keywords: list[str]) -> None:
        path = self.staging / module / "entry.json"
        entry = json.loads(path.read_text())
        entry["keywords"] = keywords
        path.write_text(json.dumps(entry))

    def plant(self, module_dir: str, count: int, text: str) -> None:
        for i in range(count):
            path = self.root / module_dir / f"zz{i}.ts"
            path.write_text(f"// {text}\nexport const v{i} = 1;\n")


class RegistryAndEdgesTest(ReconcileRepo):  # P5B-AC-012 (SI-9, SI-19)
    def test_the_staging_registry(self):
        data = self.reconcile()
        self.assertEqual(set(data), {"action", "staging_registry", "reconcile", "edges",
                                     "collisions", "duplicates", "judgement", "next"})
        text = (self.staging / "registry.json").read_text()
        doc = json.loads(text)
        self.assertEqual(text, json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
        self.assertEqual(list(doc["modules"]), SIX)
        cart = doc["modules"]["cart"]
        self.assertEqual(list(cart), ["name", "description", "status", "keywords",
                                      "context_files", "related_modules"])
        self.assertEqual((cart["name"], cart["status"]), ("cart", "active"))
        self.assertEqual(cart["context_files"], {
            "universal": "modules/cart/MODULE.md",
            "roles": {r: f"modules/cart/roles/{r}.md" for r in ROLES}})
        self.assertEqual(list(doc["modules"]["catalog"])[-1], "negative_keywords")
        self.assertEqual(state(self.root)["phases"]["reconcile"]["status"], "done")

    def test_the_edges(self):
        self.reconcile()
        edges = {m: e.get("related_modules", []) for m, e in self.registry()["modules"].items()}
        self.assertEqual(edges["cart"], [{"module": "catalog", "relation": "depends-on",
                                          "description": "imports from catalog (1 import(s), "
                                                         "init reconcile)"}])
        self.assertEqual([(e["module"], e["relation"]) for e in edges["storefront"]],
                         [("catalog", "complements"), ("cart", "depends-on"),
                          ("ui-kit", "depends-on")])  # the writer's edge wins, no duplicate
        self.assertEqual([e["module"] for e in edges["recommendations"]], ["payments"])
        self.assertEqual([e["module"] for e in edges["payments"]], ["recommendations"])  # both ways
        self.assertEqual((edges["catalog"], edges["ui-kit"]), ([], []))
        self.assertEqual(self.report()["edges"], [
            {"from": "cart", "to": "catalog", "relation": "depends-on", "source": "imports"},
            {"from": "payments", "to": "recommendations", "relation": "depends-on",
             "source": "imports"},
            {"from": "recommendations", "to": "payments", "relation": "depends-on",
             "source": "imports"},
            {"from": "storefront", "to": "cart", "relation": "depends-on", "source": "imports"},
            {"from": "storefront", "to": "catalog", "relation": "complements",
             "source": "writer"},
            {"from": "storefront", "to": "ui-kit", "relation": "depends-on",
             "source": "imports"}])
        self.assertEqual(list(self.report()), ["edges", "collisions", "duplicates", "judgement"])


class CollisionsTest(ReconcileRepo):  # P5B-AC-013 (SI-10)
    def collision(self, keyword: str) -> dict | None:
        self.reconcile()
        return next((c for c in self.report()["collisions"] if c["keyword"] == keyword), None)

    def test_one_module_and_two(self):
        self.keywords("catalog", ["catalog", "book", "isbn", "author", "title", "zeta"])
        self.assertIsNone(self.collision("zeta"))
        self.setUp()
        self.keywords("catalog", ["catalog", "book", "isbn", "author", "title", "zeta"])
        self.keywords("cart", ["cart", "basket", "line", "total", "quantity", "zeta"])
        self.plant("packages/catalog/src", 7, "zeta zeta zeta")
        self.plant("packages/cart/src", 2, "Zeta, zetas and zetaline")
        row = self.collision("zeta")
        self.assertEqual(row, {"keyword": "zeta", "owner": "catalog", "others": ["cart"],
                               "files": {"cart": 2, "catalog": 7}, "moved": ["cart"]})
        modules = self.registry()["modules"]
        self.assertEqual((modules["cart"]["keywords"], modules["cart"]["negative_keywords"]),
                         (["cart", "basket", "line", "total", "quantity"], ["zeta"]))
        self.assertIn("zeta", modules["catalog"]["keywords"])
        for entry in modules.values():
            self.assertFalse(set(entry["keywords"]) & set(entry.get("negative_keywords", [])))

    def test_a_tie_a_floor_and_the_case(self):
        self.keywords("catalog", ["catalog", "book", "isbn", "author", "title", "zeta"])
        self.keywords("cart", ["cart", "basket", "line", "total", "quantity", "zeta"])
        self.keywords("storefront", ["storefront", "page", "shop", "window", "render", "zeta"])
        self.plant("packages/catalog/src", 5, "zeta")
        self.plant("packages/cart/src", 5, "zeta")
        self.plant("apps/storefront/src", 1, "zeta")
        row = self.collision("zeta")
        self.assertEqual((row["owner"], row["moved"]), (None, []))
        self.assertIn({"kind": "keyword-tie", "keyword": "zeta", "modules": ["cart", "catalog"],
                       "files": {"cart": 5, "catalog": 5, "storefront": 1}},
                      self.report()["judgement"])
        self.setUp()
        self.keywords("catalog", ["catalog", "book", "isbn", "author", "title", "Zeta"])
        self.keywords("cart", ["cart", "basket", "line", "total", "zeta"])  # exactly 5
        self.plant("packages/catalog/src", 7, "zeta")
        self.plant("packages/cart/src", 2, "zeta")
        row = self.collision("zeta")
        self.assertEqual((row["owner"], row["moved"]), ("catalog", []))
        self.assertIn({"kind": "keyword-floor", "keyword": "zeta", "module": "cart",
                       "keywords": 5}, self.report()["judgement"])
        self.assertIn("zeta", self.registry()["modules"]["cart"]["keywords"])
        self.assertNotIn("negative_keywords", self.registry()["modules"]["cart"])

    def test_a_keyword_in_a_path(self):  # PR-13 (M-4): path or text, each file once
        self.keywords("catalog", ["catalog", "book", "isbn", "author", "title", "zeta"])
        self.keywords("cart", ["cart", "basket", "line", "total", "quantity", "zeta"])
        for i in range(3):  # the word only in the file's path (never in its text)
            path = self.root / f"packages/catalog/src/zeta-{i}.ts"
            path.write_text(f"export const v{i} = 1;\n")
        (self.root / "packages/catalog/src/zeta.png").write_bytes(b"\x89PNG\0\0binary")
        (self.root / "packages/catalog/src/zeta-text.ts").write_text("// zeta\n")  # both: once
        self.plant("packages/cart/src", 4, "zeta")
        row = self.collision("zeta")
        self.assertEqual((row["owner"], row["files"]), ("catalog", {"cart": 4, "catalog": 5}))

    def test_the_fixture_collision(self):
        self.reconcile()
        self.assertEqual(self.report()["collisions"], [
            {"keyword": "price", "owner": "cart", "others": ["catalog"],
             "files": {"cart": 2, "catalog": 1}, "moved": ["catalog"]}])


class DuplicatesTest(ReconcileRepo):  # P5B-AC-014 (SI-11)
    def test_the_planted_duplicate(self):
        self.reconcile()
        definitions = [{"module": "catalog", "file": "packages/catalog/src/books.ts", "line": 14},
                       {"module": "ui-kit", "file": "packages/ui-kit/src/index.tsx", "line": 7}]
        self.assertEqual(self.report()["duplicates"],
                         [{"name": "formatPrice", "definitions": definitions}])
        self.assertEqual([j for j in self.report()["judgement"] if j["kind"] == "duplicate"],
                         [{"kind": "duplicate", "name": "formatPrice",
                           "definitions": definitions}])
        self.assertEqual([j["kind"] for j in self.report()["judgement"]], ["duplicate"])

    def test_what_counts_as_a_definition(self):
        py = self.root / "services/payments/payments"
        py2 = self.root / "services/recommendations/recommendations"
        js = self.root / "packages/cart/src"
        js2 = self.root / "packages/catalog/src"
        (py / "defs.py").write_text("def pay():\n    def inner():\n        pass\n\nclass Ledger:\n"
                                    "    def pay(self):\n        pass\n\nasync def later():\n"
                                    "    pass\n\ndef _hidden():\n    pass\n\ndef twice():\n"
                                    "    pass\n")
        (py2 / "defs.py").write_text("def pay():\n    pass\n\nclass Ledger:\n    pass\n\n"
                                     "async def later():\n    pass\n\ndef inner():\n    pass\n\n"
                                     "def _hidden():\n    pass\n")
        (py / "more.py").write_text("def twice():\n    pass\n")
        (py2 / "test_defs.py").write_text("def pay():\n    pass\n")
        (js / "defs.ts").write_text("export function lookup() {}\nexport class Shelf {}\n"
                                    "export const LIMIT = 1;\nexport interface Row {}\n"
                                    "export type Id = string;\nexport default function main() {}\n"
                                    "export { lookup as find } from './x';\n")
        (js2 / "defs.ts").write_text("export function lookup() {}\nexport class Shelf {}\n"
                                     "export const LIMIT = 2;\nexport interface Row {}\n"
                                     "export type Id = number;\nexport function main() {}\n"
                                     "export function find() {}\n")
        (js2 / "defs.spec.ts").write_text("export function Shelf() {}\n")
        runs = []
        real = subprocess.run
        with mock.patch("subprocess.run", side_effect=lambda argv, **kw: (
                runs.append(argv[0]), real(argv, **kw))[1]):
            code, out, err = run("init", "reconcile", "--json", "--root", str(self.root))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(set(runs), {"git"})
        names = [d["name"] for d in json.loads(out)["data"]["duplicates"]]
        self.assertEqual(names, ["Id", "LIMIT", "Ledger", "Row", "Shelf", "formatPrice",
                                 "later", "lookup", "pay"])
        pay = next(d for d in self.report()["duplicates"] if d["name"] == "pay")
        self.assertEqual(pay["definitions"], [
            {"module": "payments", "file": "services/payments/payments/defs.py", "line": 1},
            {"module": "recommendations",
             "file": "services/recommendations/recommendations/defs.py", "line": 1}])


class LifecycleTest(ReconcileRepo):  # P5B-AC-015 (SI-5, SI-16)
    def test_every_module_must_be_done(self):
        s = state(self.root)
        s["modules"]["cart"]["status"] = "running"
        s["modules"]["ui-kit"]["status"] = "failed"
        (self.root / WORK / "state.json").write_text(json.dumps(s))
        code, out, err = run("init", "reconcile", "--json", "--root", str(self.root))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("not done: cart (running), ui-kit (failed)", err)
        self.assertFalse((self.staging / "registry.json").exists())
        self.assertFalse((self.root / WORK / "reconcile.json").exists())

    def test_twice_and_after_hand_edits(self):
        self.reconcile()
        first = [(p).read_bytes() for p in (self.staging / "registry.json",
                                            self.root / WORK / "reconcile.json")]
        self.reconcile()
        self.assertEqual([p.read_bytes() for p in (self.staging / "registry.json",
                                                   self.root / WORK / "reconcile.json")], first)
        doc = self.registry()
        doc["modules"]["cart"]["keywords"].append("trolley")
        (self.staging / "registry.json").write_text(json.dumps(doc, indent=2) + "\n")
        edited = (self.staging / "registry.json").read_bytes()
        code, out, err = run("init", "reconcile", "--root", str(self.root))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("staging registry edited since reconcile — keep the edits, or rerun with "
                      "--force to rebuild from entry.json", err)
        self.assertEqual((self.staging / "registry.json").read_bytes(), edited)
        self.reconcile("--force")
        self.assertEqual((self.staging / "registry.json").read_bytes(), first[0])

    def test_an_entry_edited_after_done(self):
        (self.staging / "cart/entry.json").write_text("{not json")
        code, out, err = run("init", "reconcile", "--root", str(self.root))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("cart: entry.json: invalid JSON", err)


class ExistingModuleTest(unittest.TestCase):  # P5B-AC-051 (reconcile keeps it as it is)
    def test_a_module_created_by_hand_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = shop(Path(tmp).resolve())
            ok(root, "create", "catalog", "--non-interactive", "--description",
               "Book titles, authors and ISBN lookups for the shop.", "--keywords",
               "catalog, book, isbn, author, title, price")
            before = json.loads((root / "modules/registry.json").read_text())["modules"]
            ok(root, "init", "fanout")
            ok(root, "init", "run", "--executor", executor())
            ok(root, "init", "reconcile")
            staged = json.loads((root / WORK / "staging/registry.json").read_text())["modules"]
            self.assertEqual(list(staged), ["catalog", "cart", "payments", "recommendations",
                                            "storefront", "ui-kit"])
            self.assertEqual(staged["catalog"], before["catalog"])
            report = json.loads((root / WORK / "reconcile.json").read_text())
            self.assertFalse([c for c in report["collisions"] if "catalog" in c["others"]])
            self.assertFalse((root / WORK / "staging/catalog").exists())
            # a duplicate name spans it too (Task 7 review I2): a report row, nothing changed
            self.assertEqual(report["duplicates"], [{"name": "formatPrice", "definitions": [
                {"module": "catalog", "file": "packages/catalog/src/books.ts", "line": 14},
                {"module": "ui-kit", "file": "packages/ui-kit/src/index.tsx", "line": 7}]}])
            self.assertEqual([j["kind"] for j in report["judgement"]], ["duplicate"])
            self.assertFalse([e for e in report["edges"] if "catalog" == e["from"]])


if __name__ == "__main__":
    unittest.main()
