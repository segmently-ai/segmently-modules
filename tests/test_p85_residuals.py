"""P8.5 Task 4, the P8.4 residuals (D4): MS062 treats a name holding a glob character as a
pattern (P85-AC-019, 020), the routing and skill-text tests read the split signal from the
engine (AC-021), and under `builtin_delivery = "plugin"` a bare `packs sync` / `next` infer codex
from a marked `.codex/agents/` file (AC-022…025), with the docs (AC-026)."""
import json
import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import modsys
from modsys import skill_sync
from modsys.config import core_defaults
from tests.helpers import run, run_json
from tests.test_next import nxt, rows
from tests.test_p84_codex_agents import ENGINE, NAMES, CodexRepo, snap
from tests.test_split_signals import SHELF, ReferencesTest, ShelfRepo, skill_text

REFUSAL = ("modsys: error: choose --agent claude, codex, cursor, gemini or copilot "
           "(repeatable), or set [packs] agents\n")
NO_AGENT = ("skills: no agent to check: [packs] agents is not set and no agent's skill "
            "directory holds a copy packs sync made")
PLUGIN = '[packs]\nbuiltin = ["core"]\nbuiltin_delivery = "plugin"\n'


class GlobNamesTest(ReferencesTest):  # P85-AC-019 (reuses the shelf fixture and PRESENT)
    # the I-3 tests of the parent class run again here, unchanged (AC-020)
    def probe(self, text, files=None):
        self.refs(skill_md=f"\n{text}\n", files=files or self.PRESENT)
        return self.missing_names()

    def test_a_name_with_a_glob_character_is_a_pattern(self):
        for text in ("see references/route-* here", "see `references/route-*`",
                     "see references/x?.md", "see references/[ab].md",
                     "references/route-*.md and references/<scenario>.md and references/*.md",
                     "**references/route-***", "references/*"):
            with self.subTest(text=text):
                self.assertEqual(self.probe(text), [])

    def test_a_real_missing_name_is_still_reported(self):
        for text, want in (("Read references/missing.md.", "references/missing.md"),
                           ("**references/missing-bold.md**", "references/missing-bold.md"),
                           ("[gone](references/missing.md#steps)", "references/missing.md"),
                           ("references/missing.md?plain=1", "references/missing.md"),
                           ("Did you read references/missing.md?", "references/missing.md"),
                           ("(references/missing.md)", "references/missing.md"),
                           ("**references/missing.md**,", "references/missing.md")):
            with self.subTest(text=text):
                self.assertEqual(self.probe(text), [want])

    def test_emphasis_around_a_file_name_is_checked(self):  # fix round 1, M-1
        for form in ("**{}**", "_see {}_", "*see {}*", "__{}__"):
            with self.subTest(form=form):
                self.assertEqual(self.probe(form.format("references/missing.md")),
                                 ["references/missing.md"])
                self.assertEqual(self.probe(form.format("references/restock.md")), [])

    def test_emphasis_with_sentence_punctuation_is_checked(self):  # fix round 2, N-1
        for form in ("**{}.**", "**See {}.**", "**{}**.", "*see {}*,", "_{}_;", "**{}.**,"):
            with self.subTest(form=form):
                self.assertEqual(self.probe(form.format("references/missing.md")),
                                 ["references/missing.md"])
                self.assertEqual(self.probe(form.format("references/restock.md")), [])
        for text in ("references/route-*.", "**references/route-*.**", "see references/[ab].*"):
            with self.subTest(text=text):
                self.assertEqual(self.probe(text), [])

    def test_emphasis_and_present_names_stay_clean(self):
        for text in ("_references/restock.md_", "__references/restock.md__",
                     "references/restock.md?plain=1", "Did you read references/restock.md?"):
            with self.subTest(text=text):
                self.assertEqual(self.probe(text), [])

    def test_the_message_and_the_route_file_and_the_ejected_copy(self):
        self.refs(skill_md="\nRead references/missing.md. Also references/route-*.\n",
                  files=self.PRESENT)
        self.assertEqual([f[3] for f in self.ms062()], [
            "skill 'stock-check' of pack 'shelf': SKILL.md names references/missing.md, which "
            "does not exist"])
        self.refs(skill_md="\nRoute: references/restock.md\n",
                  files={"references/restock.md": "then references/missing.md and references/x?.md "
                                                  "and references/route-*\n"})
        self.assertEqual(self.missing_names(), ["references/missing.md"])
        self.assertEqual(run("eject", SHELF, *self.R)[0], 0)
        copy = self.cfg / "overrides/skills" / SHELF
        (copy / "SKILL.md").write_text(skill_text(300) + "\nreferences/missing.md references/y?.md "
                                       "references/[ab].md references/route-*\n")
        found = [f[3] for f in self.ms062() if "ejected" in f[3] and "SKILL.md names" in f[3]]
        self.assertEqual(found, ["ejected skill 'stock-check' (.modsys/overrides/skills/"
                                 "stock-check): SKILL.md names references/missing.md, which "
                                 "does not exist"])

    def test_sync_and_changed_mode_ignore_names(self):
        self.refs(skill_md="\nreferences/route-* references/x?.md\n")
        code, env, err = run_json("packs", "sync", "--agent", "claude", *self.R)
        self.assertEqual((code, [r["status"] for r in env["data"]["skills"]]), (0, ["created"]))
        self.assertEqual(self.ms062(), [])


class SplitSignalReadTest(unittest.TestCase):  # P85-AC-021
    FILES = ("tests/test_p84_routing.py", "tests/test_p83_skill_text.py")

    def test_no_literal_bound_in_the_two_files(self):
        for rel in self.FILES:
            text = (ENGINE / rel).read_text(encoding="utf-8")
            with self.subTest(file=rel):
                self.assertIsNone(re.search(r"\b9_?000\b", text))
        self.assertIn('core_defaults()["budgets"]["skill_split_signal"]',
                      (ENGINE / self.FILES[0]).read_text(encoding="utf-8"))

    def test_the_default_moves_the_bound(self):  # the mutation check: a patched default is read
        patched = json.loads(json.dumps(core_defaults()))
        patched["budgets"]["skill_split_signal"] = 1
        code = ("import unittest, sys\n"
                "from unittest import mock\n"
                "import modsys.config as c\n"
                "real = c.core_defaults()\n"
                "real['budgets']['skill_split_signal'] = 1\n"
                "with mock.patch('modsys.config.core_defaults', return_value=real):\n"
                "    from tests import test_p84_routing as t\n"
                "    print(t.SPLIT_SIGNAL)\n")
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                              cwd=ENGINE)
        self.assertEqual((proc.returncode, proc.stdout.strip()), (0, "1"), proc.stderr)

    def test_a_recorded_decision_exempts_exactly_its_file(self):  # fix round 1, I-1
        from tests import test_p83_skill_text as p83
        from tests import test_p84_routing as p84
        from tests.test_budgets import SPLIT_DECISIONS, decision_key
        files = {"SKILL.md": "x" * 10, "references/create.md": "y" * 10}
        self.assertEqual(p84.oversize(files, 5), ["SKILL.md", "references/create.md"])
        self.assertEqual(p84.oversize(files, 10), [])
        for key, exempt in (("qa/qa-acceptance-baseline", "SKILL.md"),
                            ("qa/qa-acceptance-baseline/create", "references/create.md")):
            with mock.patch.dict(SPLIT_DECISIONS, {key: "x"}):
                self.assertEqual(p84.oversize(files, 5), [n for n in files if n != exempt])
        for wrong in ("qa/qa-acceptance-baseline/SKILL", "qa/qa-acceptance-baseline/create.md",
                      "core/qa-acceptance-baseline"):
            with mock.patch.dict(SPLIT_DECISIONS, {wrong: "x"}):
                self.assertEqual(p84.oversize(files, 5), list(files))
        self.assertEqual(decision_key("core", "module-sync"), "core/module-sync")
        self.assertEqual(p83.over_bound(("module-sync",), 1), ["module-sync"])
        with mock.patch.dict(SPLIT_DECISIONS, {"core/module-sync": "x"}):
            self.assertEqual(p83.over_bound(("module-sync", "module-discover"), 1),
                             ["module-discover"])
        with mock.patch.dict(SPLIT_DECISIONS, {"core/module-sync/SKILL": "x"}):
            self.assertEqual(p83.over_bound(("module-sync",), 1), ["module-sync"])

    def test_the_budget_test_records_through_the_same_helper(self):
        text = (ENGINE / "tests/test_budgets.py").read_text(encoding="utf-8")
        self.assertIn("decision_key(", text.split("def crossings", 1)[1])

    def test_the_split_signals_stay(self):
        self.assertIn("S, P = 9000, 60000",
                      (ENGINE / "tests/test_split_signals.py").read_text(encoding="utf-8"))


class AgentFileInferenceTest(CodexRepo):  # P85-AC-022…025
    def setUp(self):
        super().setUp()
        self.config(PLUGIN)

    def agents_dir(self) -> Path:
        d = self.root / ".codex/agents"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def marked(self, name="module-scout-agent") -> bytes:
        return skill_sync.codex_agent(name, "core", name.removesuffix("-agent"), "1")

    def bare(self, *argv, code=0):
        got, env, err = run_json("packs", "sync", *argv, *self.R)
        self.assertEqual((got, err), (code, ""), env)
        return env["data"]

    def refused(self, *argv):
        before = snap(self.root)
        got, out, err = run("packs", "sync", *argv, "--json", *self.R)
        self.assertEqual((got, out, err), (2, "", REFUSAL))
        self.assertEqual(snap(self.root), before)

    def skill_items(self):
        return [r for r in rows(nxt(self.root)) if r[0] == "skills"]

    def no_agent_skips(self):
        return [s for s in nxt(self.root)["skipped"] if "no agent to check" in s]

    def test_no_inference_from_noise(self):
        cases = {
            "absent": lambda: None,
            "empty": lambda: self.agents_dir(),
            "foreign": lambda: (self.agents_dir() / "x.toml").write_text("name = 'x'\n"),
            "damaged": lambda: (self.agents_dir() / "m.toml").write_bytes(
                b'# modsys-managed: {"schema": 1\nname = "x"\n'),
            "subdirectory": lambda: ((self.agents_dir() / "sub").mkdir(),
                                     (self.agents_dir() / "sub/m.toml").write_bytes(
                                         self.marked())),
        }

        def symlinked_file():
            other = self.tmp / "elsewhere.toml"
            other.write_bytes(self.marked())
            os.symlink(other, self.agents_dir() / "m.toml")
        cases["symlinked file"] = symlinked_file
        for label, plant in cases.items():
            with self.subTest(case=label):
                shutil.rmtree(self.root / ".codex", ignore_errors=True)
                plant()
                self.refused()
                self.assertEqual(self.skill_items(), [])
                self.assertEqual(self.no_agent_skips(), [NO_AGENT])

    def test_a_non_directory_agents_directory_infers_nothing(self):  # fix round 1, M-2
        def agents_file():
            (self.root / ".codex").mkdir()
            (self.root / ".codex/agents").write_bytes(self.marked())

        def codex_file():
            (self.root / ".codex").write_bytes(self.marked())
        for label, plant in (("agents is a file", agents_file), ("codex is a file", codex_file)):
            with self.subTest(case=label):
                if (self.root / ".codex").is_dir():
                    shutil.rmtree(self.root / ".codex")
                elif (self.root / ".codex").exists():
                    (self.root / ".codex").unlink()
                plant()
                self.refused()
                self.assertEqual(self.skill_items(), [])
                self.assertEqual(self.no_agent_skips(), [NO_AGENT])
                got, env, err = run_json("packs", "sync", "--agent", "codex", *self.R)
                self.assertEqual((got, err), (1, ""))
                self.assertEqual([r["status"] for r in env["data"]["agent_files"]],
                                 ["conflict"] * 3)

    def test_one_or_three_marked_files_infer_codex_like_agent_codex(self):
        for files in (["module-scout-agent"], NAMES):
            with self.subTest(files=files):
                shutil.rmtree(self.root / ".codex", ignore_errors=True)
                for n in files:
                    (self.agents_dir() / f"{n}.toml").write_bytes(self.marked(n))
                twin = self.tmp / "twin"
                shutil.rmtree(twin, ignore_errors=True)
                shutil.copytree(self.root, twin, symlinks=True)
                got, out, err = run("packs", "sync", "--check", "--json", *self.R)
                want = run("packs", "sync", "--check", "--agent", "codex", "--json", *self.R)
                self.assertEqual((got, out, err), want)
                self.assertEqual(json.loads(out)["data"]["agents"], ["codex"])
                got, out, err = run("packs", "sync", "--json", *self.R)
                got2, out2, err2 = run("packs", "sync", "--agent", "codex", "--json", "--root",
                                       str(twin))
                self.assertEqual((got, err), (got2, err2))
                self.assertEqual(json.loads(out)["data"]["agents"], ["codex"])
                self.assertEqual(out.replace(str(self.root), "R"), out2.replace(str(twin), "R"))

    def synced(self):
        self.sync()  # --agent codex: writes the three files under plugin delivery

    def test_a_stale_file_shows_in_next_and_a_bare_sync_fixes_it(self):  # AC-023
        self.synced()
        before = snap(self.root)
        self.assertEqual(self.skill_items(), [])
        got, out, err = run("packs", "sync", "--check", "--json", *self.R)
        self.assertEqual((got, err), (0, ""))
        self.assertEqual(snap(self.root), before)
        path = self.agent_file("module-discover-agent")
        text = path.read_bytes()
        path.write_bytes(re.sub(rb'"version": "[^"]*"', b'"version": "0.0.0"', text, count=1))
        stale = snap(self.root)
        self.assertEqual(self.skill_items(), [
            ("skills", "agent files not in sync (.codex/agents): stale module-discover-agent",
             "modsys packs sync")])
        self.assertEqual(snap(self.root), stale)  # next never writes
        self.assertEqual(run("packs", "sync", "--check", "--json", *self.R)[0], 1)
        data = self.bare()
        self.assertEqual([(r["name"], r["status"]) for r in data["agent_files"]],
                         [(n, "updated" if n == "module-discover-agent" else "unchanged")
                          for n in NAMES])
        self.assertEqual(path.read_bytes(), text)
        self.assertEqual(self.skill_items(), [])

    def test_an_edited_file_is_a_conflict_and_core_disabled_removes(self):  # AC-023
        self.synced()
        path = self.agent_file("module-scout-agent")
        path.write_bytes(path.read_bytes() + b"# edit\n")
        self.assertEqual(self.skill_items(), [
            ("skills", "agent files not in sync (.codex/agents): in conflict module-scout-agent",
             "modsys packs sync")])
        edited = path.read_bytes()
        data = self.bare(code=1)
        self.assertEqual({r["name"]: r["status"] for r in data["agent_files"]}["module-scout-agent"],
                         "conflict")
        self.assertEqual(path.read_bytes(), edited)
        path.write_bytes(self.marked("module-scout-agent"))
        self.synced()
        self.config('[packs]\nbuiltin = []\nbuiltin_delivery = "plugin"\n')
        self.assertEqual(self.skill_items(), [
            ("skills", "agent files not in sync (.codex/agents): to remove module-discover-agent, "
             "module-research-agent, module-scout-agent", "modsys packs sync")])
        data = self.bare()
        self.assertEqual([r["status"] for r in data["agent_files"]], ["removed"] * 3)
        self.refused()  # no marked file left: the bdc9f9b refusal
        self.assertEqual(self.no_agent_skips(), [NO_AGENT])

    def test_symlinked_agents_directory_infers_codex_with_conflicts(self):  # AC-022
        outside = self.tmp / "outside"
        outside.mkdir()
        for n in NAMES:
            (outside / f"{n}.toml").write_bytes(self.marked(n))
        (self.root / ".codex").mkdir()
        os.symlink(outside, self.root / ".codex/agents")
        before = snap(outside)
        data = self.bare(code=1)
        self.assertEqual(data["agents"], ["codex"])
        self.assertEqual([r["status"] for r in data["agent_files"]], ["conflict"] * 3)
        self.assertEqual(snap(outside), before)
        items = self.skill_items()
        self.assertEqual(len(items), 1)
        self.assertIn("in conflict", items[0][1])

    @unittest.skipIf(os.geteuid() == 0, "root writes into a read-only directory")
    def test_a_read_only_agents_directory_refuses_and_next_reads(self):  # AC-025
        self.synced()
        path = self.agent_file("module-discover-agent")
        path.write_bytes(re.sub(rb'"version": "[^"]*"', b'"version": "0.0.0"',
                                path.read_bytes(), count=1))
        (self.root / ".codex/agents").chmod(0o555)
        got, out, err = run("packs", "sync", "--json", *self.R)
        self.assertEqual((got, out), (2, ""))
        self.assertTrue(err.startswith("modsys: error: cannot write .codex/agents/"), err)
        self.assertEqual(err.count("\n"), 1)
        self.assertIn("stale module-discover-agent", self.skill_items()[0][1])
        got, out, err = run("packs", "sync", "--check", "--dry-run", "--json", *self.R)
        self.assertEqual((got, out), (2, ""))
        self.assertNotIn("Traceback", err)

    def test_where_the_inference_does_not_reach(self):  # AC-024
        for n in NAMES:
            (self.agents_dir() / f"{n}.toml").write_bytes(self.marked(n))
        # --agent and [packs] agents win
        data = self.bare("--check", "--agent", "claude")
        self.assertEqual(data["agents"], ["claude"])
        self.config(PLUGIN + 'agents = ["claude"]\n')
        self.assertEqual(self.bare("--check")["agents"], ["claude"])
        self.config(PLUGIN)
        # repo delivery: as at bdc9f9b (no inference from agent files)
        self.config('[packs]\nbuiltin = ["core"]\n')
        self.refused()
        self.assertEqual(self.no_agent_skips(), [NO_AGENT])
        # plugin + a marked .claude/skills copy -> claude, codex (engine order)
        self.config(PLUGIN)
        claude = self.root / ".claude/skills/stock-check"
        claude.mkdir(parents=True)
        (claude / ".modsys-managed").write_text(json.dumps(
            {"schema": "modsys.managed/1", "pack": "shelf", "skill": "stock-check",
             "version": "1", "files": {}}), encoding="utf-8")
        with mock.patch.object(skill_sync, "read_marker", side_effect=lambda d: d.parent.parent
                               .name == ".claude" or None):
            self.assertEqual(skill_sync.managed_agents(self.root, True), ["claude", "codex"])
            self.assertEqual(skill_sync.managed_agents(self.root, False), ["claude"])
        # a marked .agents/skills copy: codex once
        shutil.rmtree(self.root / ".claude")
        copy = self.root / ".agents/skills/stock-check"
        copy.mkdir(parents=True)
        with mock.patch.object(skill_sync, "read_marker", side_effect=lambda d: True):
            self.assertEqual(skill_sync.managed_agents(self.root, True), ["codex"])

    def test_setup_does_not_infer_from_agent_files(self):  # SI-P85-12
        for delivery in ('builtin_delivery = "plugin"\n', ""):
            with self.subTest(delivery=delivery):
                shutil.rmtree(self.root / ".codex", ignore_errors=True)
                self.config(f'[packs]\nbuiltin = ["core"]\n{delivery}')
                for n in NAMES:
                    (self.agents_dir() / f"{n}.toml").write_bytes(self.marked(n))
                got, env, err = run_json("setup", "--dry-run", *self.R)
                self.assertEqual(err, "")
                self.assertEqual(env["data"]["agents"], ["claude", "codex"])
        self.assertEqual(skill_sync.managed_agents(self.root), [])  # default: never from files

    def test_named_agents_without_codex_never_open_codex(self):  # AC-024, final review M-5
        (self.agents_dir() / "module-scout-agent.toml").write_bytes(self.marked())
        with mock.patch.object(skill_sync, "_marked_agent_file") as probe, \
                mock.patch("modsys.packs_cmd.plan_agent_files") as plan:
            self.bare("--check", "--agent", "claude")  # named by the flag
            self.config(PLUGIN + 'agents = ["claude"]\n')  # named by `[packs] agents`
            self.assertEqual(self.bare("--check")["agents"], ["claude"])
            self.assertEqual(self.skill_items(), [])  # `next` reads the same agents
            probe.assert_not_called()
            plan.assert_not_called()

    def test_a_real_process_and_the_tree_stays(self):  # AC-027
        for n in NAMES:
            (self.agents_dir() / f"{n}.toml").write_bytes(self.marked(n))
        env = {**os.environ, "PYTHONPATH": str(ENGINE)}
        env.pop("MODSYS_DEBUG", None)
        before = snap(self.root)
        for argv in (["packs", "sync", "--check"], ["next"]):
            proc = subprocess.run([sys.executable, "-m", "modsys", *argv, "--json", *self.R],
                                  capture_output=True, text=True, env=env, cwd=self.tmp)
            self.assertIn(proc.returncode, (0, 1), proc.stderr)
            self.assertEqual(proc.stderr, "")
            self.assertEqual(json.loads(proc.stdout)["schema"].split("/")[0][:7], "modsys.")
        self.assertEqual(snap(self.root), before)


class DocsTest(unittest.TestCase):  # P85-AC-026, AC-020
    def doc(self, rel):
        return (ENGINE / rel).read_text(encoding="utf-8")

    def flat(self, rel):
        return " ".join(self.doc(rel).split())

    def test_the_inference_is_documented(self):
        for rel in ("docs/configuration.md", "docs/cli-contract.md"):
            with self.subTest(doc=rel):
                text = self.flat(rel)
                self.assertIn('under `builtin_delivery = "plugin"`, a `.codex/agents/` holding a '
                              'marked agent file means codex', text)
        self.assertIn("else `claude` and `codex`", self.flat("docs/cli-contract.md"))
        for obj in (skill_sync.managed_agents, ):
            self.assertIn(".codex/agents", obj.__doc__)
        import modsys.next_cmd as nc
        import modsys.packs_cmd as pc
        self.assertIn(".codex/agents/", pc.__doc__)
        self.assertIn(".codex/agents/", nc.skill_copies.__doc__)

    def test_the_codex_claims_name_the_bare_plugin_run(self):  # final review M-5
        stale = ("a sync without `codex` never opens `.codex/`",
                 "Without `codex` nothing under `.codex/` is read or written",
                 "`.codex/` is never read for another agent",
                 "With no agent named, a bare `packs sync` and `next` also read `.codex/agents/`:",
                 "when no agent is named and no skill copy holds a marker")
        claim = ('a bare run under `builtin_delivery = "plugin"` reads `.codex/agents/` only to '
                 'infer codex')
        named = "names its agents without"
        files = ("docs/skills.md", "CHANGELOG.md", "docs/configuration.md",
                 "modsys/skill_sync.py", "modsys/packs_cmd.py", "modsys/next_cmd.py")
        texts = {rel: " ".join(re.sub(r"\n\s*# ", "\n", self.doc(rel)).split()) for rel in files}
        for rel, text in texts.items():
            with self.subTest(file=rel):
                self.assertEqual([s for s in stale if s in text], [])
        for rel in ("docs/skills.md", "CHANGELOG.md", "modsys/skill_sync.py",
                    "modsys/packs_cmd.py"):
            with self.subTest(file=rel):
                self.assertEqual(texts[rel].count(claim), 1)
                self.assertEqual(texts[rel].count(named), 1)
        row = texts["docs/configuration.md"].split("| `agents` | unset |", 1)[1].split(" | ", 1)[0]
        self.assertLess(row.index('under `builtin_delivery = "plugin"`'),
                        row.index("a bare `packs sync` and `next`"))
        import modsys.next_cmd as nc
        self.assertIn("no `.agents/skills` copy holds a marker", " ".join(
            nc.skill_copies.__doc__.split()))

    def test_ms062_rows_say_a_glob_is_a_pattern(self):
        for rel in ("docs/configuration.md", "docs/writing-a-pack.md"):
            with self.subTest(doc=rel):
                self.assertIn("a name holding `*`, `?` or `[` is a pattern", self.flat(rel))
        import modsys.lint as lint
        self.assertIn("pattern", Path(lint.__file__).read_text(encoding="utf-8")
                      .split("_REFERENCE")[0][-700:])

    def test_the_changelog_has_both_entries(self):
        fixed = self.doc("CHANGELOG.md").split("## [", 2)[1].split("### Fixed", 1)[1]
        self.assertRegex(fixed, r"(?s)\A\s*- Lint \*\*MS062\*\*: .*?is a pattern, not a file")
        self.assertRegex(fixed, r"(?s)- A bare `packs sync` and `next` under "
                                r"`builtin_delivery = \"plugin\"` infer codex from a `\.codex/agents/`")


if __name__ == "__main__":
    unittest.main()
