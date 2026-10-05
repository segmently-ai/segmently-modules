"""P8.8 (D8–D10): the QA skills do the job of the originals they were written from again — the
shared method (dimensions, risk → depth, decomposition, criterion quality, self-check, Quality
Score; seven techniques), qa-acceptance's criterion fields with `e2e`, five categories, Part A /
Part B and delivery in the conversation, and the baseline by block with REQ tables, the
criterion fields, a final confirmation and a `block` route. C2 of the fast mode: the contract's
phrases must be there, the removed rules gone; the two shared files are one text in both skills
(X4: routed by step, each file under the size signal)."""

import hashlib
import re
import unittest

from modsys.config import builtin_packs_root, core_defaults
from modsys.skills import read_front_matter
from tests.test_builtin_skills import section, skill_files

QA = builtin_packs_root() / "qa"
ACC, BASE = QA / "skills/qa-acceptance", QA / "skills/qa-acceptance-baseline"
SHARED = ("references/method.md", "references/techniques.md")
REFERENCES = {ACC: ["method.md", "output.md", "techniques.md"],
              BASE: ["block.md", "create.md", "exit-codes.md", "method.md", "refresh.md",
                     "techniques.md"]}
BUDGETS = core_defaults()["budgets"]
DESCRIPTION = "Shows them in the conversation; a file only at a path the user names."


def flat(text: str) -> str:
    return " ".join(text.split())


def every(directory) -> str:
    return flat("\n".join(skill_files(directory).values()))


class SharedMethodTest(unittest.TestCase):  # D8
    def test_one_text_in_both_skills(self):
        for name in SHARED:
            with self.subTest(file=name):
                self.assertEqual((ACC / name).read_bytes(), (BASE / name).read_bytes())

    def test_the_method_holds_the_dimensions_risk_and_checks(self):
        text = flat((ACC / "references/method.md").read_text("utf-8"))
        for needle in ("## The ten test dimensions", "Functional (happy path)",
                       "Negative / error handling", "Boundary / edge cases", "State management",
                       "Data integrity", "Accessibility", "Visual / responsive", "Performance",
                       "Security", "Concurrency / races", "**Dimension enforcement check**",
                       "**Minimum per dimension**", "| Critical | required | 3-value BVA |",
                       "| High | required | 2-value BVA |", "| Medium | required | EP only |",
                       "P0 = critical and high, P1 = medium, P2 = low", "**Flows first.**",
                       "**Granularity.**", "**Minimum count.**", "**Dimension cross-check.**",
                       "**Architecture-rule exception:**", "\"No crash\" alone",
                       "`baseline-ref: <module> AC-NNN`", "never renumber or reuse an id",
                       "## Self-verification, before anything is shown",
                       "Part B has one entry per `e2e` criterion",
                       "## Quality Score — the last section of every document",
                       "| **Overall** | **PASS / FAIL** | |"):
            self.assertIn(needle, text)

    def test_the_techniques_are_seven_plus_the_exploratory_tag(self):
        text = flat((ACC / "references/techniques.md").read_text("utf-8"))
        for needle in ("## Equivalence partitioning (EP)", "## Boundary value analysis (BVA)",
                       "## Decision table", "## State transition", "## Pairwise", "## Use case",
                       "## Error guessing", "`Exploratory` tag", "boundary − 1, boundary, "
                       "boundary + 1", "each condition the technique produced becomes one "
                       "criterion"):
            self.assertIn(needle, text)


class QaAcceptanceTest(unittest.TestCase):  # D9
    def setUp(self):
        self.text = (ACC / "SKILL.md").read_text("utf-8")
        self.all = every(ACC)

    def test_the_criterion_fields_and_verification_values(self):
        steps = flat(section(self.text, "## Steps"))
        for needle in ("**Title**", "**Sub-task**", "**Technique**", "**Risk**",
                       "**Verification** (`unit`, `e2e` or `manual`",
                       "Functional Correctness, Completeness, Edge Cases, Error Handling and "
                       "Regression Safety", "`baseline-ref: <module> AC-007` in Regression Safety",
                       "Regression Safety lists every P0 criterion of the touched modules",
                       "\"Baseline Updates Needed\"", "at most 10"):
            self.assertIn(needle, steps)
        self.assertIn("**Verification:** <unit | e2e | manual>", self.all)
        self.assertIn("`e2e` is never dropped or renamed", self.all)

    def test_part_a_has_the_fixed_shape(self):
        out = (ACC / "references/output.md").read_text("utf-8")
        heads = ["## Summary", "## Specification Issues", "## Task Decomposition",
                 "## Dimension Enforcement Check", "## Modules Consulted", "## Prerequisites",
                 "## Core Acceptance Criteria", "### Functional Correctness", "### Completeness",
                 "### Edge Cases", "### Error Handling", "### Regression Safety",
                 "## Baseline Updates Needed", "## Gap Analysis", "## Quality Score"]
        where = [out.index(f"\n{h}\n") for h in heads]
        self.assertEqual(where, sorted(where))
        for needle in ("**Techniques applied:**", "**Risk distribution:**", "→ AC-001, AC-002",
                       "**Check:**", "**Expected:**", "Sufficiency verdict"):
            self.assertIn(needle, out)

    def test_part_b_runnable_scenarios_coverage_first(self):
        out = flat((ACC / "references/output.md").read_text("utf-8"))
        for needle in ("One entry per `e2e` criterion", "coverage: new",
                       "`coverage: covered-by: <test file> > <test name>`",
                       "`coverage: updates-existing: <test file> > <test name>`",
                       "url: <the entry URL", "auth: <where the test account comes from",
                       "never a secret value", "- [ ] Assert:", "The format a touched module's "
                       "`qa` doc names", "names a coverage map",
                       "none: no criterion is verified by e2e"):
            self.assertIn(needle, out)
        self.assertIn("8. Write Part B: one runnable scenario per `e2e` criterion",
                      flat(section(self.text, "## Steps")))

    def test_it_shows_the_document_and_waits(self):
        steps, gates = flat(section(self.text, "## Steps")), flat(section(self.text, "## Gates"))
        self.assertIn("in the conversation, and wait for the user's OK or additions", steps)
        self.assertIn("A path the user named: write the file there too", steps)
        self.assertIn("After step 9: the user's OK or additions", gates)
        self.assertTrue(flat(section(self.text, "## Scope")).startswith(
            "Writes: nothing by default — the criteria are shown in the conversation"))

    def test_the_description_changed_one_sentence(self):  # owner, 2026-10-05
        meta = read_front_matter(ACC / "SKILL.md")["description"]
        self.assertIn(DESCRIPTION, meta)
        self.assertNotIn("Saves a Markdown file", meta)
        self.assertLessEqual(len(meta), 600)

    def test_the_removed_rules_are_gone(self):
        for gone in ("unit, integration, manual", "ask for one first",
                     "Before writing: the file path", "Saves a Markdown file the user names",
                     "Write the file at the path the user named"):
            self.assertNotIn(gone, self.all)


class BaselineTest(unittest.TestCase):  # D10
    def setUp(self):
        self.text = (BASE / "SKILL.md").read_text("utf-8")
        self.steps = flat(section(self.text, "## Steps"))

    def test_the_gates_carry_the_restored_content(self):
        for needle in ("**Integration & Dependencies** table", "the **dimension enforcement "
                       "check** of `references/method.md`, one row per block",
                       "`REQ-NNN: <requirement> [source: <file> > <section>]`",
                       "API contracts, architecture rules, data flows, integration points, edge "
                       "cases, business rules, error scenarios, user interactions",
                       "**REQ**, **Technique**, **Risk**, **Dimension** and **Verification** "
                       "(`unit`, `e2e` or `manual`", "equivalence partitioning, boundary values",
                       "pairwise, use case, error guessing", "**Final confirmation**",
                       "the Regression Risks", "the full requirements inventory",
                       "Up to 8 blocks: Gate 3 per block; 9–15: batches of 3–5 blocks",
                       "corrections or screenshots", "written in English"):
            self.assertIn(needle, self.steps)
        self.assertLess(self.steps.index("**Final confirmation**"),
                        self.steps.index("6. Write the doc."))

    def test_the_arguments_are_module_scenario_block(self):
        meta = read_front_matter(BASE / "SKILL.md")
        self.assertEqual((meta["argument-hint"], meta["arguments"]),
                         ("[module] [scenario] [block]", "module scenario block"))
        for name in ("$module", "$scenario", "$block"):
            self.assertEqual(self.text.count(name), 1, name)

    def test_the_template_is_organised_by_block(self):
        tpl = (QA / "roles/qa_acceptance.md").read_text("utf-8")
        heads = ["## Summary", "## Priority Matrix", "## Block 1: <name>", "### Requirements",
                 "### P0 — must never break", "### P1 — should work", "### P2 — good to keep",
                 "## Architecture Rule Coverage", "## Regression Risks",
                 "## Specification Issues", "## Dimension Coverage Matrix", "## Gap Analysis",
                 "## Quality Score", "## Retired"]
        where = [tpl.index(f"\n{h}\n") for h in heads]
        self.assertEqual(where, sorted(where))
        for field in ("**REQ:** REQ-001", "**Technique:**", "**Risk:**", "**Dimension:**",
                      "**Verification:** <unit | e2e | manual>",
                      "| ID | Category | Requirement | Source | Technique | Risk | Dimensions |"):
            self.assertIn(field, tpl)

    def test_the_block_route(self):
        block = flat((BASE / "references/block.md").read_text("utf-8"))
        for needle in ("roles/qa_acceptance.<category>/<name>.md", "Highest assigned id",
                       "Every block shares one id sequence", "`qa_acceptance.legacy.md`",
                       "frozen from then on and never edited", "refresh the index only",
                       "steps 1–5 run scoped to that one block, with the same gates",
                       "The index stays the registered `qa_acceptance` doc"):
            self.assertIn(needle, block)
        refresh = flat((BASE / "references/refresh.md").read_text("utf-8"))
        self.assertIn("It exists: edit it in place, block by block", refresh)
        self.assertIn("only on the user's yes at Gate 1", refresh)


class FilesAndSizesTest(unittest.TestCase):  # X4
    def test_the_references_each_skill_ships(self):
        for directory, names in REFERENCES.items():
            with self.subTest(skill=directory.name):
                self.assertEqual(sorted(p.name for p in (directory / "references").glob("*.md")),
                                 names)

    def test_every_file_under_the_signals(self):
        total = 0
        for directory in REFERENCES:
            for name, text in skill_files(directory).items():
                with self.subTest(file=f"{directory.name}/{name}"):
                    self.assertLessEqual(len(text), BUDGETS["skill_split_signal"])
                    self.assertLessEqual(len(text.splitlines()), 250)
            total += len((directory / "SKILL.md").read_text("utf-8"))
        self.assertLess(total, BUDGETS["pack_split_signal"])

    def test_the_baseline_description_is_unchanged(self):  # X3
        meta = read_front_matter(BASE / "SKILL.md")["description"]
        self.assertEqual(hashlib.sha256(meta.encode()).hexdigest()[:16], "2a0efce95123748f")

    def test_no_placeholder_in_a_reference(self):
        for directory in REFERENCES:
            for name, text in skill_files(directory).items():
                if name != "SKILL.md":
                    with self.subTest(file=f"{directory.name}/{name}"):
                        self.assertEqual(re.findall(r"\$(?:\{|[A-Za-z0-9_]+)", text), [])


if __name__ == "__main__":
    unittest.main()
