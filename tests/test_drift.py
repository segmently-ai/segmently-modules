"""lint --changed: MS050 drift, MS051 frozen snapshots, report narrowed to changed modules."""
import tempfile
import unittest

from tests.helpers import copy_fixture, git, init_git, run_json


def codes(env):
    return {(f["code"], f["severity"], f["module"]) for f in env["data"]["findings"]}


class DriftLintTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        (self.root / "modules/catalog/MODULE.legacy.md").write_text("# frozen\n")
        init_git(self.root)
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def lint(self, *extra):
        return run_json("lint", "--changed", "--fail-on", "never", *extra, *self.R)

    def touch(self, rel, text="# changed\n"):
        with (self.root / rel).open("a") as fh:
            fh.write(text)

    def test_code_without_docs_is_ms050_then_clears_after_a_doc_edit(self):
        self.touch("src/catalog/service.py")
        _, env, _ = self.lint()
        self.assertIn(("MS050", "warning", "catalog"), codes(env))
        self.assertEqual(env["data"]["changed"]["modules"], ["catalog"])
        self.touch("modules/catalog/roles/developer.md", "More notes.\n")
        _, env, _ = self.lint()
        self.assertNotIn("MS050", {c for c, _, _ in codes(env)})

    def test_legacy_snapshot_edit_does_not_count_and_is_ms051(self):
        self.touch("src/catalog/service.py")
        self.touch("modules/catalog/MODULE.legacy.md", "edited\n")
        _, env, _ = self.lint()
        got = codes(env)
        self.assertIn(("MS050", "warning", "catalog"), got)
        self.assertIn(("MS051", "error", "catalog"), got)

    def test_report_narrowed_to_changed_modules(self):
        (self.root / "modules/checkout/MODULE.md").write_text("line\n" * 700)  # MS030 on checkout
        git(self.root, "commit", "-qam", "big doc")
        self.touch("src/catalog/service.py")
        _, env, _ = self.lint()
        self.assertEqual({m for _, _, m in codes(env)}, {"catalog"})
        _, env, _ = run_json("lint", "--fail-on", "never", *self.R)  # full lint still sees it
        self.assertIn(("MS030", "warning", "checkout"), codes(env))

    def test_drift_against_base_ref_and_severity(self):
        self.touch("src/catalog/service.py")
        git(self.root, "commit", "-qam", "code only")
        _, env, _ = self.lint()  # base HEAD: nothing changed since the commit
        self.assertEqual(env["data"]["changed"]["modules"], [])
        (self.root / ".modsys/config.toml").write_text('[lint]\ndrift_severity = "error"\n')
        code, env, _ = run_json("lint", "--changed", "--base", "HEAD~1", *self.R)
        self.assertEqual(code, 1)
        self.assertIn(("MS050", "error", "catalog"), codes(env))

    def test_untracked_code_file_counts_via_code_map(self):
        (self.root / ".modsys/config.toml").write_text(
            '[[code_map]]\nid = "src"\npattern = "src/{module}/**"\n')
        (self.root / "src/catalog/new_helper.py").write_text("x = 1\n")
        _, env, _ = self.lint()
        self.assertIn(("MS050", "warning", "catalog"), codes(env))

    def test_invalid_drift_severity(self):
        (self.root / ".modsys/config.toml").write_text('[lint]\ndrift_severity = "loud"\n')
        code, env, _ = self.lint()
        self.assertEqual((code, env), (2, None))

    # acceptance gap tests (AC-021/023/024)
    def test_deleted_legacy_snapshot_is_ms051(self):
        (self.root / "modules/catalog/MODULE.legacy.md").unlink()
        _, env, _ = self.lint()
        self.assertIn(("MS051", "error", "catalog"), codes(env))


if __name__ == "__main__":
    unittest.main()
