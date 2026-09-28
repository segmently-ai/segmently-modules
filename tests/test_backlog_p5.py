"""P5a backlog, error robustness (D0a): an unreadable proposal file is `cannot read`, the
`[packs] builtin` refusals name their files root-relative, and a repository pack that takes a
built-in id gets an MS066 info finding."""
import os
import tempfile
import unittest
from pathlib import Path

from tests.helpers import copy_fixture, init_git, run, run_json


class Repo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name).resolve()
        self.R = ("--root", str(self.root))

    def tearDown(self):
        for path in self.root.rglob("*"):  # undo the mode-000 files before the cleanup
            if not path.is_symlink():
                os.chmod(path, 0o755 if path.is_dir() else 0o644)
        self._tmp.cleanup()

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def refused(self, *argv) -> str:
        code, out, err = run(*argv, *self.R)
        self.assertEqual((code, out), (2, ""), err)
        self.assertNotIn(str(self.root), err)
        return err


@unittest.skipIf(os.geteuid() == 0, "root reads mode-000 files")
class UnreadableProposalTest(Repo):  # P5A-AC-001 (M9)
    def test_list_and_sync_instructions_say_cannot_read(self):
        for run_id in ("r1", "r2"):
            code, _, err = run("propose", "--module", "catalog", "--op", "set", "--field",
                               "status", "--value", '"draft"', "--reason", "r", "--run-id",
                               run_id, *self.R)
            self.assertEqual((code, err), (0, ""))
        queue = self.root / ".modsys/proposals"
        other = (queue / "r2-cli.json").read_bytes()
        os.chmod(queue / "r1-cli.json", 0)
        want = ("modsys: error: cannot read .modsys/proposals/r1-cli.json: "
                "Permission denied\n")
        for argv in (("proposals", "list"), ("sync-instructions", "--module", "catalog"),
                     ("sync-instructions", "--files", "src/catalog/service.py")):
            for mode in ((), ("--json",)):
                with self.subTest(argv=argv, mode=mode):
                    err = self.refused(*argv, *mode)
                    self.assertEqual(err, want)
                    self.assertNotIn("internal error", err)
        self.assertEqual((queue / "r2-cli.json").read_bytes(), other)
        self.assertEqual(sorted(p.name for p in queue.iterdir()),
                         ["r1-cli.json", "r1-cli.json.lock", "r2-cli.json", "r2-cli.json.lock"])


class BuiltinRefusalPathTest(Repo):  # P5A-AC-002 (M10)
    UNKNOWN = ": [packs] builtin: unknown built-in pack 'cor' (built-in packs: core, qa, ui)\n"

    def test_the_team_and_the_user_config(self):
        for name in ("config.toml", "config.user.toml"):
            with self.subTest(file=name):
                for other in ("config.toml", "config.user.toml"):
                    (self.root / ".modsys" / other).unlink(missing_ok=True)
                self.write(f".modsys/{name}", '[packs]\nbuiltin = ["cor"]\n')
                self.assertEqual(self.refused("packs", "list"),
                                 f"modsys: error: .modsys/{name}{self.UNKNOWN}")

    def test_a_pack_that_enables_a_builtin_pack(self):
        self.write(".modsys/packs/team/pack.toml", 'id = "team"\n[packs]\nbuiltin = ["core"]\n')
        self.assertEqual(self.refused("packs", "list"),
                         "modsys: error: .modsys/packs/team/pack.toml: [packs] builtin: a pack "
                         "cannot enable built-in packs — set it in .modsys/config.toml\n")

    def test_a_config_dir_outside_the_root_is_named_absolute(self):
        outside = Path(self._tmp.name).resolve() / "cfg"
        outside.mkdir()
        (outside / "config.toml").write_text('[packs]\nbuiltin = ["cor"]\n', encoding="utf-8")
        code, out, err = run("packs", "list", "--config-dir", str(outside), *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(err, f"modsys: error: {outside / 'config.toml'}{self.UNKNOWN}")


class Ms066Test(Repo):  # P5A-AC-003 (M8)
    def ms066(self) -> list[tuple]:
        code, env, err = run_json("lint", "--fail-on", "never", *self.R)
        self.assertEqual((code, err), (0, ""))
        return [(f["severity"], f["module"], f["message"], f["path"])
                for f in env["data"]["findings"] if f["code"] == "MS066"]

    def pack(self, directory: str, pack_id: str) -> None:
        self.write(f".modsys/packs/{directory}/pack.toml", f'id = "{pack_id}"\n')

    def test_the_decision_table(self):
        core = [("info", "*", "repository pack 'core' replaces the built-in pack 'core'",
                 ".modsys/packs/core/pack.toml")]
        self.pack("core", "core")
        self.write(".modsys/config.toml", '[packs]\nbuiltin = ["core"]\n')
        self.assertEqual(self.ms066(), core)
        (self.root / ".modsys/config.toml").unlink()
        self.assertEqual(self.ms066(), core)  # the id is taken whether or not it is enabled
        (self.root / ".modsys/packs/core/pack.toml").unlink()
        self.pack("mine", "ui")
        self.write(".modsys/config.toml", "[packs]\nbuiltin = []\n")
        self.assertEqual(self.ms066(), [
            ("info", "*", "repository pack 'ui' replaces the built-in pack 'ui'",
             ".modsys/packs/mine/pack.toml")])
        (self.root / ".modsys/packs/mine/pack.toml").unlink()
        self.pack("team", "team")
        self.write(".modsys/config.toml", '[packs]\nbuiltin = ["core", "ui", "qa"]\n')
        self.assertEqual(self.ms066(), [])

    def test_changed_and_ci_never_fail_on_it(self):
        self.pack("core", "core")
        init_git(self.root)
        code, env, _ = run_json("lint", "--changed", "--fail-on", "warning", *self.R)
        self.assertEqual(code, 0)
        self.assertNotIn("MS066", [f["code"] for f in env["data"]["findings"]])
        code, env, err = run_json("ci", *self.R)
        self.assertEqual((code, err), (0, ""))
        lint = env["data"]["steps"][0]
        self.assertEqual((lint["status"], [f["code"] for f in lint["findings"]]),
                         ("passed", ["MS066"]))


if __name__ == "__main__":
    unittest.main()
