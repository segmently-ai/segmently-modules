"""P8.5 task 1 (D1, F30): the `module-discover` procedure — the body of `module-discover-agent` on
both platforms — keeps the modules step 2 verified (its kept picks) in the report even when step
4's `discover --files` gives their files to another module or to none, and its code column holds
the files the change edits or adds; files read only as evidence go on one "read for evidence"
line under the table. Three paragraphs are added and nothing else moves: every sentence of the
procedure at bdc9f9b stays in order, steps 1–4, the exit codes, Scope and Gates keep their bytes,
the rest of the skill and the other two procedures are untouched, and the plugin build and
`packs sync` carry the new bytes (P85-AC-001…007; the P8.4 pattern of `test_p84_wrapped_skills`)."""
import hashlib
import json
import re
import shutil
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from modsys import skills
from modsys.config import builtin_packs_root, core_defaults
from modsys.skills import read_front_matter
from tests.helpers import SPLIT_FIXTURE, copy_fixture, git, init_git, run, run_json
from tests.plugin_helpers import copy_engine, run_tool, tree
from tests.test_budgets import crossings
from tests.test_builtin_skills import argv, command_guard, commands, skill_files
from tests.test_p81_skill_text import command, filled, flat
from tests.test_p84_codex_agents import marker, snap
from tests.test_p84_wrapped_skills import raw_section, sandbox_free, sections, sentences

ENGINE = Path(__file__).resolve().parents[1]
CORE = builtin_packs_root() / "core" / "skills"
PROCEDURE = CORE / "module-discover" / "references" / "procedure.md"
REL = "modsys/defaults/packs/core/skills/module-discover/references/procedure.md"
SPLIT_SIGNAL = core_defaults()["budgets"]["skill_split_signal"]  # MS068's default (D5)

# The procedure at bdc9f9b: sha256[:16] and length; the sha256[:12] of each sentence of its
# `## Steps` and `## Exit codes` (the read-only-sandbox paragraph set aside, as P8.4 counts them);
# the bytes from step 1 up to step 5 and the three closing sections, sha256[:16].
BASE_SHA, BASE_LEN = "8dabcc3bef361263", 5536
BASE_SENTENCES = [
    "ac8ea9fe45a0", "1eb50f63c3c7", "b63bd2f1f2a9", "30a3e7776a59", "ceb4ed4d46b2", "00294cf671d2",
    "d03d5928927a", "fd2664d5c59e", "8c2e4001a6ec", "8fda918e1466", "44290e0e6418", "462a78b17bca",
    "272101108c66", "abc19fb107a5", "d3509a6322e9", "07d98d9c3ecd", "375379d657d3", "75c77cdf7fd3",
    "30099762807c", "9e1fb88ba206", "5ffc51bcee5f", "a4fce89999e4", "a21bf04fef4b", "4e7dd66e10e0",
    "583d7c775cc8", "fe6aece06d34", "b2de0814a445", "35019085bf7f", "3cba72a91ab7", "5e68685e2ae3",
    "6bbdfaccd074"]
REPLACED = 0  # D1 adds; no sentence of bdc9f9b is replaced (SI-P85-1)
STEPS_1_TO_4 = "1ca42456f91f6526"
CLOSING = {"Exit codes": "563ed072ebec701a", "Scope": "b5d02fbb705d432b",
           "Gates": "5472d61f2d94d059"}

# What Task 1 adds, byte for byte: one paragraph at the end of steps 5, 6 and 7 each (fix round 1:
# a kept pick's code column follows step 7's rule; its docs are read; the evidence line's place).
KEPT_PICK = (
    "   A module step 2 kept is a verified pick: it stays in the report even when step 4's `discover`\n"
    "   gives its files to another module or to none. Its `usage` in the report is set by the task,\n"
    "   not by `discover`'s `usage`. It is `modify` when the task changes its behaviour, with a note in\n"
    "   its why: \"code in `<owner>`\" (the module `discover` gives its files to) or\n"
    "   \"outside every module\". Its code column holds the files from step 3 that the change edits or\n"
    "   adds, even when the same file also stands in `<owner>`'s row; files read only as evidence go\n"
    "   on step 7's evidence line. When the change edits no file for it, its code cell says \"none\",\n"
    "   never empty. When the task only reads it, it stays a `reference` with its why. Drop a kept\n"
    "   pick only with a stated reason, listed with the dropped modules; never drop one silently. A\n"
    "   run that starts at step 4 has no kept picks.")
NOT_KEPT = (
    "   This keep-or-drop is only for the `reference` modules step 2 did not keep; a kept pick stays\n"
    "   as step 5 says. Read a kept pick's docs too: when the result gives it no `docs_to_read`, read\n"
    "   the `read` paths of `modsys show <pick> --json`.")
CODE_COLUMN = (
    "   The code column holds the files the change edits or adds: the line that computes or sets the\n"
    "   value, the files to edit, the tests to add or change. Files read only as evidence go on one\n"
    "   line right under the table, ahead of the lists that follow it; start that line with\n"
    "   \"read for evidence:\". They never go in the code column.")
ADDED = {"5. Read the result.": KEPT_PICK, "6. Read the `modify`": NOT_KEPT,
         "7. Report the touch-set": CODE_COLUMN}

# Nothing else of the skill moves (P85-AC-004): sha256[:16] at bdc9f9b. Task 3 (D3) rewrites the
# hand-off step of the three SKILL.md files after this task: it moves the first pin, nothing else.
UNMOVED = {"module-discover/SKILL.md": "9652fa87f06c7e38",
           "module-scout/references/procedure.md": "a0739ad4036f896a",
           "module-research/references/procedure.md": "aeaece498d1517ec",
           "module-sync/SKILL.md": "e95d0484c87ccf99"}
DESCRIPTION = "fa2b6d6ba50b01fd"  # module-discover's `description:` (InstallLineTest.DESCRIPTIONS)
AGENT_TABLE = "aeea977be2cdde38"  # json.dumps(skills.SKILL_AGENTS, sort_keys=True)
HEADER = ("---\nname: module-discover-agent\ndescription: Maps a confirmed task, a branch or "
          "changed files to the modules, docs and code files they touch through the modsys CLI, "
          "read-only, and reports the touch-set with file:line evidence.\ntools: Read, Grep, Glob, "
          "Bash, Agent\nmodel: sonnet\n---\n\n")  # a bdc9f9b build's front matter, blank line
CODEX_BASE = "a07e28e4822bc043"  # the bdc9f9b Codex agent file's marker sha256 (bytes after line 1)


def sha16(data: str | bytes) -> str:
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()[:16]


def h12(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def procedure() -> str:
    return PROCEDURE.read_bytes().decode("utf-8")


def base_procedure(text: str) -> str:
    """The procedure without the three added paragraphs (each with its own line break)."""
    for paragraph in ADDED.values():
        assert text.count("\n" + paragraph + "\n") == 1, paragraph[:60]
        text = text.replace("\n" + paragraph + "\n", "", 1)
    return text


def span(text: str, start: str, end: str) -> str:
    """The flat text from `start` up to `end` (excluded)."""
    text = flat(text)
    return text[text.index(start):text.index(end, text.index(start))]


def all_sentences(text: str) -> list[str]:
    text = sandbox_free(text)
    return sentences(sections(text, "Steps")) + sentences(sections(text, "Exit codes"))


class KeptPickTest(unittest.TestCase):  # P85-AC-001, P85-AC-006 (the text half)
    def setUp(self):
        self.text = procedure()
        self.steps = span(self.text, "5. Read the result.", "## Exit codes")
        self.line = flat(KEPT_PICK)

    def test_the_kept_pick_line_sits_in_step_5(self):
        step5 = span(self.text, "5. Read the result.", "6. Read the `modify`")
        self.assertEqual(step5.count(self.line), 1)
        self.assertTrue(step5.endswith(self.line + " "), step5[-200:])

    def test_the_decision_table_once_each(self):
        rows = {  # P85-AC-001's rows, each a phrase the span holds exactly once
            "a verified pick": "A module step 2 kept is a verified pick",
            "kept, whatever discover says": "it stays in the report even when step 4's "
                                            "`discover` gives its files to another module or to "
                                            "none",
            "usage set by the task (SI-P85-1)": "Its `usage` in the report is set by the task, "
                                                "not by `discover`'s `usage`.",
            "rows 1-3: modify": "It is `modify` when the task changes its behaviour",
            "the note, in its why": "with a note in its why:",
            "row 2: another module": "\"code in `<owner>`\" (the module `discover` gives its files "
                                     "to)",
            "row 3: no module": "or \"outside every module\".",
            "its code: step 7's rule (I-1)": "Its code column holds the files from step 3 that the "
                                             "change edits or adds, even when the same file also "
                                             "stands in `<owner>`'s row;",
            "its evidence (I-1)": "files read only as evidence go on step 7's evidence line.",
            "no file to edit (I-1)": "When the change edits no file for it, its code cell says "
                                     "\"none\", never empty.",
            "row 4: read only": "When the task only reads it, it stays a `reference` with its why.",
            "row 5: dropped": "Drop a kept pick only with a stated reason, listed with the "
                              "dropped modules; never drop one silently.",
            "row 6: --from-diff": "A run that starts at step 4 has no kept picks.",
            "row 6: step 6 (SI-P85-1)": "This keep-or-drop is only for the `reference` modules "
                                        "step 2 did not keep; a kept pick stays as step 5 says.",
            "its docs (review M-1)": "Read a kept pick's docs too: when the result gives it no "
                                     "`docs_to_read`, read the `read` paths of `modsys show <pick> "
                                     "--json`.",
        }
        for row, phrase in rows.items():
            with self.subTest(row=row):
                self.assertEqual(self.steps.count(phrase), 1, phrase)

    def test_the_pinned_words(self):
        for phrase in ("code in `<owner>`", "when the task changes its behaviour",
                       "a stated reason", "another module"):
            with self.subTest(phrase=phrase):
                self.assertEqual(self.steps.count(phrase), 1)
                self.assertIn(phrase, self.line)
        # once in the kept-pick line, once in step 7's "the files outside every module"
        self.assertEqual(self.line.count("outside every module"), 1)
        self.assertEqual(self.steps.count("outside every module"), 2)
        self.assertEqual(self.steps.count("the files outside every module"), 1)
        # both t0 cases (P85-AC-006): the files went to another module, or to none
        self.assertIn("to another module or to none", self.line)

    def test_no_other_drop_and_the_note_in_its_why(self):  # review M-3
        drops = [s for s in sentences(span(self.text, "5. Read the result.",
                                           "7. Report the touch-set")) if "drop" in s.lower()]
        self.assertEqual(drops, [
            "Drop a kept pick only with a stated reason, listed with the dropped modules; never "
            "drop one silently.",
            "6. Read the `modify` modules' `docs_to_read` for the rules the task must respect; "
            "keep a `reference` module only when its main doc helps (a component to reuse, a "
            "rule), drop the rest and say why.",  # bdc9f9b's, scoped by the next one
            "This keep-or-drop is only for the `reference` modules step 2 did not keep; a kept "
            "pick stays as step 5 says."])
        self.assertEqual(self.steps.count("in its why"), 1)
        self.assertEqual(self.line.count("in its why"), 1)

    def test_step_6_keeps_its_rule_for_the_others(self):
        step6 = span(self.text, "6. Read the `modify`", "7. Report the touch-set")
        self.assertIn("keep a `reference` module only when its main doc helps (a component to "
                      "reuse, a rule), drop the rest and say why.", step6)
        self.assertTrue(step6.endswith(flat(NOT_KEPT) + " "), step6)
        self.assertIn("the `reference` modules step 2 did not keep", step6)

    def test_self_contained_and_no_placeholder(self):
        for token in ("SKILL.md", "references/", "procedure.md"):
            self.assertNotIn(token, self.text)
        self.assertEqual(re.findall(r"\$[A-Za-z0-9{_]", self.text), [])

    def test_the_text_can_fail(self):  # the bdc9f9b procedure holds none of it
        old = base_procedure(self.text)
        old_steps = span(old, "5. Read the result.", "## Exit codes")
        for phrase in ("code in `<owner>`", "when the task changes its behaviour",
                       "a stated reason", "read for evidence", "step 2 did not keep"):
            self.assertNotIn(phrase, old_steps)
        self.assertEqual(old_steps.count("outside every module"), 1)


class CodeColumnTest(unittest.TestCase):  # P85-AC-002
    def setUp(self):
        self.text = procedure()
        self.step7 = span(self.text, "7. Report the touch-set", "## Exit codes")

    def test_the_files_to_change(self):
        for phrase in ("The code column holds the files the change edits or adds:",
                       "the line that computes or sets the value", "the files to edit",
                       "the tests to add or change"):
            with self.subTest(phrase=phrase):
                self.assertEqual(self.step7.count(phrase), 1)
                self.assertEqual(flat(self.text).count(phrase), 1)

    def test_one_evidence_line_under_the_table(self):
        self.assertEqual(self.text.count("read for evidence"), 1)
        self.assertEqual(self.step7.count("Files read only as evidence go on one line right under "
                                          "the table, ahead of the lists that follow it; start "
                                          "that line with \"read for evidence:\". They never go "
                                          "in the code column."), 1)
        self.assertLess(self.step7.index("|---|"), self.step7.index("read for evidence"))
        # review M-2: before the lists that follow the table, which the old step 7 names
        self.assertIn("|---|---|---|---|---|---| then the files outside every module", self.step7)

    def test_the_kept_pick_follows_the_same_rule(self):  # fix round 1, I-1
        text = procedure()  # the shipped paragraphs, not this module's copies of them
        kept = span(text, "A module step 2 kept", "6. Read the `modify`")
        column = span(text, "The code column holds", "## Exit codes")
        for part in (kept, column):  # edits or adds -> code column; read only -> evidence line
            with self.subTest(part=part[:40]):
                self.assertEqual(part.count("the change edits or adds"), 1)
                self.assertEqual(part.count("read only as evidence go on"), 1)
        self.assertIn("files read only as evidence go on step 7's evidence line", kept)
        self.assertIn("Files read only as evidence go on one line right under the table", column)
        self.assertNotIn("found for it and", kept)  # the round-1 wording that disagreed
        self.assertNotIn("read for evidence", kept)  # the phrase lives once, in step 7

    def test_the_old_step_7_stays(self):
        self.assertEqual(self.text.count(
            "\n   | module | usage | why | docs to read | docs to update | code (file:line) |\n"
            "   |---|---|---|---|---|---|\n"), 1)
        for phrase in ("every `modify` row with its code at file:line",
                       "every doc `discover` lists under `docs_to_update` — the role docs too, "
                       "not only `MODULE.md`"):
            with self.subTest(phrase=phrase):
                self.assertEqual(flat(self.text).count(phrase), 1)
                self.assertEqual(self.step7.count(phrase), 1)
        self.assertTrue(self.step7.endswith(flat(CODE_COLUMN) + " "), self.step7[-200:])


class EveryOldRuleTest(unittest.TestCase):  # P85-AC-003
    def setUp(self):
        self.text = procedure()

    def test_only_the_three_paragraphs_were_added(self):
        old = base_procedure(self.text)
        self.assertEqual((sha16(old), len(old)), (BASE_SHA, BASE_LEN))

    def test_every_old_sentence_is_there_in_order(self):
        new = [h12(s) for s in all_sentences(self.text)]
        at, missing = 0, []
        for digest in BASE_SENTENCES:
            if digest in new[at:]:
                at += new[at:].index(digest) + 1
            else:
                missing.append(digest)
        self.assertEqual(len(missing), REPLACED, missing)

    def test_the_added_sentences_are_listed(self):
        added = [s for s in all_sentences(self.text) if h12(s) not in BASE_SENTENCES]
        listed = [s for p in ADDED.values() for s in sentences(p)]
        self.assertEqual(added, listed)
        self.assertEqual(len(added), 13)
        for start, paragraph in ADDED.items():  # each in its own step
            with self.subTest(step=start):
                self.assertTrue(span(self.text, start, "## Exit codes").startswith(start))
                self.assertIn(flat(paragraph), span(self.text, start, "## Exit codes"))

    def test_steps_1_to_4_and_the_closing_sections_keep_their_bytes(self):
        a, b = self.text.index("1. Choose the candidate modules."), self.text.index(
            "5. Read the result.")
        self.assertEqual(sha16(self.text[a:b]), STEPS_1_TO_4)
        for heading, digest in CLOSING.items():
            with self.subTest(section=heading):
                self.assertEqual(sha16(raw_section(self.text, heading)), digest)
        own = (CORE / "module-discover" / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(self.text.endswith(raw_section(own, "Scope") + raw_section(own, "Gates")))
        self.assertEqual(re.findall(r"^## .*$", self.text, re.M),
                         ["## Steps", "## Exit codes", "## Scope", "## Gates"])

    def test_limits_and_commands(self):
        self.assertLessEqual(len(self.text.splitlines()), 250)
        self.assertLessEqual(len(self.text), SPLIT_SIGNAL)
        self.assertEqual([k for k in crossings() if "module-discover" in k], [])  # MS068 silent
        self.assertEqual(command_guard(skill_files(CORE / "module-discover")), [])
        cmds = [argv(c) for c in commands(self.text)]
        self.assertTrue(cmds)
        for a in cmds:
            self.assertNotIn("--task", a)
            if a[:1] in (["discover"], ["context"]) and "--task-file" in a:
                self.assertEqual(a[a.index("--match") + 1], "lexical", a)
        self.assertEqual(flat(self.text).count("`modsys:module-chooser`"), 1)


class NothingElseMovesTest(unittest.TestCase):  # P85-AC-004
    def test_the_other_files_keep_their_bytes(self):
        for rel, digest in UNMOVED.items():
            with self.subTest(file=rel):
                self.assertEqual(sha16((CORE / rel).read_bytes()), digest)

    def test_the_description_and_the_agent_table(self):
        description = read_front_matter(CORE / "module-discover" / "SKILL.md")["description"]
        self.assertEqual(sha16(description), DESCRIPTION)
        self.assertEqual(sha16(json.dumps(skills.SKILL_AGENTS, sort_keys=True)), AGENT_TABLE)
        self.assertEqual(sorted(skills.SKILL_AGENTS), ["module-discover-agent",
                                                       "module-research-agent",
                                                       "module-scout-agent"])


class PluginBuildTest(unittest.TestCase):  # P85-AC-005, the plugin half
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        base = Path(cls._tmp.name).resolve()
        engine = copy_engine(base / "engine")
        proc = run_tool(engine, "build_plugins", "--out", str(base / "new"))
        assert (proc.returncode, proc.stderr) == (0, ""), proc.stderr
        (engine / REL).write_bytes(base_procedure(procedure()).encode("utf-8"))  # bdc9f9b's
        git(engine, "commit", "-q", "-am", "the procedure at bdc9f9b")
        proc = run_tool(engine, "build_plugins", "--out", str(base / "old"))
        assert (proc.returncode, proc.stderr) == (0, ""), proc.stderr
        cls.new, cls.old = tree(base / "new"), tree(base / "old")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def built(self, which: dict, rel: str) -> bytes:
        return which[rel][1]

    def test_only_the_discover_files_differ(self):
        self.assertEqual(sorted(self.new), sorted(self.old))
        self.assertEqual(sorted(k for k in self.new if self.new[k] != self.old[k]), [
            "modsys/agents/module-discover-agent.md", f"modsys/runtime/{REL}",
            "modsys/skills/module-discover/references/procedure.md"])
        for name in ("module-scout-agent", "module-research-agent", "module-chooser"):
            rel = f"modsys/agents/{name}.md"
            self.assertEqual(self.built(self.new, rel), self.built(self.old, rel), name)

    def test_the_agent_is_the_old_header_then_the_new_procedure(self):
        data = PROCEDURE.read_bytes()
        agent = self.built(self.new, "modsys/agents/module-discover-agent.md")
        self.assertEqual(agent, HEADER.encode("utf-8") + data)
        self.assertEqual(self.built(self.old, "modsys/agents/module-discover-agent.md"),
                         HEADER.encode("utf-8") + base_procedure(procedure()).encode("utf-8"))
        for rel in ("modsys/skills/module-discover/references/procedure.md",
                    f"modsys/runtime/{REL}"):
            self.assertEqual(self.built(self.new, rel), data, rel)


class SyncTest(unittest.TestCase):  # P85-AC-005, the sync half; P85-AC-027 on its rows
    AGENTS = ("--agent", "claude", "--agent", "codex")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name).resolve()
        self.root = copy_fixture(tmp)
        (self.root / ".modsys/config.toml").write_text('[packs]\nbuiltin = ["core"]\n',
                                                       encoding="utf-8")
        self.R = ("--root", str(self.root))
        old_packs = tmp / "packs"  # the built-in packs as at bdc9f9b
        shutil.copytree(builtin_packs_root(), old_packs)
        (old_packs / "core/skills/module-discover/references/procedure.md").write_bytes(
            base_procedure(procedure()).encode("utf-8"))
        with mock.patch("modsys.config.builtin_packs_root", return_value=old_packs):
            code, env, err = run_json("packs", "sync", *self.AGENTS, *self.R)
        self.assertEqual((code, err), (0, ""))
        agent = (self.root / ".codex/agents/module-discover-agent.toml").read_bytes()
        self.assertEqual(marker(agent)[0]["sha256"][:16], CODEX_BASE)  # synced as at bdc9f9b

    def sync(self, *argv: str, code: int = 0) -> dict:
        got, env, err = run_json("packs", "sync", *self.AGENTS, *argv, *self.R)
        self.assertEqual((got, err), (code, ""), env)
        self.assertEqual(set(env), {"schema", "data"})
        self.assertEqual(env["schema"], "modsys.packs/1")
        return env["data"]

    def test_check_names_the_discover_copies_and_its_agent(self):
        before = snap(self.root)
        data = self.sync("--check", code=1)
        self.assertEqual(snap(self.root), before)  # --check writes nothing
        stale = sorted((r["agent"], r["skill"]) for r in data["skills"]
                       if r["status"] != "unchanged")
        self.assertEqual(stale, [("claude", "module-discover"), ("codex", "module-discover")])
        self.assertEqual({r["status"] for r in data["skills"] if r["skill"] == "module-discover"},
                         {"updated"})
        self.assertEqual([(r["name"], r["status"]) for r in data["agent_files"]], [
            ("module-discover-agent", "updated"), ("module-research-agent", "unchanged"),
            ("module-scout-agent", "unchanged")])
        code, out, err = run("packs", "sync", *self.AGENTS, "--check", *self.R)
        self.assertEqual((code, err), (1, ""))
        self.assertNotIn("Traceback", out)
        self.assertEqual(snap(self.root), before)

    def test_sync_writes_the_new_bytes_then_check_is_clean(self):
        self.sync()
        data = self.sync("--check")
        self.assertEqual({r["status"] for r in data["skills"]}, {"unchanged"})
        self.assertEqual({r["status"] for r in data["agent_files"]}, {"unchanged"})
        raw = (self.root / ".codex/agents/module-discover-agent.toml").read_bytes()
        head, rest = marker(raw)
        self.assertEqual(head["sha256"], hashlib.sha256(rest).hexdigest())
        self.assertEqual(tomllib.loads(raw.decode("utf-8"))["developer_instructions"], procedure())
        for where in (".claude/skills", ".agents/skills"):
            with self.subTest(where=where):
                dest = self.root / where / "module-discover"
                copy = (dest / "references/procedure.md").read_bytes()
                self.assertEqual(copy, PROCEDURE.read_bytes())
                managed = json.loads((dest / ".modsys-managed").read_text(encoding="utf-8"))
                self.assertEqual(managed["files"]["references/procedure.md"],
                                 hashlib.sha256(copy).hexdigest())


class TZeroShapeTest(unittest.TestCase):  # P85-AC-006: the procedure's commands on the t0 shape
    QUERIES = "partial refund\nrefund amount\n"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = copy_fixture(self._tmp.name, SPLIT_FIXTURE)
        init_git(self.root)
        self.file = Path(self._tmp.name) / "queries.txt"  # the keyword half's `<file>`
        self.file.write_text(self.QUERIES, encoding="utf-8")

    def cli(self, args: list[str]) -> dict:
        code, out, err = run(*args, "--root", str(self.root))
        self.assertEqual((code, err), (0, ""), args)
        return json.loads(out)["data"]

    def discover(self, files: str, task: bool) -> dict:
        args, _ = filled(command("module-discover", "modsys discover --files"),
                         {"<found files>": files, "<file>": str(self.file)})
        if not task:  # "without a task, drop `--task-file`"
            at = args.index("--task-file")
            args = args[:at] + args[at + 2:]
        return self.cli(args)

    def rows(self, data: dict) -> list[tuple]:
        return [(m["module"], m["usage"], m["sources"], m["touched_files"])
                for m in data["modules"]]

    def test_a_docs_only_child_whose_code_lives_in_another_module(self):
        args, _ = filled(command("module-discover", "modsys code-map files"),
                         {"<candidate>": "orders/refunds"})
        mapped = self.cli(args)["files"]
        self.assertEqual(mapped, [{"path": "modules/orders/submodules/refunds/MODULE.md",
                                   "via": ["docs"]}])  # no code of its own
        found = self.discover("src/payments/gateway.py", task=True)
        self.assertEqual(self.rows(found), [
            ("orders/refunds", "reference", ["keyword"], []),
            ("payments", "modify", ["diff"], ["src/payments/gateway.py"])])
        found = self.discover("src/payments/gateway.py", task=False)
        self.assertEqual(self.rows(found), [
            ("payments", "modify", ["diff"], ["src/payments/gateway.py"])])  # the child: absent

    def test_its_code_outside_every_module(self):
        (self.root / "tools").mkdir()
        (self.root / "tools/refund_report.py").write_text("# refund amount\n", encoding="utf-8")
        found = self.discover("tools/refund_report.py", task=True)
        self.assertEqual(self.rows(found), [("orders/refunds", "reference", ["keyword"], [])])
        self.assertEqual(found["files_outside_modules"], ["tools/refund_report.py"])
        found = self.discover("tools/refund_report.py", task=False)
        self.assertEqual((found["modules"], found["files_outside_modules"]),
                         ([], ["tools/refund_report.py"]))


class DocsTest(unittest.TestCase):  # P85-AC-007
    def test_the_skills_table_row(self):
        doc = (ENGINE / "docs/skills.md").read_text(encoding="utf-8")
        row = [line for line in doc.splitlines() if line.startswith("| `module-discover` |")]
        self.assertEqual(len(row), 1)
        self.assertIn("the code files to change", row[0])
        self.assertIn("a kept pick stays even when its code lives in another module", row[0])
        self.assertNotIn("update, code files |", row[0])

    def test_one_changelog_entry(self):
        log = (ENGINE / "CHANGELOG.md").read_text(encoding="utf-8")
        unreleased = log.split("## [Unreleased]", 1)[1].split("\n## [", 1)[0]
        entries = [flat(e) for e in re.split(r"\n- ", unreleased) if "read for evidence" in e]
        self.assertEqual(len(entries), 1)
        for phrase in ("`module-discover`", "kept pick", "files to change", "read for evidence",
                       "code in `<owner>`", "outside every module", "Every sentence"):
            self.assertIn(phrase, entries[0])


if __name__ == "__main__":
    unittest.main()
