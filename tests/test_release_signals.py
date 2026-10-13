"""`tools/release.py` step 3 under Ctrl-C, SIGTERM and SIGHUP (P8.3 D5 R-1, P83-AC-018): with
three test modules in flight a signal — once or twice — kills every test process group (the
modules and what they started) and reaps them before the put-back, exit 130; under `nohup` a
SIGHUP does not stop the suite and the test processes inherit the ignore. And the per-class
snapshot of a finished dev release the release tests start from (P8.3 D5 R-3, P83-AC-020)."""
import os
import subprocess
import sys
import time
import unittest

from tests.helpers import git
from tests.plugin_helpers import default_signals
from tests.release_helpers import PLANTED, SLUG, ReleaseRepo, SuiteRepo, tree_hash

AS_THEY_WERE = " — both repositories are as they were\n"


class SignalTest(SuiteRepo):  # P83-AC-018
    def alive(self, pids: list[int], wait: float = 5.0) -> list[int]:
        """The pids still alive after up to `wait` seconds (a killed grandchild is reaped by
        init: give it the time)."""
        deadline = time.time() + wait
        while True:
            left = []
            for pid in pids:
                try:
                    os.kill(pid, 0)
                    left.append(pid)
                except ProcessLookupError:
                    pass
                except PermissionError:  # a reused pid of another user's process: not ours
                    pass
            if not left or time.time() > deadline:
                return left
            time.sleep(0.05)

    def test_a_signal_kills_every_test_process_group(self):
        for name in ("INT", "TERM", "HUP"):
            for count in (1, 2):
                with self.subTest(signal=name, times=count):
                    before = self.both()
                    proc = self.run_release("dev", "--jobs", "3", env={
                        "R1_SLOW": "test_m_middle", "R1_WAIT_FOR": "3", "R1_SIGNAL": name,
                        "R1_SIGNALS": str(count), "R1_DELAY": "1.5", "R1_HOLD": "60"})
                    self.assertEqual((proc.returncode, proc.stderr),
                                     (130, "release.py: interrupted — both repositories are as "
                                           "they were\n"), proc.stdout)
                    starts = self.recorded("start")
                    self.assertEqual(sorted(starts), ["test_a_first", "test_m_middle",
                                                      "test_release_zz"])  # three in flight
                    slow = self.recorded("slow")["test_m_middle"]
                    pids = [row["pid"] for row in starts.values()] + [slow["child"]]
                    self.assertEqual(self.alive(pids), [])
                    for row in starts.values():  # no process left in any test group
                        with self.assertRaises(ProcessLookupError):
                            os.killpg(row["pgid"], 0)
                    time.sleep(max(0.0, slow["time"] + 2.0 - time.time()))
                    self.assertEqual(sorted(p.name for p in self.records.iterdir()
                                            if not p.name.endswith((".start", ".slow"))), [])
                    self.assertNotIn("step 3 tests:", proc.stdout)
                    self.assertEqual(self.both(), before)
                    self.assertEqual(list(self.tmpdir.iterdir()), [])
                    self.assertEqual(list(self.engine.rglob("__pycache__")), [])

    def test_sigint_first_then_sigkill_after_the_grace(self):  # review M-2 (ruling)
        before = self.both()
        proc = self.run_release("dev", "--jobs", "3", env={
            "R1_SLOW": "test_m_middle", "R1_WAIT_FOR": "3", "R1_SIGNAL": "TERM", "R1_SIGNALS": "1",
            "R1_DELAY": "1.5", "R1_HOLD": "60", "R1_TEMP": "test_release_zz",  # cleans up at exit
            "R1_DEAF": "test_a_first"})  # ignores SIGINT: only the SIGKILL ends it
        ended = time.time()
        self.assertEqual((proc.returncode, proc.stderr),
                         (130, "release.py: interrupted — both repositories are as they were\n"))
        signalled = self.recorded("slow")["test_m_middle"]["time"]
        self.assertGreaterEqual(ended - signalled, 2.0)  # the deaf module had its grace
        self.assertLess(ended - signalled, 2.0 + 8.0)  # then the SIGKILL and the put-back
        temp = self.recorded("temp")["test_release_zz"]["path"]
        self.assertTrue(temp.startswith(str(self.tmpdir)), temp)
        self.assertFalse(os.path.exists(temp))  # its finalizer ran: SIGINT came first
        starts = self.recorded("start")
        self.assertEqual(sorted(starts), ["test_a_first", "test_m_middle", "test_release_zz"])
        self.assertEqual(self.alive([row["pid"] for row in starts.values()]), [])
        for row in starts.values():
            with self.assertRaises(ProcessLookupError):
                os.killpg(row["pgid"], 0)
        self.assertEqual(list(self.tmpdir.iterdir()), [])
        self.assertEqual(self.both(), before)

    def test_a_child_the_interrupt_ends_is_reaped(self):  # the guard in step 1, git in step 7
        before = self.both()
        for case, env in (("guard", {"FAKE_GUARD_MODE": "hangup"}), ("git", {})):  # SIGHUP from
            if case == "git":  # the guard; SIGTERM from the git that makes the release commit
                self.git_wrapper('case "$*" in *"commit -q -m release segmently-modules"*"(dev)"*) '
                                 'kill -TERM $PPID; sleep 5; exit 1 ;; esac')
            with self.subTest(child=case):
                proc = self.run_release("dev", env={**env,
                                                    "PYTHONWARNINGS": "always::ResourceWarning"})
                self.assertEqual((proc.returncode, proc.stderr),  # no `subprocess … is still
                                 (130, "release.py: interrupted — both repositories are as they "
                                       "were\n"))  # running`
                self.assertEqual(self.both(), before)

    def test_under_nohup_a_hangup_does_not_stop_the_suite(self):
        records = self.base / "records"
        records.mkdir()
        proc = subprocess.run(  # SIGHUP ignored by the caller, as nohup does
            ["/bin/sh", "-c", 'trap "" HUP; exec "$0" "$@"', sys.executable,
             str(self.engine / "tools/release.py"), "--publish-repo", str(self.pub), "--channel",
             "dev", "--publish-slug", SLUG, "--jobs", "3"], capture_output=True, text=True,
            env={**os.environ, **self.env, "R1_RECORD": str(records), "R1_SLOW": "test_m_middle",
                 "R1_WAIT_FOR": "3", "R1_SIGNAL": "HUP", "R1_SIGNALS": "2", "R1_DELAY": "0.2",
                 "R1_HOLD": "0.3", "R1_EVAL_FAIL": "1"},
            preexec_fn=default_signals, timeout=120)
        self.assertEqual((proc.returncode, proc.stderr), (
            1, "release.py: step 3 tests failed: the adoption eval failed: adoption eval: "
               f"planted failure{AS_THEY_WERE}"))  # the suite ran to its end, then the E-A
        self.assertEqual(sorted(self.recorded("end")), list(PLANTED))
        self.assertEqual(sorted(self.recorded("marker")), ["test_m_middle"])
        self.assertTrue((records / "test_m_middle.grandchild").exists())
        self.assertEqual({row["hup_ignored"] for row in self.recorded("start").values()},
                         {True})  # the children inherit the ignore


class SnapshotTest(ReleaseRepo):  # P83-AC-020: the class's snapshot of a finished dev release
    FROM_DEV_RELEASE = ("test_a_test_that_starts_from_a_finished_dev_release",)

    def test_a_test_that_starts_from_a_finished_dev_release(self):
        snapshot = type(self).snapshot
        self.assertIsNotNone(snapshot)
        self.assertNotEqual(snapshot, self.base)
        self.assertEqual(tree_hash(snapshot), type(self).snapshot_hash)
        for name in ("engine", "publish repo"):
            self.assertEqual(git(self.base / name, "rev-parse", "HEAD"),
                             git(snapshot / name, "rev-parse", "HEAD"))
        self.assertEqual(git(self.pub, "symbolic-ref", "HEAD").strip(), "refs/heads/dev")
        proc = self.release("dev")  # the snapshot's run: no release ran here
        self.assertEqual(proc.returncode, 0)
        self.assertRegex(proc.stdout, r"\ndone: segmently-modules \S+ \(dev\)\n$")
        self.assertFalse((self.base / "git.log").exists())
        proc = self.release("dev")  # the next one runs: the same build is nothing to release
        self.assert_ok(proc)
        self.assertIn("nothing to release", proc.stdout)
        self.assertTrue((self.base / "git.log").exists())
        git(self.engine, "tag", "mine")  # the copies are the test's own
        self.assertEqual(git(snapshot / "engine", "tag", "-l"), "")


if __name__ == "__main__":
    unittest.main()
