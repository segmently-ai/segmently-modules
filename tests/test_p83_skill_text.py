"""P8.3 task 2: the skill and docs wording — the keyword rule (P83-AC-010), the code step of
module-discover (AC-011), module-sync's saved gate and baseline check (AC-012), the chooser's
cost sentence (AC-013), "a temporary file outside the repository" (AC-014), and the budgets
(AC-015)."""
import json
import re
import shlex
import tempfile
import unittest
from pathlib import Path

from modsys.config import builtin_packs_root
from tests.helpers import copy_fixture, run, run_json

ENGINE = Path(__file__).resolve().parents[1]
CORE = builtin_packs_root() / "core" / "skills"

KEYWORDS = (
    "- `keywords`: most changes add none — add one only for a new feature, command or concept later\n"
    "  tasks will name, never a code identifier (class, function, file or variable: code search finds\n"
    "  those). Keywords only grow; a split parent keeps all of them — never remove one from it.\n")
KEYWORDS = "".join("   " + ln for ln in KEYWORDS.splitlines(True))  # nested in step 5's list
CODE_STEP = (
    "3. Go to the code: `modsys code-map files <candidate> --json`; its code is the files whose `via` is\n"
    "   not `docs` (a child without code: its parent's). Search its source files (tests and plans last)\n"
    "   for the terms of `<file>` and their code forms (\"trial days\" → `trialDays`): `git grep -n -e\n"
    "   <term> -- <paths>`; the rest of the repository only when that gives nothing. For a wrong value,\n"
    "   find the line that computes it. Note each code hit as file:line.\n")
STEP_1 = (
    "   Before you edit, save the gate: `modsys ci --base <base> --json > <ci file>` (outside the\n"
    "   repository; ignore its exit code).\n")
STEP_7 = (
    "7. Check: `modsys ci --base <base> --baseline <ci file> --json`. Its steps (`lint`, `drift`,\n"
    "   `coverage`) should pass or be report-only; a `known` finding predates you: report it, never fix\n"
    "   it here. Fix what your updates caused and rerun.\n")
COST = ("The agent reads the whole work order in its own context: on a registry of about 170 modules "
        "(an 80 KB order) a call costs about 55k tokens with the plugin's agent and about 47k with "
        "`codex exec` (measured 2026-10-03).")


def skill(name):
    return (CORE / name / "SKILL.md").read_text(encoding="utf-8")


def all_skills():
    return sorted(builtin_packs_root().glob("*/skills/*/SKILL.md"))


class KeywordRuleTest(unittest.TestCase):  # P83-AC-010
    def test_step_5_bullet_is_exact_once(self):
        self.assertEqual(skill("module-sync").count(KEYWORDS), 1)

    def test_old_phrase_gone_everywhere(self):
        old = "add one only for a new public name a future task would search by"
        for p in all_skills():
            self.assertNotIn(old, " ".join(p.read_text(encoding="utf-8").split()), p)
        docs = (ENGINE / "docs" / "skills.md").read_text(encoding="utf-8")
        self.assertNotIn("a new public name a future task would", " ".join(docs.split()))
        self.assertIn("never a code identifier", " ".join(docs.split()))


class CodeStepTest(unittest.TestCase):  # P83-AC-011
    def test_step_3_is_exact(self):
        text = skill("module-discover")
        self.assertEqual(text.count(CODE_STEP), 1)
        self.assertNotIn("Grep the terms of `<file>` inside that code", text)

    def test_no_unquoted_include_glob(self):
        for p in all_skills():
            self.assertNotRegex(p.read_text(encoding="utf-8"), r"--include=\*", p)


class SavedGateTest(unittest.TestCase):  # P83-AC-012
    def test_step_1_ends_with_the_save(self):
        text = skill("module-sync")
        self.assertEqual(text.count(STEP_1), 1)
        step1 = text.split("\n2. Ask modsys what to update.")[0]
        self.assertTrue(step1.endswith("\n\n" + STEP_1.rstrip("\n") + "\n") or
                        step1.rstrip("\n").endswith(STEP_1.rstrip("\n")), step1[-300:])

    def test_step_7_is_exact(self):
        text = skill("module-sync")
        self.assertEqual(text.count(STEP_7), 1)
        self.assertNotIn("report what failed before you began", text)


class CostSentenceTest(unittest.TestCase):  # P83-AC-013
    def test_paragraph_holds_the_sentence_once(self):
        docs = (ENGINE / "docs" / "skills.md").read_text(encoding="utf-8")
        para = next(p for p in docs.split("\n\n") if p.startswith("**The choosing agent.**"))
        self.assertEqual(" ".join(para.split()).count(COST), 1)
        self.assertEqual(" ".join(docs.split()).count(COST), 1)


class TemporaryFileTest(unittest.TestCase):  # P83-AC-014
    def test_template_text(self):
        t = (ENGINE / "modsys/defaults/templates/agents-md.md").read_text(encoding="utf-8")
        self.assertIn("- Before a task, write it to a temporary file outside the repository and run\n"
                      "  `modsys context --task-file <file> --role <role> --match lexical`;", t)

    def test_scaffold_placeholder(self):
        want = "--task-file <the task in one sentence, in a temporary file outside the repository>"
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            for args, flag in ((("--role", "reviewer"), "--role reviewer "), ((), "")):
                name = "s" + str(len(args))
                code, _o, err = run("packs", "new", name, "--skill", "x" + name, *args, "--root", str(root))
                self.assertEqual((code, err), (0, ""))
                text = (root / ".modsys/packs" / name / "skills" / ("x" + name) / "SKILL.md").read_text(encoding="utf-8")
                self.assertIn(f"modsys context {want} {flag}--match lexical --json", text)

    def test_block_rewritten_once_then_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            R = ("--root", str(root))
            claude = root / "CLAUDE.md"
            self.assertEqual(run_json("agents-md", "--target", "CLAUDE.md", *R)[0], 0)
            text = claude.read_text(encoding="utf-8")
            self.assertIn("write it to a temporary file outside the repository", text)
            self.assertLess(len(text), 3200)
            claude.write_text(text.replace("a temporary file outside the repository", "a file"),
                              encoding="utf-8")
            self.assertEqual(run_json("agents-md", "--target", "CLAUDE.md", *R)[0], 0)
            self.assertEqual(claude.read_text(encoding="utf-8"), text)
            self.assertEqual(run_json("agents-md", "--target", "CLAUDE.md", "--check", *R)[0], 0)


class BudgetTest(unittest.TestCase):  # P83-AC-015
    def test_exact_sizes_of_the_two_rewritten_skills(self):
        self.assertLessEqual(len(skill("module-sync")), 9_000)
        self.assertLessEqual(len(skill("module-discover")), 9_000)


class SavedGateEndToEndTest(unittest.TestCase):  # P83-AC-012 (the two commands, run in order)
    def commands(self):
        text = skill("module-sync")
        save = re.search(r"save the gate: `(modsys ci [^`]*)`", text).group(1)
        check = re.search(r"7\. Check: `(modsys ci [^`]*)`", text).group(1)
        return save, check

    def test_save_then_check_on_a_repository_with_a_known_finding(self):
        from tests.test_ci_baseline import build_repo
        from tests.helpers import git
        save, check = self.commands()
        with tempfile.TemporaryDirectory() as repo_tmp, tempfile.TemporaryDirectory() as out_tmp:
            root = build_repo(repo_tmp)
            ci_file = Path(out_tmp) / "ci.json"
            fill = lambda c: c.replace("<base>", "HEAD~1")  # noqa: E731
            # (1) the step-1 command, as the skill writes it; its redirect is done here
            self.assertTrue(save.endswith(" > <ci file>"), save)
            argv = shlex.split(fill(save[:-len(" > <ci file>")]))[1:]
            code, out, err = run(*argv, "--root", str(root))
            self.assertEqual((code, err), (1, ""))  # the exit code is ignored by the skill
            ci_file.write_text(out, encoding="utf-8")
            # (2) a doc edit; the pre-existing finding stays (its count may change: SI-P83-1)
            with (root / "modules/catalog/MODULE.md").open("a", encoding="utf-8") as fh:
                fh.write("One more sentence.\n")
            with (root / "modules/payments/MODULE.md").open("a", encoding="utf-8") as fh:
                fh.write("The till code changed.\n")  # documents the code change: no MS050
            # (3) the step-7 command, as written
            argv = shlex.split(fill(check).replace("<ci file>", str(ci_file)))[1:]
            code, out, err = run(*argv, "--root", str(root))
            data = json.loads(out)["data"]
            steps = {st["step"] if "step" in st else st["name"]: st for st in data["steps"]}
            known = sum(st["summary"].get("known", 0) for st in steps.values() if "summary" in st)
            self.assertGreater(known, 0, out)
            self.assertEqual(err, "")
            self.assertEqual(code, 0, out)
            # (4) nothing of the gate in the repository
            self.assertNotIn("ci.json", git(root, "status", "--porcelain"))


if __name__ == "__main__":
    unittest.main()
