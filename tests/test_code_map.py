"""[[code_map]]: child targets, `exclusive` precedence, MS052 for a rule that names no target."""
import tempfile
import unittest

from tests.helpers import copy_fixture, init_git, run, run_json

# A layered repo: `payments` stands in for a shared persistence layer that owns repo/**,
# while a feature's own repository file belongs to the feature (exclusive).
LAYERED = ('[[code_map]]\nid = "persistence"\nmodule = "payments"\nglobs = ["repo/**"]\n'
           '[[code_map]]\nid = "feature-repos"\npattern = "repo/{module}.py"\nexclusive = true\n')


class CodeMapTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def config(self, text: str) -> None:
        (self.root / ".modsys" / "config.toml").write_text(text, encoding="utf-8")

    def mapped(self, *files):
        code, env, err = run_json("sync", "--files", *files, "--dry-run", *self.R)
        self.assertEqual((code, err), (0, ""))
        return ({m["module"]: sorted(m["via"]) for m in env["data"]["modules"]},
                env["data"]["unmapped"])

    def test_globs_rule_can_target_a_child(self):
        self.config('[[code_map]]\nid = "refunds"\nmodule = "payments/refunds"\n'
                    'globs = ["billing/refunds/**"]\n')
        self.assertEqual(self.mapped("billing/refunds/api.py"),
                         ({"payments/refunds": ["code_map:refunds"]}, []))

    def test_pattern_captures_one_segment_naming_a_top_level_module(self):
        self.config('[[code_map]]\nid = "apps"\npattern = "apps/{module}/**"\n')
        modules, unmapped = self.mapped("apps/payments/refunds/x.py", "apps/refunds/x.py")
        self.assertEqual((modules, unmapped), ({"payments": ["code_map:apps"]},
                                               ["apps/refunds/x.py"]))

    def test_exclusive_rule_takes_the_file_from_other_rules(self):
        self.config(LAYERED)
        modules, unmapped = self.mapped("repo/catalog.py", "repo/base.py", "repo/checkout.py")
        self.assertEqual(modules, {"catalog": ["code_map:feature-repos"],
                                   "checkout": ["code_map:feature-repos"],
                                   "payments": ["code_map:persistence"]})
        _, env, _ = run_json("sync", "--files", "repo/catalog.py", "--dry-run", *self.R)
        self.assertEqual([m["module"] for m in env["data"]["modules"]], ["catalog"])
        self.assertEqual(unmapped, [])

    def test_exclusive_leaves_docs_and_code_pointers_alone(self):
        self.config('[[code_map]]\nid = "all"\nmodule = "checkout"\nglobs = ["**"]\n'
                    'exclusive = true\n')
        modules, _ = self.mapped("src/catalog/service.py", "modules/catalog/MODULE.md")
        self.assertEqual(modules, {"catalog": ["code_pointer:file_paths", "docs"],
                                   "checkout": ["code_map:all"]})

    def test_every_matching_exclusive_rule_maps_the_file(self):
        self.config('[[code_map]]\nid = "a"\nmodule = "catalog"\nglobs = ["shared/**"]\n'
                    'exclusive = true\n'
                    '[[code_map]]\nid = "b"\nmodule = "checkout"\nglobs = ["shared/*.py"]\n'
                    'exclusive = true\n'
                    '[[code_map]]\nid = "c"\nmodule = "payments"\nglobs = ["shared/**"]\n')
        self.assertEqual(self.mapped("shared/money.py")[0],
                         {"catalog": ["code_map:a"], "checkout": ["code_map:b"]})

    def test_exclusive_must_be_a_boolean(self):
        self.config('[[code_map]]\nid = "x"\nmodule = "catalog"\nglobs = ["a/**"]\n'
                    'exclusive = "yes"\n')
        code, out, err = run("sync", "--files", "a/b.py", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("code_map.x] exclusive: expected a boolean", err)

    def test_feature_change_in_a_layered_repo_drifts_only_the_feature(self):
        self.config(LAYERED)
        init_git(self.root)
        (self.root / "repo").mkdir()
        (self.root / "repo" / "catalog.py").write_text("x = 1\n")
        code, env, _ = run_json("lint", "--changed", "--fail-on", "warning", *self.R)
        self.assertEqual(code, 1)
        self.assertEqual([(f["code"], f["module"]) for f in env["data"]["findings"]],
                         [("MS050", "catalog")])


class UnknownTargetLintTest(unittest.TestCase):
    def test_rule_naming_no_registry_target_is_ms052(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            (root / ".modsys" / "config.toml").write_text(
                '[[code_map]]\nid = "ok"\nmodule = "payments/refunds"\nglobs = ["r/**"]\n'
                '[[code_map]]\nid = "typo"\nmodule = "payments/refund"\nglobs = ["t/**"]\n'
                '[[code_map]]\nid = "gone"\nmodule = "ghost"\nglobs = ["g/**"]\n'
                '[[code_map]]\nid = "apps"\npattern = "apps/{module}/**"\n', encoding="utf-8")
            code, env, _ = run_json("lint", "--fail-on", "error", "--root", str(root))
        found = [f for f in env["data"]["findings"] if f["code"] == "MS052"]
        self.assertEqual(code, 0)
        self.assertEqual([(f["severity"], f["module"]) for f in found],
                         [("warning", "*"), ("warning", "*")])
        self.assertIn("[[code_map]] 'typo': module 'payments/refund' is not a registry module",
                      found[0]["message"])
        self.assertIn("'gone'", found[1]["message"])


if __name__ == "__main__":
    unittest.main()
