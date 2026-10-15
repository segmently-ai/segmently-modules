"""module-discover's choice of candidates under the chooser setting (DCP-AC-006…009, 023): the
settings come from `segmently-modules catalog --settings --json`; one routing table says when the
chooser runs (the user's words for this run, then `search.chooser`, then the keyword result's
`lexical_confidence`); `when_unsure` runs the keyword command first; a failing chooser falls back
to answering the order in the session; the report's search line. The by-meaning bullet — today's
path, the `always` row — stays byte for byte what it was, and the same in the four skills that
find modules."""
from __future__ import annotations

import re
import unittest

from segmently_modules.config import builtin_packs_root, core_defaults
from tests.test_builtin_skills import argv, commands, parse_problem

CORE = builtin_packs_root() / "core" / "skills"
CHOOSE = CORE / "module-discover" / "references" / "choose.md"
OTHERS = ("module-sync", "module-scout", "module-research")
# The by-meaning bullet of `references/choose.md` before the setting, byte for byte (AC-006).
BY_MEANING = (
    "- By meaning (`semantic`, `hybrid`): write the text, verbatim, to `<task file>`. **Claude Code:**\n"
    "  `segmently-modules choose --task-file <task file> > <order file>`; give `<order file>`'s path to the\n"
    "  `segmently-modules:module-chooser` agent with `model: <search.claude_model>` (without that agent: a\n"
    "  subagent told \"this file is your whole task; answer with its JSON only; change nothing\"); its\n"
    "  reply is the answer. **Codex:** the same with `--json`, its `answer_schema` written to\n"
    "  `<schema file>`, then\n"
    "  `codex exec -m <search.codex_model> -c model_reasoning_effort=<reasoning> --sandbox read-only --output-schema <schema file> - < <order file>`\n"
    "  (`low`, `medium`, `high` for `quick`, `standard`, `deep`). **Elsewhere** (no subagent, no\n"
    "  `codex exec`, or it fails, as inside a sandbox): answer the order yourself, every card read, by its rules. Pipe the answer to\n"
    "  `segmently-modules choose --apply - --json`.\n")
KEYWORD = ("- By keyword (`lexical`, `hybrid`): "
           "`segmently-modules discover --task-file <file> --match lexical --json`.\n")
HYBRID = "- `hybrid`: merge the lists; a module found both ways ranks first.\n"
# AC-006: one row per line of the decision table, in the table's order
HEADER = "| The user's words, this run | `search.chooser` | Keyword result | Mode |"
ROWS = [
    '| "by meaning" | any | any | `semantic`: the chooser runs |',
    '| "only lexical" | any | any | `lexical`: no chooser |',
    "| none | `always` | any | `hybrid` (`semantic` when `match.mode` is `semantic`): the "
    "chooser runs, as it always did |",
    "| none | `when_unsure` | `sure` | `lexical`: no chooser |",
    "| none | `when_unsure` | `unsure` | `hybrid`: the chooser runs after the keyword command |",
    "| none | `never` | any | `lexical`: no chooser |",
]
ROUTING = [  # the sentences that make the table one decision
    "**The mode.** One table decides whether the chooser (the search by meaning) runs.",
    "Read it top down; the first row that fits decides, so the user's words for this run win "
    "over `search.chooser`.",
    "The user's words count in any language.",
    "`match.mode` is only the command line's default: a `lexical` one never skips the search by "
    "meaning.",
    "The keyword commands always pass `--match lexical`.",
]
WHEN_UNSURE = [  # AC-007
    "`when_unsure`: run the keyword command first; its `lexical_confidence.level` is the keyword "
    "result.",
    "On `sure` the keyword list is the candidates: no `choose` command and no chooser agent.",
    "On `unsure` run the by-meaning half too, then merge the lists as `hybrid` does.",
]
FALLBACK = (  # AC-008
    "**A failing chooser** — no agent to hand the order to, an answer that is not JSON, or "
    "`choose --apply` exits 2 — never ends the run: answer the order yourself, every card read, "
    "by its rules (the **Elsewhere** path), and say so on the search line.")
SEARCH_LINE = [  # AC-009
    "**The search line.** The first line under the report's title says how the candidates were "
    "chosen: `Search: <lexical | by meaning | hybrid> — <the setting or the user's words> — "
    "lexical <sure | unsure: reason>`,",
    "e.g. `Search: lexical — chooser skipped (when_unsure, lexical sure)`,",
    "`Search: hybrid — when_unsure — lexical unsure: tie`,",
    "or, after a failing chooser, `Search: hybrid — always, chooser failed (no agent): answered "
    "in the session — lexical sure`.",
    'No keyword command ran ("by meaning"): `lexical not run`.',
]


def raw() -> str:
    return CHOOSE.read_bytes().decode("utf-8")


def flat(text: str) -> str:
    return " ".join(text.split())


class SettingsTest(unittest.TestCase):  # DCP-AC-023
    def test_settings_come_from_catalog_settings(self):
        text = raw()
        self.assertIn("Run `segmently-modules catalog --settings --json`; read `match.mode` and "
                      "`search`.", flat(text))
        self.assertNotIn("catalog --json", text)
        catalogs = [argv(c) for c in commands(text) if argv(c)[:1] == ["catalog"]]
        self.assertEqual(catalogs, [["catalog", "--settings", "--json"]])

    def test_every_command_parses(self):
        for c in commands(raw()):
            with self.subTest(command=c):
                self.assertIsNone(parse_problem(c))


class RoutingTableTest(unittest.TestCase):  # DCP-AC-006
    def test_one_table_with_the_six_rows_in_order(self):
        lines = raw().split("\n")
        start = lines.index(HEADER)
        self.assertEqual(lines[start + 1], "|---|---|---|---|")
        self.assertEqual(lines[start + 2:start + 2 + len(ROWS)], ROWS)
        self.assertEqual(lines[start + 2 + len(ROWS)], "")
        self.assertEqual(sum(1 for line in lines if line.startswith("|")), len(ROWS) + 2)

    def test_the_routing_sentences(self):
        body = flat(raw())
        for sentence in ROUTING:
            with self.subTest(sentence=sentence):
                self.assertEqual(body.count(sentence), 1)
        self.assertLess(body.index(ROUTING[0]), body.index(flat(HEADER)))

    def test_the_by_meaning_branch_is_byte_identical(self):  # the `always` row's path
        text = raw()
        self.assertEqual(text.count(BY_MEANING + KEYWORD + HYBRID), 1)
        for skill in OTHERS:  # the shared bullet, unchanged in the other three skills
            with self.subTest(skill=skill):
                other = (CORE / skill / "references/choose.md").read_bytes().decode("utf-8")
                self.assertEqual(other.count(BY_MEANING), 1)

    def test_the_old_mode_sentence_is_gone(self):
        body = flat(raw())
        for gone in ("The mode: `hybrid` unless the user says otherwise",
                     "which needs no setting"):
            self.assertNotIn(gone, body)


class WhenUnsureTest(unittest.TestCase):  # DCP-AC-007
    def test_lexical_first_then_the_chooser(self):
        body = flat(raw())
        at = [body.find(s) for s in WHEN_UNSURE]
        self.assertNotIn(-1, at)
        self.assertEqual(at, sorted(at))
        self.assertLess(body.index(flat(ROWS[-1])), at[0])  # after the table …
        self.assertLess(at[-1], body.index(flat(BY_MEANING)))  # … before the two halves


class FallbackTest(unittest.TestCase):  # DCP-AC-008 (the CLI side: test_search_chooser)
    def test_a_failing_chooser_falls_back_and_says_so(self):
        body = flat(raw())
        self.assertEqual(body.count(FALLBACK), 1)
        self.assertLess(body.index(flat(HYBRID)), body.index(FALLBACK))


class SearchLineTest(unittest.TestCase):  # DCP-AC-009
    def test_the_instruction_and_its_examples(self):
        body = flat(raw())
        at = [body.find(s) for s in SEARCH_LINE]
        self.assertNotIn(-1, at)
        self.assertEqual(at, sorted(at))


class SizeTest(unittest.TestCase):  # R-5.7: a signal, never a cap
    def test_within_the_split_signal(self):
        signal = core_defaults()["budgets"]["skill_split_signal"]
        for path in (CHOOSE, CORE / "module-discover/SKILL.md"):
            with self.subTest(file=path.name):
                self.assertLessEqual(len(path.read_text(encoding="utf-8")), signal)

    def test_no_dollar_placeholder(self):
        self.assertEqual(re.findall(r"\$[A-Za-z0-9{]\w*", raw()), [])


if __name__ == "__main__":
    unittest.main()
