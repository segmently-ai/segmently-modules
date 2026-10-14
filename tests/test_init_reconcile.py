"""`init reconcile` (D2, phase 5): the staging registry and its edges, keyword collisions,
duplicate names and the judgement items; the phase's order, determinism and a re-run over hand
edits."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import mutate_registry, run
from tests.init_helpers import SIX, WORK, executor, ok, shop, state, text

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
                                     "collisions", "dropped", "duplicates", "judgement",
                                     "next"})
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
        self.assertEqual(list(doc["modules"]["catalog"]), ["name", "description", "status",
                                                          "keywords", "context_files"])
        self.assertEqual([m for m, e in doc["modules"].items() if "negative_keywords" in e], [])
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
        self.assertEqual(list(self.report()), ["edges", "collisions", "dropped", "duplicates",
                                               "judgement"])


class CollisionsTest(ReconcileRepo):  # P5B-AC-013 (SI-10), P5C-AC-001, P6-AC-036 (D14)
    CATALOG = ["catalog", "book", "isbn", "author", "title", "zeta"]
    CART = ["cart", "basket", "line", "total", "quantity", "zeta"]
    STOREFRONT = ["storefront", "page", "shop", "window", "render", "zeta"]

    def collision(self, keyword: str) -> dict | None:
        self.reconcile()
        return next((c for c in self.report()["collisions"] if c["keyword"] == keyword), None)

    def judged(self) -> list[dict]:
        """The judgement items but the fixture's own duplicate name."""
        return [j for j in self.report()["judgement"] if j["kind"] != "duplicate"]

    def test_one_module_and_two(self):  # rows 1–3: a holder whose files hold it keeps it
        self.keywords("catalog", self.CATALOG)
        self.assertIsNone(self.collision("zeta"))
        for cart_files, removed in ((1, []), (0, ["cart"])):  # BVA: 1 file keeps, 0 loses
            with self.subTest(cart_files=cart_files):
                self.setUp()
                self.keywords("catalog", self.CATALOG)
                self.keywords("cart", self.CART)
                self.plant("packages/catalog/src", 7, "zeta zeta zeta")
                self.plant("packages/cart/src", cart_files, "Zeta, zetas and zetaline")
                row = self.collision("zeta")
                self.assertEqual(row, {"keyword": "zeta", "owner": "catalog", "others": ["cart"],
                                       "files": {"cart": cart_files, "catalog": 7},
                                       "removed": removed})
                modules = self.registry()["modules"]
                self.assertEqual(modules["cart"]["keywords"],
                                 self.CART if cart_files else self.CART[:-1])
                self.assertIn("zeta", modules["catalog"]["keywords"])
                for entry in modules.values():  # reconcile negates nothing
                    self.assertNotIn("negative_keywords", entry)
                self.assertEqual(self.judged(), [])

    def test_a_tie_a_floor_and_the_case(self):  # rows 5–7 and 9
        self.keywords("catalog", self.CATALOG)
        self.keywords("cart", self.CART)
        self.keywords("storefront", self.STOREFRONT)
        self.plant("packages/catalog/src", 5, "zeta")
        self.plant("packages/cart/src", 5, "zeta")
        row = self.collision("zeta")  # row 5: a tie removes nothing, not even from 0 files
        self.assertEqual((row["owner"], row["others"], row["removed"]),
                         (None, ["cart", "catalog", "storefront"], []))
        self.assertEqual(self.judged(), [{"kind": "keyword-tie", "keyword": "zeta",
                                          "modules": ["cart", "catalog"],
                                          "files": {"cart": 5, "catalog": 5, "storefront": 0}}])
        self.assertIn("zeta", self.registry()["modules"]["storefront"]["keywords"])
        self.setUp()
        self.keywords("catalog", self.CATALOG)
        self.keywords("cart", self.CART)
        row = self.collision("zeta")  # row 6: no file holds it — dropped from both (0.3.0)
        self.assertEqual((row["owner"], row["removed"]), (None, ["cart", "catalog"]))
        self.assertEqual(self.judged(), [])
        self.assertEqual(self.report()["dropped"], [{"keyword": "zeta",
                                                     "modules": ["cart", "catalog"]}])
        modules = self.registry()["modules"]
        self.assertEqual((modules["cart"]["keywords"], modules["catalog"]["keywords"]),
                         (self.CART[:-1], self.CATALOG[:-1]))
        for cart_files, floor in ((0, True), (2, False)):  # rows 7 and 9: cart has exactly 5
            with self.subTest(cart_files=cart_files):
                self.setUp()
                self.keywords("catalog", ["catalog", "book", "isbn", "author", "title", "Zeta"])
                self.keywords("cart", ["cart", "basket", "line", "total", "zeta"])
                self.plant("packages/catalog/src", 7, "zeta")
                self.plant("packages/cart/src", cart_files, "zeta")
                row = self.collision("zeta")
                self.assertEqual((row["owner"], row["removed"]), ("catalog", []))
                self.assertEqual(self.judged(), [{"kind": "keyword-floor", "keyword": "zeta",
                                                  "module": "cart", "keywords": 5}]
                                 if floor else [])  # no floor item when nothing is removed
                self.assertIn("zeta", self.registry()["modules"]["cart"]["keywords"])
                self.assertNotIn("negative_keywords", self.registry()["modules"]["cart"])

    def test_identifier_parts_and_forms_count(self):  # 0.3.0 (FoodMate init, 2026-10-14)
        self.keywords("catalog", self.CATALOG)
        self.keywords("cart", ["cart", "basket", "line", "total", "quantity", "zetas"])
        for i in range(3):  # only inside identifiers: saveZeta, zeta_count
            (self.root / f"packages/catalog/src/zz{i}.ts").write_text(
                f"export function saveZeta{i}() {{ return zeta_count; }}\n")
        row = self.collision("zeta")  # `zeta` and `zetas`: one word
        self.assertEqual(row, {"keyword": "zeta", "owner": "catalog", "others": ["cart"],
                               "files": {"cart": 0, "catalog": 3}, "removed": ["cart"]})
        self.assertNotIn("zetas", self.registry()["modules"]["cart"]["keywords"])

    def test_an_ownerless_word_and_the_floor(self):  # 0.3.0: dropped where the floor allows
        self.keywords("catalog", self.CATALOG)
        self.keywords("cart", ["cart", "basket", "line", "total", "zeta"])  # exactly 5
        self.keywords("storefront", self.STOREFRONT[:-1] + ["Zetas"])
        row = self.collision("zeta")
        self.assertEqual((row["owner"], row["removed"]), (None, ["catalog", "storefront"]))
        self.assertEqual(self.judged(), [{"kind": "keyword-floor", "keyword": "zeta",
                                          "module": "cart", "keywords": 5}])
        self.assertEqual(self.report()["dropped"], [{"keyword": "zeta",
                                                     "modules": ["catalog", "storefront"]}])
        modules = self.registry()["modules"]
        self.assertIn("zeta", modules["cart"]["keywords"])
        self.assertNotIn("Zetas", modules["storefront"]["keywords"])

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

    def test_a_keyword_only_in_a_file_name_keeps_it(self):  # row 11 (a path counts)
        self.keywords("catalog", self.CATALOG)
        self.keywords("cart", self.CART)
        self.plant("packages/catalog/src", 3, "zeta")
        (self.root / "packages/cart/src/zeta-lines.ts").write_text("export const n = 1;\n")
        row = self.collision("zeta")
        self.assertEqual((row["files"], row["removed"]), ({"cart": 1, "catalog": 3}, []))
        self.assertIn("zeta", self.registry()["modules"]["cart"]["keywords"])

    def test_the_fixture_collision(self):  # SI-22: catalog's files hold `price` — it stays
        self.reconcile()  # 0.3.0: `formatPrice` counts too (identifier parts) — now a tie
        self.assertEqual(self.report()["collisions"], [
            {"keyword": "price", "owner": None, "others": ["cart", "catalog"],
             "files": {"cart": 2, "catalog": 2}, "removed": []}])
        self.assertIn("price", self.registry()["modules"]["catalog"]["keywords"])

    def test_three_modules_the_floor_reached_and_every_case_form(self):  # rows 4, 8, 10
        self.keywords("catalog", self.CATALOG)
        self.keywords("cart", self.CART)
        self.keywords("storefront", self.STOREFRONT)
        self.plant("packages/catalog/src", 7, "zeta")
        self.plant("packages/cart/src", 2, "zeta")
        row = self.collision("zeta")  # row 4: 7 / 2 / 0
        self.assertEqual((row["owner"], row["others"], row["removed"]),
                         ("catalog", ["cart", "storefront"], ["storefront"]))
        modules = self.registry()["modules"]
        self.assertEqual(modules["cart"]["keywords"], self.CART)  # its files hold it: kept
        self.assertEqual(modules["storefront"]["keywords"],  # row 8: 6 → 5, the floor reached
                         ["storefront", "page", "shop", "window", "render"])
        self.assertEqual([m for m, e in modules.items() if "negative_keywords" in e], [])
        self.assertEqual(self.judged(), [])
        self.setUp()
        self.keywords("catalog", ["catalog", "book", "isbn", "author", "title", "Zeta"])
        self.keywords("cart", ["cart", "basket", "line", "total", "quantity", "zeta", "ZETA"])
        self.plant("packages/catalog/src", 7, "zeta")
        row = self.collision("zeta")  # row 10: 7 / 0, cart holds two case forms
        self.assertEqual((row["owner"], row["removed"]), ("catalog", ["cart"]))
        modules = self.registry()["modules"]
        self.assertEqual(modules["cart"]["keywords"],  # every case form of the keyword
                         ["cart", "basket", "line", "total", "quantity"])
        self.assertIn("Zeta", modules["catalog"]["keywords"])
        self.assertEqual([m for m, e in modules.items() if "negative_keywords" in e], [])


class ReportTest(ReconcileRepo):  # P5C-AC-003 (the row's keys, the key order, a re-run)
    def test_the_keys_and_a_re_run(self):
        self.keywords("catalog", ["catalog", "book", "isbn", "author", "title", "zeta"])
        self.keywords("cart", ["cart", "basket", "line", "total", "quantity", "zeta"])
        self.plant("packages/catalog/src", 7, "zeta")
        self.plant("packages/cart/src", 2, "zeta")
        data = self.reconcile()
        for rows in (data["collisions"], self.report()["collisions"]):
            self.assertEqual([c["keyword"] for c in rows], ["zeta"])
            for row in rows:
                self.assertEqual(list(row), ["keyword", "owner", "others", "files", "removed"])
                for key in ("others", "removed"):
                    self.assertEqual(row[key], sorted(row[key]))
                self.assertEqual(list(row["files"]), sorted(row["files"]))
        for name, entry in self.registry()["modules"].items():
            with self.subTest(module=name):  # create's order, then the edges: no negatives
                self.assertIn(list(entry), (
                    ["name", "description", "status", "keywords", "context_files"],
                    ["name", "description", "status", "keywords", "context_files",
                     "related_modules"]))
        first = [p.read_bytes() for p in (self.staging / "registry.json",
                                          self.root / WORK / "reconcile.json")]
        self.reconcile()
        self.assertEqual([p.read_bytes() for p in (self.staging / "registry.json",
                                                   self.root / WORK / "reconcile.json")], first)


class TextTest(ReconcileRepo):  # P5C-AC-003, P6-AC-037 (SI-23: the text lines)
    def test_the_collision_lines(self):
        self.keywords("catalog", ["catalog", "book", "isbn", "author", "title", "zeta", "omega",
                                  "kappa", "sigma"])
        self.keywords("cart", ["cart", "basket", "line", "total", "quantity", "zeta", "omega",
                               "kappa"])
        self.keywords("storefront", ["storefront", "page", "shop", "window", "render", "kappa",
                                     "tau"])
        self.keywords("recommendations", ["recommendation", "suggest", "reader", "history",
                                          "score", "tau"])
        self.keywords("ui-kit", ["button", "field", "form", "label", "sigma"])  # exactly 5
        self.plant("packages/catalog/src", 7, "zeta omega kappa sigma")
        self.plant("packages/cart/src", 2, "zeta kappa")
        code, out, err = text(self.root, "init", "reconcile")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual([l for l in out.splitlines() if l.startswith("collision")], [
            "collision     'kappa' — owner catalog; removed from storefront; kept by cart "
            "(their files hold it)",
            "collision     'omega' — owner catalog; removed from cart",
            "collision     'sigma' — owner catalog",  # the floor: ui-kit keeps its fifth
            "collision     'zeta' — owner catalog; kept by cart (their files hold it)"])
        self.assertIn(f"dropped       1 word(s) no holder's code holds, from every module that "
                      f"held them: tau — put one back in {WORK}/staging/registry.json when a "
                      f"module owns it", out.splitlines())
        rows = {c["keyword"]: c for c in self.report()["collisions"]}
        self.assertEqual(list(rows["kappa"]), ["keyword", "owner", "others", "files",
                                               "removed"])  # no `kept` key (D14)


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
        self.assertEqual([j["kind"] for j in self.report()["judgement"]],
                         ["duplicate", "keyword-tie"])  # `price`: formatPrice in both

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

    def test_a_work_item_missing_or_of_the_wrong_shape(self):  # follow-up C and its extension
        rows = ((None, f"{WORK}/work/cart.json is missing — start over: segmently-modules init map "
                       f"--restart"),  # the refusal a claim gives (Work.missing)
                ({"roles": None}, f"{WORK}/work/cart.json: roles is not a list of strings — "
                                  f"fix it, or start over: segmently-modules init map --restart"))
        for change, message in rows:
            for earlier in (False, True):  # no reconcile yet, or one before (rebuilt: --force)
                with self.subTest(change=change, earlier=earlier):
                    self.setUp()
                    if earlier:
                        self.reconcile()
                    cart = self.root / WORK / "work/cart.json"
                    if change is None:
                        cart.unlink()
                    else:
                        cart.write_text(json.dumps({**json.loads(cart.read_text()), **change}))
                    paths = [self.root / WORK / "state.json", self.staging / "registry.json",
                             self.root / WORK / "reconcile.json"]
                    before = [p.read_bytes() if p.exists() else None for p in paths]
                    code, out, err = run("init", "reconcile", *(("--force",) if earlier else ()),
                                         "--json", "--root", str(self.root))
                    self.assertEqual((code, out), (2, ""))
                    self.assertEqual(err, f"segmently-modules: error: {message}\n")
                    self.assertEqual([p.read_bytes() if p.exists() else None for p in paths],
                                     before)  # nothing written
                    self.assertEqual(before[1] is None, not earlier)


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

    def test_a_name_only_modules_created_by_hand_share(self):  # N-6: no row about them
        with tempfile.TemporaryDirectory() as tmp:
            root = shop(Path(tmp).resolve())
            for name, what, words in (("catalog", "Book titles, authors and ISBN lookups.",
                                       "catalog, book, isbn, author, title"),
                                      ("ui-kit", "The shared buttons, prices and layout parts.",
                                       "button, layout, widget, theme, component")):
                ok(root, "create", name, "--non-interactive", "--description", what,
                   "--keywords", words)
            ok(root, "init", "fanout")
            ok(root, "init", "run", "--executor", executor())
            ok(root, "init", "reconcile")
            report = json.loads((root / WORK / "reconcile.json").read_text())
            self.assertEqual(report["duplicates"], [])  # formatPrice: catalog and ui-kit only
            self.assertFalse([j for j in report["judgement"] if j["kind"] == "duplicate"])

    def test_a_hand_written_negative_keyword_is_kept(self):  # P5C-AC-002
        with tempfile.TemporaryDirectory() as tmp:
            root = shop(Path(tmp).resolve())
            ok(root, "create", "catalog", "--non-interactive", "--description",
               "Book titles, authors and ISBN lookups for the shop.", "--keywords",
               "catalog, book, isbn, author, title, price")
            mutate_registry(root, lambda doc: doc["modules"]["catalog"].update(
                negative_keywords=["checkout"]))
            before = json.loads((root / "modules/registry.json").read_text())["modules"]
            ok(root, "init", "fanout")
            ok(root, "init", "run", "--executor", executor())
            ok(root, "init", "reconcile")
            staged = json.loads((root / WORK / "staging/registry.json").read_text())["modules"]
            self.assertEqual(staged["catalog"], before["catalog"])  # its negatives kept
            report = json.loads((root / WORK / "reconcile.json").read_text())
            self.assertFalse([c for c in report["collisions"]
                              if "catalog" in c["others"] + c["removed"]])
            self.assertIn("price", staged["cart"]["keywords"])  # a collision needs two new ones
            self.assertEqual([m for m, e in staged.items() if "negative_keywords" in e],
                             ["catalog"])


if __name__ == "__main__":
    unittest.main()
