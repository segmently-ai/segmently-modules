"""`packs sync --agent A --remove` (P6 D5, row 6.3's uninstall): every copy `packs sync` made in
A's skill directory goes; an edited copy stays a conflict; unmanaged files, the ejected copies
and the config are never touched; the refusals that keep a shared directory safe."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from segmently_modules import skill_sync
from tests.helpers import copy_fixture, run, run_json

SKILL = "---\nname: api-review\ndescription: Reviews API changes.\n---\n\n# api-review\n"
CORE = ["module-adopt", "module-assistant", "module-create", "module-discover", "module-init",
        "module-lint", "module-research", "module-roles", "module-scout", "module-split",
        "module-sync"]


class RemoveRepo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        self.R = ("--root", str(self.root))
        team = self.root / ".segmently-modules/packs/team"
        (team / "skills/api-review").mkdir(parents=True)
        (team / "pack.toml").write_text('id = "team"\nversion = "0.1.0"\n\n[skills.api-review]\n'
                                        'path = "skills/api-review"\n')
        (team / "skills/api-review/SKILL.md").write_text(SKILL)
        self.config()

    def tearDown(self):
        self._tmp.cleanup()

    def config(self, agents: list[str] | None = None) -> None:
        text = '[packs]\nbuiltin = ["core"]\n'
        if agents is not None:
            text += f"agents = {json.dumps(agents)}\n"
        (self.root / ".segmently-modules/config.toml").write_text(text)

    def sync(self, *argv: str, code: int = 0) -> dict:
        got, env, err = run_json("packs", "sync", *argv, *self.R)
        self.assertEqual((got, err), (code, ""), env)
        self.assertEqual(env["schema"], "segmently-modules.packs/1")
        return env["data"]

    def hashes(self, *skip: str) -> dict:
        """sha256 of every file below the root, but those under the `skip` directories."""
        return {p.relative_to(self.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(self.root.rglob("*")) if p.is_file()
                and not any(p.relative_to(self.root).as_posix().startswith(s) for s in skip)}

    def statuses(self, data: dict) -> dict:
        return {r["skill"]: r["status"] for r in data["skills"]}


class RemoveTest(RemoveRepo):  # P6-AC-005
    def plant(self) -> None:
        self.assertEqual(run("eject", "module-lint", *self.R)[0], 0)
        self.untouched = self.hashes(".agents/", ".claude/")  # before the first sync
        self.sync("--agent", "claude")
        self.sync("--agent", "cursor")  # 11 managed copies under .agents/skills
        skills = self.root / ".agents/skills"
        (skills / "module-scout/NOTES.md").write_text("my notes\n")
        (skills / "my-own").mkdir()
        (skills / "my-own/SKILL.md").write_text("---\nname: my-own\ndescription: Mine.\n---\n")
        (skills / "y").mkdir()
        shutil.copy(skills / "api-review/.segmently-modules-managed", skills / "y/.segmently-modules-managed")
        self.edited = skills / "module-sync/SKILL.md"
        self.original = self.edited.read_bytes()
        self.edited.write_text("# edited\n")
        self.kept = self.hashes(".agents/skills/module-", ".agents/skills/api-review")

    def test_the_uninstall(self):
        self.plant()
        before = self.hashes()
        dry = self.sync("--agent", "cursor", "--remove", "--dry-run", code=1)
        self.assertEqual(self.hashes(), before)  # --dry-run: the same statuses, nothing written
        data = self.sync("--agent", "cursor", "--remove", code=1)
        self.assertEqual([(r["skill"], r["status"]) for r in dry["skills"]],
                         [(r["skill"], r["status"]) for r in data["skills"]])
        self.assertEqual(self.statuses(data), {**{s: "removed" for s in CORE},
                                               "module-sync": "conflict",
                                               "api-review": "removed"})
        rows = {r["skill"]: r for r in data["skills"]}
        self.assertEqual(rows["module-sync"]["reason"], "SKILL.md (locally edited; not removed)")
        self.assertEqual(rows["module-scout"]["reason"], "left unmanaged files: NOTES.md")
        self.assertEqual(rows["module-lint"]["source"], "ejected")
        self.assertEqual((data["summary"]["removed"], data["summary"]["conflict"]), (11, 1))
        self.assertEqual(sorted(p.name for p in (self.root / ".agents/skills").iterdir()),
                         ["module-scout", "module-sync", "my-own", "y"])
        self.assertEqual(sorted(p.name for p in (self.root / ".agents/skills/module-scout")
                                .iterdir()), ["NOTES.md"])
        self.assertEqual(self.hashes(".agents/skills/module-"), self.kept)
        self.assertEqual(self.edited.read_text(), "# edited\n")
        self.edited.write_bytes(self.original)
        data = self.sync("--agent", "cursor", "--remove")
        self.assertEqual(self.statuses(data), {"module-sync": "removed"})
        data = self.sync("--agent", "cursor", "--remove")
        self.assertEqual((data["skills"], data["summary"]["removed"], data["notes"]),
                         ([], 0, []))
        self.assertEqual(run("packs", "sync", "--agent", "cursor", "--remove", *self.R)[1]
                         .splitlines(), [
            "nothing to remove: no copy made by packs sync in .agents/skills",
            "packs sync --remove: 0 created, 0 updated, 0 unchanged, 0 removed, 0 conflict, "
            "0 invalid"])
        after = self.hashes(".agents/", ".claude/")
        self.assertEqual(after, self.untouched)  # nothing packs sync did not create changed
        self.assertEqual(len([p for p in (self.root / ".claude/skills").iterdir()]), 12)
        shutil.rmtree(self.root / ".agents/skills/module-scout")  # the user's own notes
        data = self.sync("--agent", "cursor")  # --remove never edits the config
        self.assertEqual(data["summary"]["created"], 12)

    def test_ctrl_c_and_an_internal_error(self):  # P6-AC-033
        self.sync("--agent", "cursor")
        calls = []
        real = Path.unlink

        def unlink(path, *a, **kw):
            if ".agents" in path.parts:
                calls.append(path.name)
                if len(calls) == 2:  # api-review: SKILL.md gone, Ctrl-C before its marker
                    raise KeyboardInterrupt
            return real(path, *a, **kw)

        with mock.patch.object(Path, "unlink", unlink):
            code, out, err = run("packs", "sync", "--agent", "cursor", "--remove", "--json",
                                 *self.R)
        self.assertEqual((code, out, err), (130, "", "segmently-modules: interrupted\n"))
        half = self.root / ".agents/skills/api-review"
        self.assertEqual(sorted(p.name for p in half.iterdir()), [".segmently-modules-managed"])
        data = self.sync("--agent", "cursor", "--remove")
        self.assertEqual(self.statuses(data)["api-review"], "removed")
        self.assertFalse(half.exists())
        self.sync("--agent", "cursor")
        with mock.patch.object(skill_sync, "plan_orphans", side_effect=RuntimeError("boom")):
            code, out, err = run("packs", "sync", "--agent", "cursor", "--remove", "--json",
                                 *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("segmently-modules: internal error: RuntimeError: boom"), err)
        self.assertNotIn("Traceback", err)

    def test_one_envelope(self):  # P6-AC-033
        self.sync("--agent", "cursor")
        code, out, err = run("packs", "sync", "--agent", "cursor", "--remove", "--json", *self.R)
        self.assertEqual((code, err), (0, ""))
        env = json.loads(out)
        self.assertEqual((env["schema"], set(env["data"])), ("segmently-modules.packs/1", {
            "agents", "check", "dry_run", "skills", "summary", "failed", "notes"}))
        self.assertEqual(env["data"]["notes"], [
            ".agents/skills is also where codex, gemini, copilot read skills — the copies are "
            "gone for them too"])


class RemoveScopeTest(RemoveRepo):  # P6-AC-032 (SI-10)
    def refused(self, *argv: str) -> str:
        before = self.hashes()
        code, out, err = run("packs", "sync", *argv, "--json", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(self.hashes(), before)
        return err

    def test_the_table(self):
        self.sync("--agent", "claude", "--agent", "cursor")
        self.config(["codex", "cursor"])
        self.assertIn("--remove needs --agent", self.refused("--remove"))
        err = self.refused("--agent", "cursor", "--remove")
        self.assertIn("codex", err)
        self.assertIn(".agents/skills", err)
        self.assertIn("--remove would delete the copies codex, cursor still read in "
                      ".agents/skills ([packs] agents lists codex, cursor) — add --agent codex "
                      "--agent cursor", self.refused("--agent", "copilot", "--remove"))
        self.assertIn("--check and --remove cannot be combined",
                      self.refused("--agent", "cursor", "--check", "--remove"))
        self.assertIn("unknown agent 'windsurf'", self.refused("--agent", "windsurf", "--remove"))
        data = self.sync("--agent", "cursor", "--agent", "codex", "--remove")
        self.assertEqual({(r["agent"], r.get("same_as")) for r in data["skills"]},
                         {("cursor", None), ("codex", "cursor")})
        self.assertEqual(data["summary"]["removed"], 24)  # 12 removed once, 12 same_as rows
        self.assertEqual(data["notes"], [".agents/skills is also where gemini, copilot read "
                                         "skills — the copies are gone for them too",
                                         "codex, cursor are still in [packs] agents: the next "
                                         "packs sync copies their skills again and packs sync "
                                         "--check is stale — take them out of [packs] agents "
                                         "to keep the copies gone"])
        self.assertTrue((self.root / ".claude/skills/module-sync").is_dir())

    def test_a_mirrored_directory(self):  # PR-9: real paths decide what is shared
        (self.root / ".claude/skills").mkdir(parents=True)
        (self.root / ".agents").mkdir()
        os.symlink("../.claude/skills", self.root / ".agents/skills")
        self.config(["claude", "codex"])
        self.sync()
        err = self.refused("--agent", "codex", "--remove")
        self.assertIn("--remove would delete the copies claude still reads in .claude/skills "
                      "([packs] agents lists claude) — add --agent claude", err)
        data = self.sync("--agent", "claude", "--agent", "codex", "--remove")
        self.assertEqual({(r["agent"], r.get("same_as")) for r in data["skills"]},
                         {("claude", None), ("codex", "claude")})
        self.assertEqual(data["summary"]["removed"], 24)  # 12 removed once, 12 same_as rows
        self.assertEqual(list((self.root / ".claude/skills").iterdir()), [])

    def test_a_configured_agent_and_a_dry_run_are_named(self):  # final review M-15, M-16
        self.sync("--agent", "cursor")
        code, out, err = run("packs", "sync", "--agent", "cursor", "--remove", "--dry-run",
                             *self.R)
        self.assertEqual((code, err), (0, ""))
        self.assertIn("note: .agents/skills is also where codex, gemini, copilot read skills — "
                      "the copies would be gone for them too", out.splitlines())
        self.config(["claude", "codex"])
        self.sync()
        data = self.sync("--agent", "claude", "--remove")
        self.assertEqual(data["summary"]["removed"], 12)
        self.assertEqual(data["notes"], [
            "claude is still in [packs] agents: the next packs sync copies its skills again "
            "and packs sync --check is stale — take it out of [packs] agents to keep the copies "
            "gone"])
        code, out, err = run("packs", "sync", "--check", *self.R)  # what the note says
        self.assertEqual(code, 1)
        self.assertIn("stale", out.splitlines()[-1])

    def test_no_config_the_other_readers_are_named(self):
        self.sync("--agent", "cursor")
        code, out, err = run("packs", "sync", "--agent", "cursor", "--remove", *self.R)
        self.assertEqual((code, err), (0, ""))
        self.assertIn("note: .agents/skills is also where codex, gemini, copilot read skills — "
                      "the copies are gone for them too", out.splitlines())
        self.assertNotIn("Copilot reads both", out)  # no Copilot note on --remove (P6-AC-004)


if __name__ == "__main__":
    unittest.main()
