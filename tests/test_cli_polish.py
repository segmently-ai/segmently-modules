"""CLI polish from the adoption eval: diff-only discover, help texts that state the rules,
doc_append spacing, lint's quiet summary, the components-table comment in the template."""
import tempfile
import unittest
from pathlib import Path

from modsys.proposals import join_blocks
from tests.helpers import copy_fixture, git, run, run_json

DESC = "Customer reviews of books: ratings, comments and moderation."
KW = [a for k in ("review", "rating", "stars", "comment", "moderation") for a in ("--keyword", k)]


def flat(text: str) -> str:
    return " ".join(text.split())  # argparse wraps help text at the terminal width


class DiscoverWithoutTaskTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def test_change_alone_is_enough(self):
        code, env, err = run_json("discover", "--files", "src/catalog/service.py", *self.R)
        self.assertEqual((code, err), (0, ""))
        self.assertIsNone(env["data"]["task"])
        [row] = env["data"]["modules"]
        self.assertEqual((row["module"], row["usage"], row["sources"], row["score"]),
                         ("catalog", "modify", ["diff"], None))  # D3(c): no task, no score

    def test_neither_task_nor_change_is_refused(self):
        for argv, needle in [((), "give the task"), (("--task", " ", "--files", "a.py"),
                                                      "give the task")]:
            with self.subTest(argv=argv):
                code, out, err = run("discover", *argv, *self.R)
                self.assertEqual((code, out), (2, ""))
                self.assertIn(needle, err)


class HelpTextTest(unittest.TestCase):
    def test_create_help_states_the_answer_limits(self):
        code, out, _ = run("create", "--help")
        self.assertEqual(code, 0)
        for needle in ("description_min–description_max characters (default 20–200)",
                       "at least [create] min_keywords distinct keywords (default 5)",
                       "a child module at least 1"):
            self.assertIn(needle, flat(out))

    def test_propose_doc_help_says_repo_relative(self):
        code, out, _ = run("propose", "--help")
        self.assertEqual(code, 0)
        self.assertIn("repo-relative path of a .md doc inside the module's own directory "
                      "(e.g. modules/<m>/roles/developer.md)", flat(out))

    def test_discover_help_names_both_inputs(self):
        self.assertIn("--task and/or --from-diff / --files", flat(run("discover", "--help")[1]))


class DocAppendSpacingTest(unittest.TestCase):
    def test_exactly_one_blank_line_between_blocks(self):
        cases = [("A\n", "B", "A\n\nB"), ("A", "B\n", "A\n\nB\n"), ("A\n\n \n\n", "\n\nB", "A\n\nB"),
                 ("A  \n", "B", "A  \n\nB"), ("", "\nB", "B"), ("\n\n", "B", "B")]
        for current, text, expected in cases:
            with self.subTest(current=current, text=text):
                self.assertEqual(join_blocks(current, text), expected)

    def test_applied_doc_append_is_separated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            dev = "modules/catalog/roles/developer.md"
            run("propose", "--module", "catalog", "--op", "doc_append", "--doc", dev,
                "--value", "## Gotchas\n\nISBN-10 ends in X.", "--reason", "r", "--run-id", "r1",
                "--root", str(root))
            self.assertEqual(run("proposals", "apply", "--root", str(root))[0], 0)
            self.assertEqual((root / dev).read_text(),
                             "# Catalog — developer\n\n## Gotchas\n\nISBN-10 ends in X.\n")


class QuietLintAndTemplateTest(unittest.TestCase):
    def test_lint_without_findings_prints_only_the_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            git(root, "init", "-q", "-b", "main")
            run("init", "--root", str(root))
            code, out, _ = run("lint", "--root", str(root))
        self.assertEqual((code, out), (0, "0 error(s), 0 warning(s), 0 info\n"))

    def test_module_template_explains_the_components_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            self.assertEqual(run("create", "reviews", "--description", DESC, *KW,
                                 "--non-interactive", "--root", str(root))[0], 0)
            text = (root / "modules/reviews/MODULE.md").read_text()
            _, env, _ = run_json("lint", "--fail-on", "never", "--root", str(root))
        section = text.split("## EXISTING Components")[1].split("## Usage")[0]
        for needle in ("<!--", "backticks", "MS040", "[[code_map]]", "code_pointer",
                       ".modsys/config.toml", "docs/configuration.md"):
            self.assertIn(needle, section)
        self.assertNotIn("reviews", {f["module"] for f in env["data"]["findings"]
                                     if f["code"] == "MS040"})


if __name__ == "__main__":
    unittest.main()
