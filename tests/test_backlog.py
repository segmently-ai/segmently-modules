"""P4a backlog (D0): hints that name the agents, the record-less ejected copy, the `${article}`
of the fallback role template, unreadable inputs, MS061 real-path containment and managed files
that the source turns into directories (and back)."""
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from modsys import lint
from modsys.skill_sync import sync_command
from tests.helpers import copy_fixture, init_git, run, run_json

SKILL = "---\nname: {sid}\ndescription: The {sid} skill.\n---\n\n# {sid}\n"
SYNC = re.compile(r"modsys packs sync(?: --agent \w+)*")


class BacklogRepo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        self.R = ("--root", str(self.root))
        self.team = self.root / ".modsys/packs/team"
        self.pack(["api-review"])

    def tearDown(self):
        for path in self.root.rglob("*"):  # undo the mode-000 files before the cleanup
            if not path.is_symlink():
                os.chmod(path, 0o755 if path.is_dir() else 0o644)
        self._tmp.cleanup()

    def pack(self, skills: list[str], roles: str = "") -> None:
        self.team.mkdir(parents=True, exist_ok=True)
        (self.team / "pack.toml").write_text(
            'id = "team"\nversion = "0.1.0"\n' + roles
            + "".join(f'[skills.{s}]\npath = "skills/{s}"\n' for s in skills))
        for sid in skills:
            md = self.team / "skills" / sid / "SKILL.md"
            md.parent.mkdir(parents=True, exist_ok=True)
            md.write_text(SKILL.format(sid=sid))

    def config(self, text: str) -> None:
        (self.root / ".modsys/config.toml").write_text(text)

    def text(self, *argv) -> str:
        return run(*argv, *self.R)[1]


class HintsNameTheAgentsTest(BacklogRepo):  # P4B-AC-001
    def test_one_helper_names_the_sync_command(self):
        both = "modsys packs sync --agent claude --agent codex"
        self.assertEqual(sync_command(None, None), both)
        self.assertEqual(sync_command(["codex", "claude"], None),
                         "modsys packs sync --agent codex --agent claude")
        self.assertEqual(sync_command(None, ["claude"]), "modsys packs sync")
        self.assertEqual(sync_command(["claude"], ["claude"]), "modsys packs sync")
        self.assertEqual(sync_command(["codex"], ["claude"]), "modsys packs sync --agent codex")

    def test_every_surface_uses_it(self):
        help_text = " ".join(run("eject", "--help")[1].split())
        self.assertEqual(SYNC.findall(help_text), [sync_command(None, None)])
        self.assertIn(f"{sync_command(None, None)} (or set [packs] agents once)", help_text)
        for configured in (None, ["claude", "codex"]):
            with self.subTest(configured=configured):
                self.config("" if configured is None else
                            '[packs]\nagents = ["claude", "codex"]\n')
                shutil.rmtree(self.root / ".modsys/overrides", ignore_errors=True)
                shutil.rmtree(self.root / ".claude", ignore_errors=True)
                eject = self.text("eject", "api-review").splitlines()[-1]
                self.assertEqual(SYNC.findall(eject), [sync_command(None, configured)])
                self.assertEqual(eject.endswith("(or set [packs] agents once)"), not configured)
                check = self.text("packs", "sync", "--check", "--agent", "codex", "--agent",
                                  "claude").splitlines()[-1]
                self.assertIn("stale — run ", check)
                self.assertEqual(SYNC.findall(check),
                                 [sync_command(["codex", "claude"], configured)])
        check = self.text("packs", "sync", "--check").splitlines()[-1]
        self.assertTrue(check.endswith("stale — run modsys packs sync"), check)
        self.assertTrue(self.text("packs", "sync", "--check", "--agent", "claude").endswith(
            "stale — run modsys packs sync --agent claude\n"))

    def test_packs_new_names_the_configured_agents(self):  # fix wave M1
        for configured in (None, ["claude"], ["claude", "codex"]):
            with self.subTest(configured=configured):
                self.config("" if configured is None else
                            f"[packs]\nagents = {json.dumps(configured)}\n")
                new = self.text("packs", "new", "late", "--skill", "notes",
                                "--dry-run").splitlines()[-1]
                self.assertTrue(new.startswith("next: "), new)
                self.assertEqual(SYNC.findall(new), [sync_command(None, configured)])


class RecordAndArticleTest(BacklogRepo):  # P4B-AC-002
    def test_a_record_less_copy_of_a_skill_no_pack_declares(self):
        self.assertEqual(run("eject", "api-review", *self.R)[0], 0)
        self.pack([])
        (self.root / ".modsys/overrides/skills/api-review/.modsys-ejected").write_text("{}\n")
        out = self.text("packs", "sync", "--agent", "claude")
        self.assertEqual(out.splitlines()[0],
                         "invalid    claude  .claude/skills/api-review  (no valid record)")
        self.assertNotIn("(None", out)

    def test_the_fallback_role_template_takes_the_article(self):
        self.config('[roles.auditor]\norder = 200\ndescription = "Audits"\n'
                    '[roles.security]\norder = 210\ndescription = "Threats"\n')
        code, env, err = run_json("create", "vault", "--non-interactive", "--description",
                                  "Stored secrets: rotation, access and audit trails.",
                                  "--keywords", "vault, secret, rotation, access, audit",
                                  "--role", "auditor", "--role", "security", *self.R)
        self.assertEqual((code, err), (0, ""))
        docs = {Path(f).name: (self.root / f).read_text() for f in env["data"]["files"]}
        self.assertIn("<!-- What an auditor needs to know", docs["auditor.md"])
        self.assertIn("<!-- What a security needs to know", docs["security.md"])
        self.assertFalse([name for name, text in docs.items() if "${article}" in text])
        rows = {r["role"]: r["source"] for r in run_json("templates", "list", *self.R)[1]["data"]}
        self.assertEqual((rows["auditor"], rows["security"]),
                         ("engine-fallback", "engine-fallback"))


@unittest.skipIf(os.geteuid() == 0, "root reads mode-000 files")
class UnreadableInputsTest(BacklogRepo):  # P4B-AC-003
    def setUp(self):
        super().setUp()
        self.pack(["api-review", "notes"])
        self.ref = self.team / "skills/api-review/references/r.md"
        self.ref.parent.mkdir()
        self.ref.write_text("a reference\n")

    def refused(self, *argv, path: str) -> None:
        code, out, err = run(*argv, "--json", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(err, f"modsys: error: cannot read {path}: Permission denied\n")

    def test_a_source_file(self):
        os.chmod(self.ref, 0)
        path = ".modsys/packs/team/skills/api-review/references/r.md"
        self.refused("packs", "sync", "--agent", "claude", path=path)
        self.assertFalse((self.root / ".claude").exists())
        self.refused("eject", "api-review", path=path)
        self.assertFalse((self.root / ".modsys/overrides").exists())
        (self.root / "AGENTS.md").write_text("# Team\n")
        self.refused("agents-md", "--target", "AGENTS.md", path=path)
        self.assertEqual((self.root / "AGENTS.md").read_text(), "# Team\n")
        self.assertEqual(run("lint", "--fail-on", "never", *self.R)[0], 0)

    def test_a_target_and_an_agent_copy(self):
        (self.root / "AGENTS.md").write_text("# Team\n")
        os.chmod(self.root / "AGENTS.md", 0)
        self.refused("agents-md", "--target", "AGENTS.md", path="AGENTS.md")
        self.assertEqual(run("packs", "sync", "--agent", "claude", *self.R)[0], 0)
        os.chmod(self.root / ".claude/skills/api-review/SKILL.md", 0)
        self.refused("packs", "sync", "--agent", "claude",
                     path=".claude/skills/api-review/SKILL.md")

    def eject_then_lock(self, side: str) -> str:
        """Commit, eject `api-review`, then make `references/r.md` of the pack's source
        (`side` "source") or of the ejected copy ("copy") unreadable; its root-relative path."""
        init_git(self.root)
        self.assertEqual(run("eject", "api-review", *self.R)[0], 0)
        path = (self.ref if side == "source" else
                self.root / ".modsys/overrides/skills/api-review/references/r.md")
        os.chmod(path, 0)
        return path.relative_to(self.root).as_posix()

    def test_ejected_then_an_unreadable_source_file(self):  # fix wave I-2 (case A)
        path = self.eject_then_lock("source")
        self.refused("eject", "api-review", "--diff", path=path)
        ms063 = [("MS063", "warning", "*", f"ejected skill 'api-review': cannot read {path}: "
                  "Permission denied — cannot tell whether pack 'team' moved on since the "
                  "eject", path)]
        code, env, err = run_json("lint", "--fail-on", "never", *self.R)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual([tuple(f.values()) for f in env["data"]["findings"]], ms063)
        code, env, err = run_json("ci", *self.R)
        self.assertEqual((code, err), (1, ""))
        lint_step = env["data"]["steps"][0]
        self.assertEqual((lint_step["name"], lint_step["status"]), ("lint", "failed"))
        self.assertEqual([tuple(f.values()) for f in lint_step["findings"]], ms063)

    def test_ejected_then_an_unreadable_copy_file(self):  # fix wave I-2 (case B)
        path = self.eject_then_lock("copy")
        self.refused("eject", "api-review", "--diff", path=path)
        for argv in (("lint",), ("ci",)):
            with self.subTest(verb=argv[0]):
                code, env, err = run_json(*argv, *self.R)
                self.assertEqual((code, err, env["data"]["failed"]), (0, "", False))


class ContainmentTest(BacklogRepo):  # P4B-AC-004 (M-4)
    ROLE = '[roles.reviewer]\ndescription = "Reviews"\ntemplate = "roles/r.md"\n'

    def ms061(self) -> list[tuple]:
        data = run_json("lint", "--fail-on", "never", *self.R)[1]["data"]
        return [(f["message"], f["path"]) for f in data["findings"] if f["code"] == "MS061"]

    def test_a_role_template_symlinked_out_of_the_pack(self):
        self.pack(["api-review"], self.ROLE)
        (self.root / "outside.md").write_text("# outside\n")
        (self.team / "roles").mkdir()
        os.symlink(self.root / "outside.md", self.team / "roles/r.md")
        self.assertEqual(self.ms061(), [("pack 'team': role 'reviewer' template 'roles/r.md' is "
                                         "outside the pack", ".modsys/packs/team/pack.toml")])
        (self.team / "roles/r.md").unlink()
        (self.team / "roles/inside.md").write_text("# ${title}\n")
        os.symlink("inside.md", self.team / "roles/r.md")
        self.assertEqual(self.ms061(), [])
        self.assertFalse(hasattr(lint, "_inside"))


class FileBecomesDirectoryTest(BacklogRepo):  # P4B-AC-004 (M-3)
    def sync(self, code=0) -> list[tuple]:
        got, env, err = run_json("packs", "sync", "--agent", "claude", *self.R)
        self.assertEqual((got, err), (code, ""), env)
        return [(r["status"], r["files"], r["reason"]) for r in env["data"]["skills"]]

    def src(self) -> Path:
        return self.team / "skills/api-review"

    def dest(self) -> Path:
        return self.root / ".claude/skills/api-review"

    def test_a_file_becomes_a_directory_and_back(self):
        (self.src() / "refs").write_text("one file\n")
        self.sync()
        (self.src() / "refs").unlink()
        (self.src() / "refs").mkdir()
        (self.src() / "refs/a.md").write_text("a\n")
        self.assertEqual(self.sync(), [("updated", ["refs", "refs/a.md"], None)])
        self.assertEqual((self.dest() / "refs/a.md").read_text(), "a\n")
        marker = json.loads((self.dest() / ".modsys-managed").read_text())
        self.assertEqual(sorted(marker["files"]), ["SKILL.md", "refs/a.md"])
        self.assertEqual(run("packs", "sync", "--check", "--agent", "claude", *self.R)[0], 0)
        shutil.rmtree(self.src() / "refs")
        (self.src() / "refs").write_text("a file again\n")
        self.assertEqual(self.sync(), [("updated", ["refs", "refs/a.md"], None)])
        self.assertEqual((self.dest() / "refs").read_text(), "a file again\n")
        self.assertEqual(run("packs", "sync", "--check", "--agent", "claude", *self.R)[0], 0)

    def test_an_edited_file_stays_a_conflict(self):
        (self.src() / "refs").write_text("one file\n")
        self.sync()
        (self.dest() / "refs").write_text("edited here\n")
        (self.src() / "refs").unlink()
        (self.src() / "refs").mkdir()
        (self.src() / "refs/a.md").write_text("a\n")
        rows = self.sync(code=1)
        self.assertEqual([r[0] for r in rows], ["conflict"])
        self.assertIn("refs (locally edited)", rows[0][2])
        self.assertEqual((self.dest() / "refs").read_text(), "edited here\n")


class PackGuideTest(unittest.TestCase):  # D0(g)
    def test_the_create_role_example_names_the_standard_roles(self):
        text = (Path(__file__).resolve().parents[1] / "docs/writing-a-pack.md").read_text()
        after = text.split("modsys packs list                     # the pack", 1)[1]
        self.assertIn("the standard roles'\ndocs (`developer`, `qa`, `po`, `architect`) are "
                      "scaffolded too", after.split("## ", 1)[0])


if __name__ == "__main__":
    unittest.main()
