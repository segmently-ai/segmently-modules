"""P8.4 task 2, the three wrapped skills (D3, D4, D6): `module-discover`, `module-scout` and
`module-research` keep the description, When to use / not, Scope and Gates, take
`argument-hint` (no `arguments:` key and no placeholder: the fix wave's ruling on the final
review's I-1 — Claude Code appends the whole invocation text as an `ARGUMENTS:` line), and hand
the task to their shipped agent in one step; the steps and the exit codes moved word for word
into `references/procedure.md` (which the agent runs), with the D6 texts in discover's step 3 and
step 7, and the procedure ends with the skill's Scope and Gates (I-2) so the agent gets them
(P84-AC-011 to 016, 027, 030). The text of the shared choose step is pinned by
`test_p81_skill_text`; the skill-eval graders by `test_skill_evals`."""
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from modsys.config import builtin_packs_root, core_defaults
from modsys.skills import front_matter
from tests.helpers import SPLIT_FIXTURE, copy_fixture, init_git, run, run_json
from tests.test_builtin_skills import argv, commands, section
from tests.test_p81_skill_text import flat

ENGINE = Path(__file__).resolve().parents[1]
CORE = builtin_packs_root() / "core" / "skills"
WRAPPED = ("module-discover", "module-scout", "module-research")
# MS068's default split signal, read from the engine (D5: a signal, never a literal cap here)
SPLIT_SIGNAL = core_defaults()["budgets"]["skill_split_signal"]
# What the three skills were before this task: the sha256 prefix of each kept section, the length
# of SKILL.md and of its `## Steps`, and the hash of each sentence of `## Steps` + `## Exit codes`
# (a sentence ends at . ! ? not after a digit; the text is whitespace-normalized).
BEFORE = {'module-discover': {'sections': {'When to use': '49dadde52140', 'When not to use': 'c4769a13ee0c', 'Scope': '151960f8fe2a', 'Gates': '0b0874de1e04'}, 'len': 5839, 'steps': 4217}, 'module-scout': {'sections': {'When to use': '70f06df280cf', 'When not to use': '0fdf403309ab', 'Scope': '09c22982efac', 'Gates': 'fa5442c6f201'}, 'len': 4966, 'steps': 3222}, 'module-research': {'sections': {'When to use': 'afe582f7edd3', 'When not to use': 'ae52bcbc4344', 'Scope': 'a01b2b1b7943', 'Gates': 'b632ccc829ac'}, 'len': 5210, 'steps': 3464}}
SENTENCES = {'module-discover': ['ac8ea9fe45a0', '1eb50f63c3c7', 'b63bd2f1f2a9', '30a3e7776a59', 'ceb4ed4d46b2', '00294cf671d2', 'd03d5928927a', 'fd2664d5c59e', '8c2e4001a6ec', '8fda918e1466', '44290e0e6418', '462a78b17bca', '272101108c66', 'abc19fb107a5', 'd3509a6322e9', '59fe8110a144', '0fa3a0662828', '659672f8b5d2', '9e1fb88ba206', '5ffc51bcee5f', 'a4fce89999e4', 'a21bf04fef4b', '4e7dd66e10e0', '583d7c775cc8', 'fe6aece06d34', 'b2de0814a445', '35019085bf7f', '3cba72a91ab7', '6bbdfaccd074'], 'module-scout': ['0cef86f8bdff', 'b35eddc90893', '1eb50f63c3c7', '0cbc94a5e5e3', 'ceb4ed4d46b2', '00294cf671d2', 'd03d5928927a', 'fd2664d5c59e', '8c2e4001a6ec', '8fda918e1466', '44290e0e6418', '5b879432326c', '272101108c66', 'b485d78e63be', '90657f08de89', '0cbfd07d2795', '8d6e69f74a2d', '0f30d8f86a66', '9c9efcc0da76', '2f8a86fb2b33', '615e96680041', '7c10cce120af', '075d29c16e69', '97f0f15a3c31', 'a08ff7657bf6', '6e031a27af64', 'a3f568405110'], 'module-research': ['ff8433b7fc5a', '0cef86f8bdff', 'b35eddc90893', '1eb50f63c3c7', '0cbc94a5e5e3', 'ceb4ed4d46b2', '00294cf671d2', 'd03d5928927a', 'fd2664d5c59e', '8c2e4001a6ec', '8fda918e1466', '44290e0e6418', '5b879432326c', '272101108c66', 'b485d78e63be', '53ef51608376', 'c8aa0afeeb38', 'bbf3af62eb26', '36fc85de475f', 'c980ba7ce3d9', '7c3dea3e30a9', '32ad8ecc0b26', 'a3619e9710c2', 'daea4a960804', 'b0c8cdc7ea25', 'e75216e25311', '70cae2040ed3', '67727e53c636', 'c40f86967d10', '6702112a89ea', 'dae4d9f75776', '68dbb0512e56']}
# discover's step 3 is replaced by D6 (P84-AC-013); these three sentences of it are gone
REPLACED = {"module-discover": 3}


def h(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def sentences(text: str) -> list[str]:
    return re.split(r"(?<=[^\d][.!?])\s+", flat(text))


def skill(name: str) -> str:
    return (CORE / name / "SKILL.md").read_text(encoding="utf-8")


def procedure(name: str) -> str:
    return (CORE / name / "references" / "procedure.md").read_text(encoding="utf-8")


def sections(text: str, name: str) -> str:
    return section("\n" + text, name if name.startswith("## ") else "## " + name)


def raw_section(text: str, heading: str) -> str:
    """The bytes of a `## ` section, its heading line included, up to the next `## ` heading
    (or the end of the text)."""
    start = text.index(f"\n## {heading}\n") + 1
    end = text.find("\n## ", start)
    return text[start:] if end < 0 else text[start:end + 1]


def sandbox_free(text: str) -> str:
    """The procedure without its one read-only-sandbox paragraph (a lead-in and a fenced block)."""
    return re.sub(r"   If a temporary file cannot be written.*?\n   ```\n", "", text, flags=re.S)


class ThinSkillTest(unittest.TestCase):  # P84-AC-011
    def test_the_kept_sections_are_byte_identical(self):
        for name in WRAPPED:
            with self.subTest(skill=name):
                for heading, digest in BEFORE[name]["sections"].items():
                    self.assertEqual(h(sections(skill(name), heading)), digest, heading)
                self.assertEqual(skill(name).count("`modsys` plugin for Claude Code"), 1)  # install line

    def test_front_matter_adds_exactly_the_hint(self):  # fix wave I-1: no `arguments:` key
        for name in WRAPPED:
            with self.subTest(skill=name):
                text = skill(name)
                self.assertEqual(list(front_matter(text)), ["name", "description", "argument-hint"])
                head = text.split("\n---\n", 1)[0]
                self.assertTrue(head.endswith('\nargument-hint: "[task]"'))
                self.assertNotIn("\narguments:", head)

    def test_no_exit_codes_and_no_command(self):
        for name in WRAPPED:
            with self.subTest(skill=name):
                self.assertNotIn("## Exit codes", skill(name))
                self.assertEqual(commands(skill(name)), [])

    def test_one_numbered_step_that_hands_the_task_over(self):
        for name in WRAPPED:
            with self.subTest(skill=name):
                steps = flat(sections(skill(name), "Steps"))
                self.assertTrue(steps.startswith("1. "), steps)
                self.assertEqual(re.findall(r"(?:^| )(\d+)\. ", steps), ["1"])
                # final review M-9: the labels and the mid-sentence phrases keep their case
                for phrase in ("hand the user's task verbatim, with what the user settled in "
                               "this conversation", "what the user settled in this conversation "
                               "(files, constraints, the depth)",
                               "give its report as yours",
                               "Claude Code: the `modsys:" + name + "-agent` agent",
                               "Codex: spawn the `" + name + "-agent` custom agent "
                               "(`.codex/agents/`)",
                               "the agent is read-only"):
                    self.assertEqual(steps.count(phrase), 1, phrase)
                # a sentence's first word may change its case; final review I-1: the condition
                # leads, the imperative follows it
                for phrase in ("only when no such agent exists, read `references/procedure.md` "
                               "and follow it",
                               "a request that also says \"change nothing\" is still a hand-off"):
                    self.assertEqual(steps.lower().count(phrase.lower()), 1, phrase)
                self.assertNotIn("Read `references/procedure.md` and follow it only", steps)
                self.assertNotIn("without that agent, read", steps)  # SI-P85-9
                self.assertNotIn("``", steps)  # no empty code span where a placeholder was

    def test_each_skill_shrank_by_its_steps(self):
        for name in WRAPPED:
            with self.subTest(skill=name):
                before = BEFORE[name]
                self.assertLessEqual(len(skill(name)), before["len"] - before["steps"] + 600)
                self.assertLess(len(skill(name)), before["len"])

    def test_no_placeholder_at_all(self):  # P84-AC-027, SI-P84-12 as the fix wave amends them
        for name in WRAPPED:
            with self.subTest(skill=name):
                self.assertEqual(re.findall(r"\$[A-Za-z0-9{]\w*", skill(name)), [])
                self.assertNotIn("$ARGUMENTS", skill(name))


class ProcedureTest(unittest.TestCase):  # P84-AC-012
    def test_every_old_sentence_is_there_in_order(self):
        for name in WRAPPED:
            with self.subTest(skill=name):
                text = sandbox_free(procedure(name))
                new = ([h(s) for s in sentences(sections(text, "Steps"))]
                       + [h(s) for s in sentences(sections(text, "Exit codes"))])
                at, missing = 0, []
                for digest in SENTENCES[name]:
                    if digest in new[at:]:
                        at += new[at:].index(digest) + 1
                    else:
                        missing.append(digest)
                self.assertEqual(len(missing), REPLACED.get(name, 0), missing)

    def test_nothing_of_the_steps_stays_in_skill_md(self):
        for name in WRAPPED:
            with self.subTest(skill=name):
                body = flat(skill(name))
                for line in ("1. No module named?", "Run `modsys catalog --json`",
                             "A change without a task starts at step 4.",
                             "Pin the question in one sentence."):
                    self.assertNotIn(line, body)

    def test_headings_and_limits(self):
        for name in WRAPPED:
            with self.subTest(skill=name):
                text = procedure(name)
                self.assertTrue(text.startswith("## Steps\n"))
                self.assertEqual(re.findall(r"^## .*$", text, re.M),
                                 ["## Steps", "## Exit codes", "## Scope", "## Gates"])
                self.assertLessEqual(len(text.splitlines()), 250)
                self.assertLessEqual(len(text), SPLIT_SIGNAL)

    def test_the_procedure_ends_with_the_skills_scope_and_gates(self):  # fix wave I-2
        for name in WRAPPED:
            with self.subTest(skill=name):
                text, own = procedure(name), skill(name)
                for heading in ("Scope", "Gates"):
                    self.assertEqual(raw_section(text, heading), raw_section(own, heading),
                                     heading)
                self.assertTrue(text.endswith(raw_section(text, "Scope")
                                              + raw_section(text, "Gates")))
                self.assertIn("never commit", flat(raw_section(text, "Scope")))

    def test_self_contained_and_no_placeholder(self):  # SI-P84-10, SI-P84-12
        others = {"SKILL.md", "references/", "procedure.md"}
        for name in WRAPPED:
            with self.subTest(skill=name):
                text = procedure(name)
                for token in others:
                    self.assertNotIn(token, text)
                self.assertEqual(re.findall(r"\$[A-Za-z0-9{]", text), [])

    def test_commands_are_lexical_and_never_take_task(self):
        for name in WRAPPED:
            with self.subTest(skill=name):
                for command in commands(procedure(name)):
                    self.assertNotIn("--task", argv(command))
                    if argv(command)[:1] in (["discover"], ["context"]) and any(
                            a.startswith("--task") for a in argv(command)):
                        self.assertIn("lexical", argv(command))

    def test_the_agent_still_names_the_chooser(self):
        for name in WRAPPED:
            with self.subTest(skill=name):
                self.assertEqual(flat(procedure(name)).count("`modsys:module-chooser`"), 1)


class DiscoverTextTest(unittest.TestCase):  # P84-AC-013, P84-AC-014
    def test_step_3_is_d2_in_full_with_f27_and_f28(self):
        text = flat(procedure("module-discover"))
        step3 = text[text.index("3. Go to the code"):text.index("4. Get the touch-set.")]
        for phrase in ("whose `via` holds more than `docs`",
                       "A picked child or a docs-only module has no code of its own",
                       "(when it has a parent)", "the task's terms",
                       "step 4's `--files` name the owner",
                       "Search its source files first — tests, fixtures and plans last —",
                       "`git grep -n -e <term> -- <path> …` (no shell glob)",
                       "the rest of the repository only when that gives nothing",
                       "not only the lines that read it", "file:line"):
            self.assertEqual(step3.count(phrase), 1, phrase)
        for gone in ("whose `via` is not `docs`", "(tests and plans last)",
                     "(a child without code: its parent's)",
                     "For a wrong value, find the line that computes it."):
            self.assertNotIn(gone, text)

    def test_step_7_names_the_role_docs(self):  # F29
        text = flat(procedure("module-discover"))
        step7 = text[text.index("7. Report the touch-set"):text.index("## Exit codes")]
        self.assertEqual(step7.count("every doc `discover` lists under `docs_to_update` — the "
                                     "role docs too, not only `MODULE.md`"), 1)
        self.assertIn("| module | usage | why | docs to read | docs to update | code (file:line) |",
                      step7)


class SandboxLineTest(unittest.TestCase):  # P84-AC-015
    TASK = 'refund a "late" book: $HOME and `whoami` stay text'

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = copy_fixture(self._tmp.name, SPLIT_FIXTURE)
        init_git(self.root)

    def test_one_line_with_a_quoted_heredoc(self):
        for name in WRAPPED:
            with self.subTest(skill=name):
                text = procedure(name)
                self.assertEqual(text.count("--task-file -"), 1)
                self.assertEqual(text.count("<<'EOF'"), 1)
                self.assertEqual(text.count("If a temporary file cannot be written"), 1)
                self.assertIn("read the order from stdout", flat(text))
                self.assertIn("modsys choose --task-file - <<'EOF'\n   <the task text, verbatim>\n"
                              "   EOF\n", text)

    def test_the_shell_hands_choose_the_text_byte_exact(self):
        for name in WRAPPED:
            with self.subTest(skill=name):
                block = re.search(r"```bash\n(   modsys choose --task-file - <<'EOF'\n.*?   EOF)\n",
                                  procedure(name), re.S).group(1)
                script = "\n".join(line.removeprefix("   ") for line in block.splitlines())
                script = script.replace("<the task text, verbatim>", self.TASK)
                script = script.replace("modsys choose --task-file -", (
                    f"'{sys.executable}' -m modsys choose --task-file - --root '{self.root}'"), 1)
                env = {**os.environ, "PYTHONPATH": str(ENGINE)}
                proc = subprocess.run(["sh", "-c", script], capture_output=True, text=True,
                                      env=env, timeout=120)
                self.assertEqual((proc.returncode, proc.stderr), (0, ""))
                self.assertTrue(proc.stdout.startswith(f"Task:\n{self.TASK}\n"), proc.stdout[:200])

    def test_choose_reads_stdin_in_process(self):
        with mock.patch("sys.stdin", io.StringIO(self.TASK)):
            code, out, err = run("choose", "--task-file", "-", "--root", str(self.root))
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(out.startswith(f"Task:\n{self.TASK}\n"))


class InvocationDocsTest(unittest.TestCase):  # fix wave I-1: how the task reaches the skill
    def test_docs_skills_says_how_the_task_is_passed(self):
        text = flat((ENGINE / "docs/skills.md").read_text(encoding="utf-8"))
        part = text.split("`module-discover`, `module-scout` and `module-research` hand", 1)[1]
        part = part.split(" ## ", 1)[0]
        for needle in ("`/module-discover <task>`", "an `ARGUMENTS:` line",
                       "no `arguments:` key and no placeholder"):
            self.assertEqual(part.count(needle), 1, needle)

    def test_the_changelog_drops_the_old_form(self):
        log = (ENGINE / "CHANGELOG.md").read_text(encoding="utf-8")
        unreleased = flat(log.split("## [Unreleased]", 1)[1].split("\n## [", 1)[0])
        for gone in ("`$task`", "`arguments: task`"):
            self.assertNotIn(gone, unreleased)
        self.assertIn("`argument-hint: \"[task]\"`", unreleased)
        self.assertIn("ends with the skill's Scope and Gates", unreleased)


# P85-AC-018, SI-P85-8 (final review M-8): what docs/skills.md says of the Codex hand-off, and
# Task 3's changelog entry (final review M-6: in `### Changed`, beside the thin-skills entry)
CODEX_DOCS = ("spawn the `module-<x>-agent` custom agent", "only when no such agent exists",
              "Known limit", "a bare \"task confirmed\" may make it implement the task",
              "ask for the touch-set to get the hand-off")
T3_ENTRY = "Codex spawns the `module-<x>-agent` custom agent (`.codex/agents/`)"
THIN_ENTRY = "`module-discover`, `module-scout` and `module-research` are thin:"


def handoff_doc_problems(doc: str) -> list[str]:
    """Each `CODEX_DOCS` phrase that the "**The skills' agents.**" paragraph of docs/skills.md
    does not hold exactly once, or that the doc holds elsewhere too."""
    paras = [p for p in doc.split("\n\n") if p.startswith("**The skills' agents.**")]
    if len(paras) != 1:
        return [f"{len(paras)} agents paragraphs"]
    para, whole = flat(paras[0]), flat(doc)
    return [n for n in CODEX_DOCS if para.count(n) != 1 or whole.count(n) != 1]


def unreleased_sections(log: str) -> dict[str, str]:
    """The `### ` sections of `[Unreleased]`, heading -> body."""
    text = log.split("## [Unreleased]", 1)[1].split("\n## [", 1)[0]
    parts = re.split(r"^### (.+)\n", text, flags=re.M)
    return dict(zip(parts[1::2], parts[2::2]))


def entries(body: str) -> list[str]:
    """The flat entries of one changelog section."""
    return [flat(e) for e in re.split(r"^- ", body, flags=re.M)[1:]]


def changelog_problems(log: str) -> list[str]:
    """A blank line inside a section's list of `[Unreleased]`; Task 3's entry not there exactly
    once, or not in `### Changed` right after the thin-skills entry."""
    sections = unreleased_sections(log)
    out = [f"### {head}: a blank line splits the list" for head, body in sections.items()
           if "\n\n" in body.strip()]
    found = [(head, i) for head, body in sections.items()
             for i, entry in enumerate(entries(body)) if T3_ENTRY in entry]
    if len(found) != 1:
        return out + [f"Task 3's entry {len(found)} times"]
    thin = [i for i, entry in enumerate(entries(sections.get("Changed", "")))
            if entry.startswith(THIN_ENTRY)]
    if found[0][0] != "Changed" or thin != [found[0][1] - 1]:
        out.append(f"Task 3's entry in ### {found[0][0]}, not after the thin-skills entry")
    return out


class HandOffDocsTest(unittest.TestCase):  # P85-AC-018, SI-P85-8; final review M-6, M-8
    def test_docs_skills_says_the_hand_off_and_the_limit_once(self):
        doc = (ENGINE / "docs/skills.md").read_text(encoding="utf-8")
        self.assertEqual(handoff_doc_problems(doc), [])

    def test_the_changelog_entry_sits_with_the_thin_skills_entry(self):
        log = (ENGINE / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertEqual(changelog_problems(log), [])
        entry = next(e for e in entries(unreleased_sections(log)["Changed"]) if T3_ENTRY in e)
        self.assertIn("`references/procedure.md` is read only when no such agent exists", entry)

    def test_the_checks_can_fail(self):
        doc = (ENGINE / "docs/skills.md").read_text(encoding="utf-8")
        self.assertEqual(handoff_doc_problems(re.sub(r"Known\s+limit: ", "", doc, count=1)),
                         ["Known limit"])
        self.assertEqual(handoff_doc_problems(doc + "\nKnown limit.\n"), ["Known limit"])
        log = (ENGINE / "CHANGELOG.md").read_text(encoding="utf-8")
        entry = log.index("\n- The wrapped skills `module-discover`, `module-scout`")
        end = log.index("\n- ", entry + 1)
        moved = log[:entry] + log[end:]  # Task 3's entry back at the head of `### Added`
        moved = moved.replace("\n### Added\n\n", "\n### Added\n" + log[entry:end] + "\n", 1)
        self.assertEqual(changelog_problems(moved),
                         ["Task 3's entry in ### Added, not after the thin-skills entry"])
        fixed = log.index("\n### Fixed\n")
        split = log[:fixed] + log[fixed:].replace("\n- ", "\n\n- ", 2)
        self.assertEqual(changelog_problems(split), ["### Fixed: a blank line splits the list"])


class FallbackRunsTest(unittest.TestCase):  # P84-AC-016 (discover: `test_p81_skill_text`)
    TASK = "refund a returned book"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = copy_fixture(self._tmp.name, SPLIT_FIXTURE)
        init_git(self.root)
        self.task = Path(self._tmp.name) / "task.txt"
        self.task.write_text(self.TASK, encoding="utf-8")

    def cli(self, args, stdin=""):
        with mock.patch("sys.stdin", io.StringIO(stdin)):
            code, out, err = run(*args, "--root", str(self.root))
        self.assertEqual((code, err), (0, ""), args)
        return out

    def commands_of(self, name):
        return [argv(c) for c in commands(sections(procedure(name), "Steps"))]

    def test_scout_and_research_commands_exit_zero(self):
        expected = {"module-scout": ["show", "related"],
                    "module-research": ["show", "related", "code-map", "lint"]}
        for name, verbs in expected.items():
            with self.subTest(skill=name):
                seen = []
                for args in self.commands_of(name):
                    if args[0] == "choose" and "--task-file" in args and args[2] == "X":
                        self.cli(["choose", "--task-file", str(self.task)])
                    elif args[0] in verbs:
                        concrete = [
                            "developer" if i and args[i - 1] == "--role" else
                            "orders/refunds" if arg == "X/X" else "orders" if arg == "X" else arg
                            for i, arg in enumerate(args)]
                        if concrete[0] == "code-map":
                            concrete = ["code-map", "files", "orders", "--json"]
                        code, out, err = run(*concrete, "--root", str(self.root))
                        self.assertEqual(code, 0, (concrete, err))
                        self.assertEqual(err, "", concrete)
                        seen.append(args[0])
                self.assertEqual([v for v in verbs if v not in seen], [])


class ReferencesTravelTest(unittest.TestCase):  # P84-AC-030 (the wrapped skills' part)
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = copy_fixture(self._tmp.name)
        (self.root / ".modsys/config.toml").write_text('[packs]\nbuiltin = ["core"]\n',
                                                       encoding="utf-8")
        self.R = ("--root", str(self.root))

    def test_sync_copies_the_procedure_with_its_hash_in_the_marker(self):
        code, env, err = run_json("packs", "sync", "--agent", "claude", "--agent", "codex", *self.R)
        self.assertEqual((code, err), (0, ""))
        for name in WRAPPED:
            for agent_dir in (".claude/skills", ".agents/skills"):
                with self.subTest(skill=name, where=agent_dir):
                    dest = self.root / agent_dir / name
                    copy = dest / "references/procedure.md"
                    self.assertEqual(copy.read_bytes(), (CORE / name / "references/procedure.md")
                                     .read_bytes())
                    marker = json.loads((dest / ".modsys-managed").read_text(encoding="utf-8"))
                    self.assertEqual(marker["files"]["references/procedure.md"],
                                     hashlib.sha256(copy.read_bytes()).hexdigest())
                    self.assertEqual((dest / "SKILL.md").read_bytes(),
                                     (CORE / name / "SKILL.md").read_bytes())  # keys kept
                    self.assertIn(f"Codex: spawn the\n   `{name}-agent` custom agent",
                                  (dest / "SKILL.md").read_text(encoding="utf-8"))  # P85-AC-017
        self.assertEqual(run("packs", "sync", "--check", "--agent", "claude", "--agent", "codex",
                             *self.R)[0], 0)

    def test_the_codex_agents_carry_the_scope_and_the_gates(self):  # fix wave I-2
        code, env, err = run_json("packs", "sync", "--agent", "codex", *self.R)
        self.assertEqual((code, err), (0, ""))
        for name in WRAPPED:
            with self.subTest(skill=name):
                agent = self.root / ".codex/agents" / f"{name}-agent.toml"
                body = tomllib.loads(agent.read_text(encoding="utf-8"))["developer_instructions"]
                self.assertEqual(body, procedure(name))
                for heading in ("Scope", "Gates"):
                    self.assertIn(raw_section(skill(name), heading), body)

    def test_an_edited_procedure_in_a_copy_is_a_conflict(self):
        run_json("packs", "sync", "--agent", "claude", *self.R)
        copy = self.root / ".claude/skills/module-scout/references/procedure.md"
        copy.write_text(copy.read_text(encoding="utf-8") + "\nlocal edit\n", encoding="utf-8")
        code, env, _ = run_json("packs", "sync", "--agent", "claude", *self.R)
        self.assertEqual(code, 1)
        self.assertEqual([r["status"] for r in env["data"]["skills"]
                          if r["skill"] == "module-scout"], ["conflict"])

    def test_eject_carries_the_procedure(self):
        code, _, err = run_json("eject", "module-research", *self.R)
        self.assertEqual((code, err), (0, ""))
        copy = self.root / ".modsys/overrides/skills/module-research/references/procedure.md"
        self.assertEqual(copy.read_bytes(),
                         (CORE / "module-research/references/procedure.md").read_bytes())


if __name__ == "__main__":
    unittest.main()
