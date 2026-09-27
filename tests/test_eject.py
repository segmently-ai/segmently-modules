"""`modsys eject` (D8): a repo-owned copy of a pack skill that `packs sync` materializes and the
pack never overwrites; `eject --diff` and lint MS063 when the pack moves on."""
import hashlib
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from modsys.skills import is_behind, pack_skills, read_ejected
from tests.helpers import copy_fixture, init_git, run, run_json

SKILL = "---\nname: api-review\ndescription: {desc}\n---\n\n# api-review\n"


class EjectRepo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        self.R = ("--root", str(self.root))
        self.set_pack("0.1.0", "Reviews API changes.")
        self.ejected = self.root / ".modsys/overrides/skills/api-review"

    def tearDown(self):
        self._tmp.cleanup()

    def set_pack(self, version: str, desc: str) -> None:
        team = self.root / ".modsys/packs/team"
        (team / "skills/api-review").mkdir(parents=True, exist_ok=True)
        (team / "pack.toml").write_text(f'id = "team"\nversion = "{version}"\n'
                                        '[skills.api-review]\npath = "skills/api-review"\n')
        (team / "skills/api-review/SKILL.md").write_text(SKILL.format(desc=desc))

    def upstream(self, rel: str = "SKILL.md"):
        return self.root / ".modsys/packs/team/skills/api-review" / rel

    def ok(self, *argv, code=0) -> dict:
        got, env, err = run_json(*argv, *self.R)
        self.assertEqual((got, err), (code, ""), env)
        return env["data"]

    def sync(self, code=0) -> list[tuple]:
        data = self.ok("packs", "sync", "--agent", "claude", "--agent", "codex", code=code)
        return [(r["agent"], r["status"], r["source"]) for r in data["skills"]]

    def agent_text(self, agent_dir=".claude/skills") -> str:
        return (self.root / agent_dir / "api-review/SKILL.md").read_text()

    def ms063(self, *argv) -> list[tuple]:
        data = self.ok("lint", "--fail-on", "never", *argv)
        return [(f["severity"], f["message"], f["path"]) for f in data["findings"]
                if f["code"] == "MS063"]


class EjectTest(EjectRepo):  # P4A-AC-017
    def test_eject_then_sync_from_the_copy(self):
        self.sync()
        before = {p: p.read_bytes() for p in (self.root / ".claude").rglob("*") if p.is_file()}
        data = self.ok("eject", "api-review")
        self.assertEqual(data, {"skill": "api-review", "pack": "team", "version": "0.1.0",
                                "dir": ".modsys/overrides/skills/api-review",
                                "files": ["SKILL.md"], "dry_run": False})
        self.assertEqual((self.ejected / "SKILL.md").read_bytes(), self.upstream().read_bytes())
        digest = hashlib.sha256(self.upstream().read_bytes()).hexdigest()
        self.assertEqual((self.ejected / ".modsys-ejected").read_text(), json.dumps(
            {"schema": "modsys.ejected/1", "skill": "api-review", "pack": "team",
             "version": "0.1.0", "files": {"SKILL.md": digest}}, indent=2, sort_keys=True)
            + "\n")
        self.assertEqual({p: p.read_bytes() for p in (self.root / ".claude").rglob("*")
                          if p.is_file()}, before)  # eject never touches the agents' copies
        self.assertEqual(self.sync(), [("claude", "updated", "ejected"),
                                       ("codex", "updated", "ejected")])
        self.assertEqual(self.ok("packs", "list")[1]["skills"][0]["ejected"], True)

    def test_the_copy_wins_over_every_pack_version(self):
        self.ok("eject", "api-review")
        (self.ejected / "SKILL.md").write_text(SKILL.format(desc="Our own review steps."))
        self.assertEqual([s for _, s, _ in self.sync()], ["created", "created"])
        for agent_dir in (".claude/skills", ".agents/skills"):
            self.assertIn("Our own review steps.", self.agent_text(agent_dir))
        self.set_pack("0.2.0", "Upstream version two.")
        self.assertEqual([s for _, s, _ in self.sync()], ["unchanged", "unchanged"])
        self.assertIn("Our own review steps.", self.agent_text())

    def test_back_to_the_pack(self):
        self.ok("eject", "api-review")
        self.sync()
        shutil.rmtree(self.ejected)
        self.assertEqual(self.sync(), [("claude", "updated", "pack"), ("codex", "updated", "pack")])
        self.assertEqual(self.agent_text(), self.upstream().read_text())

    def test_refusals_write_nothing(self):
        self.ok("eject", "api-review")
        os.symlink("SKILL.md", self.upstream("link.md"))
        (self.root / ".modsys/packs/team/pack.toml").write_text(
            'id = "team"\n[skills.api-review]\npath = "skills/api-review"\n'
            '[skills.broken]\npath = "skills/api-review"\n')
        for argv, needle in [
                (("api-review",), "skill 'api-review' is already ejected: "
                                  ".modsys/overrides/skills/api-review"),
                (("nosuch",), "unknown skill 'nosuch' (pack skills: api-review, broken)"),
                (("broken",), "skill 'broken' of pack 'team' is not loadable: symlink in "
                              "source: link.md (lint MS062); nothing written")]:
            with self.subTest(argv=argv):
                code, out, err = run("eject", *argv, "--json", *self.R)
                self.assertEqual((code, out), (2, ""))
                self.assertIn(f"modsys: error: {needle}", err)
        self.assertEqual(sorted(p.name for p in self.ejected.parent.iterdir()), ["api-review"])

    def test_dry_run_and_text(self):
        data = self.ok("eject", "api-review", "--dry-run")
        self.assertEqual((data["dry_run"], data["files"]), (True, ["SKILL.md"]))
        self.assertFalse(self.ejected.exists())
        out = run("eject", "api-review", "--dry-run", *self.R)[1].splitlines()
        self.assertEqual(out, ["would eject  api-review  (team 0.1.0) -> "
                               ".modsys/overrides/skills/api-review", "  SKILL.md",
                               "next: modsys eject api-review (to do it)"])
        out = run("eject", "api-review", *self.R)[1].splitlines()
        self.assertEqual(out, ["ejected  api-review  (team 0.1.0) -> "
                               ".modsys/overrides/skills/api-review", "  SKILL.md",
                               "edit the copy: packs sync materializes the skill from it, and "
                               "the pack never overwrites it",
                               "next: modsys packs sync --agent claude --agent codex (or set "
                               "[packs] agents once)"])
        out = run("packs", "sync", "--agent", "claude", *self.R)[1].splitlines()
        self.assertEqual(out[0], "created    claude  .claude/skills/api-review  (team 0.1.0, "
                                 "ejected copy)")

    def test_the_next_line_works_as_printed(self):  # fix wave F6
        (self.root / ".modsys/config.toml").write_text('[packs]\nagents = ["claude"]\n')
        out = run("eject", "api-review", *self.R)[1].splitlines()
        self.assertEqual(out[-1], "next: modsys packs sync")
        code, _, err = run("packs", "sync", *self.R)  # the line as printed
        self.assertEqual((code, err), (0, ""))

    def test_the_conflict_hint_names_eject(self):
        self.sync()
        (self.root / ".claude/skills/api-review/SKILL.md").write_text("# edited\n")
        out = run("packs", "sync", "--agent", "claude", *self.R)[1].splitlines()
        self.assertEqual(out[1], "  SKILL.md (locally edited) — revert it (git checkout -- "
                                 ".claude/skills/api-review) and sync again, or keep the change: "
                                 "modsys eject api-review, copy the change into "
                                 ".modsys/overrides/skills/api-review, then packs sync")


class EjectedCopyLoadableTest(EjectRepo):  # fix wave F4: lint checks the copy packs sync reads
    def ms062(self) -> list[tuple]:
        data = self.ok("lint", "--fail-on", "never")
        return [(f["severity"], f["module"], f["message"], f["path"]) for f in data["findings"]
                if f["code"] == "MS062"]

    def sync_text(self) -> list[str]:
        return run("packs", "sync", "--agent", "claude", *self.R)[1].splitlines()

    def test_an_ejected_copy_agents_cannot_load(self):
        self.ok("eject", "api-review")
        self.assertEqual(self.ms062(), [])  # a valid ejected copy
        (self.ejected / "SKILL.md").write_text("---\nname: api_review\ndescription: Ours.\n---\n")
        self.assertEqual(self.ms062(), [(
            "error", "*", "ejected skill 'api-review' (.modsys/overrides/skills/api-review) is not "
                          "loadable by agents: SKILL.md name 'api_review' is not the skill id "
                          "'api-review'", ".modsys/overrides/skills/api-review/SKILL.md")])
        self.assertEqual(run("lint", "--fail-on", "error", *self.R)[0], 1)
        self.assertEqual(self.sync(code=1), [("claude", "invalid", "ejected"),
                                             ("codex", "invalid", "ejected")])
        self.assertEqual(self.sync_text()[1], "  SKILL.md name 'api_review' is not the skill id "
                                              "'api-review' — fix the ejected copy "
                                              ".modsys/overrides/skills/api-review (plain modsys "
                                              "lint reports it as MS062)")
        (self.ejected / "SKILL.md").unlink()
        self.assertEqual([f[2:] for f in self.ms062()], [(
            "ejected skill 'api-review' (.modsys/overrides/skills/api-review) is not loadable by "
            "agents: no SKILL.md", ".modsys/overrides/skills/api-review")])

    def test_an_ejected_copy_without_its_record(self):
        self.ok("eject", "api-review")
        (self.ejected / ".modsys-ejected").write_text("{}")
        self.assertEqual(self.ms062(), [])  # MS063 reports it
        self.assertEqual(self.sync_text()[1], "  the ejected copy .modsys/overrides/skills/"
                                              "api-review has no valid .modsys-ejected record — "
                                              "fix the ejected copy .modsys/overrides/skills/"
                                              "api-review (plain modsys lint reports it as MS063)")


class EjectDiffTest(EjectRepo):  # P4A-AC-018
    def diff(self) -> dict:
        return self.ok("eject", "api-review", "--diff")

    def test_nothing_changed(self):
        self.ok("eject", "api-review")
        self.assertEqual(self.diff(), {"skill": "api-review", "pack": "team",
                                       "ejected_from": "0.1.0", "upstream_version": "0.1.0",
                                       "behind": False,
                                       "files": [{"path": "SKILL.md", "status": "same"}],
                                       "diff": ""})
        self.assertEqual(self.ms063(), [])

    def test_an_edited_copy_is_not_behind(self):
        self.ok("eject", "api-review")
        (self.ejected / "SKILL.md").write_text(SKILL.format(desc="Ours."))
        data = self.diff()
        self.assertEqual((data["behind"], data["files"]), (False, [{"path": "SKILL.md",
                                                                    "status": "changed"}]))
        self.assertIn("--- upstream/SKILL.md\n+++ ejected/SKILL.md\n", data["diff"])
        self.assertIn("-description: Reviews API changes.\n+description: Ours.\n", data["diff"])
        self.assertEqual(self.ms063(), [])

    def test_behind_by_version_or_by_files(self):
        self.ok("eject", "api-review")
        self.set_pack("0.2.0", "Reviews API changes.")  # same files, new version
        self.assertTrue(self.diff()["behind"])
        self.assertEqual(self.ms063(), [(
            "warning", "ejected skill 'api-review' is behind pack 'team' (ejected from 0.1.0, "
                       "pack is now 0.2.0) — review: modsys eject api-review --diff",
            ".modsys/overrides/skills/api-review")])
        self.set_pack("0.1.0", "Reviews API changes, version two.")  # new files, same version
        self.assertTrue(self.diff()["behind"])
        self.assertEqual(len(self.ms063()), 1)

    def test_files_on_one_side_and_binary_files(self):
        self.ok("eject", "api-review")
        self.upstream("references").mkdir()
        self.upstream("references/x.md").write_text("upstream only\n")
        (self.ejected / "local.md").write_text("ours only\n")
        self.upstream("logo.bin").write_bytes(b"\x00\x01")
        (self.ejected / "logo.bin").write_bytes(b"\x00\x02")
        data = self.diff()
        self.assertEqual(data["files"], [
            {"path": "SKILL.md", "status": "same"}, {"path": "local.md", "status": "only-ejected"},
            {"path": "logo.bin", "status": "changed"},
            {"path": "references/x.md", "status": "only-upstream"}])
        self.assertIn("Binary files upstream/logo.bin and ejected/logo.bin differ\n", data["diff"])
        self.assertNotIn("\x00", data["diff"])
        self.assertIn("+++ ejected/local.md\n", data["diff"])
        self.assertIn("--- upstream/references/x.md\n", data["diff"])

    def test_a_skill_no_pack_declares_any_more(self):
        self.ok("eject", "api-review")
        shutil.rmtree(self.root / ".modsys/packs/team")
        self.assertEqual(self.ms063(), [(
            "info", "ejected skill 'api-review': pack 'team' no longer declares it; the ejected "
                    "copy is its only source", ".modsys/overrides/skills/api-review")])
        rows = self.ok("packs", "sync", "--agent", "claude")["skills"]
        self.assertEqual([(r["status"], r["source"], r["pack"]) for r in rows],
                         [("created", "ejected", "team")])
        code, out, err = run("eject", "api-review", "--diff", "--json", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("pack 'team' no longer declares skill 'api-review'", err)

    def test_refusals_and_lint_changed(self):
        code, out, err = run("eject", "other", "--diff", "--json", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("skill 'other' is not ejected (eject it first: modsys eject other)", err)
        self.ok("eject", "api-review")
        code, _, err = run("eject", "api-review", "--diff", "--dry-run", *self.R)
        self.assertEqual(code, 2)
        self.assertIn("--dry-run applies to eject without --diff", err)
        (self.ejected / ".modsys-ejected").write_text("{}")
        self.assertEqual([m for _, m, _ in self.ms063()],
                         ["ejected skill 'api-review' has no valid .modsys-ejected record — "
                          "eject it again or restore the file"])
        self.assertEqual(self.sync(code=1)[0][1], "invalid")
        self.set_pack("0.2.0", "Changed.")
        init_git(self.root)
        (self.root / "modules/catalog/MODULE.md").write_text("# Catalog\n\nChanged.\n")
        self.assertEqual(self.ms063("--changed", "--base", "HEAD"), [])

    def test_diff_and_lint_share_one_behind_rule(self):  # fix wave F1
        self.ok("eject", "api-review")
        digest = hashlib.sha256(self.upstream().read_bytes()).hexdigest()
        with mock.patch("modsys.eject_cmd.is_behind", return_value=True) as rule:
            self.assertTrue(self.diff()["behind"])
        rule.assert_called_once()
        self.assertEqual(rule.call_args.kwargs["upstream"], {"SKILL.md": digest})
        skill = pack_skills(self.root / ".modsys")["api-review"]
        record = read_ejected(self.ejected)
        with mock.patch("modsys.skills.file_hashes", side_effect=AssertionError("hashed twice")):
            self.assertFalse(is_behind(skill, record, upstream={"SKILL.md": digest}))
            self.assertTrue(is_behind(skill, record, upstream={}))
        self.assertFalse(is_behind(skill, record))  # hashes the pack's files itself

    def test_text_output(self):
        self.ok("eject", "api-review")
        self.set_pack("0.2.0", "Version two.")
        out = run("eject", "api-review", "--diff", *self.R)[1].splitlines()
        self.assertEqual(out[:4], ["api-review: ejected from team 0.1.0; the pack is now 0.2.0 "
                                   "— behind", "changed        SKILL.md",
                                   "--- upstream/SKILL.md", "+++ ejected/SKILL.md"])


class EjectContractTest(EjectRepo):  # P4A-AC-023
    def test_garbage_config_and_interrupt(self):
        (self.root / ".modsys/config.toml").write_text("code_map = 5\n")
        for argv in (("api-review",), ("api-review", "--diff")):
            with self.subTest(argv=argv):
                code, out, err = run("eject", *argv, "--json", *self.R)
                self.assertEqual((code, out), (2, ""))
                self.assertTrue(err.startswith("modsys: error: "), err)
        (self.root / ".modsys/config.toml").unlink()
        with mock.patch("modsys.eject_cmd.copy_file", side_effect=KeyboardInterrupt):
            self.assertEqual(run("eject", "api-review", *self.R),
                             (130, "", "modsys: interrupted\n"))
        self.assertFalse(self.ejected.exists())  # no half-made copy
        self.ok("eject", "api-review")
        with mock.patch("modsys.eject_cmd.file_hashes", side_effect=KeyboardInterrupt):
            self.assertEqual(run("eject", "api-review", "--diff", *self.R),
                             (130, "", "modsys: interrupted\n"))


if __name__ == "__main__":
    unittest.main()
