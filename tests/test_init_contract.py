"""The headless contract of the phase 4–7 surface (P5B-AC-038): one envelope per `--json` call,
refusals on stderr with stdout empty, a garbage config, Ctrl-C and an unexpected error; the
action list (P5B-AC-004)."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import run
from tests.init_helpers import WORK, executor, ok, protected_sha, shop, state


class ContractRepo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.template = shop(Path(cls._tmp.name).resolve(), name="template")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(dir=self._tmp.name)).resolve()
        self.root = self.base / "shop"
        shutil.copytree(self.template, self.root, symlinks=True)

    def call(self, *argv: str) -> tuple[int, str, str]:
        return run(*argv, "--root", str(self.root))


class EnvelopeTest(ContractRepo):
    def test_one_envelope_per_action(self):
        tasks = self.base / "tasks.json"
        tasks.write_text(json.dumps([{"task": "the isbn of a book", "module": "catalog"}]))
        steps = [(("init", "fanout"), "modsys.init/1"), (("init", "next"), "modsys.init/1"),
                 (("init", "status"), "modsys.init/1"),
                 (("init", "run", "--executor", executor()), "modsys.init/1"),
                 (("init", "reconcile"), "modsys.init/1"),
                 (("eval", "routing", "--tasks", str(tasks)), "modsys.eval/1"),
                 (("eval", "routing", "--prompt"), "modsys.eval/1"),
                 (("init", "eval-tasks", "--executor", executor()), "modsys.init/1"),
                 (("init", "verify"), "modsys.init/1"), (("init", "resume"), "modsys.init/1"),
                 (("init", "finish"), "modsys.init/1"),
                 (("init", "done", "cart"), "modsys.init/1")]
        for argv, schema in steps:
            with self.subTest(argv=argv[:2]):
                code, out, err = self.call(*argv, "--json")
                self.assertEqual((code, err), (0, ""))
                env = json.loads(out)
                self.assertEqual((set(env), env["schema"]), ({"schema", "data"}, schema))

    def test_refusals_and_usage_errors(self):
        for argv in (("init", "next"), ("init", "done", "cart"), ("init", "reconcile"),
                     ("init", "verify"), ("init", "finish"), ("init", "run"),
                     ("init", "eval-tasks"), ("init", "status", "--open-pr"),
                     ("init", "finish", "--base", "main"), ("eval", "routing"),
                     ("init", "resume", "--executor", "no-such-binary-x")):
            with self.subTest(argv=argv):
                code, out, err = self.call(*argv, "--json")
                self.assertEqual((code, out), (2, ""))
                self.assertTrue(err.startswith("modsys: error: "), err)


class GarbageConfigTest(ContractRepo):
    def test_a_garbage_max_parallel(self):
        config = self.root / ".modsys/config.toml"
        config.write_text(config.read_text() + '\n[init]\nmax_parallel = "x"\n')
        for argv in (("init", "run", "--executor", executor()), ("init", "status"),
                     ("eval", "routing", "--prompt"), ("lint",)):
            with self.subTest(argv=argv[:2]):
                code, out, err = self.call(*argv, "--json")
                self.assertEqual((code, out), (2, ""))
                self.assertIn(".modsys/config.toml: [init] max_parallel must be an integer >= 1",
                              err)
                self.assertNotIn("Traceback", err)


class InterruptTest(ContractRepo):
    def interrupted(self, target: str, *argv: str) -> None:
        with mock.patch(target, side_effect=KeyboardInterrupt):
            self.assertEqual(self.call(*argv), (130, "", "modsys: interrupted\n"))
        json.loads((self.root / WORK / "state.json").read_text())

    def test_ctrl_c_in_next_reconcile_and_finish(self):
        ok(self.root, "init", "fanout")
        self.interrupted("modsys.init_work.Work.item", "init", "next")
        ok(self.root, "init", "run", "--executor", executor())
        self.interrupted("modsys.init_reconcile.Reconcile.duplicates", "init", "reconcile")
        self.assertFalse((self.root / WORK / "staging/registry.json").exists())
        ok(self.root, "init", "reconcile")
        ok(self.root, "init", "verify")
        (self.root / "CLAUDE.md").write_text("# notes\n")
        before = protected_sha(self.root)
        self.interrupted("modsys.agents_md_cmd.atomic_write", "init", "finish")  # the block
        self.assertEqual(protected_sha(self.root), before)  # all or nothing
        self.assertFalse((self.root / "modules/cart").exists())
        self.assertEqual(state(self.root)["phases"]["finish"]["status"], "running")
        self.assertIn("init finish was interrupted", ok(self.root, "init", "status")["next"])
        ok(self.root, "init", "finish")
        self.assertTrue((self.root / "modules/cart/MODULE.md").is_file())

    def verified(self) -> str:
        for argv in (("fanout",), ("run", "--executor", executor()), ("reconcile",),
                     ("verify",)):
            ok(self.root, "init", *argv)
        (self.root / "AGENTS.md").write_text("# agents\n")
        os.symlink("AGENTS.md", self.root / "CLAUDE.md")  # a common setup
        return protected_sha(self.root)

    def test_ctrl_c_after_the_writes(self):  # I-1: the state saved as finished is the last step
        before = self.verified()
        self.interrupted("modsys.init_finish.Finish.git_add", "init", "finish")
        self.assertEqual(protected_sha(self.root), before)
        self.assertTrue((self.root / "CLAUDE.md").is_symlink())  # I-2: put back through the link
        self.assertEqual((self.root / "AGENTS.md").read_text(), "# agents\n")
        self.assertFalse((self.root / "modules/cart").exists())
        self.assertEqual(state(self.root)["phases"]["finish"]["status"], "running")
        nxt = ok(self.root, "init", "status")["next"]
        self.assertIn("init finish was interrupted: run modsys init finish again", nxt)
        self.assertNotIn("nothing kept", nxt)
        data = ok(self.root, "init", "finish")
        self.assertEqual(data["agents_md"], [{"path": "CLAUDE.md", "status": "added"},
                                             {"path": "AGENTS.md", "status": "added"}])
        self.assertTrue((self.root / "CLAUDE.md").is_symlink())

    def test_a_state_save_that_fails_at_the_commit_point(self):
        from modsys.init_flow import InitFlow
        before = self.verified()
        real = InitFlow.save_state

        def save(flow, s):
            if s["phases"]["finish"]["status"] == "done":
                raise KeyboardInterrupt  # the last step of finish
            return real(flow, s)

        with mock.patch("modsys.init_flow.InitFlow.save_state", autospec=True, side_effect=save):
            self.assertEqual(self.call("init", "finish"), (130, "", "modsys: interrupted\n"))
        self.assertEqual(protected_sha(self.root), before)
        self.assertEqual(state(self.root)["phases"]["finish"]["status"], "running")
        ok(self.root, "init", "finish")
        self.assertEqual(state(self.root)["phase"], "finished")

    def test_ctrl_c_right_after_the_commit_point(self):  # N-7: the state says finished: kept
        from modsys.init_flow import InitFlow
        before = self.verified()
        real = InitFlow.save_state

        def save(flow, s):
            real(flow, s)
            if s["phases"]["finish"]["status"] == "done":
                raise KeyboardInterrupt  # renamed into place, before apply() returns

        with mock.patch("modsys.init_flow.InitFlow.save_state", autospec=True, side_effect=save):
            self.assertEqual(self.call("init", "finish"), (130, "", "modsys: interrupted\n"))
        self.assertEqual(state(self.root)["phase"], "finished")
        self.assertNotEqual(protected_sha(self.root), before)  # the writes stand
        self.assertTrue((self.root / "modules/cart/MODULE.md").is_file())
        self.assertIn("modsys:begin", (self.root / "AGENTS.md").read_text())
        self.assertTrue((self.root / "CLAUDE.md").is_symlink())
        self.assertIn("init is finished", ok(self.root, "init", "status")["next"])
        self.assertEqual(len(ok(self.root, "list")), 6)

    def test_an_unexpected_error(self):
        ok(self.root, "init", "fanout")
        with mock.patch("modsys.init_work.Work.claim", side_effect=RuntimeError("boom")), \
                mock.patch.dict(os.environ):
            os.environ.pop("MODSYS_DEBUG", None)
            code, out, err = self.call("init", "next")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("modsys: internal error: RuntimeError: boom", err)
        self.assertNotIn("Traceback", err)


class RetryContractTest(ContractRepo):  # P5C-AC-021 (D3): the retry and a P5b state
    def test_a_p5b_state_and_the_exit_codes(self):
        ok(self.root, "init", "fanout")
        s = state(self.root)  # what the P5b engine wrote: a refused module, no `problems` key
        s["modules"]["cart"].update(status="failed", attempts=1, error="MODULE.md is empty")
        (self.root / WORK / "state.json").write_text(json.dumps(s))
        ok(self.root, "init", "resume")
        item = ok(self.root, "init", "next")["item"]
        self.assertEqual(item, json.loads((self.root / WORK / "work/cart.json").read_text()))
        for flags, code in ((("--invent", "payments"), 0), (("--invent-always", "payments"), 1)):
            with self.subTest(flags=flags):
                self.setUp()
                ok(self.root, "init", "fanout")
                got, out, err = self.call("init", "run", "--executor", executor(*flags), "--json")
                self.assertEqual((got, json.loads(out)["data"]["failed"]), (code, bool(code)))
                self.assertIn("modsys: payments: refused — retrying once", err.splitlines())
                self.assertNotIn("Traceback", err)

    def test_a_state_write_that_fails_during_a_retry(self):
        from modsys import init_flow
        ok(self.root, "init", "fanout")
        real = init_flow.os.replace

        def replace(src, dst):  # the save that records the refused problems
            if Path(dst).name == "state.json" and '"problems"' in Path(src).read_text():
                raise PermissionError(13, "Permission denied")
            return real(src, dst)

        with mock.patch("modsys.init_flow.os.replace", side_effect=replace):
            got = self.call("init", "run", "--executor", executor("--invent", "cart"), "--json")
        self.assertEqual(got[:2], (2, ""))
        self.assertIn("modsys: error: cannot write .modsys/init/state.json: Permission denied",
                      got[2])
        self.assertNotIn("Traceback", got[2])
        self.assertNotIn("problems", state(self.root)["modules"]["cart"])

    def test_a_damaged_problems_entry(self):
        ok(self.root, "init", "fanout")
        s = state(self.root)
        s["modules"]["cart"]["problems"] = "MODULE.md is empty"  # not a list
        (self.root / WORK / "state.json").write_text(json.dumps(s))
        for action in ("status", "next"):
            with self.subTest(action=action):
                code, out, err = self.call("init", action, "--json")
                self.assertEqual((code, out), (2, ""))
                self.assertEqual(err, f"modsys: error: {WORK}/state.json: not a valid init state "
                                      f"(module 'cart': problems is not a list of strings — "
                                      f"remove it, or start over: modsys init map --restart)\n")
        del s["modules"]["cart"]["problems"]  # the way out it names first
        (self.root / WORK / "state.json").write_text(json.dumps(s))
        self.assertEqual(ok(self.root, "init", "next")["item"]["module"], "cart")
        s["modules"]["payments"]["attempts"] = "one"  # any other damage: as before
        (self.root / WORK / "state.json").write_text(json.dumps(s))
        code, out, err = self.call("init", "status", "--json")
        self.assertEqual((code, out), (2, ""))
        self.assertIn(f"{WORK}/state.json: not a valid init state (module 'payments') — start "
                      f"over: modsys init map --restart", err)


class ActionsTest(ContractRepo):  # P5B-AC-004 (the action list)
    def test_an_unknown_action_names_every_action(self):
        code, out, err = self.call("init", "bogus")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("unknown init action 'bogus' (actions: map, confirm, status, resume, "
                      "fanout, next, done, run, reconcile, eval-tasks, verify, finish)", err)


if __name__ == "__main__":
    unittest.main()
