"""module-discover reads with fewer turns and less code (DCP-AC-025, DCP-AC-035). Formalization eval
2026-10-15: the owner adopted the lite text — the procedure is the model's, the contract is pinned.
The steps intro says the steps name what to find and what the report must hold, and leaves how to
search and how much to read to the agent; independent reads still run together (parallel tool
calls, or one Bash call only when every output is short), and a long output cut to a preview is
read back from the file it names (final review I-1). Each step keeps its own rule: step 2 one
score 0–10, kept at 5 or more; step 3 forward edges only; step 5 every doc `show --all-roles` lists
for a `modify` or `consume` module, the main doc only for a `reference` one, never the
`*.legacy.md` files; step 6 reads just enough to name the symbol and what changes, not whole files.
The per-step batching examples, "never batch commands whose input depends on an earlier output"
and the outline-first reading left the skill on purpose, and the test that ran the outline command
taken from `SKILL.md` went with them."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from segmently_modules.config import builtin_packs_root
from tests.test_builtin_skills import section

ENGINE = Path(__file__).resolve().parents[1]
SKILL = builtin_packs_root() / "core/skills/module-discover/SKILL.md"
INTRO = [  # the lite text's steps intro, in this order, before step 1
    "The steps say what to find and what the report must hold; how to search and how much to read "
    "is your call.",
    # final review I-1: a Bash batch only of short outputs
    "Run independent reads together (parallel tool calls, or one Bash call when every output is "
    "short).",
    # final review I-1: a cut output is read back, never used as it is
    "A host may cut a long output to a preview: then read the file it names, or rerun narrower.",
]
NOT_BATCHED = (  # final review I-1: outputs that can be long never join a Bash batch
    "and then the docs they list", "step 6's searches", "in one Bash call (`a; b; c`, or a loop) "
    "or as parallel tool calls")
COMMANDS = {2: "segmently-modules show <module> --json",  # the read command each step runs
            3: "segmently-modules related <module> --json",
            5: "segmently-modules show <module> --all-roles --json"}
STEPS = {  # each step's own rule, in its own step and in this order
    2: ["Read each candidate's description and main doc",
        "a split module: its INDEX, then the child the task is in;",
        "exit 1 is a pointer stub: read its successor",
        "Score how much the task needs the module, 0–10, and keep it at 5 or more;",
        "a dropped candidate goes on the rejected list with its score or \"off-topic by its "
        "description\"."],
    3: ["of a kept module may show another module the task needs (follow forward edges only); "
        "verify it as in step 2."],
    5: ["A `modify` or `consume` module: every doc `segmently-modules show <module> --all-roles "
        "--json` lists;",
        "a `reference` module: its main doc only.",
        "Never `MODULE.legacy.md` or `roles/*.legacy.md`.",
        "Take from each doc what bears on the task — rules, constraints, contracts, pitfalls — as "
        "short extracts with the doc's path and role;",
        "a doc with nothing for the task gets \"read, nothing for this task\".",
        "Never a retelling."],
    6: ["Read just enough to name the symbol and what changes, not whole files."],
}


def raw() -> str:
    return SKILL.read_bytes().decode("utf-8")


def flat(s: str) -> str:
    return " ".join(s.split())


def steps() -> str:
    return section(raw(), "## Steps")


def step(n: int) -> str:
    """Step `n` of `## Steps`, flat: from its numbered line to the next one."""
    body = steps()
    start = re.search(rf"^{n}\. \*\*", body, re.M)
    end = re.search(rf"^{n + 1}\. \*\*", body, re.M)
    return flat(body[start.start():end.start() if end else len(body)]) if start else ""


def at(body: str, phrases: list[str]) -> list[int]:
    return [body.find(p) for p in phrases]


class StepsIntroTest(unittest.TestCase):  # DCP-AC-025, as the lite text says it
    def test_the_intro_binds_every_step(self):
        body = flat(steps())
        found = at(body, INTRO)
        self.assertNotIn(-1, found, [p for p, i in zip(INTRO, found) if i < 0])
        self.assertEqual(found, sorted(found))
        self.assertEqual([body.count(p) for p in INTRO], [1, 1, 1])
        self.assertLess(found[-1], body.index("1. **Candidates.**"))  # before the first step
        self.assertEqual(flat(raw()).count(INTRO[0]), 1)  # once in the whole skill

    def test_only_short_outputs_join_a_bash_batch(self):  # final review I-1
        body = flat(raw())
        for gone in NOT_BATCHED:
            with self.subTest(gone=gone):
                self.assertNotIn(gone, body)
        rule = flat(steps()).split("1. **Candidates.**", 1)[0]
        self.assertNotIn("git grep", rule)  # a search is never named as a Bash batch
        self.assertIn("parallel tool calls", rule)
        self.assertIn("when every output is short", rule)


class StepRulesTest(unittest.TestCase):  # the rule each step keeps in the lite text
    def test_each_step_names_its_read_command(self):
        for number, command in COMMANDS.items():
            with self.subTest(step=number):
                self.assertIn(f"`{command}`", step(number))
        for scoped in (5, 6):  # the step's own scope
            self.assertIn("`modify` or `consume` module", step(scoped))

    def test_each_rule_in_its_step_in_order(self):
        for number, phrases in STEPS.items():
            with self.subTest(step=number):
                found = at(step(number), phrases)
                self.assertNotIn(-1, found, [p for p, i in zip(phrases, found) if i < 0])
                self.assertEqual(found, sorted(found))

    def test_step_6_reads_after_the_list(self):  # how much to read, once the code is found
        body = step(6)
        self.assertLess(body.index("--source-only --paths"), body.index(STEPS[6][0]))
        self.assertLess(body.index(STEPS[6][0]), body.index("Record existing code only"))
        self.assertEqual(flat(raw()).count(STEPS[6][0]), 1)  # step 6 only
        self.assertNotIn("<file>", body)  # final review M-2: `<file>` is the terms file


CHANGELOG_LINE = (  # the lite text's one Unreleased line (owner ruling, formalization eval)
    "- module-discover's steps say what to find and what the report must hold, and leave how to "
    "search and how much to read to the agent (independent reads still run together; an output "
    "cut to a preview is read back from the file it names); in a 7-task comparison with the "
    "step-by-step text it found as much (more `edit` files) at about 80% of the cost.")


class ChangelogTest(unittest.TestCase):  # R-5
    def test_the_unreleased_line(self):
        log = (ENGINE / "CHANGELOG.md").read_text(encoding="utf-8")
        unreleased = log.split("## [Unreleased]", 1)[1].split("\n## [", 1)[0]
        changed = unreleased.split("### Changed\n", 1)[1].split("\n### ", 1)[0]
        self.assertEqual(changed.splitlines().count(CHANGELOG_LINE), 1)
        self.assertEqual(unreleased.count("module-discover's steps say"), 1)
        for gone in ("outline-first", "batches independent reads", "four questions"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, unreleased)  # the line it replaces is gone


if __name__ == "__main__":
    unittest.main()
