"""Lint MS053: two [[code_map]] rules route the same file to two different targets."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from unittest import mock

from tests.helpers import init_git, make_repo, run, run_json

MODULES = {"m1": ["one"], "m2": ["two"], "m3": ["three"], "db": ["database"],
           "tasks": ["task"], "catalog": ["book"], "catalog/search": ["search"],
           "catalog/admin": ["admin"]}
TAIL = " — mark the more specific rule exclusive = true or narrow its globs"


def rule(rule_id: str, target: str | None, glob: str, exclusive: bool = False) -> str:
    key = f'module = "{target}"\nglobs = ["{glob}"]\n' if target else f'pattern = "{glob}"\n'
    return f'[[code_map]]\nid = "{rule_id}"\n{key}' + ("exclusive = true\n" if exclusive else "")


class OverlapTest(unittest.TestCase):  # P32-AC-014
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.n = 0

    def tearDown(self):
        self._tmp.cleanup()

    def ms053(self, config: str, files):
        self.n += 1
        root = make_repo(f"{self._tmp.name}/{self.n}", MODULES, config, files)
        init_git(root)
        code, env, err = run_json("lint", "--fail-on", "never", "--root", str(root))
        self.assertEqual((code, err), (0, ""))
        found = [f for f in env["data"]["findings"] if f["code"] == "MS053"]
        for f in found:
            self.assertEqual((f["severity"], f["module"], f["path"]), ("warning", "*", None))
        return [f["message"] for f in found]

    def test_a_pattern_and_a_broad_layer_rule(self):
        config = rule("feat", None, "app/{module}/**") + rule("db", "db", "app/**")
        self.assertEqual(self.ms053(config, ["app/tasks/x.py"]), [
            "[[code_map]] 'db' (-> db) and 'feat' (-> tasks) both map 1 file(s), "
            "e.g. app/tasks/x.py" + TAIL])
        config = rule("feat", None, "app/{module}/**", exclusive=True) + rule("db", "db", "app/**")
        self.assertEqual(self.ms053(config, ["app/tasks/x.py"]), [])

    def test_parent_and_child_do_not_overlap_siblings_do(self):
        files = ["lib/x.py"]
        self.assertEqual(self.ms053(rule("a", "catalog", "lib/**")
                                    + rule("b", "catalog/search", "lib/**"), files), [])
        self.assertEqual(self.ms053(rule("a", "catalog/search", "lib/**")
                                    + rule("b", "catalog/admin", "lib/**"), files), [
            "[[code_map]] 'a' (-> catalog/search) and 'b' (-> catalog/admin) both map 1 "
            "file(s), e.g. lib/x.py" + TAIL])

    def test_two_rules_to_the_same_target(self):
        self.assertEqual(self.ms053(rule("a", "tasks", "lib/**") + rule("b", "tasks", "lib/*.py"),
                                    ["lib/x.py"]), [])

    def test_one_finding_per_pair(self):
        config = rule("c", "m3", "lib/**") + rule("a", "m1", "lib/**") + rule("b", "m2", "lib/**")
        self.assertEqual([m.split(" both")[0] for m in self.ms053(config, ["lib/x.py"])], [
            "[[code_map]] 'a' (-> m1) and 'b' (-> m2)",
            "[[code_map]] 'a' (-> m1) and 'c' (-> m3)",
            "[[code_map]] 'b' (-> m2) and 'c' (-> m3)"])

    def test_count_and_first_path(self):
        files = [f"shared/f{i:02}.py" for i in (11, 3, 0, 7, 1, 2, 4, 5, 6, 8, 9, 10)]
        self.assertEqual(self.ms053(rule("b", "m2", "shared/**") + rule("a", "m1", "shared/**"),
                                    files), [
            "[[code_map]] 'a' (-> m1) and 'b' (-> m2) both map 12 file(s), e.g. shared/f00.py"
            + TAIL])

    def test_a_capture_naming_no_module_routes_nothing(self):
        config = rule("feat", None, "app/{module}/**") + rule("db", "db", "app/**")
        self.assertEqual(self.ms053(config, ["app/base/x.py"]), [])


class OverlapConfigTest(unittest.TestCase):  # P32-AC-015, P32-AC-016 (git calls)
    OVERLAP = rule("a", "m1", "lib/**") + rule("b", "m2", "lib/**")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.n = 0

    def tearDown(self):
        self._tmp.cleanup()

    def repo(self, config: str, git=True):
        self.n += 1
        root = make_repo(f"{self._tmp.name}/{self.n}", MODULES, config, ["lib/x.py"])
        if git:
            init_git(root)
        return root

    def test_severity_is_configurable(self):
        root = self.repo(self.OVERLAP + '[lint]\noverlap_severity = "error"\n')
        code, env, _ = run_json("lint", "--root", str(root))
        self.assertEqual(code, 1)
        self.assertEqual([f["severity"] for f in env["data"]["findings"] if f["code"] == "MS053"],
                         ["error"])
        (root / ".segmently-modules/config.toml").write_text(self.OVERLAP + '[lint]\noverlap_severity = '
                                                                 '"info"\n')
        _, env, _ = run_json("lint", "--root", str(root))
        self.assertEqual([f["severity"] for f in env["data"]["findings"] if f["code"] == "MS053"],
                         ["info"])
        (root / ".segmently-modules/config.toml").write_text('[lint]\noverlap_severity = "loud"\n')
        code, out, err = run("lint", "--root", str(root))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("config.toml: [lint] overlap_severity: expected info, warning or error", err)

    def git_calls(self, root, *argv) -> list:
        with mock.patch("segmently_modules.changes.subprocess.run", wraps=subprocess.run) as spy:
            code, env, err = run_json("lint", "--fail-on", "never", *argv, "--root", str(root))
        self.assertEqual((code, err), (0, ""))
        return [c.args[0][3:5] for c in spy.call_args_list]

    def test_without_rules_or_git_the_check_is_skipped(self):
        self.assertEqual(self.git_calls(self.repo("", git=False)), [])  # no git command at all
        # one rule outside git: MS053 needs two, MS054 asks git once whether it is a work tree
        self.assertEqual(self.git_calls(self.repo(rule("a", "m1", "lib/**"), git=False)),
                         [["rev-parse", "--is-inside-work-tree"]])
        root = self.repo(self.OVERLAP, git=False)
        self.assertEqual(self.git_calls(root), [["rev-parse", "--is-inside-work-tree"]])

    def test_one_ls_files_pair_per_lint(self):
        root = self.repo(self.OVERLAP)
        self.assertEqual(self.git_calls(root), [["rev-parse", "--is-inside-work-tree"],
                                                ["ls-files", "-z"], ["ls-files", "-z"]])

    def test_lint_changed_drops_it(self):
        root = self.repo(self.OVERLAP)
        (root / "lib/x.py").write_text("x = 2\n")
        _, env, _ = run_json("lint", "--changed", "--fail-on", "never", "--root", str(root))
        self.assertEqual([f["code"] for f in env["data"]["findings"]], ["MS050", "MS050"])


if __name__ == "__main__":
    unittest.main()
