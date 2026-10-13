"""The release tests after their split (P8.3 D5 R-3, SI-P83-16, P83-AC-020): every test of the
one `tests/test_release.py` of 758d085 is loaded exactly once from the `tests/test_release*.py`
modules, with its class's and its own AC comment and its source unchanged (the one exception:
RunTest's step-3 regex, SI-P83-14); the shared helpers and constants are unchanged and live
outside `test_*.py`; the per-class snapshot copies every repository and remote and is only
read. The docs of task 3 (P83-AC-022): `docs/releasing.md`, the `release.py` docstring and
`CHANGELOG.md` name `--jobs` and `--suite-passed`."""
import ast
import hashlib
import importlib
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.helpers import changelog_since_first_release, git
from tests.plugin_helpers import ENGINE
from tests.release_helpers import copy_repos, tree_hash

TESTS = ENGINE / "tests"
# P83-PRE-005: the 44 tests of tests/test_release.py at 758d085 — (class, method, the class
# line's comment, the def line's comment, sha256[:16] of the method's source lines)
REFERENCE = [
    ("RunTest", "test_dev_then_stable", "P6-AC-014, 015, 017", "", "6baedbaa97a7bebc"),  # the rename: git lists pyproject.toml first
    ("RunTest", "test_both_channels_start_from_the_same_main_commit", "P6-AC-014, 015, 017", "",
     "789a56076d846fcd"),
    ("RunTest", "test_push_only_with_push", "P6-AC-014, 015, 017", "", "f29f59f776742d36"),
    ("RunTest", "test_without_claude", "P6-AC-014, 015, 017", "", "21e36a1483f415cc"),
    ("CommitTest", "test_ignore_rules_and_a_repository_without_modes",
     "final review I-1: the commit is the build, whatever git is told", "", "a7c58f64088fed32"),
    ("CommitTest", "test_a_commit_that_is_not_the_build_fails_step_7",
     "final review I-1: the commit is the build, whatever git is told", "", "f18b08bd36fc636e"),
    ("CloneTest", "test_a_channel_that_exists_only_on_origin",
     "final review I-3: a fresh clone of the publish repository", "", "f6594048e4703006"),
    ("PushTest", "test_a_failed_push_leaves_the_release_and_names_the_commands",
     "final review I-4, M-9: the push is never put back", "", "48648bf23b632560"),
    ("PushTest", "test_ctrl_c_during_the_engine_push_resets_nothing",
     "final review I-4, M-9: the push is never put back", "", "ab9eb6d0f3666161"),
    ("OwnershipTest", "test_foreign_content_is_kept", "P6-AC-016 (SI-17), P6-AC-021", "",
     "c784cfb4ac73876f"),
    ("OwnershipTest", "test_the_organisation_anywhere_in_the_engine",
     "P6-AC-016 (SI-17), P6-AC-021", "", "60383a85bc68c1c7"),  # the rename: the two public slugs
    ("OwnershipTest", "test_the_organisation_scan_names_places_not_hashes",
     "P6-AC-016 (SI-17), P6-AC-021", "", "8c1723ddafb1efb7"),  # the rename: the two public slugs
    ("NoopTest", "test_twice_then_a_change", "P6-AC-029", "", "badf6fdb1f8d796c"),
    ("NoopTest", "test_stable_again_is_refused", "P6-AC-029", "", "331578689d7b4f9f"),
    ("RefusalTest", "test_the_guard", "P6-AC-030 (SI-1, SI-16, SI-17)", "", "a489668e1c3f2bf4"),
    ("RefusalTest", "test_a_guard_that_fails_is_not_a_guard_with_hits",
     "P6-AC-030 (SI-1, SI-16, SI-17)", "final review M-3", "60aef70212230e07"),
    ("RefusalTest", "test_dirty_trees_and_tags", "P6-AC-030 (SI-1, SI-16, SI-17)", "",
     "879d234c6e38f7a3"),
    ("RefusalTest", "test_a_version_without_devn_and_a_symlinked_directory",
     "P6-AC-030 (SI-1, SI-16, SI-17)", "final M-7, M-5", "e1ad48955ee0b1e4"),
    ("RefusalTest", "test_a_release_under_nohup_keeps_running", "P6-AC-030 (SI-1, SI-16, SI-17)",
     "re-review N-4", "95500e342c2657dd"),
    ("RefusalTest", "test_flags", "P6-AC-030 (SI-1, SI-16, SI-17)", "", "796faff349bee83a"),
    ("RefusalTest", "test_an_export_of_the_engine_and_no_git", "P6-AC-030 (SI-1, SI-16, SI-17)",
     "never a traceback before step 1", "8b805f8a995c52da"),
    ("RefusalTest", "test_an_unknown_flag", "P6-AC-030 (SI-1, SI-16, SI-17)", "P6-AC-033",
     "d06d70b4d25a65e5"),
    ("AllOrNothingTest", "test_each_failing_step", "P6-AC-031 (SI-16)", "", "69755c308e1783e6"),
    ("AllOrNothingTest", "test_an_empty_repository_and_a_detached_head", "P6-AC-031 (SI-16)", "",
     "c38bf7d512ab1e46"),
    ("AllOrNothingTest", "test_a_publish_file_the_release_cannot_use", "P6-AC-031 (SI-16)", "",
     "d774daf5ce6410db"),
    ("AllOrNothingTest", "test_a_symlinked_directory_on_the_channel_branch", "P6-AC-031 (SI-16)",
     "re-review N-1", "52639e9c1de91a83"),
    ("AllOrNothingTest", "test_what_appears_beside_the_run_is_never_put_back",
     "P6-AC-031 (SI-16)", "final review I-2", "1b4c12e4916fc45d"),
    ("AllOrNothingTest", "test_the_put_back_finishes_and_says_what_is_true", "P6-AC-031 (SI-16)",
     "task-8 review C2", "8a04d243c5f8e1aa"),
    ("AllOrNothingTest", "test_sigterm_and_a_closed_terminal_are_an_interrupt",
     "P6-AC-031 (SI-16)", "", "569fc5af6a99376f"),
    ("SignalDefaultsTest", "test_a_tool_the_tests_start_gets_the_default_signals",
     "the gate runs the suite detached: nohup … &", "", "72371d0ca74a5215"),
    ("SectionsTest", "test_the_readme_and_the_changelog", "P6-AC-016: only our sections change",
     "", "890d2e0d6a73900f"),
    ("SectionsTest", "test_a_crlf_file_keeps_its_line_endings",
     "P6-AC-016: only our sections change", "", "02155adce55890da"),
    ("SectionsTest", "test_damaged_markers_fail_naming_the_file",
     "P6-AC-016: only our sections change", "", "7337e81b1f4af8d3"),
    ("NotesTest", "test_the_unreleased_section",
     "P61-AC-021, 022, 031, 036 (D6, SI-P61-9/10): pure parts", "", "3408768749ec25b6"),
    ("NotesTest", "test_empty_is_no_item_line",
     "P61-AC-021, 022, 031, 036 (D6, SI-P61-9/10): pure parts", "SI-P61-10", "b020f21edea4e45b"),
    ("NotesTest", "test_no_heading_two_headings_no_file",
     "P61-AC-021, 022, 031, 036 (D6, SI-P61-9/10): pure parts", "P61-AC-031", "3c4fbe4a3c941c16"),
    ("NotesTest", "test_the_release_commit_dates_the_section",
     "P61-AC-021, 022, 031, 036 (D6, SI-P61-9/10): pure parts", "P61-AC-021, AC-031 (CRLF)",
     "66365dd66174e42b"),
    ("NotesTest", "test_the_publish_entry",
     "P61-AC-021, 022, 031, 036 (D6, SI-P61-9/10): pure parts", "P61-AC-021, AC-022",
     "33043d953638ad43"),
    ("NotesTest", "test_the_date", "P61-AC-021, 022, 031, 036 (D6, SI-P61-9/10): pure parts",
     "SI-P61-9", "d7ff290f03c6eafb"),
    ("NotesRunTest", "test_a_dev_release_writes_the_pending_notes",
     "P61-AC-022, 031, 036: the notes through whole runs", "P61-AC-022, AC-031 (no file)",
     "46dfa5b46f387d9c"),
    ("NotesRunTest", "test_stable_without_notes_is_refused_before_any_work",
     "P61-AC-022, 031, 036: the notes through whole runs", "P61-AC-036, AC-031",
     "b46714f4249fd730"),
    ("NotesRunTest", "test_a_crlf_changelog_stays_crlf",
     "P61-AC-022, 031, 036: the notes through whole runs", "P61-AC-031", "e4708d0ec08c988e"),
    ("ChangelogFileTest", "test_keep_a_changelog_down_to_the_first_release",
     "P61-AC-020: the engine's own CHANGELOG.md", "", "0742ccb46c477779"),
    ("ChangelogFileTest", "test_no_host_organisation_slug_or_machine_path",
     "P61-AC-020: the engine's own CHANGELOG.md", "D13", "0a4b5b716fc0b4bb"),
]
# the helpers of the test classes and of the base, and the module's constants, at 758d085
# (P8.9: SKILL names the ui pack's skill by its new directory, `designer`)
HELPERS = [("files", "279c159e7bff31a4"), ("committed", "32c9fd83b2b6d873"),
           ("refused", "342ce0815e5c6c05"), ("failed", "8c64fe4afcae49d4"),
           ("planted", "6b018d6bb95cbc27"), ("setUp", "00b616d7e6204801"),
           ("refused", "cdf165789a31f414"), ("index", "4f758577aff67cd4"),
           ("refused_at_step_1", "77d2cf7081b54bb0"), ("setUp", "3f53c88864a910e6"),
           ("tearDown", "959d70d2d2c295a7"), ("git_wrapper", "36c7af41b59fe5ba"),
           ("claude_on_path", "ebd52bf9493d0455"), ("state", "7d5716823d8a5a16"),
           ("both", "b4ff08465fcb7a71"), ("calls", "f3ecda5635fb1020"),
           ("assert_ok", "8beec193d0c8cc34"), ("commit", "48a1f27f9a532432"),
           ("change_a_skill", "1a847d0bd49cb7c4"), ("notes", "23d71885fd53fc1e"),
           ("remotes", "d133f6a188cbdd68"), ("log", "71c5ec419a37f3ed"),
           ("entries", "cba12c4597b16c8a"), ("refs", "7eaeaac89aaf4cc7")]
# ENG moved once: dev_version(), so that a release tag's checkout runs the release tests too
CONSTANTS = [("ENG", "b535f6aec9393fb8"), ("REL", "1434606f64af146b"),
             ("NXT", "0a820ae9d519fb43"), ("NXT_DEV", "d8e71a70b5dd1f4a"),
             ("SLUG", "56b4fc0f4f63fd8b"), ("DATE", "b3ef3d9158fe5fe0"),
             ("CHANGELOG", "db1ed4d42a418b33"), ("(LOG_BEGIN, LOG_END)", "fd6ee0206c1ee46e"),
             ("PLANT", "e313c1171b7ebcc8"), ("EXTRA", "bd6a5909fe0afa53"),
             ("GUARD", "dad6c0ac40fe2e4c"), ("ALLOWED", "e0e1224bfffede7a"),
             ("IDENTITY", "605869b23454875e"), ("CREDENTIALS", "7cd8aac41204ceea"),
             ("MACHINE_PATHS", "0028ce936080354f"), ("STEPS", "0cfb498b38f92f86"),
             ("SKILL", "94abb1ff405089d0"), ("TAGS", "7211bc9c3de1fc71"),
             ("NO_NOTE", "735749ddc280b275"), ("NO_HEADING", "bb55fec2af3a7a9b"),
             ("NO_FILE", "3333fa2b1a7f22ed"), ("MARKER", "263d8729191cb388"),
             ("UNTRACKED", "8967b61a632eec58"), ("two_headings", "586c9d2ca7d4deb2")]
# SI-P83-14: the one assertion that changed — RunTest's step-3 regex (old line, new lines)
OLD_REGEX = (r'        self.assertRegex(proc.stdout, r"step 3 tests: Ran 3 tests in [\d.]+s, '
             r'OK \(skipped=1\); "')
NEW_REGEX = (r'        self.assertRegex(proc.stdout, r"step 3 tests: Ran 3 tests in 2 modules '
             r'\(\d+ jobs?\), "' "\n"
             r'                                      r"OK \(skipped=1\); "')
FIRST_RELEASE = 'self.assert_ok(self.release("dev"))'  # a test that starts from that release


def modules() -> list[Path]:
    return sorted(TESTS.glob("test_release*.py"))


def comment(line: str) -> str:
    found = re.search(r"#\s*(.*)$", line)
    return found.group(1).strip() if found else ""


def digest(text: str) -> str:
    """The first 16 hex digits of the text's sha256, taken under the name the digests were
    recorded with (modsys, before the rename): the rename changed names only, and still matches.
    Both new forms map to the one old name, so a package/command swap inside a digested test is
    invisible here — the tests themselves catch that."""
    for name in ("SEGMENTLY_MODULES_", "segmently_modules", "segmently-modules",
                 "Segmently Modules"):
        text = text.replace(name, "MODSYS_" if name.endswith("_") and name.isupper() else "modsys")
    return hashlib.sha256(text.encode()).hexdigest()[:16]


class Source:
    """The classes and functions of one file: their source lines and their comments."""

    def __init__(self, path: Path):
        self.path = path
        self.lines = path.read_text(encoding="utf-8").split("\n")
        self.tree = ast.parse("\n".join(self.lines))

    def text(self, node) -> str:
        return "\n".join(self.lines[node.lineno - 1:node.end_lineno])

    def classes(self):
        return [n for n in self.tree.body if isinstance(n, ast.ClassDef)]

    def functions(self):
        return [(c, f) for c in self.classes() for f in c.body if isinstance(f, ast.FunctionDef)]


class SplitTest(unittest.TestCase):  # P83-AC-020
    def test_every_test_of_the_one_module_runs_once_unchanged(self):
        self.assertFalse((TESTS / "test_release.py").exists())
        self.assertGreaterEqual(len(modules()), 2)
        loaded = {}
        for path in modules():
            suite = unittest.defaultTestLoader.loadTestsFromName(f"tests.{path.stem}")
            self.assertGreaterEqual(suite.countTestCases(), 1, path.name)  # SI-P83-14
            for test in iter_tests(suite):
                key = tuple(test.id().split(".")[-2:])
                loaded.setdefault(key, []).append(path.stem)
        found = {}
        for path in modules():
            source = Source(path)
            for cls, func in source.functions():
                found.setdefault((cls.name, func.name), []).append((
                    comment(source.lines[cls.lineno - 1]), comment(source.lines[func.lineno - 1]),
                    source.text(func)))
        for cls, method, cls_note, def_note, sha in REFERENCE:
            with self.subTest(test=f"{cls}.{method}"):
                self.assertEqual(len(loaded.get((cls, method), [])), 1, loaded.get((cls, method)))
                [(got_cls, got_def, text)] = found[(cls, method)]
                self.assertEqual((got_cls, got_def), (cls_note, def_note))
                if method == "test_dev_then_stable":
                    self.assertEqual(text.count(NEW_REGEX), 1)
                    text = text.replace(NEW_REGEX, OLD_REGEX)
                self.assertEqual(digest(text), sha)
        self.assertEqual(len(REFERENCE), 44)
        self.assertEqual(sum(len(v) for v in loaded.values()), len(loaded))  # no id twice

    def test_the_helpers_and_constants_are_unchanged_outside_test_modules(self):
        shared = Source(TESTS / "release_helpers.py")
        texts = [digest(s.text(f)) for s in (shared, *map(Source, modules()))
                 for _, f in s.functions()]
        for name, sha in HELPERS:
            with self.subTest(helper=name):
                self.assertIn(sha, texts)
        top = {}
        for node in shared.tree.body:
            if isinstance(node, (ast.Assign, ast.FunctionDef)):
                name = node.name if isinstance(node, ast.FunctionDef) else ast.unparse(
                    node.targets[0])
                top[name] = digest(shared.text(node))
        for name, sha in CONSTANTS:
            self.assertEqual(top.get(name), sha, name)
        for path in modules():  # the bases and the constants live in release_helpers only
            source = Source(path)
            module = importlib.import_module(f"tests.{path.stem}")
            for cls in source.classes():
                if issubclass(getattr(module, cls.name), unittest.TestCase):
                    self.assertTrue(any(f.name.startswith("test") for f in cls.body
                                        if isinstance(f, ast.FunctionDef)),
                                    f"{path.name} {cls.name}")
            names = {t.id for n in source.tree.body if isinstance(n, ast.Assign)
                     for t in n.targets if isinstance(t, ast.Name)}
            self.assertEqual(names & {name for name, _ in CONSTANTS}, set(), path.name)

    def test_a_test_that_starts_from_a_finished_dev_release_uses_the_snapshot(self):
        starts, marked = set(), set()
        for path in modules():
            source = Source(path)
            for cls in source.classes():
                for node in cls.body:
                    if isinstance(node, ast.Assign) and ast.unparse(
                            node.targets[0]) == "FROM_DEV_RELEASE":
                        marked |= {(cls.name, n) for n in ast.literal_eval(node.value)}
                    if isinstance(node, ast.FunctionDef) and node.name.startswith("test") and \
                            ast.dump(node.body[0]) == ast.dump(ast.parse(FIRST_RELEASE).body[0]):
                        starts.add((cls.name, node.name))
        self.assertEqual(starts - marked, set())
        self.assertGreaterEqual(starts, {("AllOrNothingTest", "test_each_failing_step"),
                                         ("NoopTest", "test_twice_then_a_change")})

    def test_the_snapshot_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, dest = Path(tmp).resolve() / "snapshot", Path(tmp).resolve() / "test"
            dest.mkdir()
            work, bare = source / "work tree", source / "origin.git"
            work.mkdir(parents=True)
            git(work, "init", "-q", "-b", "main")
            (work / "a.txt").write_text("a\n")
            git(work, "add", "a.txt")
            git(work, "commit", "-q", "-m", "a")
            subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
            git(work, "remote", "add", "origin", str(bare))
            git(work, "remote", "add", "elsewhere", "/nonexistent/other.git")
            git(work, "push", "-q", "origin", "main")
            (source / "bin").mkdir()  # not a repository: not copied
            (source / "work tree/link").symlink_to("a.txt")
            before = tree_hash(source)
            self.assertEqual(copy_repos(source, dest), ["origin.git", "work tree"])
            self.assertEqual(sorted(p.name for p in dest.iterdir()), ["origin.git", "work tree"])
            copy = dest / "work tree"
            self.assertEqual(git(copy, "remote", "get-url", "origin").strip(),
                             str(dest / "origin.git"))
            self.assertEqual(git(copy, "remote", "get-url", "elsewhere").strip(),
                             "/nonexistent/other.git")
            self.assertTrue((copy / "link").is_symlink())
            (copy / "b.txt").write_text("b\n")
            git(copy, "add", "b.txt")
            git(copy, "commit", "-q", "-m", "b")
            git(copy, "push", "-q", "origin", "main")  # into the copied remote
            self.assertEqual(git(dest / "origin.git", "log", "--format=%s", "main").split(),
                             ["b", "a"])
            self.assertEqual(git(bare, "log", "--format=%s", "main").split(), ["a"])
            self.assertEqual(tree_hash(source), before)  # the snapshot is only read


class DocsTest(unittest.TestCase):  # P83-AC-022
    def flat(self, text: str) -> str:
        return " ".join(text.split())

    def test_releasing_the_docstring_and_the_changelog(self):
        doc = self.flat((ENGINE / "docs/releasing.md").read_text(encoding="utf-8"))
        tool = (ENGINE / "tools/release.py").read_text(encoding="utf-8")
        docstring = self.flat(ast.get_docstring(ast.parse(tool)))
        for text in (doc, docstring):
            for needle in ("runs each `tests/test_*.py` module in its own process",
                           "`--jobs N` at a time (1–32, default `min(4, CPU count)`)",
                           "the `test_release*` modules first",
                           "`--suite-passed TREE`", "`HEAD^{tree}`",
                           "--suite-passed <TREE> is not this engine's tree <tree> — leave the "
                           "flag out and the suite runs",
                           "the adoption eval always runs", "on both channels",
                           "kill every running test process group"):
                self.assertIn(needle, text)
        changes = (ENGINE / "CHANGELOG.md").read_text(encoding="utf-8")
        unreleased = changelog_since_first_release(changes)
        for flag in ("`--jobs N`", "`--suite-passed TREE`"):
            self.assertIn(flag, unreleased)


def iter_tests(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from iter_tests(test)
        else:
            yield test


if __name__ == "__main__":
    unittest.main()
