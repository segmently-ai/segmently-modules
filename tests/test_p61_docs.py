"""P6.1 docs: the three new verbs in the contract and the docs, the release notes step and the
CI triggers, the Python note, and the `module-sync` section that adds a role."""

import json
import re
import shlex
import shutil
import tempfile
import tomllib
import unittest
from pathlib import Path

from modsys.config import builtin_packs_root
from tests.helpers import copy_fixture, init_git, run

ROOT = Path(__file__).resolve().parent.parent
SYNC = builtin_packs_root() / "core" / "skills" / "module-sync" / "SKILL.md"
ROLES = builtin_packs_root() / "core" / "skills" / "module-roles" / "SKILL.md"

# The module-sync front matter: it must not change by accident (a new trigger moves the skill's
# routing). P8.7 (X3, owner): the trigger widened to a session that revealed module knowledge.
SYNC_NAME = "module-sync"
SYNC_DESCRIPTION = (
    "Brings module docs and registry fields in line with a work session — what it decided, "
    "rejected, discovered and changed. Takes the session's knowledge first and the code "
    "change second, asks modsys sync-instructions which docs to update, prints findings and a "
    "proposal per module, edits docs, keywords and links, runs the sync hooks and checks with "
    "modsys ci. Autonomous, it asks only in four ambiguous cases and never commits. Use at "
    "the end of a session that changed module code or revealed module knowledge, when the "
    "user says \"sync the session\", \"sync the docs\", or a CI drift check fails.")


def doc(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


class ModuleSyncRoleSectionTest(unittest.TestCase):
    """P61-AC-025; since P8.4 D2 (P84-AC-018) the scenario lives in `module-roles`' Steps and
    `module-sync` keeps its front matter and no `## A new role` section."""

    def setUp(self):
        self.sync = SYNC.read_bytes().decode("utf-8")
        self.text = ROLES.read_bytes().decode("utf-8")

    def test_front_matter_is_unchanged(self):
        head, _, _ = self.sync[4:].partition("\n---\n")
        self.assertEqual(head, f"name: {SYNC_NAME}\ndescription: {SYNC_DESCRIPTION}")

    def test_module_sync_has_no_role_section(self):
        self.assertNotIn("## A new role", self.sync)

    def section(self):
        self.assertEqual(self.text.count("\n## Steps\n"), 1)
        return self.text.split("\n## Steps\n", 1)[1].split("\n## ", 1)[0]

    def test_the_section_has_the_five_steps_in_order(self):
        steps = re.findall(r"^(\d)\. (.*)", self.section(), re.M)
        self.assertEqual([n for n, _ in steps], ["1", "2", "3", "4", "5"])
        starts = ["`modsys roles add ROLE --all --dry-run`", "`modsys roles add ROLE --all --json`",
                  "Fill each new doc", "`modsys lint", "`modsys next"]
        for (n, line), start in zip(steps, starts):
            self.assertTrue(line.startswith(start), f"step {n}: {line!r}")

    def test_an_undeclared_role_is_declared_before_step_1(self):  # fix wave item 8
        before = " ".join(self.section().split("\n1. ", 1)[0].split())
        for fact in ("`modsys roles list --json`", "[roles.", ".modsys/config.toml", "order",
                     "standard = true", "description", "ask the user", "pack",
                     "continue with step 1"):
            self.assertIn(fact, before, fact)

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

    def shortest_start(self) -> list[tuple[str, str]]:
        """The fenced blocks of "The shortest start", in order: (language, body)."""
        section = self.text.split("\n## The shortest start\n", 1)[1].split("\n## ", 1)[0]
        return re.findall(r"^```(\w+)\n(.*?)^```$", section, re.M | re.S)

    def test_the_shortest_start_declares_the_role_it_adds(self):  # final review I-3
        blocks = self.shortest_start()
        self.assertEqual([lang for lang, _ in blocks], ["bash", "toml", "bash"])
        role = tomllib.loads(blocks[1][1])["roles"]["security"]
        self.assertEqual((sorted(role), role["standard"]),
                         (["description", "order", "standard"], True))
        commands = [shlex.split(line, comments=True) for line in blocks[2][1].splitlines()]
        self.assertEqual(commands, [["modsys", "roles", "add", "security", "--all", "--dry-run"],
                                    ["modsys", "roles", "add", "security", "--all"]])
        self.assertNotIn("roles add designer", self.text)

    def test_the_shortest_start_runs_as_written(self):  # final review I-3
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(Path(tmp).resolve())
            shutil.rmtree(root / ".modsys/packs")  # the engine's roles only, as after a setup
            init_git(root)
            results = []
            for lang, body in self.shortest_start():
                if lang == "toml":  # the snippet goes into the team config setup wrote
                    with open(root / ".modsys/config.toml", "a", encoding="utf-8") as fh:
                        fh.write("\n" + body)
                    continue
                for line in body.splitlines():
                    argv = shlex.split(line, comments=True)
                    self.assertEqual(argv[0], "modsys", line)
                    code, out, err = run(*argv[1:], "--json", "--root", str(root))
                    self.assertEqual((code, err), (0, ""), line)
                    results.append(json.loads(out)["data"])
            self.assertEqual([r["status"] for r in results[-1]["results"]], ["created"] * 3 + ["inherited"])
            self.assertTrue((root / "modules/catalog/roles/security.md").is_file())


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

    def test_releasing_steps_and_notes_say_what_the_tool_does(self):  # final review M-3
        text = doc("docs/releasing.md")
        steps = dict(re.findall(r"^\| (\d) [^|]*\| (.*) \|$", text, re.M))
        for fact in ("`CHANGELOG.md`", "`## [Unreleased]`", "`stable`", "note"):
            self.assertIn(fact, steps["1"], fact)  # the notes check runs first
        for fact in ("`CHANGELOG.md`", "`## [X.Y.Z] - DATE`"):
            self.assertIn(fact, steps["4"], fact)  # the release commit dates the section
        notes = text.split("\n## Release notes\n", 1)[1].split("\n## ", 1)[0]
        flat = " ".join(notes.split())
        for fact in ("two `## [Unreleased]` headings", "`<!-- modsys:changelog:`",
                     "dev as well as stable", "comment line", "dropped"):
            self.assertIn(fact, flat, fact)

    def test_the_actions_event_keyword_stays_in_the_workflow(self):
        keyword = "pull" + "_request"
        for name in ("README.md", "docs/releasing.md", "docs/cli-contract.md",
                     "docs/configuration.md", "docs/writing-a-pack.md", "docs/skills.md"):
            self.assertNotIn(keyword, doc(name), name)


if __name__ == "__main__":
    unittest.main()
