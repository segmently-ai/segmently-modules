"""`[search] generic`: the modules that match almost any task (a shared UI kit, a
shared data layer), listed by id; a listed module covers its family (itself and its children,
`<id>/…`). `discover --json`'s `lexical_confidence` leaves their keyword rows out of its verdict,
in this order: `no_hits` (no keyword row), `generic` (keyword rows exist and every one is
generic; `top` = the generic modules at the top score), `tie` / `low_score` over the other rows
only, else `sure` (`top` from the other rows). The module list and every other output stay as
they were; with `generic = []`, or ids that name no module, every output is byte-identical (here
and in `tests/test_search_base_outputs.py`). How a wrong value is refused, how layers add up,
`catalog --settings`, and the docs that say so."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from segmently_modules.config import builtin_packs_root, search_all
from segmently_modules.workspace import Workspace
from tests import test_search_chooser as chooser
from tests.agent_helpers import AgentRepo
from tests.helpers import make_repo, run, run_json

ENGINE = Path(__file__).resolve().parents[1]
WEIGHT_ONE = chooser.WEIGHT_ONE  # a keyword hit scores 1, min_score 1
SHOP = chooser.SHOP  # shelf, till, stock (+ stock/restock), reviews
ALLOWED = "a list of module ids (non-empty strings)"


def flat(text: str) -> str:
    return " ".join(text.split())


def search(generic: list[str] | None) -> str:
    return "" if generic is None else f"\n[search]\ngeneric = {json.dumps(generic)}\n"


class Shop(unittest.TestCase):
    """The synthetic shop of the confidence tests (keyword weight 1: a score is the number of
    keywords hit), with a `[search] generic` list written per call."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = make_repo(self._tmp.name, SHOP, WEIGHT_ONE)
        self.R = ("--root", str(self.root))
        clean = {k: v for k, v in os.environ.items() if not k.startswith("SEGMENTLY_MODULES_")}
        patcher = mock.patch.dict(os.environ, clean, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def use(self, generic: list[str] | None) -> None:
        (self.root / ".segmently-modules/config.toml").write_text(WEIGHT_ONE + search(generic),
                                                                   encoding="utf-8")

    def discover(self, task: str, generic: list[str] | None, *extra) -> tuple[str, dict]:
        """(stdout, data) of `discover --task TASK --match lexical --json` under `generic`."""
        self.use(generic)
        code, out, err = run("discover", "--task", task, "--match", "lexical", *extra, "--json",
                             *self.R)
        self.assertEqual((code, err), (0, ""))
        data = json.loads(out)["data"]
        self.assertEqual(list(data)[0], "lexical_confidence")
        return out, data

    def confidence(self, task: str, generic: list[str] | None) -> dict:
        return self.discover(task, generic)[1]["lexical_confidence"]

    def check(self, task: str, generic: list[str] | None, reason, top: list[str]) -> None:
        self.assertEqual(self.confidence(task, generic),
                         {"level": "sure" if reason is None else "unsure", "reason": reason,
                          "top": top})


class RuleOrderTest(Shop):
    def test_no_hits_comes_first(self):
        self.check("the weather on a sunny day", ["shelf", "till"], "no_hits", [])

    def test_only_generic_rows_is_generic(self):
        self.check("a shelf in the aisle", None, None, ["shelf"])  # sure without the key
        self.check("a shelf in the aisle", ["shelf"], "generic", ["shelf"])

    def test_generic_comes_before_low_score_and_tie(self):
        self.check("a shelf", None, "low_score", ["shelf"])  # review M-2: asserted, not only said
        self.check("a shelf", ["shelf"], "generic", ["shelf"])
        task = "a shelf in the aisle by the till with a receipt"  # shelf 2, till 2
        self.check(task, None, "tie", ["shelf", "till"])
        self.check(task, ["shelf", "till"], "generic", ["shelf", "till"])

    def test_generic_top_is_the_generic_modules_at_the_top_score(self):
        task = "a shelf in the aisle, a bookcase by the till"  # shelf 3, till 1
        self.check(task, ["shelf", "till"], "generic", ["shelf"])

    def test_tie_over_the_other_rows(self):
        # stock 2, stock/restock 2, shelf 1, till 1: one family on top (sure) without the key
        task = "stock in the warehouse from a supplier who will restock, a shelf by the till"
        self.check(task, None, None, ["stock", "stock/restock"])
        self.check(task, ["stock"], "tie", ["shelf", "till"])

    def test_a_lower_generic_row_changes_no_tie(self):
        task = "a shelf in the aisle by the till with a receipt, a review"  # 2, 2, reviews 1
        self.check(task, ["reviews"], "tie", ["shelf", "till"])

    def test_a_generic_row_in_a_tie_is_no_tie(self):
        task = "a shelf in the aisle by the till with a receipt"  # shelf 2, till 2
        self.check(task, ["till"], None, ["shelf"])

    def test_low_score_over_the_other_rows(self):
        task = "a shelf in the aisle by the till"  # shelf 2, till 1
        self.check(task, None, None, ["shelf"])
        self.check(task, ["shelf"], "low_score", ["till"])

    def test_sure_ignores_a_higher_generic_row(self):
        task = "a shelf in the aisle, a bookcase by the till with a receipt"  # shelf 3, till 2
        self.check(task, None, None, ["shelf"])
        self.check(task, ["shelf"], None, ["till"])

    def test_sure_min_score_applies_to_the_other_rows(self):
        task = "a shelf in the aisle, a bookcase by the till with a receipt"  # shelf 3, till 2
        (self.root / ".segmently-modules/config.toml").write_text(
            WEIGHT_ONE + '\n[search]\nsure_min_score = 3\ngeneric = ["shelf"]\n', encoding="utf-8")
        code, env, err = run_json("discover", "--task", task, "--match", "lexical", *self.R)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(env["data"]["lexical_confidence"],
                         {"level": "unsure", "reason": "low_score", "top": ["till"]})


class FamilyTest(Shop):
    def test_a_child_of_a_listed_parent_is_generic(self):
        self.check("a supplier who will restock", ["stock"], "generic", ["stock/restock"])
        task = "stock in the warehouse from a supplier who will restock, a shelf in the aisle"
        self.check(task, None, "tie", ["shelf", "stock", "stock/restock"])
        self.check(task, ["stock"], None, ["shelf"])

    def test_a_listed_child_leaves_its_parent(self):
        task = "stock in the warehouse from a supplier who will restock"  # stock 2, restock 2
        self.check(task, ["stock/restock"], None, ["stock"])
        self.check("a supplier who will restock", ["stock/restock"], "generic", ["stock/restock"])

    def test_an_id_is_a_whole_module_name(self):  # a prefix of a name covers nothing
        self.check("stock in the warehouse", ["sto", "stock/", "she"], None, ["stock"])
        self.check("a shelf in the aisle", ["sto", "stock/", "she"], None, ["shelf"])


class NothingElseChangesTest(Shop):
    def test_an_unknown_id_or_an_empty_list_changes_nothing(self):
        for generic in ([], ["bookmarks"], ["bookmarks", "stock/postcards"]):
            for case, task, level, reason, top in chooser.ConfidenceTableTest.CASES:
                with self.subTest(generic=generic, case=case):
                    base_out, _ = self.discover(task, None)
                    out, data = self.discover(task, generic)
                    self.assertEqual(out, base_out)  # byte for byte
                    self.assertEqual(data["lexical_confidence"],
                                     {"level": level, "reason": reason, "top": top})

    def test_the_module_list_and_the_text_stay(self):
        task = "a shelf in the aisle, a bookcase by the till with a receipt"
        base_out, base = self.discover(task, None)
        out, data = self.discover(task, ["shelf"])
        self.assertNotEqual(out, base_out)  # the verdict changed …
        base.pop("lexical_confidence")
        data.pop("lexical_confidence")
        self.assertEqual(data, base)  # … and nothing else: the generic module stays listed
        self.assertEqual([m["module"] for m in data["modules"]], ["shelf", "till"])
        texts = []
        for generic in (None, ["shelf"]):
            self.use(generic)
            texts.append(run("discover", "--task", task, "--match", "lexical", *self.R))
        # the text's first line is the verdict (2026-10-19), and only it changes
        self.assertEqual([t[1].split("\n", 1)[0] for t in texts],
                         ["lexical: sure (top: shelf)", "lexical: sure (top: till)"])
        self.assertEqual([(t[0], t[1].split("\n", 1)[1], t[2]) for t in texts][0],
                         [(t[0], t[1].split("\n", 1)[1], t[2]) for t in texts][1])
        self.assertEqual(texts[0][0], 0)
        contexts = []
        for generic in (None, ["shelf"]):
            self.use(generic)
            contexts.append(run("context", "--task", task, "--match", "lexical", "--json",
                                *self.R))
        self.assertEqual(contexts[0], contexts[1])


class Split(AgentRepo, unittest.TestCase):
    """The split fixture (catalog, orders with checkout / refunds / invoices, payments)."""

    def settings(self) -> dict:
        code, env, err = run_json("catalog", "--settings", *self.R)
        self.assertEqual((code, err), (0, ""))
        return env["data"]["search"]

    def lexical(self, *extra) -> dict:
        code, env, err = run_json("discover", "--task", "refund", *extra, *self.R)
        self.assertEqual((code, err), (0, ""))
        return env["data"]["lexical_confidence"]


class FixtureTest(Split):
    def test_lexical_and_hybrid(self):  # hybrid with no agent: the keyword rows
        self.config('[search]\ngeneric = ["orders"]\n')
        for mode in ("lexical", "hybrid"):
            with self.subTest(mode=mode):
                self.assertEqual(self.lexical("--match", mode),
                                 {"level": "unsure", "reason": "generic",
                                  "top": ["orders/refunds"]})


class ValuesTest(Split):
    def test_the_default_and_good_values(self):
        for value in (None, [], ["orders"], ["orders", "payments"], ["orders/refunds"],
                      ["bookmarks"]):
            with self.subTest(value=value):
                self.config(search(value))
                want = value or []
                self.assertEqual(self.settings()["generic"], want)
                self.assertEqual(search_all(Workspace.load(self.root).config)["generic"], want)
                for argv in (("catalog",), ("list",), ("lint", "--fail-on", "never"),
                             ("discover", "--task", "refund", "--match", "lexical"),
                             ("choose", "--task", "refund")):
                    self.assertEqual(run(*argv, *self.R)[0], 0, argv)

    def test_a_caller_cannot_change_the_default(self):
        config = Workspace.load(self.root).config
        search_all(config)["generic"].append("orders")
        self.assertEqual(search_all(config)["generic"], [])


class RefusalTest(Split):
    CASES = [  # (line, the value as given)
        ('generic = "orders"', "got 'orders'"),
        ("generic = 1", "got 1"),
        ("generic = true", "got True"),
        ("generic = [1]", "got [1]"),
        ('generic = ["orders", ""]', "got ['orders', '']"),
        ('generic = [""]', "got ['']"),
        ('generic = [["orders"]]', "got [['orders']]"),
        ("generic = { orders = true }", "got {'orders': True}"),
    ]
    VERBS = (("catalog", "--settings", "--json"), ("catalog",), ("list",),
             ("discover", "--task", "refund", "--match", "lexical", "--json"),
             ("choose", "--task", "refund"))

    def test_each_wrong_value_is_exit_2_naming_file_key_allowed_and_value(self):
        for name in ("config.toml", "config.user.toml"):
            for line, given in self.CASES:
                self.config(f"[search]\n{line}\n", name)
                before = chooser.tree_hash(self.root)
                for argv in self.VERBS:
                    with self.subTest(file=name, line=line, argv=argv):
                        code, out, err = run(*argv, *self.R)
                        self.assertEqual((code, out), (2, ""))
                        self.assertTrue(err.startswith("segmently-modules: error: "), err)
                        self.assertNotIn("Traceback", err)
                        self.assertEqual(err.count("\n"), 1, err)
                        self.assertIn(f".segmently-modules/{name}: [search] generic: expected "
                                      f"{ALLOWED}, {given}", err)
                self.assertEqual(chooser.tree_hash(self.root), before)  # nothing written
                (self.root / ".segmently-modules" / name).unlink()

    def test_a_pack_layer_is_checked_too(self):
        pack = self.root / ".segmently-modules/packs/shelfwise"
        pack.mkdir(parents=True)
        (pack / "pack.toml").write_text('id = "shelfwise"\nversion = "0.1.0"\n\n[search]\n'
                                        'generic = "orders"\n', encoding="utf-8")
        code, out, err = run("catalog", "--settings", "--json", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn(f"packs/shelfwise/pack.toml: [search] generic: expected {ALLOWED}, "
                      "got 'orders'", err)


class LayersTest(Split):
    def test_the_layers_add_up(self):  # base order first, each id once
        pack = self.root / ".segmently-modules/packs/shelfwise"
        pack.mkdir(parents=True)
        (pack / "pack.toml").write_text('id = "shelfwise"\nversion = "0.1.0"\n\n[search]\n'
                                        'generic = ["catalog"]\n', encoding="utf-8")
        self.assertEqual(self.settings()["generic"], ["catalog"])
        self.config('[search]\ngeneric = ["orders"]\n')
        self.config('[search]\ngeneric = ["payments", "orders"]\n', "config.user.toml")
        self.assertEqual(self.settings()["generic"], ["catalog", "orders", "payments"])

    def test_the_verdict_takes_every_layer(self):
        self.assertEqual(self.lexical("--match", "lexical")["level"], "sure")
        self.config('[search]\ngeneric = ["payments"]\n')
        self.config('[search]\ngeneric = ["orders"]\n', "config.user.toml")
        self.assertEqual(self.lexical("--match", "lexical")["reason"], "generic")


class SettingsTest(Split):
    def test_json_shows_the_key_last(self):
        self.assertEqual(list(self.settings()), chooser.SEARCH_KEYS)
        self.assertEqual(chooser.SEARCH_KEYS[-1], "generic")
        self.assertEqual(self.settings()["generic"], [])

    def test_text_shows_the_list_as_toml_writes_it(self):
        for value, line in ((None, "generic = []"),
                            (["orders", "payments"], 'generic = ["orders", "payments"]')):
            with self.subTest(value=value):
                self.config(search(value))
                code, out, err = run("catalog", "--settings", *self.R)
                self.assertEqual((code, err), (0, ""))
                search_part = out.split("\n\n[rules]")[0]  # [rules] follows [search] since 2026-10-18
                self.assertEqual(search_part.split("\n")[-1], line)
                self.assertTrue(search_part.split("\n")[-2].startswith("cards = "))

    def test_catalog_without_the_flag_keeps_three_search_keys(self):
        self.config('[search]\ngeneric = ["orders"]\n')
        code, env, err = run_json("catalog", *self.R)
        self.assertEqual(list(env["data"]["search"]), ["claude_model", "codex_model", "effort"])


class DocsTest(unittest.TestCase):
    @staticmethod
    def read(rel: str) -> str:
        return (ENGINE / rel).read_text(encoding="utf-8")

    def test_configuration(self):
        rows = [line for line in self.read("docs/configuration.md").split("\n")
                if line.startswith("| `[search] generic` |")]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertTrue(row.startswith("| `[search] generic` | `[]` | "), row[:40])
        for phrase in ('e.g. `["ui-kit", "data-core"]`',
                       "a listed module covers its family — the module and its children "
                       "(`<id>/…`)",
                       "`unsure` with the reason `generic`",
                       "`tie`, `low_score` and `sure` are decided over the other modules' rows",
                       "They stay in `discover`'s `modules` and in every other output.",
                       "An id that names no module is ignored.",
                       "the ids of every layer add up",
                       f"anything but {ALLOWED} is exit 2 naming the file"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, row)
        table = self.read("docs/configuration.md").split("| `[search] cards` |", 1)[1]
        self.assertTrue(table.split("\n", 1)[1].startswith("| `[search] generic` |"))

    def test_cli_contract(self):
        doc = flat(self.read("docs/cli-contract.md"))
        self.assertIn("`lexical_confidence: {level: sure\\|unsure, reason: "
                      "no_hits\\|generic\\|tie\\|low_score\\|null, top: [module]}`", doc)
        order = ["`unsure` with `no_hits` (no keyword hit)",
                 "else `generic` (every keyword row is a module `[search] generic` lists, or a "
                 "child of one; `top` = those at the top score)",
                 "else, over the other modules' rows only, `tie`",
                 "else `low_score`", "otherwise `sure` with `reason` null",
                 "`top` = the modules at the top score of the rows the verdict is decided over",
                 "The generic modules stay in `modules`."]
        at = [doc.find(p) for p in order]
        self.assertNotIn(-1, at, [p for p, i in zip(order, at) if i < 0])
        self.assertEqual(at, sorted(at))
        self.assertIn("search: {claude_model, codex_model, effort, card_keywords, chooser, "
                      "sure_min_score, cards, generic}", doc)

    def test_changelog(self):
        log = self.read("CHANGELOG.md")
        unreleased = flat(log.split("## [Unreleased]", 1)[1].split("\n## [", 1)[0])
        self.assertIn("`[search] generic` lists the modules that match almost any task", unreleased)
        self.assertIn("the reason `generic`", unreleased)

    def test_readme(self):
        self.assertIn("`generic` = the modules that match almost any task, which alone never make "
                      "the keyword result sure", flat(self.read("README.md")))

    def test_how_to(self):
        howto = (builtin_packs_root() / "core/skills/module-assistant/references/how-to/"
                 "search.md").read_text(encoding="utf-8")
        body = flat(howto.split("## When module-discover runs the chooser", 1)[1]
                    .split("\n## ")[0])
        self.assertIn("a top score below `[search] sure_min_score`, or hits only on modules "
                      "`[search] generic` lists", body)
        self.assertIn('A module that matches almost every task (a shared UI kit) makes '
                      'the keyword result look sure: list it, with the other such modules, under '
                      '`[search]` as `generic = ["<module>"]`', body)


if __name__ == "__main__":
    unittest.main()
