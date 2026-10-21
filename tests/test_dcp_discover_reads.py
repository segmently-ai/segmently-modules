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
taken from `SKILL.md` went with them.

Owner ruling 2026-10-19 (after the benchmark stand): how much to read is no longer the agent's call.
Every reader had cut its `--json` outputs with a script or `head` and read few docs whole, while it
read a text output written to a file to the end. The intro now says what the steps name is read
whole — a command's text output through a temp file, never `--json`; a doc with the file-read tool —
and only code is read in part; each step names its command with the temp file."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from segmently_modules.config import builtin_packs_root
from tests.test_builtin_skills import section

ENGINE = Path(__file__).resolve().parents[1]
SKILL = builtin_packs_root() / "core/skills/module-discover/SKILL.md"
INTRO = [  # the steps intro, in this order, before step 1
    "The steps say what to find and what the report must hold; how to search is your call.",
    # owner 2026-10-19: what the steps name is read whole, a command's output through a file
    "What they name is read whole, to the end: a command's text output (never `--json`) through a "
    "temp file, a doc with your file-read tool; only code is read in part.",
    "Run independent reads together.",
]
NOT_BATCHED = (  # final review I-1: outputs that can be long never join a Bash batch
    "and then the docs they list", "step 6's searches", "in one Bash call (`a; b; c`, or a loop) "
    "or as parallel tool calls")
COMMANDS = {2: "segmently-modules show <module> > <temp file>",  # the read command each step runs
            3: "segmently-modules related <module> > <temp file>",
            5: "segmently-modules show <module> --discover > <temp file>"}  # [discover] docs / read (2026-10-19)
STEPS = {  # each step's own rule, in its own step and in this order
    2: ["Read each candidate's main doc to the end",
        "a split module: its INDEX, then the child the task is in;",
        "exit 1 is a pointer stub: read its successor",
        "Score how much the task needs the module, 0–10, and keep it at 5 or more;",
        "a dropped candidate goes on the rejected list with its score or \"off-topic by its "
        "description\"."],
    3: ["of a kept module may show another module the task needs (follow forward edges only); "
        "verify it as in step 2."],
    5: ["A `modify` or `consume` module: every doc `segmently-modules show <module> --discover > "
        "<temp file>` lists, each read to the end;",
        "a `reference` module: its main doc only.",
        "Never `MODULE.legacy.md` or `roles/*.legacy.md`.",
        "Take from each doc what bears on the task — rules, constraints, contracts, pitfalls — as "
        "short extracts with the doc's path and role;",
        "a doc with nothing for the task gets \"read, nothing for this task\".",
        "Never a retelling.",
        "`segmently-modules rules <every kept module> > <temp file>`, read to the end, gives their "
        "critical rules whole:"],
    6: ["Read just enough code to name the symbol and what changes."],
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

    def test_what_the_steps_name_is_read_whole(self):  # owner 2026-10-19
        body = flat(raw())
        for gone in NOT_BATCHED + ("how much to read", "not whole files", "cut a long output"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, body)
        rule = flat(steps()).split("1. **Candidates.**", 1)[0]
        self.assertNotIn("git grep", rule)  # a search is never named as a Bash batch
        for said in ("never `--json`", "through a temp file", "file-read tool", "only code is read in part"):
            with self.subTest(said=said):
                self.assertIn(said, rule)


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


CHANGELOG_LINE = (  # the one Unreleased line (owner rulings: formalization eval; the stand, 2026-10-19)
    "- module-discover's steps say what to find and what the report must hold, and leave how to s"
    "earch to the agent; what they name is read whole, to the end — a command's text output throu"
    'gh a temp file (never `--json`), a doc with the file-read tool — and only code is read in pa'
    'rt. In a 7-task comparison with the step-by-step text the lite text found as much (more `edi'
    't` files) at about 80% of the cost; on the benchmark stand (2026-10-19) every reader then cu'
    't its `--json` outputs with a script or `head` and read few docs to the end, so how much to '
    'read is no longer its call.')


class ChangelogTest(unittest.TestCase):  # R-5
    def test_the_unreleased_line(self):
        log = (ENGINE / "CHANGELOG.md").read_text(encoding="utf-8")
        unreleased = log.split("## [Unreleased]", 1)[1].split("\n## [0.3.0]", 1)[0]
        changed = unreleased.split("### Changed\n", 1)[1].split("\n### ", 1)[0]
        self.assertEqual(changed.splitlines().count(CHANGELOG_LINE), 1)
        self.assertEqual(unreleased.count("module-discover's steps say"), 1)
        for gone in ("outline-first", "batches independent reads", "four questions"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, unreleased)  # the line it replaces is gone


if __name__ == "__main__":
    unittest.main()
