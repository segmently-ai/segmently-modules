"""`modsys packs sync` (D7): statuses decided before anything is written, file safety, agents,
`--check` / `--dry-run`, mirrored agent directories and the `[packs]` config section."""
import errno
import hashlib
import json
import os
import shutil
import stat
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from modsys import skill_sync
from modsys.init_cmd import starter_config
from tests.helpers import copy_fixture, run, run_json

SKILL = "---\nname: {sid}\ndescription: {desc}\n---\n\n# {sid}\n"
BLOCK = '[skills.{sid}]\npath = "skills/{sid}"\n'
EDIT_HINT = ("  SKILL.md (locally edited) — revert it (git checkout -- "
             ".claude/skills/api-review) and sync again, or keep the change: modsys eject "
             "api-review, copy the change into .modsys/overrides/skills/api-review, then packs "
             "sync")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class SyncRepo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        self.R = ("--root", str(self.root))
        self.team = self.root / ".modsys/packs/team"
        self.pack("team", ["api-review"])

    def tearDown(self):
        self._tmp.cleanup()

    def pack(self, pack_id: str, skills: list[str], version: str = "0.1.0",
             priority: int = 50) -> None:
        d = self.root / ".modsys/packs" / pack_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "pack.toml").write_text(
            f'id = "{pack_id}"\nversion = "{version}"\npriority = {priority}\n'
            + "".join(BLOCK.format(sid=s) for s in skills), encoding="utf-8")
        for sid in skills:
            md = d / "skills" / sid / "SKILL.md"
            if not md.exists():
                md.parent.mkdir(parents=True, exist_ok=True)
                md.write_text(SKILL.format(sid=sid, desc=f"The {sid} skill of {pack_id}."),
                              encoding="utf-8")

    def src(self, rel: str, pack_id: str = "team", sid: str = "api-review") -> Path:
        return self.root / ".modsys/packs" / pack_id / "skills" / sid / rel

    def dest(self, rel: str = "", sid: str = "api-review", agent_dir=".claude/skills") -> Path:
        return self.root / agent_dir / sid / rel

    def sync(self, *argv, code=0, agents=("claude",)) -> dict:
        flags = [a for agent in agents for a in ("--agent", agent)]
        got, env, err = run_json("packs", "sync", *flags, *argv, *self.R)
        self.assertEqual((got, err), (code, ""), env)
        self.assertEqual(env["schema"], "modsys.packs/1")
        self.assertIs(env["data"]["failed"], code == 1)
        return env["data"]

    def statuses(self, data) -> list[tuple]:
        return [(r["agent"], r["skill"], r["status"]) for r in data["skills"]]

    def snapshot(self, top: str = ".claude") -> dict:
        base = self.root / top
        return {p.relative_to(base).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in sorted(base.rglob("*")) if p.is_file()} if base.exists() else {}


class SyncTransitionsTest(SyncRepo):  # P4A-AC-014
    def test_created_writes_every_file_and_the_marker_last(self):
        self.src("references/api.md").parent.mkdir()
        self.src("references/api.md").write_text("# API\n")
        data = self.sync()
        self.assertEqual(data["skills"], [{
            "agent": "claude", "skill": "api-review", "pack": "team", "version": "0.1.0",
            "source": "pack", "dir": ".claude/skills/api-review", "status": "created",
            "files": ["SKILL.md", "references/api.md"], "reason": None}])
        files = {rel: sha(self.src(rel).read_bytes()) for rel in ("SKILL.md", "references/api.md")}
        self.assertEqual(self.dest(".modsys-managed").read_text(), json.dumps(
            {"schema": "modsys.managed/1", "pack": "team", "skill": "api-review",
             "version": "0.1.0", "source": "pack", "files": files},
            indent=2, sort_keys=True) + "\n")
        for rel in files:
            self.assertEqual(self.dest(rel).read_bytes(), self.src(rel).read_bytes())

    def test_a_rerun_rewrites_nothing(self):
        self.sync()
        before = self.snapshot()
        data = self.sync()
        self.assertEqual((self.statuses(data), data["skills"][0]["files"]),
                         ([("claude", "api-review", "unchanged")], []))
        self.assertEqual(self.snapshot(), before)

    def test_updated_when_the_pack_changes(self):
        self.sync()
        self.src("SKILL.md").write_text(SKILL.format(sid="api-review", desc="Version two."))
        self.pack("team", ["api-review"], version="0.2.0")
        data = self.sync()
        self.assertEqual((self.statuses(data), data["skills"][0]["files"]),
                         ([("claude", "api-review", "updated")], ["SKILL.md"]))
        self.assertEqual(self.dest("SKILL.md").read_bytes(), self.src("SKILL.md").read_bytes())
        marker = json.loads(self.dest(".modsys-managed").read_text())
        self.assertEqual((marker["version"], marker["files"]["SKILL.md"]),
                         ("0.2.0", sha(self.src("SKILL.md").read_bytes())))

    def test_files_added_and_dropped_by_the_source(self):
        self.src("notes.md").write_text("notes\n")
        self.sync()
        self.src("notes.md").unlink()
        self.src("references").mkdir()
        self.src("references/api.md").write_text("# API\n")
        data = self.sync()
        self.assertEqual((self.statuses(data)[0][2], data["skills"][0]["files"]),
                         ("updated", ["notes.md", "references/api.md"]))
        self.assertFalse(self.dest("notes.md").exists())
        self.assertEqual(self.dest("references/api.md").read_text(), "# API\n")

    def test_a_local_edit_is_a_conflict_and_other_skills_still_sync(self):
        self.pack("team", ["api-review", "notes"])
        self.sync()
        self.dest("SKILL.md").write_text("# edited by hand\n")
        (self.src("SKILL.md", sid="notes")).write_text(SKILL.format(sid="notes", desc="New."))
        data = self.sync(code=1)
        self.assertEqual(self.statuses(data), [("claude", "api-review", "conflict"),
                                               ("claude", "notes", "updated")])
        self.assertEqual(data["skills"][0]["reason"], "SKILL.md (locally edited)")
        self.assertEqual(self.dest("SKILL.md").read_text(), "# edited by hand\n")
        self.assertEqual(self.dest("SKILL.md", sid="notes").read_text(),
                         SKILL.format(sid="notes", desc="New."))
        out = run("packs", "sync", "--agent", "claude", *self.R)[1].splitlines()
        self.assertEqual(out[1], EDIT_HINT)

    def test_other_conflicts_leave_the_skill_untouched(self):
        cases = {
            "deleted": (lambda: self.dest("SKILL.md").unlink(), "SKILL.md (locally deleted)"),
            "no marker": (lambda: self.dest(".modsys-managed").unlink(),
                          "not managed by modsys (no .modsys-managed)"),
            "another pack": (lambda: self.dest(".modsys-managed").write_text(
                self.dest(".modsys-managed").read_text().replace('"team"', '"other"')),
                "managed for pack 'other', skill 'api-review'"),
            "unmanaged file": (lambda: (self.dest("notes.md").write_text("mine\n"),
                                        self.src("notes.md").write_text("theirs\n")),
                               "notes.md (exists and is not managed by modsys)")}
        for name, (change, reason) in cases.items():
            with self.subTest(case=name):
                shutil.rmtree(self.root / ".claude", ignore_errors=True)
                self.src("notes.md").unlink(missing_ok=True)
                self.sync()
                change()
                before = self.snapshot()
                data = self.sync(code=1)
                self.assertEqual((data["skills"][0]["status"], data["skills"][0]["reason"]),
                                 ("conflict", reason))
                self.assertEqual(self.snapshot(), before)

    def test_removed_when_no_pack_declares_it(self):
        self.src("references").mkdir()
        self.src("references/api.md").write_text("# API\n")
        self.sync()
        self.dest("extra.txt").write_text("mine\n")
        self.pack("team", [])  # the pack no longer declares the skill
        data = self.sync()
        self.assertEqual(data["skills"], [{
            "agent": "claude", "skill": "api-review", "pack": "team", "version": "0.1.0",
            "source": "pack", "dir": ".claude/skills/api-review", "status": "removed",
            "files": ["SKILL.md", "references/api.md"], "reason": "left unmanaged files: "
                                                                  "extra.txt"}])
        self.assertEqual(sorted(p.name for p in self.dest().rglob("*")), ["extra.txt"])
        self.dest("extra.txt").unlink()
        self.dest().rmdir()
        self.pack("team", ["api-review"])
        self.assertEqual(self.statuses(self.sync()), [("claude", "api-review", "created")])
        shutil.rmtree(self.team)  # the whole pack is gone
        self.assertEqual(self.statuses(self.sync()), [("claude", "api-review", "removed")])
        self.assertFalse(self.dest().exists())

    def test_hand_written_skills_and_local_extras_are_left_alone(self):  # Review Focus
        mine = self.root / ".claude/skills/my-own/SKILL.md"
        mine.parent.mkdir(parents=True)
        mine.write_text("---\nname: my-own\ndescription: Ours.\n---\n")
        self.sync()
        self.dest("cache.json").write_text("{}\n")  # a file the agent keeps next to the skill
        self.src("SKILL.md").write_text(SKILL.format(sid="api-review", desc="Two."))
        data = self.sync(agents=("claude", "claude"))
        self.assertEqual((data["agents"], self.statuses(data)),
                         (["claude"], [("claude", "api-review", "updated")]))
        self.assertEqual(self.dest("cache.json").read_text(), "{}\n")
        self.pack("team", [])
        data = self.sync()
        self.assertEqual((self.statuses(data), data["skills"][0]["reason"]),
                         ([("claude", "api-review", "removed")],
                          "left unmanaged files: cache.json"))
        self.assertEqual(mine.read_text(), "---\nname: my-own\ndescription: Ours.\n---\n")

    def test_an_interrupted_update_resumes(self):
        self.src("old.md").write_text("old\n")
        self.sync()
        self.src("SKILL.md").write_text(SKILL.format(sid="api-review", desc="Resumed."))
        self.src("old.md").unlink()
        self.src("new.md").write_text("new\n")
        shutil.copy2(self.src("SKILL.md"), self.dest("SKILL.md"))  # written before the stop
        shutil.copy2(self.src("new.md"), self.dest("new.md"))
        self.dest("old.md").unlink()
        data = self.sync()
        self.assertEqual((data["skills"][0]["status"], data["skills"][0]["reason"]),
                         ("updated", None))
        marker = json.loads(self.dest(".modsys-managed").read_text())
        self.assertEqual(sorted(marker["files"]), ["SKILL.md", "new.md"])


class SyncFileSafetyTest(SyncRepo):  # P4A-AC-015
    def test_modes_and_bytes_are_kept(self):
        run_sh = self.src("scripts/run.sh")
        run_sh.parent.mkdir()
        run_sh.write_text("#!/bin/sh\necho ok\n")
        os.chmod(run_sh, 0o755)
        os.chmod(self.src("SKILL.md"), 0o644)
        blob = bytes(range(256))
        self.src("assets.bin").write_bytes(blob)
        self.sync()
        self.assertEqual(stat.S_IMODE(self.dest("scripts/run.sh").stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE(self.dest("SKILL.md").stat().st_mode), 0o644)
        self.assertEqual(self.dest("assets.bin").read_bytes(), blob)
        os.chmod(self.dest("scripts/run.sh"), 0o644)  # a lost executable bit is restored
        self.assertEqual(self.sync()["skills"][0]["files"], ["scripts/run.sh"])
        self.assertEqual(stat.S_IMODE(self.dest("scripts/run.sh").stat().st_mode), 0o755)

    def test_generated_and_marker_files_are_not_copied(self):
        for rel in ("__pycache__/x.pyc", "x.pyc", ".DS_Store", ".modsys-managed",
                    ".modsys-ejected", "lib/__pycache__/y.pyc", "lib/y.py"):
            self.src(rel).parent.mkdir(parents=True, exist_ok=True)
            self.src(rel).write_text("x\n")
        self.assertEqual(self.sync()["skills"][0]["files"], ["SKILL.md", "lib/y.py"])
        self.assertEqual(sorted(p.relative_to(self.dest()).as_posix()
                                for p in self.dest().rglob("*") if p.is_file()),
                         [".modsys-managed", "SKILL.md", "lib/y.py"])

    def test_unloadable_sources_are_invalid_and_never_written(self):
        os.symlink("SKILL.md", self.src("link.md"))
        data = self.sync(code=1)
        self.assertEqual((data["skills"][0]["status"], data["skills"][0]["reason"],
                          data["skills"][0]["files"]),
                         ("invalid", "symlink in source: link.md", []))
        self.assertFalse(self.dest().exists())
        self.src("link.md").unlink()
        for text, reason in [("# no front matter\n", "SKILL.md has no front matter (a --- "
                                                     "block at the top, closed by a --- line)"),
                             (SKILL.format(sid="other-name", desc="d"),
                              "SKILL.md name 'other-name' is not the skill id 'api-review'")]:
            with self.subTest(reason=reason):
                self.src("SKILL.md").write_text(text)
                data = self.sync(code=1)
                self.assertEqual((data["skills"][0]["status"], data["skills"][0]["reason"]),
                                 ("invalid", reason))
                self.assertFalse(self.dest().exists())

    def test_an_unwritable_agent_directory_is_a_usage_error(self):  # Review Focus
        (self.root / ".claude").mkdir()
        (self.root / ".claude/skills").write_text("not a directory\n")
        code, out, err = run("packs", "sync", "--agent", "claude", "--json", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("modsys: error: cannot write .claude/skills/api-review: "),
                        err)
        self.assertIn("run packs sync again", err)

    def test_a_first_sync_that_fails_part_way_resumes(self):  # fix wave F2
        self.src("references").mkdir()
        self.src("references/api.md").write_text("# API\n")
        real = skill_sync.copy_file
        for error, code, needle in [
                (OSError(errno.ENOSPC, "No space left on device"), 2,
                 "modsys: error: cannot write .claude/skills/api-review: No space left on device"),
                (KeyboardInterrupt(), 130, "modsys: interrupted\n")]:
            with self.subTest(error=type(error).__name__):
                calls = []

                def the_second_write_fails(src, path):
                    calls.append(path)
                    if len(calls) == 2:
                        raise error
                    real(src, path)

                with mock.patch("modsys.skill_sync.copy_file", side_effect=the_second_write_fails):
                    got, out, err = run("packs", "sync", "--agent", "claude", "--json", *self.R)
                self.assertEqual((got, out, len(calls)), (code, "", 2))
                self.assertTrue(err.startswith(needle), err)
                self.assertFalse(os.path.lexists(self.dest()))  # nothing half-made stays
                self.assertTrue((self.root / ".claude/skills").is_dir())
                self.assertEqual(self.statuses(self.sync()), [("claude", "api-review", "created")])
                shutil.rmtree(self.root / ".claude")

    def test_every_write_stays_inside_the_skill_directory(self):
        outside = self.root / "outside"
        outside.mkdir()
        self.src("references").mkdir()
        self.src("references/api.md").write_text("# API\n")
        self.sync()
        shutil.rmtree(self.dest("references"))
        os.symlink(outside, self.dest("references"))  # a symlink in the way
        self.src("references/api.md").write_text("# API v2\n")
        data = self.sync(code=1)
        self.assertEqual(data["skills"][0]["reason"],
                         "references/api.md (a symlink or directory in the way)")
        self.assertEqual(list(outside.iterdir()), [])
        marker = json.loads(self.dest(".modsys-managed").read_text())
        marker["files"]["../../escape.md"] = sha(b"x")
        self.dest(".modsys-managed").write_text(json.dumps(marker))
        self.dest("references").unlink()
        data = self.sync(code=1)
        self.assertEqual(data["skills"][0]["reason"], ".modsys-managed is not a valid marker")
        self.assertFalse((self.root / ".claude/escape.md").exists())
        written = sorted(p for p in (self.root / ".claude").rglob("*") if p.is_file())
        self.assertTrue(all(self.dest() in p.parents for p in written), written)


class SyncAgentsTest(SyncRepo):  # P4A-AC-016
    def config(self, text: str) -> None:
        (self.root / ".modsys/config.toml").write_text(text, encoding="utf-8")

    def test_the_agents_come_from_flags_or_config(self):
        code, out, err = run("packs", "sync", "--json", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("modsys: error: choose --agent claude, codex, cursor, gemini or copilot "
                      "(repeatable), or set [packs] agents", err)  # P6 D5 (SI-9)
        self.config('[packs]\nagents = ["claude"]\n')
        self.assertEqual(self.statuses(self.sync(agents=())), [("claude", "api-review",
                                                                "created")])
        self.assertFalse((self.root / ".agents").exists())
        data = self.sync(agents=("codex",))  # the flags replace the config list
        self.assertEqual((data["agents"], self.statuses(data)),
                         (["codex"], [("codex", "api-review", "created")]))

    def test_both_agents_in_the_given_order(self):
        self.pack("team", ["api-review", "notes"])
        data = self.sync(agents=("codex", "claude"))
        self.assertEqual(self.statuses(data), [
            ("codex", "api-review", "created"), ("codex", "notes", "created"),
            ("claude", "api-review", "created"), ("claude", "notes", "created")])
        self.assertEqual(data["summary"], {"created": 4, "updated": 0, "unchanged": 0,
                                           "removed": 0, "conflict": 0, "invalid": 0})
        self.assertTrue(self.dest("SKILL.md", agent_dir=".agents/skills").is_file())

    def test_unknown_agents(self):  # P6 D5: cursor is an agent now — windsurf is not
        self.config('[packs]\nagents = ["windsurf"]\n')
        for argv in (("list", "--json"), ("packs", "list", "--json")):
            with self.subTest(argv=argv):
                code, out, err = run(*argv, *self.R)
                self.assertEqual((code, out), (2, ""))
                self.assertIn(".modsys/config.toml: [packs] agents: unknown agent 'windsurf' "
                              "(agents: claude, codex, cursor, gemini, copilot)", err)
        self.config("")
        code, out, err = run("packs", "sync", "--agent", "windsurf", "--json", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("unknown agent 'windsurf' (agents: claude, codex, cursor, gemini, copilot)",
                      err)

    def test_check_and_dry_run(self):
        self.assertEqual(self.statuses(self.sync("--check", code=1)),
                         [("claude", "api-review", "created")])
        self.assertFalse((self.root / ".claude").exists())
        self.sync()
        self.assertTrue(self.sync("--check")["check"])
        self.src("SKILL.md").write_text(SKILL.format(sid="api-review", desc="Changed."))
        self.assertEqual(self.statuses(self.sync("--check", code=1))[0][2], "updated")
        before = self.snapshot()
        self.assertEqual(self.statuses(self.sync("--dry-run"))[0][2], "updated")
        self.assertEqual(self.snapshot(), before)
        self.dest("SKILL.md").write_text("# edited\n")
        before = self.snapshot()
        data = self.sync("--dry-run", code=1)
        self.assertEqual((data["dry_run"], data["skills"][0]["status"]), (True, "conflict"))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.statuses(self.sync("--check", code=1))[0][2], "conflict")
        code, out, err = run("packs", "sync", "--agent", "claude", "--check", "--dry-run",
                             "--json", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("--check and --dry-run cannot be combined", err)

    def test_a_removed_skill_makes_check_fail(self):
        self.sync()
        self.pack("team", [])
        self.assertEqual(self.statuses(self.sync("--check", code=1)),
                         [("claude", "api-review", "removed")])
        self.assertTrue(self.dest("SKILL.md").exists())

    def test_mirrored_agent_directories_are_written_once(self):
        (self.root / ".claude/skills").mkdir(parents=True)
        (self.root / ".agents").mkdir()
        os.symlink("../.claude/skills", self.root / ".agents/skills")
        data = self.sync(agents=("claude", "codex"))
        self.assertEqual([(r["agent"], r["status"], r.get("same_as")) for r in data["skills"]],
                         [("claude", "created", None), ("codex", "created", "claude")])
        self.assertEqual(data["skills"][1]["dir"], ".agents/skills/api-review")
        self.assertTrue((self.root / ".agents/skills").is_symlink())
        data = self.sync(agents=("claude", "codex"))
        self.assertEqual([r["status"] for r in data["skills"]], ["unchanged", "unchanged"])
        out = run("packs", "sync", "--agent", "claude", "--agent", "codex", *self.R)[1]
        self.assertIn("unchanged  codex   .agents/skills/api-review  (team 0.1.0)  same "
                      "directory as claude", out)

    def test_the_higher_precedence_pack_is_materialized(self):  # P4A-AC-007
        self.pack("a", ["api-review"], priority=10)
        self.pack("b", ["api-review"], priority=60)
        self.sync()
        marker = json.loads(self.dest(".modsys-managed").read_text())
        self.assertEqual(marker["pack"], "a")
        self.assertEqual(self.dest("SKILL.md").read_bytes(),
                         self.src("SKILL.md", pack_id="a").read_bytes())

    def test_text_output(self):
        out = run("packs", "sync", "--agent", "claude", "--agent", "codex", *self.R)[1]
        self.assertEqual(out.splitlines(), [
            "created    claude  .claude/skills/api-review  (team 0.1.0)",
            "created    codex   .agents/skills/api-review  (team 0.1.0)",
            "note: GitHub Copilot reads both .claude/skills and .agents/skills, so it sees each "
            "skill twice — where Copilot works, sync only one of the two directories (Copilot "
            "reads either)",  # P6 D5 (SI-20)
            "packs sync: 2 created, 0 updated, 0 unchanged, 0 removed, 0 conflict, 0 invalid"])
        out = run("packs", "sync", "--agent", "claude", "--check", *self.R)[1]
        self.assertEqual(out.splitlines()[-1], "packs sync --check: 0 created, 0 updated, "
                                               "1 unchanged, 0 removed, 0 conflict, 0 invalid: "
                                               "in sync")
        shutil.rmtree(self.team)
        shutil.rmtree(self.root / ".claude")
        shutil.rmtree(self.root / ".agents")
        self.assertEqual(run("packs", "sync", "--agent", "claude", *self.R)[1].splitlines()[0],
                         "no pack skills (add one: modsys packs new ID --skill NAME)")


class SyncHintsTest(SyncRepo):  # fix wave F3: each conflict reason gets a hint that works
    def text(self, *argv) -> list[str]:
        return run("packs", "sync", "--agent", "claude", *argv, *self.R)[1].splitlines()

    def test_a_managed_file_edited_or_deleted(self):
        self.sync()
        self.dest("SKILL.md").write_text("# edited\n")
        self.assertEqual(self.text()[1], EDIT_HINT)
        self.src("notes.md").write_text("theirs\n")
        self.dest("notes.md").write_text("mine\n")  # joined with a move problem: the edit wins
        self.assertEqual(self.text()[1], EDIT_HINT.replace(
            "SKILL.md (locally edited)", "SKILL.md (locally edited); notes.md (exists and is not "
                                         "managed by modsys)"))
        self.assertEqual(run("eject", "api-review", *self.R)[0], 0)  # the source is the copy
        self.dest("SKILL.md").unlink()
        self.assertEqual(self.text()[1], "  SKILL.md (locally deleted); notes.md (exists and is "
                                         "not managed by modsys) — revert it (git checkout -- "
                                         ".claude/skills/api-review) and sync again, or keep the "
                                         "change: copy it into .modsys/overrides/skills/"
                                         "api-review, then packs sync")

    def test_something_in_the_way(self):
        self.sync()
        self.src("notes.md").write_text("theirs\n")
        self.dest("notes.md").write_text("mine\n")
        self.assertEqual(self.text()[1], "  notes.md (exists and is not managed by modsys) — "
                                         "move it away, then sync again")
        shutil.rmtree(self.root / ".claude")
        (self.root / "elsewhere").mkdir()
        self.dest().parent.mkdir(parents=True)
        os.symlink(self.root / "elsewhere", self.dest())
        self.assertEqual(self.sync(code=1)["skills"][0]["reason"], "the destination is a symlink")
        self.assertEqual(self.text()[1], "  the destination is a symlink — move it away, then "
                                         "sync again")
        self.dest().unlink()
        self.dest().write_text("a file\n")
        self.assertEqual(self.text()[1], "  the destination is not a directory — move it away, "
                                         "then sync again")

    def test_a_directory_that_is_not_ours(self):
        self.dest().mkdir(parents=True)
        self.dest("SKILL.md").write_text("mine\n")
        self.assertEqual(self.text()[1], "  not managed by modsys (no .modsys-managed) — a skill "
                                         "written by hand: move or rename it, then sync again")
        shutil.rmtree(self.root / ".claude")
        self.sync()
        marker = self.dest(".modsys-managed")
        marker.write_text(marker.read_text().replace('"team"', '"other"'))
        self.assertEqual(self.text()[1], "  managed for pack 'other', skill 'api-review' — it "
                                         "belongs to pack 'other': remove it if that pack is "
                                         "gone, or rename one of the skills")
        marker.write_text("{}\n")
        self.assertEqual(self.text()[1], "  .modsys-managed is not a valid marker — restore the "
                                         "marker (git checkout -- .claude/skills/api-review) or "
                                         "move the directory away, then sync again")

    def test_orphans(self):
        self.sync()
        self.pack("team", [])
        self.dest("SKILL.md").write_text("# edited\n")
        self.assertEqual(self.text()[:2], [
            "conflict   claude  .claude/skills/api-review  (team 0.1.0)",
            "  SKILL.md (locally edited; not removed) — revert the edit, or delete the directory "
            "if the skill is no longer wanted"])
        self.dest(".modsys-managed").write_text("{}\n")
        self.assertEqual(self.text()[:2], [
            "conflict   claude  .claude/skills/api-review  (no valid marker)",
            "  .modsys-managed is not a valid marker (not removed) — restore the marker (git "
            "checkout -- .claude/skills/api-review) or delete the directory"])

    def test_check_says_what_would_fix_it(self):
        self.pack("team", ["api-review", "notes"])
        self.sync()
        mine = self.dest("SKILL.md").read_text()
        self.dest("SKILL.md").write_text("# edited\n")
        counts = ("packs sync --check: 0 created, {} updated, {} unchanged, 0 removed, "
                  "{} conflict, 0 invalid: ")
        blocked = "blocked — resolve the conflict / invalid rows above"
        self.assertEqual(self.text("--check")[-1], counts.format(0, 1, 1) + blocked)
        self.src("SKILL.md", sid="notes").write_text(SKILL.format(sid="notes", desc="New."))
        self.assertEqual(self.text("--check")[-1], counts.format(1, 0, 1)
                         + "stale — run modsys packs sync --agent claude; " + blocked)
        self.dest("SKILL.md").write_text(mine)
        self.assertEqual(self.text("--check")[-1], counts.format(1, 1, 0)
                         + "stale — run modsys packs sync --agent claude")

    def test_invalid_sources(self):
        self.src("SKILL.md").write_text("# no front matter\n")
        self.assertEqual(self.text()[1], "  SKILL.md has no front matter (a --- block at the top, "
                                         "closed by a --- line) — fix the skill in its pack "
                                         "(plain modsys lint reports it as MS062)")


class PacksConfigAndContractTest(SyncRepo):  # D7 [packs], D10 init starter, P4A-AC-023
    def test_the_packs_section(self):
        (self.root / ".modsys/config.toml").write_text('[packs]\nagents = "claude"\n')
        code, out, err = run("list", "--json", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("[packs] agents: expected a list of strings", err)
        text = starter_config("single")
        self.assertEqual(tomllib.loads(text), {"packs": {"builtin": ["core"]}})  # P4b D8
        self.assertIn('[packs]\nbuiltin = ["core"]                   # or ["core", "ui", "qa"]\n'
                      '# agents = ["claude", "codex"]\n', text)
        self.assertIn("modsys packs new ID --role NAME --skill NAME", text)

    def test_usage_errors(self):
        for argv, needle in [(("sync", "team", "--agent", "claude"), "packs sync takes no ID"),
                             (("sync", "--agent", "claude", "--role", "x"),
                              "packs sync takes no --role"),
                             (("new", "t", "--agent", "claude"), "packs new takes no --agent"),
                             (("list", "--check"), "packs list takes no --check")]:
            with self.subTest(argv=argv):
                code, out, err = run("packs", *argv, "--json", *self.R)
                self.assertEqual((code, out), (2, ""))
                self.assertIn(needle, err)

    def test_garbage_config_and_interrupt(self):
        (self.root / ".modsys/config.toml").write_text("code_map = 5\n")
        code, out, err = run("packs", "sync", "--agent", "claude", "--json", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("modsys: error: "), err)
        (self.root / ".modsys/config.toml").unlink()
        with mock.patch("modsys.packs_cmd.apply_plan", side_effect=KeyboardInterrupt):
            self.assertEqual(run("packs", "sync", "--agent", "claude", *self.R),
                             (130, "", "modsys: interrupted\n"))


class AgentsFromManagedCopiesTest(SyncRepo):  # P5A-AC-009 (D0d)
    REFUSAL = ("modsys: error: choose --agent claude, codex, cursor, gemini or copilot "
               "(repeatable), or set [packs] agents\n")  # P6 D5 (SI-9): the five agents

    def agents(self, *argv) -> list[str]:
        code, env, err = run_json("packs", "sync", *argv, *self.R)
        self.assertEqual((code, err), (0, ""), env)
        return env["data"]["agents"]

    def refused(self) -> None:
        before = self.snapshot(".claude"), self.snapshot(".agents")
        code, out, err = run("packs", "sync", "--json", *self.R)
        self.assertEqual((code, out, err), (2, "", self.REFUSAL))
        self.assertEqual((self.snapshot(".claude"), self.snapshot(".agents")), before)

    def test_the_decision_table(self):
        self.refused()  # no marker anywhere
        self.sync(agents=("codex",))
        self.assertEqual(self.agents(), ["codex"])
        (self.root / ".modsys/config.toml").write_text('[packs]\nagents = ["claude"]\n')
        self.assertEqual(self.agents(), ["claude"])  # the config wins over the markers
        self.assertEqual(self.agents("--agent", "codex"), ["codex"])  # the flags win
        (self.root / ".modsys/config.toml").unlink()
        self.assertEqual(self.agents(), ["claude", "codex"])  # both hold markers now
        shutil.rmtree(self.root / ".agents")
        self.assertEqual(self.agents("--check"), ["claude"])
        self.assertEqual(self.agents("--dry-run"), ["claude"])

    def test_only_valid_markers_count(self):
        self.sync(agents=("codex",))
        (self.root / ".claude/skills/notes").mkdir(parents=True)
        (self.root / ".claude/skills/notes/SKILL.md").write_text("# by hand\n")
        self.assertEqual(self.agents(), ["codex"])
        self.dest(".modsys-managed", agent_dir=".agents/skills").write_text("{not json")
        (self.root / ".claude/skills/notes/.modsys-managed").write_text("[]")
        self.refused()

    def test_mirrored_agent_directories(self):
        self.sync()
        (self.root / ".agents").mkdir()
        os.symlink("../.claude/skills", self.root / ".agents/skills")
        code, env, err = run_json("packs", "sync", *self.R)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(env["data"]["agents"], ["claude", "codex"])
        self.assertEqual([(r["agent"], r.get("same_as")) for r in env["data"]["skills"]],
                         [("claude", None), ("codex", "claude")])


if __name__ == "__main__":
    unittest.main()
