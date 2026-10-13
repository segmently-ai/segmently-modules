"""P8.3 task 2: the skill and docs wording — the keyword rule (P83-AC-010), the code step of
module-discover (AC-011), module-sync's saved gate and baseline check (AC-012), the chooser's
cost sentence (AC-013), "a temporary file outside the repository" (AC-014), and the budgets
(AC-015). The final review's fix wave: step 7 fixes a stale path the change itself caused (I-1),
the release notes name T2's changes (I-3), the docs name the saved gate (M-2)."""
import json
import re
import shlex
import tempfile
import unittest
from pathlib import Path

from segmently_modules.config import builtin_packs_root, core_defaults
from tests.helpers import changelog_release, changelog_since_first_release, copy_fixture, run, run_json
from tests.test_budgets import SPLIT_DECISIONS, decision_key

ENGINE = Path(__file__).resolve().parents[1]
CORE = builtin_packs_root() / "core" / "skills"

KEYWORDS = (
    "- `keywords`: most changes add none. Add one only for a new feature, command or concept that\n"
    "  people will name in later tasks and that no keyword or the description covers yet — never a\n"
    "  code identifier (a class, function, file or variable name: code search finds those), never\n"
    "  one per task. Keywords only grow; a split parent keeps all of them — never remove one from it.\n")
KEYWORDS = "".join("   " + ln for ln in KEYWORDS.splitlines(True))  # nested in step 5's list
CODE_STEP = (  # P84-AC-013: D2 in full, F27, F28 (SI-P84-18 as amended); a wrapped skill's
    # steps live in its procedure
    "3. Go to the code: `segmently-modules code-map files <candidate> --json`; its code is the files whose `via`\n"
    "   holds more than `docs`. A picked child or a docs-only module has no code of its own: search its\n"
    "   parent's code paths (when it has a parent) for the task's terms and let step 4's `--files` name\n"
    "   the owner. Search its source files first — tests, fixtures and plans last — for the terms of\n"
    "   `<file>` and their code forms (\"trial days\" → `trialDays`):\n"
    "   `git grep -n -e <term> -- <path> …` (no shell glob); the rest of the repository only when that\n"
    "   gives nothing. For a wrong value, find where it is computed and set, not only the lines that\n"
    "   read it. Note each code hit as file:line.\n")
STEP_1 = (
    "   Before you edit, save the gate: `segmently-modules ci --base <base> --json > <ci file>` (outside the\n"
    "   repository; ignore its exit code).\n")
STEP_7 = (  # final review I-1 (ruled): a stale path the change itself caused is fixed, not excused
    # (P8.7 D5: the check is step 9 since the session's knowledge came first)
    "9. Check: `segmently-modules ci --base <base> --baseline <ci file> --json`. Its steps (`lint`, `drift`,\n"
    "   `coverage`) should pass or be report-only; a `known` finding predates your edits: report it, but\n"
    "   fix one the change caused (a moved or deleted path). Fix what your updates caused and rerun.\n")
FIX_CLAUSE = ("a `known` finding predates your edits: report it, but fix one the change caused "
              "(a moved or deleted path).")
MAP_ONLY = '[[code_map]]\nid = "src"\npattern = "src/{module}/**"\n'
PAYMENTS_DOC = ("# payments\n\nThe till and the receipts.\n\n## EXISTING Components\n\n"
                "| Path | Role |\n|---|---|\n| `src/payments/till.py` | the till |\n")
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
    def test_the_p83_code_step_gave_way_to_d2(self):  # P8.6 D2: touch points for planning
        text = skill("module-discover")
        self.assertFalse((CORE / "module-discover/references/procedure.md").exists())
        self.assertNotIn(CODE_STEP, text)
        self.assertNotIn("computed and set", text)  # discover is no search for a bug's cause
        self.assertNotIn("Grep the terms of `<file>` inside that code", text)
        self.assertEqual(text.count("6. **Code touch points.**"), 1)

    def test_no_unquoted_include_glob(self):
        for p in all_skills():
            self.assertNotRegex(p.read_text(encoding="utf-8"), r"--include=\*", p)


class SavedGateTest(unittest.TestCase):  # P83-AC-012
    def test_step_1_ends_with_the_save(self):
        text = skill("module-sync")
        self.assertEqual(text.count(STEP_1), 1)
        step1 = text.split("\n3. Ask Segmently Modules what to update")[0]  # P8.7: the pin is step 2
        self.assertTrue(step1.endswith("\n\n" + STEP_1), step1[-300:])  # its own lines (review M-1)

    def test_step_7_is_exact(self):
        text = skill("module-sync")
        self.assertEqual(text.count(STEP_7), 1)
        self.assertNotIn("report what failed before you began", text)
        flat = " ".join(text.split())
        self.assertEqual(flat.count(FIX_CLAUSE), 1)
        self.assertNotIn("predates you: report it, never fix it here", flat)  # final review I-1


class CostSentenceTest(unittest.TestCase):  # P83-AC-013
    def test_paragraph_holds_the_sentence_once(self):
        docs = (ENGINE / "docs" / "skills.md").read_text(encoding="utf-8")
        para = next(p for p in docs.split("\n\n") if p.startswith("**The choosing agent.**"))
        self.assertEqual(" ".join(para.split()).count(COST), 1)
        self.assertEqual(" ".join(docs.split()).count(COST), 1)


class TemporaryFileTest(unittest.TestCase):  # P83-AC-014
    def test_template_text(self):
        t = (ENGINE / "segmently_modules/defaults/templates/agents-md.md").read_text(encoding="utf-8")
        self.assertIn("- Before a task, write it to a temporary file outside the repository and run\n"
                      "  `segmently-modules context --task-file <file> --role <role> --match lexical`;", t)

    def test_scaffold_placeholder(self):
        want = "--task-file <the task in one sentence, in a temporary file outside the repository>"
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            for args, flag in ((("--role", "reviewer"), "--role reviewer "), ((), "")):
                name = "s" + str(len(args))
                code, _o, err = run("packs", "new", name, "--skill", "x" + name, *args, "--root", str(root))
                self.assertEqual((code, err), (0, ""))
                text = (root / ".segmently-modules/packs" / name / "skills" / ("x" + name) / "SKILL.md").read_text(encoding="utf-8")
                self.assertIn(f"segmently-modules context {want} {flag}--match lexical --json", text)

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


def over_bound(names, bound: int) -> list[str]:
    """The core skills over `bound` that `SPLIT_DECISIONS` does not record (SI-P85-11)."""
    return [n for n in names
            if len(skill(n)) > bound and decision_key("core", n) not in SPLIT_DECISIONS]


class BudgetTest(unittest.TestCase):  # P83-AC-015
    def test_the_two_rewritten_skills_are_within_the_skill_bound(self):  # review M-3: a name
        self.assertEqual(over_bound(("module-sync", "module-discover"),
                                    core_defaults()["budgets"]["skill_split_signal"]), [])


class SavedGateEndToEndTest(unittest.TestCase):  # P83-AC-012 (the two commands, run in order)
    def commands(self):
        text = skill("module-sync")
        save = re.search(r"save the gate: `(segmently-modules ci [^`]*)`", text).group(1)
        check = re.search(r"9\. Check: `(segmently-modules ci [^`]*)`", text).group(1)
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
            # (4) the two commands wrote nothing into the repository: only the two doc edits
            self.assertEqual(sorted(git(root, "status", "--porcelain").splitlines()),
                             [" M modules/catalog/MODULE.md", " M modules/payments/MODULE.md"])

    def test_a_path_the_change_moved_is_known_and_the_skill_says_fix_it(self):  # final review I-1
        from tests.helpers import git, init_git, make_repo
        save, check = self.commands()
        self.assertEqual(" ".join(skill("module-sync").split()).count(FIX_CLAUSE), 1)
        stale = ("MS040", "payments", "component path missing on disk: src/payments/till.py",
                 "modules/payments/MODULE.md")
        with tempfile.TemporaryDirectory() as repo_tmp, tempfile.TemporaryDirectory() as out_tmp:
            root = make_repo(repo_tmp, {"catalog": ["book", "shelf"],
                                        "payments": ["till", "receipt"]},
                             MAP_ONLY, ("src/catalog/shelf.py", "src/payments/till.py"))
            doc = root / "modules/payments/MODULE.md"
            doc.write_text(PAYMENTS_DOC, encoding="utf-8")
            init_git(root)
            # the committed change renames the file the payments doc lists
            git(root, "mv", "src/payments/till.py", "src/payments/register.py")
            git(root, "commit", "-q", "-m", "payments: the till is the register")
            ci_file = Path(out_tmp) / "ci.json"
            def ci(command):  # a command of the skill, its placeholders filled in
                command = command.replace("<base>", "HEAD~1").replace("<ci file>", str(ci_file))
                code, out, err = run(*shlex.split(command)[1:], "--root", str(root))
                self.assertEqual(err, "")
                data = json.loads(out)["data"]
                return code, out, {(st["name"], f["code"], f["module"], f["message"], f["path"]):
                                   f.get("known") for st in data["steps"]
                                   for f in st.get("findings", [])}

            # step 1: the saved gate already holds the stale path the change caused
            code, out, first = ci(save[:-len(" > <ci file>")])
            self.assertEqual(code, 1)
            self.assertIn(("lint", *stale), first)
            self.assertIn(("drift", *stale), first)
            ci_file.write_text(out, encoding="utf-8")
            # the sync documents the change but keeps the stale path: step 7 calls it known …
            with doc.open("a", encoding="utf-8") as fh:
                fh.write("The till is the register now.\n")
            code, _, found = ci(check)
            self.assertEqual(code, 0)
            self.assertEqual((found[("lint", *stale)], found[("drift", *stale)]), (True, True))
            # … and the skill says to fix it: with the path fixed the finding is gone
            doc.write_text(doc.read_text(encoding="utf-8").replace("till.py", "register.py"),
                           encoding="utf-8")
            code, _, found = ci(check)
            self.assertEqual((code, found), (0, {}))


class ReleaseNotesTest(unittest.TestCase):  # final review I-3
    def unreleased(self):
        log = (ENGINE / "CHANGELOG.md").read_text(encoding="utf-8")
        return changelog_since_first_release(log)

    def test_the_keyword_line_states_the_d1_rule(self):  # P8.4 fix wave M-1: once, final words
        flat = " ".join(self.unreleased().split())
        self.assertNotIn("a keyword only for a new public name", flat)
        self.assertEqual(flat.count("adds a keyword only"), 1)
        self.assertIn("`module-sync` adds a keyword only for a new feature, command or concept "
                      "that later tasks will name and that no keyword or the description covers "
                      "yet — never a code identifier, never one per task;", flat)

    def test_one_changed_entry_names_t2(self):
        log = (ENGINE / "CHANGELOG.md").read_text(encoding="utf-8")  # 0.1.1 shipped it
        changed = changelog_release(log, "0.1.1").split("### Changed", 1)[1].split("### Fixed", 1)[0]
        entries = [" ".join(e.split()) for e in changed.split("\n- ")]
        mine = [e for e in entries if "`ci --baseline`" in e and "never a code identifier" in e]
        self.assertEqual(len(mine), 1, entries)
        for needle in ("`git grep -n -e <term> -- <paths>`",
                       "saves the gate", "a temporary file outside the repository", "`packs new`"):
            self.assertIn(needle, mine[0])
        self.assertNotIn("where a wrong value is computed", mine[0])  # P8.6 D2 removed the rule
        self.assertTrue(mine[0].endswith(
            "run `modsys agents-md` and `modsys packs sync` after the upgrade — `--check` "  # the old name
            "reports the old block and stale copies until then."), mine[0])


class DocsSavedGateTest(unittest.TestCase):  # final review M-2 (1)
    def test_skills_md_names_the_saved_gate(self):
        docs = (ENGINE / "docs" / "skills.md").read_text(encoding="utf-8")
        start = docs.index("\n`module-sync` reads the plan")  # module-sync's passage
        passage = docs[start:docs.index("\n## ", start)]
        paras = [p for p in passage.split("\n\n") if "saves the gate" in p]
        self.assertEqual(len(paras), 1, passage)
        flat = " ".join(paras[0].split())
        for needle in ("saves the gate", "`segmently-modules ci --base \"$BASE\" --json`",
                       "`segmently-modules ci --base \"$BASE\" --baseline", "known"):
            self.assertIn(needle, flat)


if __name__ == "__main__":
    unittest.main()
