"""P6.1 docs: the three new verbs in the contract and the docs, the release notes step and the
CI triggers, the Python note, and the `module-sync` section that adds a role."""

import re
import unittest
from pathlib import Path

from modsys.config import builtin_packs_root

ROOT = Path(__file__).resolve().parent.parent
SYNC = builtin_packs_root() / "core" / "skills" / "module-sync" / "SKILL.md"

# The module-sync front matter as the previous release shipped it: it must not change (a new
# trigger would move the skill's routing).
SYNC_NAME = "module-sync"
SYNC_DESCRIPTION = (
    "Brings module docs and registry fields in line with finished work. Asks modsys "
    "sync-instructions which modules the change touched, which docs to update, which drift "
    "checks fail and what each field's sync hint says, then edits the docs, updates keywords "
    "and links, runs the team's sync hooks and checks the result with modsys ci. Autonomous, "
    "it asks only in four ambiguous cases and never commits. Use at the end of a task that "
    "changed module code, when the user says \"sync the docs\", \"update the module docs\", or "
    "when a CI drift check fails.")


def doc(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


class ModuleSyncRoleSectionTest(unittest.TestCase):
    """P61-AC-025"""

    def setUp(self):
        self.text = SYNC.read_bytes().decode("utf-8")

    def test_front_matter_is_unchanged(self):
        head, _, _ = self.text[4:].partition("\n---\n")
        self.assertEqual(head, f"name: {SYNC_NAME}\ndescription: {SYNC_DESCRIPTION}")

    def section(self):
        self.assertEqual(self.text.count("\n## A new role\n"), 1)
        return self.text.split("\n## A new role\n", 1)[1].split("\n## ", 1)[0]

    def test_the_section_has_the_five_steps_in_order(self):
        steps = re.findall(r"^(\d)\. (.*)", self.section(), re.M)
        self.assertEqual([n for n, _ in steps], ["1", "2", "3", "4", "5"])
        starts = ["`modsys roles add ROLE --all --dry-run`", "`modsys roles add ROLE --all --json`",
                  "Fill each new doc", "`modsys lint", "`modsys next"]
        for (n, line), start in zip(steps, starts):
            self.assertTrue(line.startswith(start), f"step {n}: {line!r}")

    def test_the_section_names_no_tool_but_modsys_and_git(self):
        spans = re.findall(r"`([^`]+)`", self.section())
        commands = [s for s in spans if not s.startswith("-")]  # a flag is not a command
        self.assertTrue(commands)
        for command in commands:
            self.assertRegex(command, r"^(modsys|git) ", command)

    def test_the_section_keeps_the_placeholder_out(self):
        self.assertNotIn("<owner>", self.section())


class ReadmeTest(unittest.TestCase):
    """P61-AC-024 (README)"""

    def setUp(self):
        self.text = doc("README.md")

    def test_the_three_verbs(self):
        for verb in ("modsys setup", "modsys next", "modsys roles add"):
            self.assertIn(verb, self.text)

    def test_the_python_note(self):
        for fact in ("Python ≥ 3.11", "3.9", "/usr/bin/python3", "uvx", "brew install python"):
            self.assertIn(fact, self.text)

    def test_gemini_target(self):
        self.assertIn("--target GEMINI.md", self.text)

    def test_placeholders_stay_and_no_comparison_section(self):
        self.assertIn("<owner>/<repo>", self.text)
        self.assertNotIn("How it compares", self.text)


class ContractTest(unittest.TestCase):
    """P61-AC-024 (contract)"""

    def test_a_row_per_verb_with_schema_and_exit_codes(self):
        rows = {m.group(1): m.group(0) for m in
                re.finditer(r"^\| `(roles|next|setup)\b[^\n]*", doc("docs/cli-contract.md"), re.M)}
        self.assertEqual(sorted(rows), ["next", "roles", "setup"])
        for verb, row in rows.items():
            self.assertIn(f"modsys.{verb}/1", row, verb)
            self.assertRegex(row, r"exit (0|1|2)", verb)


class DocPagesTest(unittest.TestCase):
    """P61-AC-024 (configuration, pack docs, releasing)"""

    def test_roles_add_for_existing_modules(self):
        for name in ("docs/configuration.md", "docs/writing-a-pack.md"):
            text = doc(name)
            for fact in ("modsys roles add", "--all", "--dry-run", "--recreate", "modsys roles list",
                         "modsys next"):
                self.assertIn(fact, text, f"{name}: {fact}")

    def test_releasing_notes_and_ci_triggers(self):
        text = doc("docs/releasing.md")
        for fact in ("[Unreleased]", "CHANGELOG.md", "MODSYS_RELEASE_DATE", "no notes yet",
                     "pull requests", "version tags"):
            self.assertIn(fact, text)

    def test_the_actions_event_keyword_stays_in_the_workflow(self):
        keyword = "pull" + "_request"
        for name in ("README.md", "docs/releasing.md", "docs/cli-contract.md",
                     "docs/configuration.md", "docs/writing-a-pack.md", "docs/skills.md"):
            self.assertNotIn(keyword, doc(name), name)


if __name__ == "__main__":
    unittest.main()
