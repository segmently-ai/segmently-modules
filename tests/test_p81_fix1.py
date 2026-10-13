"""P8.1 task 3b fix round 1: the tracked personal config (C1), model values (M2), nested agent
calls (I2), the agent's output cap (M3), temp-dir errors (M4), the child's cwd (M5), the number
of picks (M6), skipped hybrid context (M8)."""
import json
import os
import sys
import time
import unittest
from unittest import mock

from segmently_modules import agent as agent_mod
from tests import SENTINEL_LOG
from tests.agent_helpers import AgentRepo, picks
from tests.helpers import git, run, run_json
from tests.test_p81_agent import ENGINE, MATCH_TASK, TASK, rows_of



class Base(AgentRepo, unittest.TestCase):
    def commit_user_config(self):
        git(self.root, "add", "-f", ".segmently-modules/config.user.toml")
        git(self.root, "commit", "-q", "-m", "oops")


class PersonalConfigTest(Base):
    def test_a_personal_config_without_an_agent_is_fine(self):
        self.config('[search]\neffort = "quick"\n', "config.user.toml")
        self.assertEqual(run("catalog", *self.R)[0], 0)

    def test_init_ignores_the_personal_config(self):
        repo = self.tmp / "fresh"
        repo.mkdir()
        git(repo, "init", "-q")
        self.assertEqual(run("init", "--root", str(repo))[0], 0)
        lines = (repo / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn(".segmently-modules/config.user.toml", lines)
        before = (repo / ".gitignore").read_bytes()
        self.assertEqual(run("init", "--root", str(repo))[0], 0)
        self.assertEqual((repo / ".gitignore").read_bytes(), before)


class SearchModelTest(Base):  # M2
    def test_a_leading_dash_is_refused(self):
        for key in ("claude_model", "codex_model"):
            for bad in ("--dangerously-skip-permissions", "-m", "a b"):
                self.config(f'[search]\n{key} = "{bad}"\n')
                code, out, err = run("catalog", *self.R)
                self.assertEqual((code, out), (2, ""), bad)
                self.assertIn(f"[search] {key}", err)
                self.assertIn("config.toml", err)
            for ok in ("sonnet", "gpt-5.6-luna", "a:b/c@1.2+x_y-z", "9x"):
                self.config(f'[search]\n{key} = "{ok}"\n')
                self.assertEqual(run("catalog", *self.R)[0], 0, ok)
            self.config('[search]\n')


class NestedTest(Base):  # I2
    def test_an_agent_that_runs_segmently_modules_gets_the_lexical_rows(self):
        nested = [sys.executable, "-m", "segmently_modules", "match", MATCH_TASK, "--match", "hybrid",
                  *self.R]
        self.agent(answer=picks(("payments", 0.9)), nested=nested, cwd=str(ENGINE),
                   nested_env={"PYTHONPATH": str(ENGINE)})
        self.assertEqual(run("choose", "--task", TASK, "--run", *self.R)[0], 0)
        (call,) = self.calls()  # the agent was called exactly once
        inner = call["nested"]
        self.assertEqual(inner["rc"], 0, inner["err"])
        self.assertIn("semantic part skipped: nested agent call", inner["out"])
        self.assertNotIn("[semantic]", inner["out"])

    def test_nested_semantic_and_run_are_refused_and_catalog_says_false(self):
        self.agent(answer=picks())
        with mock.patch.dict(os.environ, {"SEGMENTLY_MODULES_WORK_ORDER": "/x"}):
            for argv in (("match", MATCH_TASK, "--match", "semantic"),
                         ("choose", "--task", TASK, "--run")):
                code, out, err = run(*argv, *self.R)
                self.assertEqual((code, out), (2, ""))
                self.assertIn("nested", err)
            _, env, _ = run_json("catalog", *self.R)
            self.assertFalse(env["data"]["match"]["semantic"])
        self.assertEqual(self.calls(), [])


class AgentLimitsTest(Base):
    def test_output_cap(self):  # M3
        self.agent(flood=64, answer="{}")
        with mock.patch.object(agent_mod, "MAX_STDOUT", 32):
            code, out, err = run("choose", "--task", TASK, "--run", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("printed more than 32 bytes", err)

    def test_unwritable_temp_dir(self):  # M4
        self.agent(answer=picks())
        with mock.patch("tempfile.mkdtemp", side_effect=PermissionError(13, "denied")):
            code, out, err = run("choose", "--task", TASK, "--run", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("cannot write", err)
        self.assertNotIn("internal error", err)

    def test_the_child_runs_in_the_workspace_root(self):  # M5
        self.agent(answer=picks())
        other = self.tmp / "elsewhere"
        other.mkdir()
        cwd = os.getcwd()
        os.chdir(other)
        try:
            self.assertEqual(run("choose", "--task", TASK, "--run", *self.R)[0], 0)
        finally:
            os.chdir(cwd)
        self.assertEqual(os.path.realpath(self.calls()[0]["cwd"]),
                         os.path.realpath(self.root))

    def test_number_of_picks_follows_top(self):  # M6
        self.agent(answer=picks(("payments", 0.9)))
        run("match", MATCH_TASK, "--match", "semantic", "--top", "7", *self.R)
        self.assertEqual(json.loads(self.calls()[0]["stdin"])["max_picks"], 7)
        run("match", MATCH_TASK, "--match", "semantic", "--top", "2", *self.R)
        self.assertEqual(json.loads(self.calls()[1]["stdin"])["max_picks"], 5)
        code, out, _ = run("match", MATCH_TASK, "--match", "semantic", "--top", "0", *self.R)
        self.assertEqual(code, 0)
        self.assertEqual(len(self.calls()), 2)  # --top 0 never spawns the agent

    def test_skipped_hybrid_context_equals_lexical(self):  # M8
        text = "zzz nothing matches"
        lexical = run("context", "--task", text, *self.R)
        hybrid = run("context", "--task", text, "--match", "hybrid", *self.R)
        note = "semantic part skipped: no agent command configured"
        self.assertEqual(hybrid[0], 0)
        self.assertEqual(hybrid[1].splitlines()[:-1], lexical[1].splitlines())
        self.assertEqual(hybrid[1].splitlines()[-1], note)

    def test_group_is_killed_after_success(self):  # M11
        pidfile = self.tmp / "bg"
        self.agent(answer=picks(), grandchild=str(pidfile))
        self.assertEqual(run("choose", "--task", TASK, "--run", *self.R)[0], 0)
        import time
        pid = int(pidfile.read_text())
        for _ in range(40):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.05)
        self.fail("the agent's background child outlived the call")

    def test_more_verbs_without_a_connection(self):  # M12
        import socket
        self.agent(answer=picks(("payments", 0.9)))
        with mock.patch.object(socket.socket, "connect", side_effect=AssertionError("net")):
            for argv in (("show", "orders"), ("lint",), ("roles", "list"), ("next",),
                         ("context", "--task", MATCH_TASK, "--match", "hybrid")):
                self.assertIn(run(*argv, *self.R)[0], (0, 1), argv)


class HelperHoldingStdoutTest(Base):  # N2
    def test_a_valid_answer_survives_a_helper_that_holds_stdout(self):
        self.agent(answer=picks(("payments", 0.9)), helper=30, timeout_s=3)
        t0 = time.monotonic()
        code, out, err = run("choose", "--task", TASK, "--run", *self.R, "--json")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out)["data"]["picks"][0]["module"], "payments")
        self.assertLess(time.monotonic() - t0, 3 + 2 * agent_mod.KILL_GRACE_S + 2)

    def test_no_answer_fails_within_the_deadline(self):
        self.agent(helper=30, timeout_s=3)
        t0 = time.monotonic()
        code, out, err = run("choose", "--task", TASK, "--run", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("agent", err)
        self.assertNotIn("ResourceWarning", err)
        self.assertLess(time.monotonic() - t0, 3 + 2 * agent_mod.KILL_GRACE_S + 2)


if __name__ == "__main__":
    unittest.main()
