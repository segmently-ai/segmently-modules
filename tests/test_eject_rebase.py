"""`modsys eject SKILL --rebase` (D1): the MS063 acknowledge path — after a team took what it
wants from the pack by hand, the `.modsys-ejected` record takes the declaring pack's current
pack, version and file hashes; the ejected files are never touched."""
import hashlib
import json
import os
import shutil
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import run, run_json
from tests.test_builtin_packs import FakeBuiltins
from tests.test_eject import SKILL, EjectRepo


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RebaseRepo(EjectRepo):
    def setUp(self):
        super().setUp()
        self.upstream("notes.md").write_text("upstream notes\n")
        self.ok("eject", "api-review")
        (self.ejected / "SKILL.md").write_text(SKILL.format(desc="Our own review steps."))
        self.record = self.ejected / ".modsys-ejected"

    def copy_files(self) -> dict:
        return {p.name: p.read_bytes() for p in self.ejected.iterdir()
                if p.name != ".modsys-ejected"}

    def rebase(self, *argv) -> dict:
        got, env, err = run_json("eject", "api-review", "--rebase", *argv, *self.R)
        self.assertEqual((got, err, env["schema"]), (0, "", "modsys.eject/1"))
        return env["data"]

    def pack_hashes(self) -> dict:
        base = self.upstream("")
        return {p.relative_to(base).as_posix(): sha(p) for p in sorted(base.rglob("*"))
                if p.is_file()}

    def assert_rebased(self, data: dict, before: dict) -> None:
        record = json.loads(self.record.read_text())
        self.assertEqual(self.record.read_text(), json.dumps(record, indent=2, sort_keys=True)
                         + "\n")
        self.assertEqual((record["schema"], record["skill"]), ("modsys.ejected/1", "api-review"))
        self.assertEqual((record["pack"], record["version"]),
                         (data["rebased_to"]["pack"], data["rebased_to"]["version"]))
        self.assertEqual(self.copy_files(), before)  # the ejected files are never touched
        self.assertEqual([p.name for p in self.ejected.iterdir() if p.name.endswith(".tmp")], [])
        diff = self.ok("eject", "api-review", "--diff")
        self.assertEqual((diff["behind"], diff["reason"]), (False, None))
        self.assertEqual(self.ms063(), [])
        stamp = (self.record.read_bytes(), self.record.stat().st_mtime_ns)
        again = self.rebase()
        self.assertEqual((again["files_changed"], again["rebased_from"], again["rebased_to"]),
                         (0, data["rebased_to"], data["rebased_to"]))
        self.assertEqual((self.record.read_bytes(), self.record.stat().st_mtime_ns), stamp)


class RebaseTransitionsTest(RebaseRepo):  # P5A-AC-013
    def test_a_new_version_with_a_changed_skill(self):
        self.set_pack("0.2.0", "Reviews API changes, the new way.")
        before = self.copy_files()
        data = self.rebase()
        self.assertEqual(data, {"skill": "api-review", "pack": "team",
                                "rebased_from": {"pack": "team", "version": "0.1.0"},
                                "rebased_to": {"pack": "team", "version": "0.2.0"},
                                "files_changed": 1, "dry_run": False})
        self.assertEqual(json.loads(self.record.read_text())["files"], self.pack_hashes())
        self.assert_rebased(data, before)
        out = run("eject", "api-review", "--rebase", "--dry-run", *self.R)[1]
        self.assertIn("nothing to rebase", out)

    def test_files_added_or_removed_upstream(self):
        self.upstream("references").mkdir()
        self.upstream("references/x.md").write_text("x\n")
        before = self.copy_files()
        data = self.rebase()
        self.assertEqual(data["files_changed"], 1)
        self.assertIn("references/x.md", json.loads(self.record.read_text())["files"])
        self.assert_rebased(data, before)
        self.upstream("notes.md").unlink()
        data = self.rebase()
        self.assertEqual(data["files_changed"], 1)
        self.assertNotIn("notes.md", json.loads(self.record.read_text())["files"])
        self.assert_rebased(data, before)

    def test_another_pack_declares_the_skill_now(self):
        team = self.root / ".modsys/packs/team"
        team.rename(team.with_name("team2"))
        toml = team.with_name("team2") / "pack.toml"
        toml.write_text(toml.read_text().replace('id = "team"', 'id = "team2"'))
        before = self.copy_files()
        data = self.rebase()
        self.assertEqual((data["rebased_from"]["pack"], data["rebased_to"]["pack"],
                          data["files_changed"]), ("team", "team2", 0))
        self.assert_rebased(data, before)

    def test_a_version_alone(self):
        self.set_pack("0.2.0", "Reviews API changes.")
        before = self.copy_files()
        data = self.rebase()
        self.assertEqual((data["files_changed"], data["rebased_to"]["version"]), (0, "0.2.0"))
        self.assert_rebased(data, before)
        out = run("eject", "api-review", "--diff", *self.R)[1]
        self.assertNotIn("next:", out)

    def test_nothing_moved_is_a_no_op(self):
        stamp = (self.record.read_bytes(), self.record.stat().st_mtime_ns)
        data = self.rebase()
        self.assertEqual((data["files_changed"], data["rebased_from"], data["rebased_to"]),
                         (0, {"pack": "team", "version": "0.1.0"},
                          {"pack": "team", "version": "0.1.0"}))
        self.assertEqual((self.record.read_bytes(), self.record.stat().st_mtime_ns), stamp)

    def test_dry_run_and_text(self):
        self.set_pack("0.2.0", "Reviews API changes, the new way.")
        stamp = (self.record.read_bytes(), self.record.stat().st_mtime_ns)
        data = self.rebase("--dry-run")
        self.assertEqual((data["files_changed"], data["dry_run"]), (1, True))
        self.assertEqual((self.record.read_bytes(), self.record.stat().st_mtime_ns), stamp)
        self.assertEqual(run("eject", "api-review", "--rebase", "--dry-run", *self.R)[1],
                         "would rebase  api-review: team 0.1.0 -> team 0.2.0 (1 file(s) changed "
                         "in the record; the ejected files are unchanged)\n")
        self.assertEqual(run("eject", "api-review", "--rebase", *self.R)[1],
                         "rebased  api-review: team 0.1.0 -> team 0.2.0 (1 file(s) changed in "
                         "the record; the ejected files are unchanged)\n")

    def test_the_diff_points_at_rebase(self):
        self.set_pack("0.2.0", "Reviews API changes, the new way.")
        out = run("eject", "api-review", "--diff", *self.R)[1].splitlines()
        self.assertEqual(out[-1], "next: take what you want by hand, then modsys eject "
                                  "api-review --rebase")


class BuiltinRebaseTest(FakeBuiltins):  # P5A-AC-013: a built-in pack, the engine moved on
    def test_the_engine_version(self):
        self.enable("core")
        self.ok("eject", "notes")
        record = self.root / ".modsys/overrides/skills/notes/.modsys-ejected"
        with mock.patch("modsys.config.__version__", "99.0.0"):
            data = self.ok("eject", "notes", "--rebase")
        self.assertEqual((data["files_changed"], data["rebased_to"]),
                         (0, {"pack": "core", "version": "99.0.0"}))
        self.assertEqual(json.loads(record.read_text())["version"], "99.0.0")


class RebaseRefusalsTest(RebaseRepo):  # P5A-AC-014
    def refused(self, *argv, skill: str = "api-review") -> str:
        state = {p: p.read_bytes() for p in self.ejected.rglob("*") if p.is_file()} \
            if self.ejected.exists() else {}
        code, out, err = run("eject", skill, "--rebase", *argv, "--json", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("modsys: error: "), err)
        self.assertEqual({p: p.read_bytes() for p in self.ejected.rglob("*") if p.is_file()}
                         if self.ejected.exists() else {}, state)
        return err

    def test_the_decision_table(self):
        self.assertIn("skill 'nosuch' is not ejected (eject it first: modsys eject nosuch)",
                      self.refused(skill="nosuch"))
        err = self.refused("--diff")
        self.assertIn("--rebase and --diff cannot be combined", err)
        self.record.write_text("{not json")
        self.assertIn(".modsys/overrides/skills/api-review has no valid .modsys-ejected record — "
                      "eject it again or restore the file", self.refused())
        self.record.unlink()
        self.assertIn("no valid .modsys-ejected record", self.refused())
        shutil.rmtree(self.ejected)
        self.assertIn("skill 'api-review' is not ejected (eject it first: modsys eject "
                      "api-review)", self.refused())
        self.ok("eject", "api-review")
        shutil.rmtree(self.root / ".modsys/packs/team")
        self.assertIn("pack 'team' no longer declares skill 'api-review' — the ejected copy "
                      ".modsys/overrides/skills/api-review is its only source (nothing to "
                      "rebase onto)", self.refused())

    @unittest.skipIf(os.geteuid() == 0, "root reads mode-000 files")
    def test_an_unreadable_pack_file(self):
        os.chmod(self.upstream("notes.md"), 0)
        try:
            self.assertIn("cannot read .modsys/packs/team/skills/api-review/notes.md: "
                          "Permission denied", self.refused())
        finally:
            os.chmod(self.upstream("notes.md"), 0o644)


class RebaseEdgesTest(RebaseRepo):  # P5A-AC-012 (--rebase), P5A-AC-046 (--rebase)
    def test_a_symlink_at_the_ejected_path(self):
        target = self.root / "elsewhere"
        self.ejected.rename(target)
        self.ejected.symlink_to(target)
        before = {p.name: p.read_bytes() for p in target.iterdir()}
        code, out, err = run("eject", "api-review", "--rebase", "--json", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn(".modsys/overrides/skills/api-review is in the way: a symlink, not an "
                      "ejected copy", err)
        self.assertEqual({p.name: p.read_bytes() for p in target.iterdir()}, before)

    def test_garbage_config_an_internal_error_and_options_after_the_verb(self):
        before = self.record.read_bytes()
        (self.root / ".modsys/config.toml").write_text("code_map = 5\n")
        code, out, err = run("eject", "api-review", "--rebase", "--json", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("config.toml", err)
        self.assertNotIn("Traceback", err)
        (self.root / ".modsys/config.toml").unlink()
        with mock.patch("modsys.eject_cmd.source_hashes", side_effect=RuntimeError("boom")), \
                mock.patch.dict(os.environ):
            os.environ.pop("MODSYS_DEBUG", None)
            code, out, err = run("eject", "api-review", "--rebase", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("modsys: internal error: RuntimeError: boom", err)
        self.assertEqual(self.record.read_bytes(), before)
        code, out, err = run("eject", "--json", "api-review", "--rebase", "--dry-run", "--root",
                             str(self.root), "--config-dir", str(self.root / ".modsys"))
        self.assertEqual((code, err, json.loads(out)["schema"]), (0, "", "modsys.eject/1"))


class RebaseInterruptTest(RebaseRepo):  # P5A-AC-044: Ctrl-C while the record is written
    def test_the_record_is_old_or_new_never_half(self):
        self.set_pack("0.2.0", "Reviews API changes, the new way.")
        before = self.record.read_bytes()
        with mock.patch("modsys.store.os.replace", side_effect=KeyboardInterrupt):
            self.assertEqual(run("eject", "api-review", "--rebase", *self.R),
                             (130, "", "modsys: interrupted\n"))
        self.assertEqual(self.record.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.ejected.iterdir()),
                         [".modsys-ejected", "SKILL.md", "notes.md"])


if __name__ == "__main__":
    unittest.main()
