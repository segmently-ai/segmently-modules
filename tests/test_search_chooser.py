"""The chooser setting (DCP-AC-001…005, 008, 010, 022): `[search] chooser`, `sure_min_score` and
`cards`, how they merge and how a wrong value is refused; `catalog --settings`; the keyword
result's confidence in `discover --json` (`lexical_confidence`); the compact cards of
`choose --cards brief`; a non-JSON answer piped to `choose --apply -`."""
from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from segmently_modules.config import search_all
from segmently_modules.workspace import Workspace
from tests.agent_helpers import AgentRepo, picks
from tests.helpers import make_repo, run, run_json

ENGINE = Path(__file__).resolve().parents[1]
SEARCH_KEYS = ["claude_model", "codex_model", "effort", "card_keywords", "chooser",
               "sure_min_score", "cards", "generic"]  # + generic (tests/test_dcp_generic.py)
MATCH_KEYS = ["mode", "semantic", "keyword_weight", "combination_weight", "negative_weight",
              "min_score", "top", "normalize"]


def tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        h.update(p.relative_to(root).as_posix().encode())
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


class Split(AgentRepo, unittest.TestCase):
    """The split fixture (catalog, orders with checkout / refunds / invoices, payments)."""

    def settings(self) -> dict:
        code, env, err = run_json("catalog", "--settings", *self.R)
        self.assertEqual((code, err), (0, ""))
        return env["data"]


class ChooserValuesTest(Split):  # DCP-AC-001
    def test_three_values_and_the_default(self):
        for value in ("always", "when_unsure", "never", None):
            with self.subTest(value=value):
                self.config(f'[search]\nchooser = "{value}"\n' if value else "")
                want = value or "always"
                self.assertEqual(self.settings()["search"]["chooser"], want)
                config = Workspace.load(self.root).config
                self.assertEqual(search_all(config)["chooser"], want)
                for argv in (("catalog",), ("list",), ("lint", "--fail-on", "never"),
                             ("discover", "--task", "refund", "--match", "lexical")):
                    self.assertEqual(run(*argv, *self.R)[0], 0, argv)

    def test_defaults_of_the_other_keys(self):
        search = self.settings()["search"]
        self.assertEqual((search["sure_min_score"], search["cards"]), (2, "full"))
        self.config('[search]\nsure_min_score = 5\ncards = "brief"\n')
        search = self.settings()["search"]
        self.assertEqual((search["sure_min_score"], search["cards"]), (5, "brief"))


class RefusalTest(Split):  # DCP-AC-002
    CASES = [  # (line, the key, the allowed values, the value as given)
        ('chooser = "sometimes"', "[search] chooser", "always, when_unsure, never",
         "'sometimes'"),
        ("chooser = 1", "[search] chooser", "always, when_unsure, never", "got 1"),
        ("chooser = true", "[search] chooser", "always, when_unsure, never", "got True"),
        ("sure_min_score = -1", "[search] sure_min_score", "an integer >= 1", "got -1"),
        ('sure_min_score = "2"', "[search] sure_min_score", "an integer >= 1", "got '2'"),
        ("sure_min_score = 0", "[search] sure_min_score", "an integer >= 1", "got 0"),
        ("sure_min_score = true", "[search] sure_min_score", "an integer >= 1", "got True"),
        ("sure_min_score = 1.5", "[search] sure_min_score", "an integer >= 1", "got 1.5"),
        ('cards = "tiny"', "[search] cards", "full, brief", "got 'tiny'"),
        ("cards = 1", "[search] cards", "full, brief", "got 1"),
    ]
    VERBS = (("catalog", "--settings", "--json"), ("catalog",), ("list",),
             ("discover", "--task", "refund", "--match", "lexical", "--json"),
             ("choose", "--task", "refund"))

    def test_each_wrong_value_is_exit_2_naming_file_key_values_and_value(self):
        for name in ("config.toml", "config.user.toml"):
            for line, key, allowed, given in self.CASES:
                self.config(f"[search]\n{line}\n", name)
                before = tree_hash(self.root)
                for argv in self.VERBS:
                    with self.subTest(file=name, line=line, argv=argv):
                        code, out, err = run(*argv, *self.R)
                        self.assertEqual((code, out), (2, ""))
                        self.assertTrue(err.startswith("segmently-modules: error: "), err)
                        self.assertNotIn("Traceback", err)
                        self.assertEqual(err.count("\n"), 1, err)
                        for needle in (f".segmently-modules/{name}: {key}: expected", allowed,
                                       given):
                            self.assertIn(needle, err)
                self.assertEqual(tree_hash(self.root), before)  # nothing written
                (self.root / ".segmently-modules" / name).unlink()

    def test_a_pack_layer_is_checked_too(self):
        pack = self.root / ".segmently-modules/packs/shelfwise"
        pack.mkdir(parents=True)
        (pack / "pack.toml").write_text('id = "shelfwise"\nversion = "0.1.0"\n\n[search]\n'
                                        'chooser = "sometimes"\n', encoding="utf-8")
        code, out, err = run("catalog", "--settings", "--json", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("packs/shelfwise/pack.toml: [search] chooser: expected one of always, "
                      "when_unsure, never, got 'sometimes'", err)


class LayersTest(Split):  # DCP-AC-003
    def test_the_user_config_wins(self):
        self.config('[search]\nchooser = "always"\n')
        self.config('[search]\nchooser = "never"\n', "config.user.toml")
        self.assertEqual(self.settings()["search"]["chooser"], "never")

    def test_a_pack_value_shows_when_only_a_pack_sets_it(self):
        pack = self.root / ".segmently-modules/packs/shelfwise"
        pack.mkdir(parents=True)
        (pack / "pack.toml").write_text(
            'id = "shelfwise"\nversion = "0.1.0"\n\n[search]\nchooser = "when_unsure"\n'
            'sure_min_score = 3\ncards = "brief"\n', encoding="utf-8")
        search = self.settings()["search"]
        self.assertEqual((search["chooser"], search["sure_min_score"], search["cards"]),
                         ("when_unsure", 3, "brief"))
        self.config('[search]\nchooser = "never"\n')  # the team config over the pack
        self.assertEqual(self.settings()["search"]["chooser"], "never")


class SettingsTest(Split):  # DCP-AC-022
    def test_json_holds_only_match_and_search_with_every_key(self):
        code, out, err = run("catalog", "--settings", "--json", *self.R)
        self.assertEqual((code, err), (0, ""))
        env = json.loads(out)
        self.assertEqual(env["schema"], "segmently-modules.catalog/1")
        data = env["data"]
        self.assertEqual(list(data), ["match", "search", "rules", "discover"])  # [rules] mode since 2026-10-18,
        self.assertEqual(data["rules"], {"index": "sync"})  # [discover] since 2026-10-20 (module-discover's save)
        self.assertEqual(data["discover"], {"docs": "all", "read": "whole", "save": "always",
                                            "save_dir": ".segmently-modules/tasks"})
        self.assertEqual(list(data["search"]), SEARCH_KEYS)
        self.assertEqual(list(data["match"]), MATCH_KEYS)
        self.assertEqual(data["search"], {
            "claude_model": "sonnet", "codex_model": "gpt-5.6-luna", "effort": "standard",
            "card_keywords": 10, "chooser": "always", "sure_min_score": 2, "cards": "full",
            "generic": []})
        self.assertEqual(data["match"], {
            "mode": "lexical", "semantic": False, "keyword_weight": 3, "combination_weight": 2,
            "negative_weight": -5, "min_score": 3, "top": 8, "normalize": "suffix"})
        catalog = run_json("catalog", *self.R)[1]["data"]
        for group in ("match", "search"):  # what `catalog --json` shows, the same values
            for key, value in catalog[group].items():
                self.assertEqual(data[group][key], value, (group, key))

    def test_the_values_follow_the_config(self):
        self.config('[match]\nmode = "hybrid"\nnormalize = "none"\ntop = 4\n\n[search]\n'
                    'effort = "deep"\ncard_keywords = 2\nchooser = "when_unsure"\n')
        data = self.settings()
        self.assertEqual((data["match"]["mode"], data["match"]["normalize"],
                          data["match"]["top"]), ("hybrid", "none", 4))
        self.assertEqual((data["search"]["effort"], data["search"]["card_keywords"],
                          data["search"]["chooser"]), ("deep", 2, "when_unsure"))

    def test_text_is_one_line_per_key_under_two_headings(self):
        code, out, err = run("catalog", "--settings", *self.R)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, "[match]\nmode = \"lexical\"\nsemantic = false\n"
                              "keyword_weight = 3\ncombination_weight = 2\nnegative_weight = -5\n"
                              "min_score = 3\ntop = 8\nnormalize = \"suffix\"\n\n"
                              "[search]\nclaude_model = \"sonnet\"\n"
                              "codex_model = \"gpt-5.6-luna\"\neffort = \"standard\"\n"
                              "card_keywords = 10\nchooser = \"always\"\nsure_min_score = 2\n"
                              "cards = \"full\"\ngeneric = []\n\n[rules]\nindex = \"sync\"\n\n"
                              "[discover]\ndocs = \"all\"\nread = \"whole\"\nsave = \"always\"\n"
                              "save_dir = \".segmently-modules/tasks\"\n")

    def test_no_module_card_and_no_registry_read(self):
        out = run("catalog", "--settings", *self.R)[1]
        self.assertNotIn("orders", out)
        (self.root / "modules/registry.json").write_text("{ not json", encoding="utf-8")
        self.assertEqual(run("catalog", "--settings", "--json", *self.R)[0], 0)
        self.assertEqual(run("catalog", "--json", *self.R)[0], 2)

    def test_catalog_without_the_flag_keeps_three_search_keys(self):
        self.config('[search]\nchooser = "never"\nsure_min_score = 4\ncards = "brief"\n')
        data = run_json("catalog", *self.R)[1]["data"]
        self.assertEqual(list(data), ["match", "search", "modules"])
        self.assertEqual(list(data["search"]), ["claude_model", "codex_model", "effort"])
        self.assertEqual(list(data["match"]), ["mode", "semantic"])


# --- the keyword result's confidence (DCP-AC-004, 005) ---------------------------------------

WEIGHT_ONE = "[match]\nkeyword_weight = 1\nmin_score = 1\n"
SHOP = {"shelf": ["shelf", "aisle", "bookcase"], "till": ["till", "receipt", "cash"],
        "stock": ["stock", "warehouse"], "stock/restock": ["restock", "supplier"],
        "reviews": ["review", "rating"]}


class Shop(unittest.TestCase):
    """A synthetic shop whose keyword weight is 1: a score is the number of keywords hit."""
    CONFIG = WEIGHT_ONE

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = make_repo(self._tmp.name, SHOP, self.CONFIG)
        self.R = ("--root", str(self.root))

    def discover(self, task: str, *extra) -> dict:
        code, env, err = run_json("discover", "--task", task, "--match", "lexical", *extra,
                                  *self.R)
        self.assertEqual((code, err), (0, ""))
        return env["data"]

    def confidence(self, task: str, *extra) -> dict:
        data = self.discover(task, *extra)
        self.assertEqual(list(data)[0], "lexical_confidence")  # the first key, so a cut read keeps it
        return data["lexical_confidence"]


class ConfidenceTableTest(Shop):  # DCP-AC-004
    CASES = [  # (case, task, level, reason, top)
        (1, "the weather on a sunny day", "unsure", "no_hits", []),
        (2, "a shelf in the aisle", "sure", None, ["shelf"]),
        (3, "stock in the warehouse from a supplier who will restock", "sure", None,
         ["stock", "stock/restock"]),
        (4, "a shelf in the aisle by the till with a receipt", "unsure", "tie",
         ["shelf", "till"]),
        (5, "a shelf", "unsure", "low_score", ["shelf"]),
        (6, "stock warehouse restock supplier shelf aisle till receipt review rating", "unsure",
         "tie", ["reviews", "shelf", "stock", "stock/restock", "till"]),
    ]

    def test_each_row(self):
        for case, task, level, reason, top in self.CASES:
            with self.subTest(case=case):
                self.assertEqual(self.confidence(task),
                                 {"level": level, "reason": reason, "top": top})

    def test_tie_comes_before_low_score(self):  # two families tied below sure_min_score
        self.assertEqual(self.confidence("a shelf by the till"),
                         {"level": "unsure", "reason": "tie", "top": ["shelf", "till"]})

    def test_a_lower_module_does_not_count(self):  # the top score only
        self.assertEqual(self.confidence("a shelf in the aisle by the till"),
                         {"level": "sure", "reason": None, "top": ["shelf"]})

    def test_top_does_not_change_it(self):  # computed over every keyword row, not the shown ones
        self.assertEqual(self.confidence("a shelf in the aisle by the till with a receipt",
                                         "--top", "1"),
                         {"level": "unsure", "reason": "tie", "top": ["shelf", "till"]})
        data = self.discover("a shelf in the aisle by the till with a receipt", "--top", "1")
        self.assertEqual([m["module"] for m in data["modules"]], ["shelf"])

    def test_change_rows_are_not_keyword_rows(self):  # a module found through the change
        data = self.discover("the weather on a sunny day", "--files", "modules/till/MODULE.md")
        self.assertEqual([(m["module"], m["score"]) for m in data["modules"]], [("till", 0)])
        self.assertEqual(data["lexical_confidence"],
                         {"level": "unsure", "reason": "no_hits", "top": []})

    def test_the_text_output_leads_with_it(self):  # 2026-10-19: module-discover reads the text, whole
        code, out, err = run("discover", "--task", "a shelf", "--match", "lexical", *self.R)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.splitlines()[0], "lexical: unsure: low_score (top: shelf)")
        code, out, _ = run("discover", "--task", "a shelf in the aisle", "--match", "lexical", *self.R)
        self.assertEqual(out.splitlines()[0], "lexical: sure (top: shelf)")
        code, out, _ = run("discover", "--files", "modules/till/MODULE.md", *self.R)  # no task: no line
        self.assertFalse(out.startswith("lexical:"))


class ScoreBoundaryTest(Shop):  # DCP-AC-005
    def test_one_two_three(self):
        for task, level, reason in (("a shelf", "unsure", "low_score"),
                                    ("a shelf in the aisle", "sure", None),
                                    ("a shelf in the aisle, a bookcase", "sure", None)):
            with self.subTest(task=task):
                got = self.confidence(task)
                self.assertEqual((got["level"], got["reason"], got["top"]),
                                 (level, reason, ["shelf"]))

    def test_the_setting_moves_the_boundary(self):
        (self.root / ".segmently-modules/config.toml").write_text(
            WEIGHT_ONE + "\n[search]\nsure_min_score = 3\n", encoding="utf-8")
        self.assertEqual(self.confidence("a shelf in the aisle")["reason"], "low_score")
        self.assertEqual(self.confidence("a shelf in the aisle, a bookcase")["level"], "sure")
        (self.root / ".segmently-modules/config.toml").write_text(
            WEIGHT_ONE + "\n[search]\nsure_min_score = 1\n", encoding="utf-8")
        self.assertEqual(self.confidence("a shelf")["level"], "sure")


class DefaultWeightsTest(Shop):
    CONFIG = ""

    def test_the_engine_defaults(self):  # a keyword hit scores 3, sure_min_score is 2
        self.assertEqual(self.confidence("a shelf"),
                         {"level": "sure", "reason": None, "top": ["shelf"]})
        self.assertEqual(self.confidence("an aisle at the till"),
                         {"level": "unsure", "reason": "tie", "top": ["shelf", "till"]})


class WhenTheKeyIsAddedTest(Split):  # R-3: a task and keyword routing, JSON only
    def data(self, *argv) -> dict:
        code, env, err = run_json("discover", *argv, *self.R)
        self.assertEqual((code, err), (0, ""))
        return env["data"]

    def test_lexical_and_hybrid_have_it_files_only_and_semantic_do_not(self):
        lexical = self.data("--task", "refund", "--match", "lexical")
        self.assertEqual(lexical["lexical_confidence"],
                         {"level": "sure", "reason": None, "top": ["orders/refunds"]})
        hybrid = self.data("--task", "refund", "--match", "hybrid")  # no agent: lexical rows
        self.assertEqual(list(hybrid)[0], "lexical_confidence")
        self.assertEqual(list(hybrid)[-2:], ["mode", "notes"])
        self.assertNotIn("lexical_confidence", self.data("--files", "src/orders/service.py"))
        self.agent(answer=picks(("orders/refunds", 0.9, "r")))
        semantic = self.data("--task", "refund", "--match", "semantic")
        self.assertNotIn("lexical_confidence", semantic)
        hybrid = self.data("--task", "refund", "--match", "hybrid")  # the agent answered
        self.assertEqual(hybrid["lexical_confidence"]["top"], ["orders/refunds"])
        self.assertEqual(list(hybrid)[0], "lexical_confidence")

    def test_context_and_match_do_not_have_it(self):
        _, env, _ = run_json("context", "--task", "refund", "--match", "lexical", *self.R)
        self.assertNotIn("lexical_confidence", env["data"])


# --- choose --cards (DCP-AC-010) --------------------------------------------------------------

class CardsTest(Split):
    def order(self, *extra) -> dict:
        code, env, err = run_json("choose", "--task", "refund a book", *extra, *self.R)
        self.assertEqual((code, err), (0, ""))
        return env["data"]

    def test_brief_cards_hold_name_description_and_children_only(self):
        # task-1 review M6 (controller ruling): one card per module AND per child — a child card
        # {module, description, parent}, a parent card {module, description, children}
        full, brief = self.order(), self.order("--cards", "brief")
        said = {c["module"]: c["description"] for c in full["cards"]}
        self.assertEqual(brief["cards"], [
            {"module": "catalog", "description": said["catalog"]},
            {"module": "orders", "description": said["orders"],
             "children": ["orders/checkout", "orders/refunds", "orders/invoices"]},
            {"module": "orders/checkout", "description": said["orders/checkout"],
             "parent": "orders"},
            {"module": "orders/refunds", "description": said["orders/refunds"],
             "parent": "orders"},
            {"module": "orders/invoices", "description": said["orders/invoices"],
             "parent": "orders"},
            {"module": "payments", "description": said["payments"]}])
        self.assertEqual([c["module"] for c in brief["cards"]],
                         [c["module"] for c in full["cards"]])  # the same cards, in one order
        self.assertNotEqual(said["orders/refunds"], said["orders"])  # a child's own words
        for key in ("task", "rules", "answer_schema", "max_picks", "search"):
            self.assertEqual(brief[key], full[key], key)
        self.assertNotEqual(brief["catalog_digest"], full["catalog_digest"])

    def test_full_is_the_default_and_byte_identical(self):
        for as_json in ((), ("--json",)):
            plain = run("choose", "--task", "refund a book", *as_json, *self.R)
            full = run("choose", "--task", "refund a book", "--cards", "full", *as_json, *self.R)
            self.assertEqual(plain, full)

    def test_brief_is_smaller(self):
        for as_json in ((), ("--json",)):
            with self.subTest(json=bool(as_json)):
                full = run("choose", "--task", "refund a book", *as_json, *self.R)
                brief = run("choose", "--task", "refund a book", "--cards", "brief", *as_json,
                            *self.R)
                self.assertEqual((full[0], full[2], brief[0], brief[2]), (0, "", 0, ""))
                self.assertLess(len(brief[1]), len(full[1]))

    def test_brief_text(self):
        code, out, err = run("choose", "--task", "refund a book", "--cards", "brief", *self.R)
        self.assertEqual((code, err), (0, ""))
        cands = out.split("\n\nAnswer schema:")[0].split("Candidates")[1].splitlines()
        self.assertEqual(cands[0], " (one per line: module, description, children):")
        self.assertEqual(len(cands), 7)  # a line per module and per child (task-1 review M6)
        self.assertTrue(cands[2].startswith("orders  Order lifecycle"))
        self.assertTrue(cands[2].endswith(
            "  (children: orders/checkout, orders/refunds, orders/invoices)"))
        self.assertEqual(cands[4], "orders/refunds  Returned books: refund requests, partial "
                                   "refunds and restocking.  (child of orders)")
        for line in cands[3:6]:
            self.assertTrue(line.endswith("  (child of orders)"), line)
        self.assertNotIn("refund, partial refund", out)  # no keyword
        self.assertNotIn("[", "\n".join(cands[1:]))

    def test_ties_keep_the_card_order_of_a_full_order(self):  # one id per card, no repeat
        tie = [{"module": m, "confidence": 0.5} for m in ("payments", "orders/refunds", "catalog")]
        for kind in ("full", "brief"):
            with self.subTest(cards=kind):
                self.config(f'[search]\ncards = "{kind}"\n')
                with mock.patch("sys.stdin", io.StringIO(json.dumps({"picks": tie}))):
                    code, out, err = run("choose", "--apply", "-", "--json", *self.R)
                self.assertEqual((code, err), (0, ""))
                self.assertEqual([p["module"] for p in json.loads(out)["data"]["picks"]],
                                 ["catalog", "orders/refunds", "payments"])

    def test_the_setting_is_the_flags_default(self):
        self.config('[search]\ncards = "brief"\n')
        self.assertIn("children", self.order()["cards"][1])
        self.assertNotIn("children", self.order("--cards", "full")["cards"][1])
        self.config('[search]\ncards = "full"\n')
        self.assertEqual(self.order(), self.order("--cards", "full"))

    def test_apply_takes_a_child_of_a_brief_order(self):
        self.config('[search]\ncards = "brief"\n')
        order = self.order()
        self.assertIn("children", order["cards"][1])  # the order the chooser was given
        digest = order["catalog_digest"]
        answer = json.dumps({"picks": [{"module": "orders/refunds", "confidence": 0.9}],
                             "none": False, "catalog_digest": digest})
        with mock.patch("sys.stdin", io.StringIO(answer)):
            code, out, err = run("choose", "--apply", "-", "--json", *self.R)
        self.assertEqual((code, err), (0, ""))
        data = json.loads(out)["data"]
        self.assertEqual([p["module"] for p in data["picks"]], ["orders/refunds"])
        self.assertEqual(data["notes"], [])  # the digest of the brief order

    def test_run_asks_with_the_cards_it_is_given(self):
        self.agent(answer=picks(("orders/refunds", 0.8, "r")))
        for extra, brief in (((), False), (("--cards", "brief"), True)):
            with self.subTest(extra=extra):
                code, out, err = run("choose", "--task", "refund a book", "--run", *extra,
                                     "--json", *self.R)
                self.assertEqual((code, err), (0, ""))
                self.assertEqual(json.loads(out)["data"]["picks"][0]["module"],
                                 "orders/refunds")
                sent = json.loads(json.loads(self.calls_log.read_text("utf-8"))[-1]["stdin"])
                self.assertEqual("children" in sent["cards"][1], brief)
                self.assertEqual("keywords" in sent["cards"][1], not brief)
                self.assertEqual(sent["cards"][3]["parent"], "orders")  # a child keeps its card
                self.assertEqual(len(sent["cards"]), 6)

    def test_the_docs_say_so(self):  # task-1 review M6: the follow-ups the final review lists
        config = " ".join((ENGINE / "docs/configuration.md").read_text("utf-8").split())
        self.assertIn("`brief` (one card per module and per child: name and description, a "
                      "parent's card naming its children, a child's its parent, no keyword — a "
                      "smaller order)", config)
        contract = " ".join((ENGINE / "docs/cli-contract.md").read_text("utf-8").split())
        self.assertIn("`brief` = `cards: [{module, description, children?, parent?}]`, one per "
                      "module and per child (a parent's `children`: its children's ids; a "
                      "child's `parent`), no keywords", contract)
        self.assertNotIn("one per top-level module", contract)
        self.assertIn("a child's ` (child of a)`", contract)  # flat: the two spaces are one
        log = (ENGINE / "CHANGELOG.md").read_text("utf-8")
        unreleased = " ".join(log.split("## [Unreleased]", 1)[1].split("\n## [", 1)[0].split())
        self.assertIn("a smaller work order with a card per module and per child — its name and "
                      "description, a parent's card naming its children, a child's its parent — "
                      "without keywords", unreleased)

    def test_a_wrong_flag_value(self):
        code, out, err = run("choose", "--task", "t", "--cards", "tiny", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("argument --cards: invalid choice: 'tiny'", err)


# --- a failing chooser's answer (DCP-AC-008) ---------------------------------------------------

class NonJsonAnswerTest(Split):
    def test_stdin_that_is_not_json_is_exit_2_with_nothing_on_stdout(self):
        env = {**os.environ, "PYTHONPATH": str(ENGINE)}
        for text in ("I picked orders/refunds.", "", "```\nnot json\n```"):
            with self.subTest(text=text):
                proc = subprocess.run(
                    [sys.executable, "-m", "segmently_modules", "choose", "--apply", "-",
                     "--json", *self.R], input=text.encode("utf-8"), capture_output=True,
                    env=env, timeout=120)
                self.assertEqual((proc.returncode, proc.stdout), (2, b""))
                err = proc.stderr.decode("utf-8")
                self.assertTrue(err.startswith("segmently-modules: error: stdin: "), err)
                self.assertNotIn("Traceback", err)


if __name__ == "__main__":
    unittest.main()
