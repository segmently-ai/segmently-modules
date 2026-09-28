"""`init` phase 2, map (D5): candidates and their names, import resolution, CODEOWNERS,
co-change and hints, confidence and keywords, `unassigned` — and row 5.3: `init map` on the
synthetic `bookshop_monorepo` (its history built by `tests/fixtures/build_monorepo.py`) yields
exactly the pinned proposal."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from modsys import mapper, preflight
from modsys.config import load_config
from modsys.create import NAME
from modsys.init_flow import InitFlow
from tests.fixtures.build_monorepo import build
from tests.helpers import git, run, run_json

EXPECTED = {'schema': 'modsys.init-proposal/1',
 'root': '<root>',
 'candidates': [{'name': 'storefront',
                 'include': True,
                 'paths': ['apps/storefront/**'],
                 'confidence': 0.73,
                 'rationale': ['a package root: apps/storefront/package.json names it '
                               "'storefront'",
                               'imports: 0 within the unit, 3 to other candidates (cohesion '
                               '0.0)',
                               'one owner set in CODEOWNERS: @bookshop/web',
                               'co-change: at most 0.3333 with another candidate (ui-kit)'],
                 'signals': {'manifest': 1.0,
                             'cohesion': 0.0,
                             'owners': 1.0,
                             'isolation': 0.6667,
                             'intra_imports': 0,
                             'cross_imports': 3,
                             'owner_sets': [['@bookshop/web']],
                             'co_change': 0.3333,
                             'co_change_partner': 'ui-kit'},
                 'edges': [{'to': 'cart', 'imports': 1},
                           {'to': 'catalog', 'imports': 1},
                           {'to': 'ui-kit', 'imports': 1}],
                 'keywords': ['storefront', 'shop', 'window', 'book', 'pages', 'checkout']},
                {'name': 'cart',
                 'include': True,
                 'paths': ['packages/cart/**'],
                 'confidence': 0.7,
                 'rationale': ['a package root: packages/cart/package.json names it '
                               "'@bookshop/cart'",
                               'imports: 1 within the unit, 1 to other candidates (cohesion '
                               '0.5)',
                               'one owner set in CODEOWNERS: @bookshop/web',
                               'co-change: at most 1.0 with another candidate (catalog)'],
                 'signals': {'manifest': 1.0,
                             'cohesion': 0.5,
                             'owners': 1.0,
                             'isolation': 0.0,
                             'intra_imports': 1,
                             'cross_imports': 1,
                             'owner_sets': [['@bookshop/web']],
                             'co_change': 1.0,
                             'co_change_partner': 'catalog'},
                 'edges': [{'to': 'catalog', 'imports': 1}],
                 'keywords': ['cart', 'bookshop', 'basket', 'lines', 'totals']},
                {'name': 'catalog',
                 'include': True,
                 'paths': ['packages/catalog/**'],
                 'confidence': 0.8,
                 'rationale': ['a package root: packages/catalog/package.json names it '
                               "'@bookshop/catalog'",
                               'imports: 1 within the unit, 0 to other candidates (cohesion '
                               '1.0)',
                               'one owner set in CODEOWNERS: @bookshop/web',
                               'co-change: at most 1.0 with another candidate (cart)'],
                 'signals': {'manifest': 1.0,
                             'cohesion': 1.0,
                             'owners': 1.0,
                             'isolation': 0.0,
                             'intra_imports': 1,
                             'cross_imports': 0,
                             'owner_sets': [['@bookshop/web']],
                             'co_change': 1.0,
                             'co_change_partner': 'cart'},
                 'edges': [],
                 'keywords': ['catalog',
                              'bookshop',
                              'books',
                              'isbn',
                              'book',
                              'titles',
                              'authors']},
                {'name': 'ui-kit',
                 'include': True,
                 'paths': ['packages/ui-kit/**'],
                 'confidence': 0.73,
                 'rationale': ['a package root: packages/ui-kit/package.json names it '
                               "'@bookshop/ui-kit'",
                               'imports: 1 within the unit, 0 to other candidates (cohesion '
                               '1.0)',
                               'co-change: at most 0.3333 with another candidate (storefront)'],
                 'signals': {'manifest': 1.0,
                             'cohesion': 1.0,
                             'owners': 0.0,
                             'isolation': 0.6667,
                             'intra_imports': 1,
                             'cross_imports': 0,
                             'owner_sets': [['@bookshop/design'], ['@bookshop/forms']],
                             'co_change': 0.3333,
                             'co_change_partner': 'storefront'},
                 'edges': [],
                 'keywords': ['ui',
                              'kit',
                              'bookshop',
                              'button',
                              'form',
                              'buttons',
                              'forms',
                              'price',
                              'labels']},
                {'name': 'payments',
                 'include': True,
                 'paths': ['services/payments/**'],
                 'confidence': 0.6,
                 'rationale': ['a package root: services/payments/pyproject.toml names it '
                               "'payments'",
                               'imports: 0 within the unit, 1 to other candidates (cohesion '
                               '0.0)',
                               'one owner set in CODEOWNERS: @bookshop/backend',
                               'co-change: at most 1.0 with another candidate '
                               '(recommendations)'],
                 'signals': {'manifest': 1.0,
                             'cohesion': 0.0,
                             'owners': 1.0,
                             'isolation': 0.0,
                             'intra_imports': 0,
                             'cross_imports': 1,
                             'owner_sets': [['@bookshop/backend']],
                             'co_change': 1.0,
                             'co_change_partner': 'recommendations'},
                 'edges': [{'to': 'recommendations', 'imports': 1}],
                 'keywords': ['payments',
                              'payment',
                              'refund',
                              'charges',
                              'refunds',
                              'book',
                              'orders']},
                {'name': 'recommendations',
                 'include': True,
                 'paths': ['services/recommendations/**'],
                 'confidence': 0.7,
                 'rationale': ['a package root: services/recommendations/pyproject.toml names '
                               "it 'recommendations'",
                               'imports: 1 within the unit, 1 to other candidates (cohesion '
                               '0.5)',
                               'one owner set in CODEOWNERS: @bookshop/backend',
                               'co-change: at most 1.0 with another candidate (payments)'],
                 'signals': {'manifest': 1.0,
                             'cohesion': 0.5,
                             'owners': 1.0,
                             'isolation': 0.0,
                             'intra_imports': 1,
                             'cross_imports': 1,
                             'owner_sets': [['@bookshop/backend']],
                             'co_change': 1.0,
                             'co_change_partner': 'payments'},
                 'edges': [{'to': 'payments', 'imports': 1}],
                 'keywords': ['recommendations',
                              'recommendation',
                              'books',
                              'reader',
                              'like',
                              'next']}],
 'unassigned': ['tools/report.js', 'tools/seed.py'],
 'hints': [{'kind': 'merge',
            'candidates': ['payments', 'recommendations'],
            'reason': 'they import each other and change together (Jaccard 3/3 of the recent '
                      'commits)'},
           {'kind': 'split',
            'candidates': ['ui-kit'],
            'reason': 'its files have disjoint owner sets in CODEOWNERS: @bookshop/design; '
                      '@bookshop/forms'}]}


def write_files(root: Path, files: dict) -> Path:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        (path.write_bytes if isinstance(text, bytes) else path.write_text)(text)
    return root


def commit(root: Path, history: list[list[str]]) -> None:
    """A git repository: the first commit adds everything, each later one touches its files."""
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "--", ".")
    git(root, "commit", "-q", "-m", "first")
    for n, paths in enumerate(history, start=2):
        for rel in paths:
            with (root / rel).open("a") as fh:
                fh.write(f"# change {n}\n")
        git(root, "add", "--", *paths)
        git(root, "commit", "-q", "-m", f"change {n}")


def proposal(root: Path) -> dict:
    """The proposal `init map` would write (computed, nothing written)."""
    root = Path(root).resolve()
    flow = InitFlow(root, root / ".modsys", load_config(root / ".modsys", root))
    return flow.map(False, True)["proposal"]


def rows(doc: dict) -> list[tuple]:
    return [(c["name"], c["paths"]) for c in doc["candidates"]]


class MapRepo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name).resolve()

    def tearDown(self):
        self._tmp.cleanup()


class MonorepoTest(MapRepo):  # P5A-AC-037 (row 5.3)
    def setUp(self):
        super().setUp()
        self.root = build(self.base / "shop")
        for argv in (("init",), ("init", "map")):
            code, _, err = run_json(*argv, "--root", str(self.root))
            self.assertEqual((code, err), (0, ""))
        self.work = self.root / ".modsys/init"

    def written(self) -> dict:
        return json.loads((self.work / "proposal.json").read_text(encoding="utf-8"))

    def test_the_pinned_proposal(self):
        self.assertEqual(self.written(), {**EXPECTED, "root": str(self.root)})
        doc = self.written()
        self.assertEqual(rows(doc), [
            ("storefront", ["apps/storefront/**"]), ("cart", ["packages/cart/**"]),
            ("catalog", ["packages/catalog/**"]), ("ui-kit", ["packages/ui-kit/**"]),
            ("payments", ["services/payments/**"]),
            ("recommendations", ["services/recommendations/**"])])
        edges = sorted((c["name"], e["to"]) for c in doc["candidates"] for e in c["edges"])
        self.assertEqual(edges, [("cart", "catalog"), ("payments", "recommendations"),
                                 ("recommendations", "payments"), ("storefront", "cart"),
                                 ("storefront", "catalog"), ("storefront", "ui-kit")])
        self.assertEqual([(h["kind"], h["candidates"]) for h in doc["hints"]],
                         [("merge", ["payments", "recommendations"]), ("split", ["ui-kit"])])
        self.assertEqual(doc["unassigned"], ["tools/report.js", "tools/seed.py"])
        self.assertNotIn("formatPrice", json.dumps(doc))  # one name exported by two packages

    def test_determinism(self):
        first = [(self.work / n).read_bytes() for n in ("preflight.json", "proposal.json")]
        code, _, err = run_json("init", "map", "--root", str(self.root))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual([(self.work / n).read_bytes() for n in ("preflight.json",
                                                                 "proposal.json")], first)
        other = build(self.base / "elsewhere")
        self.assertEqual(git(other, "rev-parse", "HEAD"), git(self.root, "rev-parse", "HEAD"))
        self.assertEqual(proposal(other), {**self.written(), "root": str(other)})

    def test_the_unedited_proposal_confirms(self):
        code, env, err = run_json("init", "confirm", "--root", str(self.root))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(len(env["data"]["included"]), 6)


class CandidatesTest(MapRepo):  # P5A-AC-033
    def candidates(self, files: dict) -> list[tuple]:
        root = self.base / f"r{len(list(self.base.iterdir()))}"
        doc = proposal(write_files(root, files))
        for c in doc["candidates"]:
            self.assertIs(c["include"], True)
            self.assertTrue(NAME.fullmatch(c["name"]) and len(c["name"]) <= 48, c["name"])
        flow = InitFlow(root, root / ".modsys", load_config(root / ".modsys", root))
        self.assertEqual(flow.validate(doc), [])  # an unedited proposal always passes
        self.doc = doc
        return rows(doc)

    def test_the_decision_table(self):
        js = "export const a = 1;\n"
        self.assertEqual(self.candidates({
            "package.json": '{"workspaces": ["packages/*"]}',
            "packages/a/package.json": '{"name": "a"}', "packages/a/index.js": js,
            "packages/b/package.json": '{"name": "b"}', "packages/b/index.js": js}),
            [("a", ["packages/a/**"]), ("b", ["packages/b/**"])])
        self.assertEqual(self.candidates({"package.json": '{"name": "app"}',
                                          "src/x/a.js": js, "src/y/b.js": js}),
                         [("x", ["src/x/**"]), ("y", ["src/y/**"])])
        self.assertEqual([n for n, _ in self.candidates(
            {f"{d}/{u}/m.py": "X = 1\n" for d, u in [("src", "x"), ("lib", "y"), ("app", "z"),
                                                     ("packages", "p"), ("services", "s"),
                                                     ("apps", "q")]})],
            ["x", "y", "z", "p", "s", "q"])
        self.assertEqual(self.candidates({"shelf/a.py": "X = 1\n", "till/b.py": "X = 1\n",
                                          "docs/readme.md": "# docs\n"}),
                         [("shelf", ["shelf/**"]), ("till", ["till/**"])])
        self.assertEqual(self.candidates({
            "packages/a/package.json": '{"name": "a"}', "packages/a/index.js": js,
            "packages/a/examples/demo/package.json": '{"name": "demo"}'}),
            [("a", ["packages/a/**"])])
        self.assertIn("packages/a/examples/demo", " ".join(self.doc["candidates"][0]["rationale"]))
        self.assertEqual(self.candidates({"packages/a/package.json": "{not json",
                                          "packages/a/index.js": js}), [("a", ["packages/a/**"])])
        self.assertEqual([n for n, _ in self.candidates({
            "packages/c/package.json": '{"name": "@bookshop/catalog"}',
            "services/s/pyproject.toml": '[project]\nname = "Book_Shelf"\n'})],
            ["catalog", "book-shelf"])
        self.assertEqual([n for n, _ in self.candidates({"packages/catalog/a.py": "X = 1\n",
                                                         "services/catalog/b.py": "X = 1\n"})],
                         ["packages-catalog", "services-catalog"])


class UniqueNamesTest(MapRepo):  # P5A-AC-033, SI-15: every unit gets a unique, valid name
    LONG = "inventory-reconciliation-and-warehouse-sync-service"  # 51 characters

    @staticmethod
    def unit(d: str, name: str | None = None) -> dict:
        return {"dir": d, "rationale": [],
                "manifest": {"name": name, "kind": "package.json"} if name else None}

    def test_names_that_collide(self):
        cut = self.LONG[:48]  # both long names read the same after the 48-character cut
        for found, expected in [
            ([self.unit("billing", "app"), self.unit("shipping", "app")],
             ["billing", "shipping"]),  # top-level units fall back too
            ([self.unit("services/billing", "app"), self.unit("services/shipping", "app")],
             ["billing", "shipping"]),  # siblings: their own directory names
            ([self.unit("packages/a", "@one/utils"), self.unit("packages/b", "@two/utils")],
             ["a", "b"]),
            ([self.unit(f"packages/{self.LONG}-east"), self.unit(f"packages/{self.LONG}-west")],
             [cut, cut[:46] + "-2"]),  # unique only before the cut: a numeric suffix
            ([self.unit("billing", "app"), self.unit("shipping", "app"),
              self.unit("x", "billing")], ["billing", "shipping", "x"]),  # a fallback collides
            ([self.unit("a_b"), self.unit("a-b"), self.unit("a-b-2")],
             ["a-b", "a-b-3", "a-b-2"])]:  # a suffix never takes another unit's name
            with self.subTest(dirs=[u["dir"] for u in found]):
                got = mapper.names(found)
                self.assertEqual(got, expected)
                self.assertEqual(len(set(got)), len(got))
                for name in got:
                    self.assertTrue(NAME.fullmatch(name) and len(name) <= 48, name)

    def test_the_unedited_proposal_confirms(self):
        py = '[project]\nname = "app"\n'
        repos = {
            "cookie-cutter": {"billing/pyproject.toml": py, "billing/app/main.py": "X = 1\n",
                              "shipping/pyproject.toml": py, "shipping/app/main.py": "X = 1\n"},
            "siblings": {"services/billing/pyproject.toml": py,
                         "services/billing/app/main.py": "X = 1\n",
                         "services/shipping/pyproject.toml": py,
                         "services/shipping/app/main.py": "X = 1\n"},
            "scopes": {"packages/a/package.json": '{"name": "@one/utils"}',
                       "packages/a/index.js": "var a = 1;\n",
                       "packages/b/package.json": '{"name": "@two/utils"}',
                       "packages/b/index.js": "var b = 1;\n"},
            "long": {f"packages/{self.LONG}-{side}/{rel}": text for side in ("east", "west")
                     for rel, text in (("package.json", f'{{"name": "{self.LONG}-{side}"}}'),
                                       ("index.js", "var x = 1;\n"))}}
        for label, files in repos.items():
            with self.subTest(repo=label):
                root = write_files(self.base / label, files)
                commit(root, [])
                code, env, err = run_json("init", "map", "--root", str(root))
                self.assertEqual((code, err), (0, ""))
                names = env["data"]["candidates"]
                self.assertEqual(len(set(names)), 2, names)
                code, env, err = run_json("init", "confirm", "--root", str(root))
                self.assertEqual((code, err), (0, ""), env)
                self.assertEqual(env["data"]["included"], names)


class ImportsTest(MapRepo):  # P5A-AC-034
    def test_the_statement_table(self):
        root = write_files(self.base / "shop", {
            "packages/cart/package.json": '{"name": "@bookshop/cart"}',
            "packages/cart/src/index.ts": (
                "import { price } from '@bookshop/catalog';\n"
                "import { fmt } from '@bookshop/catalog/utils';\n"
                "export * from './util';\n"
                "import './style';\n"
                "const x = require('../../catalog/src/x');\n"
                "const kit = import('@bookshop/ui-kit');\n"
                "const other = import(name);\n"
                "import React from 'react';\n"),
            "packages/cart/src/util.ts": "export const u = 1;\n",
            "packages/cart/src/style/index.ts": "export const s = 1;\n",
            "packages/cart/src/bad.ts": b"\xff\xfe import k from '@bookshop/ui-kit';\n",
            "packages/catalog/package.json": '{"name": "@bookshop/catalog"}',
            "packages/catalog/src/x.ts": "export const x = 1;\n",
            "packages/ui-kit/package.json": '{"name": "@bookshop/ui-kit"}',
            "packages/ui-kit/src/index.ts": "export const k = 1;\n",
            "services/payments/pyproject.toml": '[project]\nname = "payments"\n',
            "services/payments/payments/__init__.py": "",
            "services/payments/payments/gateway.py": "def charge():\n    return 1\n",
            "services/recommendations/pyproject.toml": '[project]\nname = "recommendations"\n',
            "services/recommendations/recommendations/__init__.py": "",
            "services/recommendations/recommendations/model.py": "X = 1\n",
            "services/recommendations/recommendations/util.py": "U = 1\n",
            "services/recommendations/recommendations/engine.py": (
                "import os\nfrom payments.gateway import charge\nimport payments\n"
                "from .model import X\nfrom . import util\nimport shared\n"),
            "services/twin-a/pyproject.toml": '[project]\nname = "twin-a"\n',
            "services/twin-a/shared/__init__.py": "",
            "services/twin-b/pyproject.toml": '[project]\nname = "twin-b"\n',
            "services/twin-b/shared/__init__.py": ""})
        doc = {c["name"]: c for c in proposal(root)["candidates"]}
        self.assertEqual(doc["cart"]["edges"], [{"to": "catalog", "imports": 3},
                                                {"to": "ui-kit", "imports": 1}])
        self.assertEqual(doc["cart"]["signals"]["intra_imports"], 2)
        self.assertEqual(doc["recommendations"]["edges"], [{"to": "payments", "imports": 2}])
        self.assertEqual(doc["recommendations"]["signals"]["intra_imports"], 2)
        for c in doc.values():
            self.assertNotIn(c["name"], [e["to"] for e in c["edges"]])  # no self edge
            self.assertEqual([e["to"] for e in c["edges"]], sorted(e["to"] for e in c["edges"]))


class OwnersAndCoChangeTest(MapRepo):  # P5A-AC-035
    UNITS = {"packages/cart/package.json": '{"name": "cart"}',
             "packages/cart/a.js": "export const a = 1;\n",
             "packages/cart/forms/b.js": "export const b = 1;\n"}

    def owners(self, files: dict) -> dict:
        doc = proposal(write_files(self.base / f"o{len(list(self.base.iterdir()))}",
                                   {**self.UNITS, **files}))
        self.doc = doc
        return doc["candidates"][0]["signals"]["owner_sets"]

    def test_codeowners(self):
        self.assertEqual(self.owners({".github/CODEOWNERS": "* @a\n", "CODEOWNERS": "* @z\n"}),
                         [["@a"]])
        self.assertEqual(self.owners({"CODEOWNERS": "* @a\n/packages/cart/ @b\n"}), [["@b"]])
        self.assertEqual(self.owners({"CODEOWNERS": "* @a\n!x @c\n[ab].js @d\n"}), [["@a"]])
        self.assertEqual(self.owners({"CODEOWNERS": "* @a\n/packages/cart/forms/ @b\n"}),
                         [["@a"], ["@b"]])
        self.assertEqual([(h["kind"], h["candidates"]) for h in self.doc["hints"]],
                         [("split", ["cart"])])
        self.assertEqual(self.owners({"CODEOWNERS": "* @a @b\n/packages/cart/forms/ @b\n"}),
                         [["@a", "@b"], ["@b"]])
        self.assertEqual(self.doc["hints"], [])

    def pair(self, history: list[list[str]], both_ways: bool = True) -> list:
        root = self.base / f"p{len(list(self.base.iterdir()))}"
        write_files(root, {
            "services/p/pyproject.toml": '[project]\nname = "p"\n',
            "services/p/p/__init__.py": "import q\n" if both_ways else "",
            "services/q/pyproject.toml": '[project]\nname = "q"\n',
            "services/q/q/__init__.py": "import p\n"})
        commit(root, history)
        return [(h["kind"], h["candidates"]) for h in proposal(root)["hints"]]

    def test_the_jaccard_boundary_and_the_hints(self):
        self.assertEqual([mapper.co_changed(i, u) for i, u in [(59, 100), (3, 5), (60, 100),
                                                               (61, 100), (0, 0)]],
                         [False, True, True, True, False])
        p, q = "services/p/p/__init__.py", "services/q/q/__init__.py"
        merge = [("merge", ["p", "q"])]
        self.assertEqual(self.pair([[p, q], [p, q], [p], [q]]), merge)  # 3/5
        self.assertEqual(self.pair([[p, q], [p], [q], [p]]), [])  # 2/5
        self.assertEqual(self.pair([[p, q], [p, q], [p, q], [p]], both_ways=False), [])  # 0.8
        root = write_files(self.base / "untouched", {
            "services/p/pyproject.toml": '[project]\nname = "p"\n',
            "services/p/p/__init__.py": "import q\n",
            "services/q/pyproject.toml": '[project]\nname = "q"\n',
            "services/q/q/__init__.py": "import p\n", "README.md": "# r\n"})
        git(root, "init", "-q", "-b", "main")
        git(root, "add", "--", "README.md")
        git(root, "commit", "-q", "-m", "readme only")
        self.assertEqual(proposal(root)["hints"], [])  # never changed: Jaccard 0

    def test_hints_never_change_the_candidates(self):
        root = build(self.base / "shop")
        with_all = proposal(root)
        (root / ".github/CODEOWNERS").unlink()
        (root / ".modsys").mkdir()
        (root / ".modsys/config.toml").write_text("[init]\nco_change_commits = 0\n")
        without = proposal(root)
        self.assertEqual([(c["name"], c["include"], c["paths"]) for c in with_all["candidates"]],
                         [(c["name"], c["include"], c["paths"]) for c in without["candidates"]])
        self.assertEqual(without["hints"], [])


class ConfidenceAndKeywordsTest(MapRepo):  # P5A-AC-036
    def test_confidence_is_recomputable(self):
        for c in EXPECTED["candidates"]:
            s = c["signals"]
            with self.subTest(candidate=c["name"]):
                self.assertEqual(c["confidence"], round(0.4 * s["manifest"] + 0.2 * s["cohesion"]
                                                        + 0.2 * s["owners"]
                                                        + 0.2 * s["isolation"], 2))
                self.assertTrue(0 <= c["confidence"] <= 1)
        doc = proposal(write_files(self.base / "bare", {"packages/a/package.json": '{"name": "a"}',
                                                        "packages/a/index.js": "var a = 1;\n"}))
        self.assertEqual(doc["candidates"][0]["confidence"], 0.4)
        self.assertEqual(len(doc["candidates"][0]["rationale"]), 1)

    def test_rationale_keywords_and_unassigned(self):
        catalog = next(c for c in EXPECTED["candidates"] if c["name"] == "catalog")
        why = " ".join(catalog["rationale"])
        for needle in ("packages/catalog/package.json", "1 within the unit", "@bookshop/web",
                       "(cart)"):
            self.assertIn(needle, why)
        self.assertEqual(catalog["keywords"], ["catalog", "bookshop", "books", "isbn", "book",
                                               "titles", "authors"])
        self.assertEqual(EXPECTED["unassigned"], ["tools/report.js", "tools/seed.py"])
        for never in ("README.md", ".github/CODEOWNERS", "package.json"):
            self.assertNotIn(never, EXPECTED["unassigned"])


class InitKeysTest(MapRepo):  # P5A-AC-032 (the effect of [init] exclude and co_change_commits)
    def test_exclude(self):
        root = build(self.base / "shop")
        (root / ".modsys").mkdir()
        (root / ".modsys/config.toml").write_text('[init]\nexclude = ["tools/**"]\n')
        doc = proposal(root)
        self.assertEqual(doc["unassigned"], [])
        self.assertFalse([p for c in doc["candidates"] for p in c["paths"] if "tools" in p])
        code, env, err = run_json("init", "map", "--dry-run", "--root", str(root))
        self.assertEqual((code, err), (0, ""))
        flow = InitFlow(root, root / ".modsys", load_config(root / ".modsys", root))
        self.assertFalse([f for f in flow.files() if f.startswith("tools/")])

    def test_co_change_commits(self):
        root = build(self.base / "shop")
        (root / ".modsys").mkdir()
        (root / ".modsys/config.toml").write_text("[init]\nco_change_commits = 0\n")
        real = subprocess.run
        logs = []
        with mock.patch("subprocess.run", side_effect=lambda argv, **kw: (
                logs.append(argv) if "log" in argv else None) or real(argv, **kw)):
            doc = proposal(root)
        self.assertEqual(logs, [])
        self.assertEqual({c["signals"]["isolation"] for c in doc["candidates"]}, {0.0})
        self.assertEqual([h["kind"] for h in doc["hints"]], ["split"])
        small = write_files(self.base / "three", {"a.py": "A = 1\n"})
        commit(small, [["a.py"], ["a.py"]])
        self.assertEqual([len(mapper.co_change(small, n)) for n in (2, 3, 4)], [2, 3, 3])


class CostTest(MapRepo):  # P5A-AC-045 (the spies; the timings are recorded at the gate)
    def test_one_listing_one_log_one_read_per_file(self):
        root = build(self.base / "shop")
        listings, logs, reads = [], [], []
        real_list, real_read, real_run = preflight.list_files, preflight._read, subprocess.run
        with mock.patch("modsys.preflight.list_files",
                        side_effect=lambda *a: listings.append(1) or real_list(*a)), \
                mock.patch("modsys.preflight._read",
                           side_effect=lambda p: reads.append(p) or real_read(p)), \
                mock.patch("subprocess.run", side_effect=lambda argv, **kw: (
                    logs.append(argv) if "log" in argv else None) or real_run(argv, **kw)):
            code, _, err = run("init", "map", "--root", str(root))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual((len(listings), len(logs)), (1, 1))
        self.assertEqual(len(reads), len(set(reads)))
        self.assertTrue(reads)

    def test_an_empty_codeowners_and_files_that_are_not_utf8_or_text(self):
        root = build(self.base / "shop")
        odd = {".github/CODEOWNERS": b"",
               "packages/cart/src/latin1.ts": b"// caf\xe9\nimport x from './lines';\n",
               "services/payments/payments/latin1.py": b"# caf\xe9\nimport os\n",
               "packages/cart/src/nul.ts": b"\0import k from '@bookshop/ui-kit';\n",
               "tools/package.json": b'{"name": "caf\xe9"}\n'}
        for rel, data in odd.items():
            (root / rel).write_bytes(data)
        reads, real = [], preflight._read
        with mock.patch("modsys.preflight._read",
                        side_effect=lambda p: reads.append(p) or real(p)):
            code, _, err = run("init", "map", "--root", str(root))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual([p for p in set(reads) if reads.count(p) > 1], [])
        for rel in odd:
            self.assertIn(root / rel, reads)


if __name__ == "__main__":
    unittest.main()
