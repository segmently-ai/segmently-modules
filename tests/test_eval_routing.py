"""`segmently-modules eval routing` (D3, verb 27): `--tasks` — hits with `context`'s scoring, the threshold
and `--top`, input errors; `--prompt` — what the task writer sees (never the keywords); the
staging overlay while `init` runs."""
import json
import re
import tempfile
import unittest
from pathlib import Path

from segmently_modules.cli import build_parser
from segmently_modules.match import term_pattern
from tests.helpers import git, make_repo, run, run_json
from tests.init_helpers import executor, ok, shop
from tests.test_cli_contract import DOC as CONTRACT, GOLDEN

MODULES = {"catalog": ["catalog", "isbn", "author", "title", "shelf"],
           "cart": ["cart", "basket", "quantity", "total", "line"],
           "storefront": ["storefront", "page", "window", "banner", "render"],
           "ui-kit": ["button", "widget", "form", "label", "field"],
           "payments": ["payment", "charge", "invoice", "gateway", "card"],
           "payments/refunds": ["refund", "partial refund"]}
TABLE = [  # (task, expected, hit?)
    ("catalog isbn lookup", "catalog", True),
    ("the cart basket page window and the isbn", "catalog", True),  # catalog 3rd
    ("cart basket quantity, page window banner, button widget form, and the isbn", "catalog",
     False),  # catalog 4th
    ("nothing about the shop at all", "catalog", False),  # no module reaches min_score
    ("a partial refund please", "payments", True),  # the child counts for its parent
    ("charge the card through the gateway", "payments/refunds", False),  # never the reverse
]


class RoutingRepo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name).resolve()
        self.root = make_repo(self._tmp.name, MODULES)
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def tasks(self, rows, name="tasks.json") -> Path:
        path = self.base / name
        path.write_text(json.dumps([{"task": t, "module": m} for t, m in rows]))
        return path

    def evaluate(self, *argv, code=0) -> dict:
        got, env, err = run_json("eval", "routing", *argv, *self.R)
        self.assertEqual((got, err), (code, ""))
        self.assertEqual(env["schema"], "segmently-modules.eval/1")
        return env["data"]


class HitsTest(RoutingRepo):  # P5B-AC-016
    def test_the_table_and_one_scoring(self):
        path = self.tasks([(t, m) for t, m, _ in TABLE])
        data = self.evaluate("--tasks", str(path), code=1)
        self.assertEqual({k: data[k] for k in ("hit_rate", "top", "tasks", "hits")},
                         {"hit_rate": 0.5, "top": 3, "tasks": 6, "hits": 3})
        rows = {r["module"]: r for r in data["per_module"]}
        self.assertEqual(list(rows), sorted(MODULES))  # every module, name order
        self.assertEqual((rows["ui-kit"]["tasks"], rows["ui-kit"]["misses"]), (0, []))
        misses = {m["task"]: m["got"] for r in data["per_module"] for m in r["misses"]}
        for task, expected, hit in TABLE:
            context = run_json("context", "--task", task, "--top", "3", *self.R)[1]["data"]
            got = [m["module"] for m in context["modules"]]
            with self.subTest(task=task):
                self.assertEqual(task not in misses, hit)
                if not hit:
                    self.assertEqual(misses[task], got)  # the same scoring as context
        self.assertEqual(misses["cart basket quantity, page window banner, button widget form, "
                                "and the isbn"], ["cart", "storefront", "ui-kit"])
        self.assertEqual(misses["nothing about the shop at all"], [])

    def test_text_output(self):
        path = self.tasks([(t, m) for t, m, _ in TABLE])
        code, out, err = run("eval", "routing", "--tasks", str(path), *self.R)
        lines = out.splitlines()
        self.assertEqual((code, err, lines[0]), (1, "", "hit rate 0.5 (3/6, top 3); first "
                                                       "place 0.333; 1.66 module(s) matched "
                                                       "per task"))
        self.assertIn("catalog  2/4 (first 1)", lines)
        self.assertIn("  unused  author, title, shelf", lines)
        self.assertIn('  miss  "nothing about the shop at all" → (no module)', lines)
        self.assertIn('  miss  "charge the card through the gateway" → payments', lines)
        self.assertEqual(lines[-1], "threshold 0.8: FAILED")


class PrecisionTest(RoutingRepo):  # 0.3.0: how precise, not only whether the module is there
    def test_first_place_modules_per_task_and_unused_words(self):
        path = self.tasks([("catalog isbn lookup", "catalog"),  # first
                           ("the cart basket page window and the isbn", "catalog"),  # third
                           ("a partial refund please", "payments")])  # its child, first
        data = self.evaluate("--tasks", str(path))
        self.assertEqual({k: data[k] for k in ("hit_rate", "top1_hit_rate", "mean_matched")},
                         {"hit_rate": 1.0, "top1_hit_rate": 0.666, "mean_matched": 1.66})
        rows = {r["module"]: r for r in data["per_module"]}
        self.assertEqual((rows["catalog"]["hits"], rows["catalog"]["top1_hits"]), (2, 1))
        self.assertEqual(rows["catalog"]["unused_keywords"], ["author", "title", "shelf"])
        self.assertEqual(rows["payments/refunds"]["unused_keywords"], [])
        self.assertEqual(list(data), ["hit_rate", "top1_hit_rate", "mean_matched", "top",
                                      "tasks", "per_module", "hits", "min_hit_rate", "passed"])
        self.assertEqual(list(rows["catalog"]), ["module", "tasks", "hits", "top1_hits",
                                                 "misses", "unused_keywords"])

    def test_a_word_the_code_holds_is_used(self):
        root = make_repo(self.base / "code", MODULES, config=(
            '[[code_map]]\nid = "catalog-code"\nglobs = ["src/catalog/**"]\nmodule = "catalog"\n'))
        (root / "src/catalog").mkdir(parents=True)
        (root / "src/catalog/shelf_view.py").write_text("def findAuthorTitles():\n    pass\n")
        git(root, "init", "-q")
        path = self.tasks([("catalog isbn lookup", "catalog")])
        code, env, err = run_json("eval", "routing", "--tasks", str(path), "--root", str(root))
        rows = {r["module"]: r for r in env["data"]["per_module"]}
        self.assertEqual((code, err), (0, ""))  # the path's `shelf_view` holds `shelf`, the
        self.assertEqual(rows["catalog"]["unused_keywords"], [])  # identifier the rest


class ThresholdTest(RoutingRepo):  # P5B-AC-017 (SI-14)
    HIT, MISS = ("catalog isbn lookup", "catalog"), ("nothing relevant", "catalog")

    def measure(self, n, hits, *flags, code):
        path = self.tasks([self.HIT] * hits + [self.MISS] * (n - hits))
        return self.evaluate("--tasks", str(path), *flags, code=code)["hit_rate"]

    def test_the_boundaries(self):
        self.assertEqual(self.measure(100, 79, code=1), 0.79)
        self.assertEqual(self.measure(100, 80, code=0), 0.8)
        self.assertEqual(self.measure(100, 81, code=0), 0.81)
        self.assertEqual(self.measure(5, 4, code=0), 0.8)
        self.assertEqual(self.measure(3, 2, "--min-hit-rate", "0.667", code=1), 0.666)
        self.assertEqual(self.measure(30, 30, "--min-hit-rate", "1.0", code=0), 1.0)
        self.assertEqual(self.measure(30, 0, "--min-hit-rate", "0", code=0), 0.0)
        (self.root / ".segmently-modules/config.toml").write_text("[init]\nrouting_min_hit_rate = 0.81\n")
        self.assertEqual(self.measure(100, 80, code=1), 0.8)
        self.assertEqual(self.measure(100, 81, code=0), 0.81)

    def test_top(self):
        path = self.tasks([("cart basket isbn", "catalog")])  # catalog ranks 2nd
        self.assertEqual(self.evaluate("--tasks", str(path), "--top", "1", code=1)["hits"], 0)
        for top in ("3", "20"):
            self.assertEqual(self.evaluate("--tasks", str(path), "--top", top)["hits"], 1)
        self.assertEqual(self.evaluate("--tasks", str(path))["top"], 3)
        for top in ("0", "21", "-1"):
            with self.subTest(top=top):
                code, out, err = run("eval", "routing", "--tasks", str(path), "--top", top,
                                     "--json", *self.R)
                self.assertEqual((code, out), (2, ""))
                self.assertIn("--top must be from 1 to 20", err)

    def test_bad_thresholds(self):
        path = self.tasks([self.HIT])
        for value in ("1.01", "-0.1", '"high"', "true"):
            with self.subTest(config=value):
                (self.root / ".segmently-modules/config.toml").write_text(
                    f"[init]\nrouting_min_hit_rate = {value}\n")
                for argv in (("eval", "routing", "--tasks", str(path)), ("lint",)):
                    code, out, err = run(*argv, "--json", *self.R)
                    self.assertEqual((code, out), (2, ""))
                    self.assertIn(".segmently-modules/config.toml: [init] routing_min_hit_rate must be a "
                                  "number from 0 to 1", err)
        (self.root / ".segmently-modules/config.toml").unlink()
        code, out, err = run("eval", "routing", "--tasks", str(path), "--min-hit-rate", "1.5",
                             "--json", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("--min-hit-rate must be from 0 to 1", err)


class InputErrorsTest(RoutingRepo):  # P5B-AC-018 (SI-14)
    def refused(self, *argv) -> str:
        code, out, err = run("eval", *argv, "--json", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith(("segmently-modules: error: ", "usage: ")), err)
        self.assertNotIn("Traceback", err)
        return err

    def test_the_table(self):
        self.assertIn("eval needs an action (routing)", self.refused())
        self.assertIn("unknown eval action 'nosuch'", self.refused("nosuch"))
        self.assertIn("exactly one of --tasks, --prompt", self.refused("routing"))
        good = self.tasks([("catalog isbn", "catalog")])
        self.assertIn("exactly one of --tasks, --prompt",
                      self.refused("routing", "--tasks", str(good), "--prompt"))
        self.assertIn("cannot read ", self.refused("routing", "--tasks",
                                                   str(self.base / "missing.json")))
        cases = [("[]", "no tasks in"), ("{not json", "invalid JSON"),
                 ('{"task": "x", "module": "catalog"}', "not a list"),
                 ('[{"task": "x"}]', "task #1"), ('[{"task": 3, "module": "catalog"}]', "task #1"),
                 ('[{"task": "a", "module": "catalog"}, "b"]', "task #2"),
                 ('[{"task": "x", "module": "nosuch"}]', "unknown module 'nosuch' in")]
        for text, needle in cases:
            with self.subTest(text=text):
                path = self.base / "bad.json"
                path.write_text(text)
                err = self.refused("routing", "--tasks", str(path))
                self.assertIn(needle, err)
                self.assertIn("bad.json", err)

    @unittest.skipIf(__import__("os").geteuid() == 0, "root reads a mode-000 file")
    def test_an_unreadable_file(self):
        path = self.tasks([("catalog isbn", "catalog")])
        path.chmod(0)
        try:
            err = self.refused("routing", "--tasks", str(path))
        finally:
            path.chmod(0o644)
        self.assertIn("cannot read", err)
        self.assertNotIn("internal error", err)


class PromptTest(RoutingRepo):  # P5B-AC-019 (SI-13, SI-14)
    def setUp(self):
        super().setUp()
        registry = self.root / "modules/registry.json"
        doc = json.loads(registry.read_text())
        doc["modules"]["catalog"]["keywords"].append("zqxlisting")
        doc["modules"]["catalog"]["description"] = "Zqx catalog description sentence here"
        registry.write_text(json.dumps(doc, indent=2))
        (self.root / "modules/catalog/MODULE.md").write_text(
            "# Catalog\n\n> Zqx catalog description sentence here\n\n## Purpose\n\n"
            "<!-- a comment -->\nBooks, authors and search.\n\nMore text.\n")
        (self.root / ".segmently-modules/config.toml").write_text(
            '[[code_map]]\nid = "src"\npattern = "src/{module}/**"\n')
        for rel in ("src/catalog/books.py", "src/catalog/search.py", "src/cart/lines.py"):
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text("X = 1\n")
        git(self.root, "init", "-q", "-b", "main")

    def test_what_the_writer_sees(self):
        data = self.evaluate("--prompt")
        self.assertEqual(set(data), {"mode", "per_module", "modules", "prompt"})
        self.assertEqual((data["mode"], data["per_module"], data["modules"]),
                         ("prompt", 5, sorted(MODULES)))
        prompt = data["prompt"]
        block = prompt.split("## `catalog`", 1)[1].split("## `", 1)[0]
        self.assertIn("Books, authors and search.", block)
        self.assertNotIn("More text.", block)
        self.assertIn("Files (2):\n- `src/catalog/books.py`\n- `src/catalog/search.py`", block)
        self.assertIn("For each module write 5 task(s)", prompt)
        self.assertIn('{"task": "<the task>", "module": "<the module name>"}', prompt)
        for secret in ("zqxlisting", "Zqx", "registry.json",
                       *[f"The {m} module." for m in MODULES if "/" not in m]):
            self.assertNotIn(secret, prompt)
        names = {p for m in MODULES for p in m.split("/")}
        for keyword in (k for ks in MODULES.values() for k in ks if k not in names):
            with self.subTest(keyword=keyword):  # a keyword is never shown (a name is)
                self.assertIsNone(term_pattern(keyword).search(prompt.lower()))
        self.assertIn("## `cart`\n\nno purpose paragraph\n\nFiles (1):\n- `src/cart/lines.py`",
                      prompt)
        self.assertNotIn("${", prompt)
        code, out, err = run("eval", "routing", "--prompt", *self.R)
        self.assertEqual((code, out, err), (0, prompt, ""))

    def test_a_blockquote_or_a_comment_inside_the_paragraph(self):  # Task 8 review I1
        doc = self.root / "modules/catalog/MODULE.md"
        doc.write_text("# Catalog\n\n## Purpose\n\nBooks, authors\n> a note in between\n"
                       "and search,\n<!-- a comment\nover two lines -->\nfor every reader.\n"
                       "\nMore text.\n")
        block = self.evaluate("--prompt")["prompt"].split("## `catalog`", 1)[1]
        self.assertIn("\n\nBooks, authors and search, for every reader.\n\n", block)
        self.assertNotIn("More text.", block)
        self.assertNotIn("a note in between", block)

    def test_per_module_and_the_template_chain(self):
        self.assertIn("write 1 task(s)", self.evaluate("--prompt", "--per-module", "1")["prompt"])
        self.assertIn("write 20 task(s)", self.evaluate("--prompt", "--per-module", "20")["prompt"])
        for value in ("0", "21", "x"):
            with self.subTest(per_module=value):
                code, out, _ = run("eval", "routing", "--prompt", "--per-module", value, "--json",
                                   *self.R)
                self.assertEqual((code, out), (2, ""))
        code, out, _ = run("eval", "routing", "--tasks", "t.json", "--per-module", "2", *self.R)
        self.assertEqual((code, out), (2, ""))
        override = self.root / ".segmently-modules/overrides/templates/init/routing_prompt.md"
        override.parent.mkdir(parents=True)
        override.write_text("Team: ${per_module} per module for ${count} modules.\n")
        self.assertEqual(self.evaluate("--prompt")["prompt"],
                         "Team: 5 per module for 6 modules.\n")


class OverlayTest(unittest.TestCase):  # P5B-AC-016 (the staging overlay while init runs)
    def test_eval_routing_reads_the_staging_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = shop(Path(tmp).resolve())
            ok(root, "init", "fanout")
            ok(root, "init", "run", "--executor", executor())
            tasks = Path(tmp) / "tasks.json"
            tasks.write_text(json.dumps([{"task": "the isbn of a book", "module": "catalog"}]))
            code, env, err = run_json("eval", "routing", "--tasks", str(tasks), "--root",
                                      str(root))
            self.assertEqual((code, env), (2, None))  # before reconcile: the empty registry
            self.assertIn("unknown module 'catalog'", err)
            ok(root, "init", "reconcile")
            data = ok(root, "eval", "routing", "--tasks", str(tasks))
            self.assertEqual((data["hits"], [r["module"] for r in data["per_module"]]),
                             (1, ["cart", "catalog", "payments", "recommendations", "storefront",
                                  "ui-kit"]))
            prompt = ok(root, "eval", "routing", "--prompt")["prompt"]
            self.assertIn("## `catalog`\n\nFinds a book by its ISBN and formats its price for "
                          "display.\n\nFiles (3):\n- `packages/catalog/package.json`", prompt)


class ContractTest(unittest.TestCase):  # P5B-AC-037 (the verb count; P6.1 W3-W5: + roles…setup)
    def test_thirty_two_verbs_everywhere(self):
        parser = set(build_parser()._subparsers._group_actions[0].choices)
        contract = set(re.findall(r"^\| `([a-z-]+)", CONTRACT.read_text(encoding="utf-8"), re.M))
        self.assertEqual((len(parser), parser, {argv[0] for argv, _ in GOLDEN}),
                         (32, contract, contract))
        self.assertIn("eval", parser)


if __name__ == "__main__":
    unittest.main()
