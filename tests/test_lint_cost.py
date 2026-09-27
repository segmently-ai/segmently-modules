"""D0 (Task 0): `lint --changed` never computes MS053, and MS053 routes files through the
`[[code_map]]` rules only — docs and `code_pointer` sources are never evaluated for it."""
import subprocess
import tempfile
import unittest
from dataclasses import asdict
from unittest import mock

from modsys import lint as linter
from modsys.changes import code_map_routes, routes
from modsys.lint import drift_report, lint_registry, severity_counts
from modsys.workspace import Workspace
from tests.helpers import init_git, make_repo, mutate_registry, run_json
from tests.test_overlap_lint import MODULES, TAIL, rule

OVERLAP = rule("a", "m1", "lib/**") + rule("b", "m2", "lib/**")
FIELD = ('[fields.code_paths]\ntype = "string[]"\nkind = "code_pointer"\n'
         'scope = ["module", "submodule"]\n')


class Repo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.n = 0

    def tearDown(self):
        self._tmp.cleanup()

    def repo(self, config: str, files=("lib/x.py",)):
        self.n += 1
        root = make_repo(f"{self._tmp.name}/{self.n}", MODULES, config, files)
        init_git(root)
        return root


class LintChangedSkipsOverlapTest(Repo):  # P4A-AC-001
    def calls(self, root, *argv) -> tuple[int, dict]:
        with mock.patch("modsys.lint.overlap_findings", wraps=linter.overlap_findings) as spy:
            code, env, err = run_json(*argv, "--root", str(root))
        self.assertEqual((code, err), (0, ""))
        return spy.call_count, env["data"]

    def test_each_verb_computes_the_overlap_check_at_most_once(self):
        root = self.repo(OVERLAP)
        (root / "lib/x.py").write_text("x = 2\n")
        n, data = self.calls(root, "lint", "--fail-on", "never")
        self.assertEqual((n, [f["code"] for f in data["findings"]].count("MS053")), (1, 1))
        n, data = self.calls(root, "lint", "--changed", "--base", "HEAD", "--fail-on", "never")
        self.assertEqual((n, [f["code"] for f in data["findings"]]), (0, ["MS050", "MS050"]))
        n, data = self.calls(root, "ci", "--base", "HEAD", "--fail-on", "never")
        lint_step, drift_step = data["steps"][0], data["steps"][1]
        self.assertEqual(n, 1)
        self.assertIn("MS053", [f["code"] for f in lint_step["findings"]])
        self.assertEqual([f["code"] for f in drift_step["findings"]], ["MS050", "MS050"])

    def test_zero_or_one_rule_never_computes_it_under_changed(self):
        for config in ("", rule("a", "m1", "lib/**")):
            with self.subTest(rules=config.count("[[code_map]]")):
                root = self.repo(config)
                (root / "lib/x.py").write_text("x = 2\n")
                n, _ = self.calls(root, "lint", "--changed", "--base", "HEAD", "--fail-on",
                                  "never")
                self.assertEqual(n, 0)

    def test_changed_data_equals_the_computed_then_dropped_result(self):
        """The 50e8b11 path computed MS053 and dropped it while narrowing; the data is equal."""
        root = self.repo(OVERLAP, files=("lib/x.py", "lib/y.py"))
        (root / "lib/x.py").write_text("x = 2\n")
        ws = Workspace.load(root)
        old, changed = drift_report(ws, "HEAD", lint_registry(ws, overlap=True))
        code, env, _ = run_json("lint", "--changed", "--base", "HEAD", "--fail-on", "never",
                                "--root", str(root))
        self.assertEqual(env["data"], {"findings": [asdict(f) for f in old],
                                       "summary": severity_counts(old), "failed": False,
                                       "changed": changed})

    def git_calls(self, root) -> list:
        with mock.patch("modsys.changes.subprocess.run", wraps=subprocess.run) as spy:
            code, _, err = run_json("lint", "--changed", "--base", "HEAD", "--fail-on", "never",
                                    "--root", str(root))
        self.assertEqual((code, err), (0, ""))
        return [c.args[0][3:] for c in spy.call_args_list]

    def test_no_whole_repository_listing_under_changed(self):
        with_rules, without = self.repo(OVERLAP), self.repo("")
        for root in (with_rules, without):
            (root / "lib/x.py").write_text("x = 2\n")
        calls = self.git_calls(with_rules)
        self.assertEqual(calls, self.git_calls(without))
        self.assertNotIn(["rev-parse", "--is-inside-work-tree"], calls)
        self.assertNotIn(["ls-files", "-z"], calls)  # the tracked-file listing of MS053


class OverlapSourcesTest(Repo):  # P4A-AC-002
    def pointer_repo(self):
        root = self.repo(FIELD + OVERLAP)

        def point_everything_at_lib(data):
            for entry in data["modules"].values():
                entry["code_paths"] = ["lib/"]
                for child in (entry.get("submodules") or {}).values():
                    child["code_paths"] = ["lib/"]

        mutate_registry(root, point_everything_at_lib)
        return root

    def test_findings_are_unchanged_with_docs_and_pointers_on_the_same_files(self):
        root = self.pointer_repo()
        with mock.patch("modsys.changes._pointer_paths",
                        side_effect=AssertionError("code_pointer evaluated")):
            code, env, err = run_json("lint", "--fail-on", "never", "--root", str(root))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual([f["message"] for f in env["data"]["findings"] if f["code"] == "MS053"],
                         ["[[code_map]] 'a' (-> m1) and 'b' (-> m2) both map 1 file(s), "
                          "e.g. lib/x.py" + TAIL])

    def test_the_rule_routes_never_carry_docs_or_pointer_sources(self):
        root = self.pointer_repo()
        ws = Workspace.load(root)
        files = ["lib/x.py", "modules/m1/MODULE.md"]
        self.assertEqual(list(code_map_routes(ws, files)),
                         [("lib/x.py", "m1", "a"), ("lib/x.py", "m2", "b")])
        self.assertEqual({via.partition(":")[0] for _, _, via in routes(ws, files)},
                         {"docs", "code_pointer", "code_map"})

    def test_code_map_files_keeps_every_source(self):
        root = self.pointer_repo()
        code, env, _ = run_json("code-map", "files", "m1", "--root", str(root))
        via = {f["path"]: f["via"] for f in env["data"]["files"]}
        self.assertEqual((code, via["lib/x.py"], via["modules/m1/MODULE.md"]),
                         (0, ["code_pointer:code_paths", "code_map:a"], ["docs"]))


if __name__ == "__main__":
    unittest.main()
