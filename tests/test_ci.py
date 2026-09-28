"""`modsys ci`: one gate — lint, drift since --base, coverage — always all three steps; and
the docs describe the whole P3.2 surface."""
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from modsys.cli import build_parser
from tests.helpers import git, init_git, make_repo, run, run_json
from tests.test_cli_contract import GOLDEN

ENGINE = Path(__file__).resolve().parents[1]

RULE = '[[code_map]]\nid = "src"\npattern = "src/{module}/**"\n'
GHOST = '[[code_map]]\nid = "typo"\nmodule = "ghost"\nglobs = ["g/**"]\n'
NOTE = "nothing to compare: the working tree equals HEAD — in CI pass --base <target branch>"


class CiRepo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_repo(self._tmp.name, {"tasks": ["task"], "lists": ["list"]}, RULE,
                              ("src/tasks/a.py", "src/lists/b.py"))
        init_git(self.root)
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def ci(self, *argv, code=0) -> dict:
        got, env, err = run_json("ci", *argv, *self.R)
        self.assertEqual((got, err, env["schema"]), (code, "", "modsys.ci/1"))
        return env["data"]

    def statuses(self, data) -> list:
        return [s["status"] for s in data["steps"]]

    def config(self, text: str) -> None:
        (self.root / ".modsys/config.toml").write_text(RULE + text, encoding="utf-8")

    def touch(self, *rels) -> None:
        for rel in rels:
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write("# changed\n")


class CiStepsTest(CiRepo):  # P32-AC-018
    def test_a_documented_change_passes(self):
        self.touch("src/tasks/a.py", "modules/tasks/MODULE.md")
        data = self.ci()
        self.assertEqual(self.statuses(data), ["passed", "passed", "report-only"])
        self.assertEqual((data["failed"], data["notes"]), (False, []))

    def test_a_config_level_warning_fails_lint(self):
        self.config(GHOST)
        data = self.ci(code=1)
        self.assertEqual(self.statuses(data)[0], "failed")
        self.assertEqual([f["code"] for f in data["steps"][0]["findings"]], ["MS052"])

    def test_a_code_only_change_fails_drift(self):
        self.touch("src/tasks/a.py")
        data = self.ci(code=1)
        self.assertEqual(self.statuses(data), ["passed", "failed", "report-only"])
        self.assertEqual([(f["code"], f["module"]) for f in data["steps"][1]["findings"]],
                         [("MS050", "tasks")])

    def test_the_coverage_threshold(self):
        self.touch("README.md", "tools/t.py")  # 2 of 4 counted files unmapped: share 0.5
        data = self.ci("--fail-under", "80", code=1)
        self.assertEqual(self.statuses(data), ["passed", "passed", "failed"])
        self.assertEqual({k: data["steps"][2]["summary"][k] for k in ("share", "unmapped")},
                         {"share": 0.5, "unmapped": 2})
        self.config("[ci]\ncoverage_fail_under = 40\n")
        self.assertEqual(self.statuses(self.ci())[2], "passed")

    def test_a_clean_tree_against_head_has_nothing_to_compare(self):
        data = self.ci()
        self.assertEqual((self.statuses(data)[1], data["notes"]), ("no-changes", [NOTE]))
        self.assertEqual(data["steps"][1]["findings"], [])

    def test_fail_on_error_lets_warnings_pass(self):
        self.config(GHOST)
        self.touch("src/tasks/a.py")
        self.assertEqual(self.statuses(self.ci("--fail-on", "error")),
                         ["passed", "passed", "report-only"])

    def test_every_step_runs_and_reports_in_order(self):
        self.config(GHOST)
        self.touch("src/tasks/a.py", "README.md")
        data = self.ci("--fail-under", "100", code=1)
        self.assertEqual([(s["name"], s["status"]) for s in data["steps"]],
                         [("lint", "failed"), ("drift", "failed"), ("coverage", "failed")])

    def test_usage_errors_stop_before_any_step(self):
        injected = Path(self._tmp.name) / "injected.txt"
        for argv, needle in [(("--base", "nosuch"), "'nosuch' is not a commit"),
                             (("--base=-x",), "may not start with '-'"),
                             ((f"--base=--output={injected}",), "may not start with '-'"),
                             (("--fail-under", "101"), "--fail-under must be between 0 and 100")]:
            with self.subTest(argv=argv), mock.patch("modsys.ci_cmd.lint_registry") as lint:
                code, out, err = run("ci", *argv, "--json", *self.R)
                self.assertEqual((code, out), (2, ""))
                self.assertIn(needle, err)
                lint.assert_not_called()
        self.assertFalse(injected.exists())

    def test_outside_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            plain = make_repo(tmp, {"tasks": ["task"]})
            code, out, err = run("ci", "--json", "--root", str(plain))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("ci needs a git repository", err)

    def test_before_the_first_commit(self):  # M-1
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp, {"tasks": ["task"]})
            git(root, "init", "-q", "-b", "main")
            code, out, err = run("ci", "--json", "--root", str(root))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("the repository has no commit yet — commit first", err)
        self.assertNotIn("fetch", err)

    def test_unknown_base_names_where_it_came_from(self):  # M-1
        self.touch("src/tasks/a.py")
        git(self.root, "commit", "-q", "-am", "code only")
        code, out, err = run("ci", "--base", "nosuch", "--json", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("--base 'nosuch' is not a commit in this repository", err)
        self.config('[ci]\nbase = "nosuch"\n')
        code, out, err = run("ci", "--json", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("[ci] base 'nosuch' is not a commit in this repository", err)


class CiOptionsTest(CiRepo):  # P32-AC-019
    def test_fail_on_precedence(self):
        self.touch("src/tasks/a.py")
        self.config('[ci]\nfail_on = "error"\n')
        self.assertEqual((self.ci()["fail_on"], self.statuses(self.ci())[1]), ("error", "passed"))
        data = self.ci("--fail-on", "warning", code=1)
        self.assertEqual((data["fail_on"], self.statuses(data)[1]), ("warning", "failed"))
        self.config("")
        self.assertEqual(self.ci(code=1)["fail_on"], "warning")

    def test_drift_base_precedence(self):
        first = git(self.root, "rev-parse", "HEAD").strip()
        self.touch("src/tasks/a.py")
        git(self.root, "commit", "-q", "-am", "code only")
        self.assertEqual(self.ci()["base"], "HEAD")
        self.config(f'[ci]\nbase = "{first}"\n')
        data = self.ci(code=1)
        self.assertEqual((data["base"], self.statuses(data)[1]), (first, "failed"))
        data = self.ci("--base", "HEAD")
        self.assertEqual((data["base"], self.statuses(data)[1]), ("HEAD", "passed"))

    def test_threshold_precedence(self):
        self.touch("README.md", "tools/t.py")
        self.assertEqual(self.statuses(self.ci())[2], "report-only")
        self.config("[ci]\ncoverage_fail_under = 40\n")
        self.assertEqual(self.ci()["steps"][2]["summary"]["fail_under"], 40)
        self.assertEqual(self.statuses(self.ci("--fail-under", "80", code=1))[2], "failed")

    def test_json_shape_and_text(self):
        self.touch("src/tasks/a.py")
        data = self.ci(code=1)
        self.assertEqual(set(data), {"base", "fail_on", "steps", "failed", "notes"})
        self.assertEqual([set(s) for s in data["steps"]],
                         [{"name", "status", "summary", "findings"},
                          {"name", "status", "summary", "findings"},
                          {"name", "status", "summary"}])
        code, out, _ = run("ci", *self.R)
        lines = out.splitlines()
        self.assertEqual(code, 1)
        self.assertEqual([l.split()[:2] for l in lines if not l.startswith(" ")][:3],
                         [["lint", "passed"], ["drift", "failed"], ["coverage", "report-only"]])
        self.assertIn("  WARNING MS050 tasks: code changed (1 file(s)) but none of its docs", lines)
        self.assertEqual(lines[-1], "ci: failed")
        self.touch("modules/tasks/MODULE.md")
        self.assertEqual(run("ci", *self.R)[1].splitlines()[-1], "ci: passed")

    def test_a_failed_coverage_step_lists_unmapped_paths(self):  # M-5
        for i in range(6):
            self.touch(f"extra/e{i:02}.py")
        out = run("ci", "--fail-under", "100", *self.R)[1]
        unmapped = sorted(f"extra/e{i:02}.py" for i in range(6))
        for path in unmapped[:5]:
            self.assertIn(f"  {path}", out.splitlines())
        self.assertNotIn(unmapped[5], out)
        self.assertIn("run modsys coverage for the full list", out)

    def test_text_mode_note_and_no_changes_summary(self):  # M-10
        code, out, _ = run("ci", *self.R)
        lines = out.splitlines()
        self.assertEqual(code, 0)
        drift_line = next(l for l in lines if l.split()[0] == "drift")
        self.assertEqual(drift_line.split()[:2], ["drift", "no-changes"])
        self.assertIn("no changed files since HEAD", drift_line)
        self.assertIn(f"note: {NOTE}", lines)
        self.assertEqual(lines[-1], "ci: passed")


class DriftSplitTest(CiRepo):  # P5A-AC-008 (D0b)
    def drift(self, *argv) -> dict:
        return self.ci("--fail-on", "never", *argv)["steps"][1]

    def counts(self, *argv) -> tuple:
        s = self.drift(*argv)["summary"]
        return s["committed"], s["uncommitted"], s["files"]

    def commit(self, *rels) -> None:
        self.touch(*rels)
        git(self.root, "add", "--", *rels)
        git(self.root, "commit", "-q", "-m", "change")

    def test_the_decision_table(self):
        self.commit("src/tasks/b.py", "src/tasks/d.py")
        base = git(self.root, "rev-parse", "HEAD").strip()
        self.assertEqual(self.counts("--base", base), (0, 0, 0))
        self.assertEqual(self.drift("--base", base)["status"], "no-changes")
        self.commit("src/tasks/a.py")
        self.assertEqual(self.counts("--base", base), (1, 0, 1))
        self.touch("src/tasks/b.py")
        self.assertEqual(self.counts("--base", base), (1, 1, 2))
        self.touch("src/lists/c.py")  # untracked
        self.assertEqual(self.counts("--base", base), (1, 2, 3))
        self.commit("src/tasks/d.py")
        self.touch("src/tasks/d.py")
        self.assertEqual(self.counts("--base", base), (2, 3, 4))
        self.assertEqual(self.counts("--base", "HEAD"), (0, 3, 3))
        self.assertEqual(set(self.drift("--base", base)["summary"]),
                         {"base", "files", "committed", "uncommitted", "modules", "error",
                          "warning", "info"})
        out = run("ci", "--base", base, "--fail-on", "never", *self.R)[1]
        self.assertIn(f"4 file(s) changed since {base} (2 committed, 3 uncommitted)", out)


class CiConfigTest(CiRepo):  # P32-AC-020, P32-AC-022
    def test_values(self):
        for text, needle in [("coverage_fail_under = -0.1", "0–100"),
                             ("coverage_fail_under = 100.5", "0–100"),
                             ('coverage_fail_under = "80"', "expected a number"),
                             ("coverage_fail_under = true", "expected a number"),
                             ('fail_on = "sometimes"', "error, never, warning"),
                             ("base = 5", "expected a string")]:
            with self.subTest(text=text):
                self.config(f"[ci]\n{text}\n")
                code, out, err = run("ci", "--json", *self.R)
                self.assertEqual((code, out), (2, ""))
                self.assertIn("config.toml: [ci]", err)
                self.assertIn(needle, err)
        for text in ("coverage_fail_under = 0", "coverage_fail_under = 100",
                     "coverage_fail_under = 79.5", "coverage_fail_under = 80", 'colour = "x"'):
            with self.subTest(text=text):
                self.config(f"[ci]\n{text}\n")
                self.assertIn(run("ci", *self.R)[0], (0, 1))

    def test_garbage_config_and_interrupt(self):
        (self.root / ".modsys/config.toml").write_text("code_map = 5\n")
        code, out, err = run("ci", "--json", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertNotIn("Traceback", err)
        self.config("")
        with mock.patch("modsys.ci_cmd.lint_registry", side_effect=KeyboardInterrupt):
            self.assertEqual(run("ci", *self.R)[0], 130)


class DocsAndVerbsTest(unittest.TestCase):  # P32-AC-021
    VERBS = {"init", "schema", "match", "show", "related", "list", "lint", "registry", "index",
             "propose", "proposals", "hooks", "sync", "create", "migrate", "context", "discover",
             "coverage", "code-map", "ci", "templates", "packs", "eject", "agents-md",
             "sync-instructions", "adopt", "eval"}  # P5a D6: + adopt; P5b D3: + eval

    def doc(self, rel: str) -> str:
        return " ".join((ENGINE / rel).read_text(encoding="utf-8").split())

    def test_twenty_verbs_everywhere(self):
        parser = set(build_parser()._subparsers._group_actions[0].choices)
        contract = set(re.findall(r"^\| `([a-z-]+)",
                                  (ENGINE / "docs/cli-contract.md").read_text(encoding="utf-8"),
                                  re.M))
        self.assertEqual((parser, contract, {argv[0] for argv, _ in GOLDEN}), (self.VERBS,) * 3)

    def test_the_docs_describe_the_p32_surface(self):
        contract, config = self.doc("docs/cli-contract.md"), self.doc("docs/configuration.md")
        for needle in ("`code-map list\\|add\\|files`", "| `ci` |", "near_misses: [{module, score",
                       "keywords, read:", "missing_files", "files: [{path, modules: [target]}]",
                       "every `score` are `null`", "defaults to `$MODSYS_AGENT`, else `cli`"):
            self.assertIn(needle, contract)
        for needle in ("## `[ci]`", "| `overlap_severity` |", "| MS053 |",
                       'has no {module} segment — for a fixed module use globs = ["docs/**"]',
                       "routes nothing for that file", "-> (no module)",
                       "Add rules with `modsys code-map add` (the preferred way)"):
            self.assertIn(needle, config)
        self.assertIn("modsys ci --base origin/main", self.doc("README.md"))


if __name__ == "__main__":
    unittest.main()
