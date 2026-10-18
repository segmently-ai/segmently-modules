"""lint --changed: MS050 drift, MS051 frozen snapshots, report narrowed to changed modules."""
import tempfile
import unicodedata
import unittest
from pathlib import Path

from tests.helpers import copy_fixture, git, init_git, run, run_json


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
        (self.root / ".segmently-modules/config.toml").write_text('[lint]\ndrift_severity = "error"\n')
        code, env, _ = run_json("lint", "--changed", "--base", "HEAD~1", *self.R)
        self.assertEqual(code, 1)
        self.assertIn(("MS050", "error", "catalog"), codes(env))

    def test_untracked_code_file_counts_via_code_map(self):
        (self.root / ".segmently-modules/config.toml").write_text(
            '[[code_map]]\nid = "src"\npattern = "src/{module}/**"\n')
        (self.root / "src/catalog/new_helper.py").write_text("x = 1\n")
        _, env, _ = self.lint()
        self.assertIn(("MS050", "warning", "catalog"), codes(env))

    def test_invalid_drift_severity(self):
        (self.root / ".segmently-modules/config.toml").write_text('[lint]\ndrift_severity = "loud"\n')
        code, env, _ = self.lint()
        self.assertEqual((code, env), (2, None))

    # acceptance gap tests (AC-021/023/024)
    def test_deleted_legacy_snapshot_is_ms051(self):
        (self.root / "modules/catalog/MODULE.legacy.md").unlink()
        _, env, _ = self.lint()
        self.assertIn(("MS051", "error", "catalog"), codes(env))

    # final-review hardening of the git listings (F4b-d)
    def test_renamed_legacy_snapshot_is_ms051(self):
        git(self.root, "mv", "modules/catalog/MODULE.legacy.md", "modules/catalog/OLD.md")
        _, env, _ = self.lint()
        self.assertIn(("MS051", "error", "catalog"), codes(env))
        self.assertIn("modules/catalog/MODULE.legacy.md", env["data"]["changed"]["files"])

    def test_refs_that_look_like_options_are_refused(self):
        out = Path(self._tmp.name) / "injected.txt"
        cases = [("lint", "--changed", f"--base=--output={out}"),
                 ("sync", f"--from-diff=--output={out}"),
                 ("discover", "--task", "isbn", f"--from-diff=--output={out}")]
        for argv in cases:
            with self.subTest(verb=argv[0]):
                code, stdout, err = run(*argv, *self.R)
                self.assertEqual((code, stdout), (2, ""))
                self.assertIn("may not start with '-'", err)
                self.assertFalse(out.exists())

    def test_non_ascii_paths_map_to_their_module(self):
        (self.root / ".segmently-modules/config.toml").write_text(
            '[[code_map]]\nid = "src"\npattern = "src/{module}/**"\n', encoding="utf-8")
        tracked = self.root / "src" / "catalog" / "café.py"
        tracked.write_text("x = 1\n", encoding="utf-8")
        git(self.root, "add", ".segmently-modules/config.toml", str(tracked))
        git(self.root, "commit", "-qm", "non-ascii file")
        with tracked.open("a") as fh:  # a tracked change: the diff listing
            fh.write("y = 2\n")
        git(self.root, "commit", "-qam", "change it")
        _, env, _ = run_json("sync", "--from-diff", "HEAD~1..HEAD", "--dry-run", *self.R)
        self.assertEqual(env["data"]["unmapped"], [])
        self.assertEqual([(m["module"], [unicodedata.normalize("NFC", f) for f in m["files"]])
                          for m in env["data"]["modules"]],
                         [("catalog", ["src/catalog/café.py"])])
        (self.root / "src" / "catalog" / "nëu.py").write_text("z = 3\n", encoding="utf-8")
        _, env, _ = self.lint()  # an untracked file: the ls-files listing
        self.assertEqual([unicodedata.normalize("NFC", f) for f in env["data"]["changed"]["files"]],
                         ["src/catalog/nëu.py"])
        self.assertIn(("MS050", "warning", "catalog"), codes(env))


class DriftInSubdirectoryRootTest(unittest.TestCase):
    """The segmently-modules root is a subdirectory of the git repository (a monorepo package)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.top = Path(self._tmp.name)
        self.root = copy_fixture(self._tmp.name)  # <top>/repo
        (self.top / "outside.txt").write_text("outside\n")
        init_git(self.top)
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def test_code_only_change_is_ms050_and_files_outside_the_root_drop_out(self):
        with (self.root / "src/catalog/service.py").open("a") as fh:
            fh.write("# changed\n")
        with (self.top / "outside.txt").open("a") as fh:
            fh.write("changed too\n")
        code, env, _ = run_json("lint", "--changed", "--fail-on", "never", *self.R)
        self.assertEqual(code, 0)
        self.assertEqual(env["data"]["changed"]["files"], ["src/catalog/service.py"])
        self.assertIn(("MS050", "warning", "catalog"), codes(env))
        git(self.top, "commit", "-qam", "change")
        _, env, _ = run_json("sync", "--from-diff", "HEAD~1..HEAD", "--dry-run", *self.R)
        self.assertEqual((env["data"]["changed_files"], [m["module"] for m in env["data"]["modules"]]),
                         (["src/catalog/service.py"], ["catalog"]))


if __name__ == "__main__":
    unittest.main()


class IndexOnlyChangeTest(unittest.TestCase):
    """A doc change that sits inside its critical-rules section — a rules index written or kept —
    documents no code change: MS050 still fires for the code (2026-10-18; the drift gate went
    blind when discover wrote indexes)."""
    DOC = "modules/catalog/MODULE.md"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, rel, text):
        (self.root / rel).write_text(text, encoding="utf-8")

    def ms050(self):
        _, env, _ = run_json("lint", "--changed", "--fail-on", "never", *self.R)
        return ("MS050", "warning", "catalog") in codes(env)

    def test_an_entry_added_to_an_existing_section(self):
        base = (self.root / self.DOC).read_text(encoding="utf-8").rstrip("\n")
        self.write(self.DOC, base + "\n\n## Critical Rules\n\n- Prices are cents. — `MODULE.md:3`\n\n## After\n\nText.\n")
        init_git(self.root)
        DriftLintTest.touch(self, "src/catalog/service.py")
        text = (self.root / self.DOC).read_text(encoding="utf-8")
        self.write(self.DOC, text.replace("- Prices are cents.", "Indexed: every rule of this doc, 2026-10-18.\n\n"
                                          "- Prices are cents.\n- Never delete a SKU. — `MODULE.md:4`"))
        self.assertTrue(self.ms050())  # the index alone covers no code
        self.write(self.DOC, (self.root / self.DOC).read_text(encoding="utf-8").replace("Text.", "Text, updated."))
        self.assertFalse(self.ms050())  # an edit outside the section is a doc update

    def test_a_new_section_appended_and_a_heading_edit(self):
        init_git(self.root)
        DriftLintTest.touch(self, "src/catalog/service.py")
        base = (self.root / self.DOC).read_text(encoding="utf-8")
        self.write(self.DOC, base.rstrip("\n") + "\n\n## Critical Rules\n\nIndexed: every rule of this doc, "
                   "2026-10-18.\n\n- Prices are cents. — `MODULE.md:3`\n")
        self.assertTrue(self.ms050())
        self.write(self.DOC, "# Renamed\n" + base.split("\n", 1)[1])  # a change outside: covers
        self.assertFalse(self.ms050())
