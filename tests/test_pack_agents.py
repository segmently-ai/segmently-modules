"""`packs sync` for five agents (P6 D5): `cursor`, `gemini` and `copilot` write `.agents/skills`
like `codex` — one write per directory —, the Copilot duplicate note, the agents inferred from
managed copies and the hints that name them."""
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from segmently_modules import skill_sync
from tests.helpers import copy_fixture, run, run_json

SKILL = "---\nname: {sid}\ndescription: The {sid} skill.\n---\n\n# {sid}\n"
FIVE = ("claude", "codex", "cursor", "gemini", "copilot")
COPILOT = ("GitHub Copilot reads both .claude/skills and .agents/skills, so it sees each skill "
           "twice — where Copilot works, sync only one of the two directories (Copilot reads "
           "either)")


class AgentsRepo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        self.R = ("--root", str(self.root))
        team = self.root / ".segmently-modules/packs/team"
        text = 'id = "team"\nversion = "0.1.0"\n'
        for sid in ("api-review", "notes"):
            (team / "skills" / sid).mkdir(parents=True)
            (team / "skills" / sid / "SKILL.md").write_text(SKILL.format(sid=sid))
            text += f'\n[skills.{sid}]\npath = "skills/{sid}"\n'
        (team / "pack.toml").write_text(text)

    def tearDown(self):
        self._tmp.cleanup()

    def sync(self, *agents: str, flags=(), code: int = 0) -> dict:
        argv = [a for agent in agents for a in ("--agent", agent)]
        got, env, err = run_json("packs", "sync", *argv, *flags, *self.R)
        self.assertEqual((got, err), (code, ""), env)
        self.assertEqual(env["schema"], "segmently-modules.packs/1")
        return env["data"]

    def config(self, text: str) -> None:
        (self.root / ".segmently-modules/config.toml").write_text(text)


class FiveAgentsTest(AgentsRepo):  # P6-AC-003
    def test_each_new_agent_alone(self):
        for agent in ("cursor", "gemini", "copilot"):
            with self.subTest(agent=agent):
                shutil.rmtree(self.root / ".agents", ignore_errors=True)
                data = self.sync(agent)
                self.assertEqual([(r["agent"], r["dir"], r["status"]) for r in data["skills"]],
                                 [(agent, ".agents/skills/api-review", "created"),
                                  (agent, ".agents/skills/notes", "created")])
                marker = (self.root / ".agents/skills/notes/.segmently-modules-managed").read_text()
                self.assertNotIn(agent, marker)  # the marker carries no agent

    def test_all_five_write_each_file_once(self):
        written = []
        real = skill_sync.copy_file
        with mock.patch.object(skill_sync, "copy_file",
                               side_effect=lambda src, path: (written.append(path),
                                                              real(src, path))[1]):
            data = self.sync(*FIVE)
        self.assertEqual([(r["agent"], r["skill"], r["status"], r.get("same_as"))
                          for r in data["skills"]], [
            ("claude", "api-review", "created", None), ("claude", "notes", "created", None),
            ("codex", "api-review", "created", None), ("codex", "notes", "created", None),
            *[(a, s, "created", "codex") for a in ("cursor", "gemini", "copilot")
              for s in ("api-review", "notes")]])
        self.assertEqual(len(written), len(set(written)))
        root = self.root.resolve()
        self.assertEqual(sorted(Path(p).resolve().relative_to(root).as_posix()
                                for p in written), [
            ".agents/skills/api-review/SKILL.md", ".agents/skills/notes/SKILL.md",
            ".claude/skills/api-review/SKILL.md", ".claude/skills/notes/SKILL.md"])
        self.assertEqual(data["summary"]["created"], 10)  # same_as rows count (P4a rule)
        again = self.sync(*FIVE, flags=("--check",))
        self.assertEqual({r["status"] for r in again["skills"]}, {"unchanged"})
        out = run("packs", "sync", *[a for x in FIVE for a in ("--agent", x)], *self.R)[1]
        self.assertIn("unchanged  copilot .agents/skills/notes  (team 0.1.0)  same directory as "
                      "codex", out.splitlines())  # the agent column fits copilot

    def test_the_first_agent_of_a_directory_writes_it(self):
        data = self.sync("cursor", "codex")
        self.assertEqual([(r["agent"], r.get("same_as")) for r in data["skills"]],
                         [("cursor", None), ("cursor", None), ("codex", "cursor"),
                          ("codex", "cursor")])
        data = self.sync("cursor", "cursor")
        self.assertEqual([r["agent"] for r in data["skills"]], ["cursor", "cursor"])

    def test_the_config_names_them_too(self):
        self.config('[packs]\nagents = ["gemini", "copilot"]\n')
        data = self.sync()
        self.assertEqual(data["agents"], ["gemini", "copilot"])
        self.assertEqual([(r["agent"], r["status"], r.get("same_as")) for r in data["skills"]],
                         [("gemini", "created", None), ("gemini", "created", None),
                          ("copilot", "created", "gemini"), ("copilot", "created", "gemini")])

    def test_an_unknown_agent(self):
        for how in ("flag", "config"):
            with self.subTest(how=how):
                self.config('[packs]\nagents = ["windsurf"]\n' if how == "config" else "")
                argv = ("--agent", "windsurf") if how == "flag" else ()
                code, out, err = run("packs", "sync", *argv, "--json", *self.R)
                self.assertEqual((code, out), (2, ""))
                self.assertIn("unknown agent 'windsurf' (agents: claude, codex, cursor, gemini, "
                              "copilot)", err)
                if how == "config":
                    self.assertIn(".segmently-modules/config.toml: [packs] agents: ", err)

    def test_a_local_edit_under_agents_skills(self):  # P4A-AC-014/015 hold for cursor
        self.sync("cursor")
        (self.root / ".agents/skills/notes/SKILL.md").write_text("# mine\n")
        data = self.sync("cursor", code=1)
        row = next(r for r in data["skills"] if r["skill"] == "notes")
        self.assertEqual((row["status"], row["reason"]), ("conflict",
                                                          "SKILL.md (locally edited)"))


class CopilotNoteTest(AgentsRepo):  # P6-AC-004 (SI-20)
    def test_the_agent_sets(self):
        for agents, noted in ((("claude",), False), (("codex",), False), (("cursor",), False),
                              (("copilot",), False), (("claude", "codex"), True),
                              (("claude", "cursor"), True), (("claude", "gemini"), True),
                              (("claude", "copilot"), True), (FIVE, True)):
            for dirs in (".claude", ".agents"):
                shutil.rmtree(self.root / dirs, ignore_errors=True)
            for flags, code in ((("--dry-run",), 0), (("--check",), 1), ((), 0)):
                with self.subTest(agents=agents, flags=flags):
                    data = self.sync(*agents, flags=flags, code=code)  # exit unaffected
                    self.assertEqual(data["notes"], [COPILOT] if noted else [])

    def test_the_text_line_and_a_mirrored_directory(self):
        (self.root / ".claude/skills").mkdir(parents=True)
        (self.root / ".agents").mkdir()
        os.symlink("../.claude/skills", self.root / ".agents/skills")
        code, out, err = run("packs", "sync", "--agent", "claude", "--agent", "codex", *self.R)
        self.assertEqual((code, err), (0, ""))
        lines = out.splitlines()
        self.assertEqual(lines[-2:], [f"note: {COPILOT}", "packs sync: 4 created, 0 updated, "
                                      "0 unchanged, 0 removed, 0 conflict, 0 invalid"])
        self.assertEqual(sum(line.startswith("note:") for line in lines), 1)


class InferredAgentsTest(AgentsRepo):  # P6-AC-027 (SI-9)
    def agents(self, code: int = 0) -> list[str]:
        got, env, err = run_json("packs", "sync", *self.R)
        self.assertEqual((got, err), (code, ""), env)
        return env["data"]["agents"]

    def test_the_decision_table(self):
        code, out, err = run("packs", "sync", "--json", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(err, "segmently-modules: error: choose --agent claude, codex, cursor, gemini or "
                              "copilot (repeatable), or set [packs] agents\n")
        self.sync("cursor")
        got, env, err = run_json("packs", "sync", *self.R)
        self.assertEqual(env["data"]["agents"], ["codex"])  # a marker in .agents/skills
        self.assertEqual({r["status"] for r in env["data"]["skills"]}, {"unchanged"})
        self.sync("claude")
        self.assertEqual(self.agents(), ["claude", "codex"])
        shutil.rmtree(self.root / ".agents")
        self.assertEqual(self.agents(), ["claude"])

    def test_the_hints_keep_claude_and_codex(self):
        code, out, err = run("eject", "api-review", *self.R)
        self.assertEqual(out.splitlines()[-1], "next: segmently-modules packs sync --agent claude --agent "
                                               "codex (or set [packs] agents once)")
        self.sync("claude")
        (self.root / ".segmently-modules/packs/team/skills/notes/SKILL.md").write_text(
            SKILL.format(sid="notes").replace("The notes skill.", "Changed."))
        shutil.rmtree(self.root / ".segmently-modules/overrides")
        code, out, err = run("packs", "sync", "--check", "--agent", "claude", *self.R)
        self.assertTrue(out.splitlines()[-1].endswith("stale — run segmently-modules packs sync --agent "
                                                      "claude"), out)
        self.assertIn("--agent claude --agent codex", run("eject", "--help")[1].replace("\n",
                                                                                       " "))


class NoPluginAgentsTest(AgentsRepo):  # P6-AC-002 row 7 (SI-7)
    def test_cursor_under_plugin_delivery(self):
        self.config('[packs]\nbuiltin = ["core", "ui", "qa"]\nbuiltin_delivery = "plugin"\n')
        data = self.sync("claude", "cursor")
        self.assertEqual({r["skill"] for r in data["skills"]}, {"api-review", "notes"})
        self.assertEqual(data["notes"], [
            'builtin_delivery = "plugin": the built-in skills come from the plugins segmently-modules '
            '(core), segmently-modules-qa (qa), segmently-modules-ui (ui) — packs sync copies none of them',
            'cursor gets no built-in skills: no segmently-modules plugin exists for it — set [packs] '
            'builtin_delivery = "repo" to sync the built-in skills for it', COPILOT])
        data = self.sync("gemini", "copilot")
        self.assertIn('gemini, copilot get no built-in skills: no segmently-modules plugin exists for them '
                      '— set [packs] builtin_delivery = "repo" to sync the built-in skills for '
                      'them', data["notes"])


if __name__ == "__main__":
    unittest.main()
