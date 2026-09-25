"""sync: changed files -> modules, post_sync hooks, proposals."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

from tests.helpers import copy_fixture, git, init_git, run, run_json


class SyncMappingTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def modules(self, env):
        return {m["module"]: m["via"] for m in env["data"]["modules"]}

    def test_from_diff_maps_code_pointer(self):
        init_git(self.root)
        with (self.root / "src/catalog/service.py").open("a") as fh:
            fh.write("# changed\n")
        git(self.root, "commit", "-qam", "change")
        code, env, _ = run_json("sync", "--from-diff", "HEAD~1..HEAD", *self.R)
        self.assertEqual((code, env["schema"]), (0, "modsys.sync/1"))
        self.assertEqual(self.modules(env), {"catalog": ["code_pointer:file_paths"]})
        self.assertEqual(env["data"]["changed_files"], ["src/catalog/service.py"])

    def test_code_map_pattern_and_globs(self):
        (self.root / ".modsys" / "config.toml").write_text(
            '[[code_map]]\nid = "apps"\npattern = "apps/{module}/**"\n'
            '[[code_map]]\nid = "billing"\nmodule = "payments"\nglobs = ["billing/**", "*.pay"]\n',
            encoding="utf-8")
        _, env, _ = run_json("sync", "--files", "apps/checkout/cart.py", "apps/unknown/x.py",
                             "billing/api/charge.py", "fees.pay", "README.md", *self.R)
        self.assertEqual(self.modules(env), {"checkout": ["code_map:apps"],
                                             "payments": ["code_map:billing"]})
        self.assertEqual(env["data"]["unmapped"], ["README.md", "apps/unknown/x.py"])

    def test_docs_map_to_module_or_child(self):
        _, env, _ = run_json("sync", "--files", "modules/payments/submodules/refunds/MODULE.md",
                             "./modules/catalog/roles/qa.md", *self.R)
        self.assertEqual(self.modules(env), {"catalog": ["docs"], "payments/refunds": ["docs"]})

    def test_refusals(self):
        cases = [(("--files", "../outside.py"), "outside the repository"),
                 (("--from-diff", "nope..HEAD"), "git diff --name-only nope..HEAD failed")]
        for argv, needle in cases:
            with self.subTest(needle=needle):
                code, out, err = run("sync", *argv, *self.R)
                self.assertEqual((code, out), (2, ""))
                self.assertIn(needle, err)
        (self.root / ".modsys" / "config.toml").write_text(
            '[[code_map]]\nid = "x"\npattern = "apps/**"\n', encoding="utf-8")
        code, _, err = run("sync", "--files", "a.py", *self.R)
        self.assertEqual(code, 2)
        self.assertIn("pattern needs a {module} segment", err)


class SyncHooksAndProposalsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        self.R = ("--root", str(self.root))
        hook = self.root / "tools" / "tag.py"
        hook.parent.mkdir()
        hook.write_text(
            "import json, sys\n"
            "p = json.load(sys.stdin)\n"
            "print(json.dumps({'messages': ['modules: ' + ','.join(p['changed_modules'])],\n"
            "  'proposals': [{'op': 'append', 'module': m, 'field': 'keywords',\n"
            "                 'value': 'touched', 'reason': 'sync'} for m in p['changed_modules']]}))\n",
            encoding="utf-8")
        (self.root / ".modsys" / "config.toml").write_text(
            f'[[hooks.post_sync]]\nid = "tag"\nrun = [{json.dumps(sys.executable)}, "./tools/tag.py"]\n',
            encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_hook_proposals_applied_in_the_same_sync(self):
        code, env, _ = run_json("sync", "--files", "src/catalog/service.py", "--apply-proposals",
                                "--run-id", "r7", *self.R)
        self.assertEqual(code, 0)
        self.assertEqual(env["data"]["hooks"]["hooks"][0]["messages"], ["modules: catalog"])
        self.assertEqual(env["data"]["proposals"]["summary"]["applied"], 1)
        reg = json.loads((self.root / "modules/registry.json").read_text())
        self.assertIn("touched", reg["modules"]["catalog"]["keywords"])

    def test_dry_run_runs_no_hooks_and_writes_nothing(self):
        before = (self.root / "modules/registry.json").read_bytes()
        code, env, _ = run_json("sync", "--files", "src/catalog/service.py", "--dry-run",
                                "--apply-proposals", *self.R)
        self.assertEqual((code, env["data"]["hooks"]), (0, None))
        self.assertEqual((self.root / "modules/registry.json").read_bytes(), before)
        self.assertFalse((self.root / ".modsys/proposals").exists())

    def test_required_hook_failure_is_exit_1(self):
        (self.root / ".modsys" / "config.toml").write_text(
            f'[[hooks.post_sync]]\nid = "gate"\nrequired = true\n'
            f'run = [{json.dumps(sys.executable)}, "-c", "import sys; sys.exit(1)"]\n',
            encoding="utf-8")
        code, env, _ = run_json("sync", "--files", "src/catalog/service.py", *self.R)
        self.assertEqual(code, 1)
        self.assertEqual(env["data"]["hooks"]["hooks"][0]["status"], "failed")

    # acceptance gap tests (AC-021/023/024)
    def test_run_id_restricts_apply(self):
        run("propose", "--module", "checkout", "--op", "set", "--field", "status",
            "--value", '"draft"', "--reason", "r", "--run-id", "r1", *self.R)
        _, env, _ = run_json("sync", "--files", "src/catalog/service.py", "--apply-proposals",
                             "--run-id", "r7", *self.R)
        self.assertEqual([f["run_id"] for f in env["data"]["proposals"]["files"]], ["r7"])
        self.assertEqual([r["run_id"] for r in run_json("proposals", "list", *self.R)[1]["data"]],
                         ["r1"])

    def test_sources_are_exclusive_and_run_id_defaults(self):
        self.assertEqual(run("sync", *self.R)[0], 2)
        self.assertEqual(run("sync", "--files", "a.py", "--from-diff", "a..b", *self.R)[0], 2)
        with mock.patch.dict(os.environ, {"MODSYS_RUN_ID": "envrun"}):
            _, env, _ = run_json("sync", "--files", "a.py", "--dry-run", *self.R)
        self.assertEqual(env["data"]["run_id"], "envrun")


if __name__ == "__main__":
    unittest.main()
