"""Hooks runner: [[hooks.post_sync]] from packs and team config."""
import json
import sys
import tempfile
import unittest

from modsys.hooks import run_hooks
from modsys.workspace import Workspace
from tests.helpers import copy_fixture, run, run_json

SCRIPTS = {
    "ok.py": "import json, sys\n"
             "p = json.load(sys.stdin)\n"
             "print(json.dumps({'proposals': [{'op': 'append', 'module': 'catalog',\n"
             "    'field': 'keywords', 'value': 'hooked', 'reason': 'from hook'}],\n"
             "    'messages': ['saw ' + ','.join(p['changed_modules'])]}))\n",
    "fail.py": "import sys\nprint('boom', file=sys.stderr)\nsys.exit(3)\n",
    "slow.py": "import time\ntime.sleep(5)\n",
    "badjson.py": "print('not json')\n",
    "badprop.py": "import json\nprint(json.dumps({'proposals': [{'op': 'set', 'module': 'catalog',\n"
                  "    'field': 'owner_team', 'value': 'x', 'reason': 'r'}]}))\n",
    # garbage that used to escape the per-hook report (exit 2 "internal error" for the sync)
    "docint.py": "import json\nprint(json.dumps({'proposals': [{'op': 'doc_append',\n"
                 "    'module': 'catalog', 'doc': 5, 'value': 'x', 'reason': 'r'}]}))\n",
    "fieldlist.py": "import json\nprint(json.dumps({'proposals': [{'op': 'set',\n"
                    "    'module': 'catalog', 'field': ['a'], 'value': 'x', 'reason': 'r'}]}))\n",
    "nonutf8.py": "import sys\nsys.stdout.buffer.write(b'{\"messages\": [\"\\xff\\xfe\"]}\\n')\n",
    "marker.py": "import pathlib\npathlib.Path('hook-ran.marker').write_text('ran')\n",
}


class HooksTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        self.pack = self.root / ".modsys" / "packs" / "notify"
        (self.pack / "hooks").mkdir(parents=True)
        for name, body in SCRIPTS.items():
            (self.pack / "hooks" / name).write_text(body, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def use(self, *hooks: str, team: str = "") -> Workspace:
        """Declare pack hooks: each arg is 'id:script[:required][:timeout]'."""
        lines = ['id = "notify"', "priority = 30"]
        for spec in hooks:
            hid, script, *rest = spec.split(":")
            lines += ["[[hooks.post_sync]]", f'id = "{hid}"',
                      f'run = [{json.dumps(sys.executable)}, "./hooks/{script}"]']
            if "required" in rest:
                lines.append("required = true")
            if any(r.isdigit() for r in rest):
                lines.append(f"timeout_s = {[r for r in rest if r.isdigit()][0]}")
        (self.pack / "pack.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
        if team:
            (self.root / ".modsys" / "config.toml").write_text(team, encoding="utf-8")
        return Workspace.load(self.root)

    def fire(self, ws):
        return run_hooks(ws, "post_sync", {"changed_modules": ["catalog", "checkout"],
                                           "changed_files": [], "diff_range": "a..b"}, "r1")

    def test_ok_hook_queues_proposals_and_returns_messages(self):
        report = self.fire(self.use("tag:ok.py"))
        hook = report["hooks"][0]
        self.assertEqual((hook["status"], hook["queued"], hook["owner"]), ("ok", 1, "notify"))
        self.assertEqual(hook["messages"], ["saw catalog,checkout"])
        queued = json.loads((self.root / ".modsys/proposals/r1-hook-tag.json").read_text())
        self.assertEqual(queued["items"][0]["value"], "hooked")
        self.assertFalse(report["failed_required"])

    def test_failures_are_reported_never_raised(self):
        report = self.fire(self.use("a:fail.py", "b:slow.py:1", "c:badjson.py", "d:badprop.py"))
        errors = {h["id"]: h["error"] for h in report["hooks"]}
        self.assertTrue(all(h["status"] == "failed" for h in report["hooks"]))
        self.assertEqual(errors["a"], "exit 3: boom")
        self.assertEqual(errors["b"], "timed out after 1s")
        self.assertIn("bad output", errors["c"])
        self.assertIn("unknown field 'owner_team'", errors["d"])
        self.assertFalse(report["failed_required"])
        self.assertFalse((self.root / ".modsys/proposals/r1-hook-d.json").exists())

    def test_garbage_output_fails_that_hook_only_and_sync_still_exits_0(self):
        self.use("a:docint.py", "b:fieldlist.py", "c:nonutf8.py", "tag:ok.py")
        code, env, err = run_json("sync", "--files", "src/catalog/service.py",
                                  "--run-id", "r1", "--root", str(self.root))
        self.assertEqual((code, err), (0, ""))
        hooks = {h["id"]: h for h in env["data"]["hooks"]["hooks"]}
        for hid in ("a", "b", "c"):
            with self.subTest(hook=hid):
                self.assertEqual(hooks[hid]["status"], "failed")
                self.assertIn("bad output", hooks[hid]["error"])
                self.assertFalse((self.root / f".modsys/proposals/r1-hook-{hid}.json").exists())
        self.assertIn("not valid UTF-8", hooks["c"]["error"])
        self.assertEqual((hooks["tag"]["status"], hooks["tag"]["queued"]), ("ok", 1))
        self.assertFalse(env["data"]["hooks"]["failed_required"])

    def test_garbage_output_of_a_required_hook_fails_the_run(self):
        self.use("a:docint.py:required", "tag:ok.py")
        code, env, _ = run_json("sync", "--files", "src/catalog/service.py",
                                "--root", str(self.root))
        self.assertEqual(code, 1)
        self.assertTrue(env["data"]["hooks"]["failed_required"])
        self.assertEqual(env["data"]["hooks"]["hooks"][1]["status"], "ok")

    def test_hook_id_outside_the_safe_charset_is_exit_2_at_load(self):
        for where in ("team", "pack"):
            with self.subTest(where=where):
                bad = '[[hooks.post_sync]]\nid = "bad id/x"\nrun = ["true"]\n'
                if where == "team":
                    (self.pack / "pack.toml").write_text('id = "notify"\n', encoding="utf-8")
                    (self.root / ".modsys" / "config.toml").write_text(bad, encoding="utf-8")
                    source = "config.toml"
                else:
                    (self.root / ".modsys" / "config.toml").write_text("", encoding="utf-8")
                    (self.pack / "pack.toml").write_text('id = "notify"\n' + bad,
                                                         encoding="utf-8")
                    source = "pack.toml"
                code, out, err = run("hooks", "list", "--root", str(self.root))
                self.assertEqual((code, out), (2, ""))
                self.assertIn(source, err)
                self.assertIn("'bad id/x'", err)

    def test_sync_refuses_a_bad_run_id_before_any_hook_runs(self):
        self.use("mark:marker.py")
        for run_id in ("../x", "a b"):
            with self.subTest(run_id=run_id):
                code, out, err = run("sync", "--files", "src/catalog/service.py",
                                     "--run-id", run_id, "--root", str(self.root))
                self.assertEqual((code, out), (2, ""))
                self.assertIn("run id", err)
                self.assertFalse((self.root / "hook-ran.marker").exists())
        self.assertEqual(run("sync", "--files", "src/catalog/service.py", "--run-id", "ok-1",
                             "--root", str(self.root))[0], 0)
        self.assertTrue((self.root / "hook-ran.marker").exists())  # the marker hook works

    def test_required_failure_flags_the_run(self):
        self.assertTrue(self.fire(self.use("a:fail.py:required"))["failed_required"])

    def test_team_config_disables_a_pack_hook_by_id(self):
        ws = self.use("tag:ok.py", team='[[hooks.post_sync]]\nid = "tag"\nenabled = false\n')
        self.assertEqual(self.fire(ws)["hooks"][0]["status"], "skipped")
        _, env, _ = run_json("hooks", "list", "--root", str(self.root))
        self.assertEqual([(r["id"], r["owner"], r["enabled"]) for r in env["data"]],
                         [("tag", "notify", False)])

    def test_invalid_hook_config_is_exit_2_naming_the_file(self):
        cases = [('[hooks]\npost_sync = 5\n', "must be an array of tables"),
                 ('[[hooks.post_sync]]\nrun = ["x"]\n', "needs an id"),
                 ('[[hooks.post_sync]]\nid = "x"\nrun = []\n', "run is empty"),
                 ('[[hooks.post_sync]]\nid = "x"\ntimeout_s = 0\n', "timeout_s must be > 0"),
                 ('[[hooks.post_sync]]\nid = "x"\nrequired = "yes"\n', "expected a boolean")]
        for text, needle in cases:
            with self.subTest(needle=needle):
                (self.root / ".modsys" / "config.toml").write_text(text, encoding="utf-8")
                code, _, err = run("hooks", "list", "--root", str(self.root))
                self.assertEqual(code, 2)
                self.assertIn("config.toml", err)
                self.assertIn(needle, err)

    def test_hook_without_run_fails_alone_the_rest_still_run(self):
        pack = ('id = "notify"\npriority = 30\n'
                '[[hooks.post_sync]]\nid = "norun"\n'
                '[[hooks.post_sync]]\nid = "tag"\n'
                f'run = [{json.dumps(sys.executable)}, "./hooks/ok.py"]\n')
        (self.pack / "pack.toml").write_text(pack, encoding="utf-8")
        report = self.fire(Workspace.load(self.root))
        results = {h["id"]: h for h in report["hooks"]}
        self.assertEqual(results["norun"]["status"], "failed")
        self.assertIn("no run command", results["norun"]["error"])
        self.assertEqual(results["tag"]["status"], "ok")
        self.assertFalse(report["failed_required"])

    def test_hook_without_run_required_flags_the_run(self):
        pack = ('id = "notify"\npriority = 30\n'
                '[[hooks.post_sync]]\nid = "norun"\nrequired = true\n')
        (self.pack / "pack.toml").write_text(pack, encoding="utf-8")
        self.assertTrue(self.fire(Workspace.load(self.root))["failed_required"])


if __name__ == "__main__":
    unittest.main()
