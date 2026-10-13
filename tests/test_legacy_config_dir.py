"""A root that still holds the config of modsys 0.1.x (`.modsys/`) and no `.segmently-modules/`:
every verb, `init`, `setup` and `adopt` exit 2 and write nothing, naming the rename command — the
engine defaults never replace the team's config silently. An explicit `--config-dir` is the user's
choice; with both directories present the new one wins. (Until 0.3.0.)"""
import contextlib
import shutil
import tempfile
import unittest

from tests.helpers import copy_fixture, git, init_git, run, run_json

RENAME = "git mv .modsys .segmently-modules"


class LegacyConfigDirTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name).resolve()
        (self.root / ".segmently-modules").rename(self.root / ".modsys")
        init_git(self.root)
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def refused(self, *argv) -> str:
        code, out, err = run(*argv, *self.R)
        self.assertEqual((code, out), (2, ""), err)
        self.assertEqual(git(self.root, "status", "--short", "--untracked-files=all"), "")
        return err

    def test_a_verb_is_refused_with_the_rename_command(self):
        err = self.refused("lint")
        self.assertIn(f"segmently-modules: error: {self.root / '.modsys'} is the config of "
                      f"modsys 0.1.x — rename it first: {RENAME}", err)
        self.assertIn("Upgrading from modsys 0.1.x", err)
        for argv in (("show", "catalog"), ("next",), ("ci", "--base", "HEAD")):
            with self.subTest(argv=argv):
                self.assertIn(RENAME, self.refused(*argv))

    def test_init_setup_and_adopt_write_nothing(self):
        for argv in (("init",), ("setup",), ("adopt",)):
            with self.subTest(argv=argv):
                self.assertIn(RENAME, self.refused(*argv))

    def test_an_explicit_config_dir_is_read(self):
        code, env, err = run_json("lint", "--config-dir", str(self.root / ".modsys"), *self.R)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(env["schema"], "segmently-modules.lint/1")

    def test_a_nested_legacy_root_is_found_and_refused(self):
        # below the git root, its registry elsewhere: only `.modsys/` marks it, and without
        # --root the search must stop there (not at the git root, with the engine defaults)
        app = self.root / "app"
        app.mkdir()
        (self.root / ".modsys").rename(app / ".modsys")
        (app / "src").mkdir()
        with contextlib.chdir(app / "src"):
            code, out, err = run("lint")
        self.assertEqual((code, out), (2, ""), err)
        self.assertIn(f"{app / '.modsys'} is the config of modsys 0.1.x", err)

    def test_both_directories_the_new_one_wins(self):
        shutil.copytree(self.root / ".modsys", self.root / ".segmently-modules")
        (self.root / ".modsys" / "config.toml").write_text("not = [toml\n", encoding="utf-8")
        code, _env, err = run_json("lint", *self.R)
        self.assertEqual((code, err), (0, ""))


if __name__ == "__main__":
    unittest.main()
