"""`tools/release.py --suite-passed TREE` (P8.3 D5 R-2, SI-P83-15, P83-AC-019): a TREE equal to
the engine's `HEAD^{tree}` skips step 3's unit suite (no test process starts) while the E-A
still runs, on both channels; any other 40-hex tree is a refusal in step 2 that writes nothing;
a malformed TREE is a usage error; after a put-back the same TREE is accepted again, after a
finished stable release it is refused."""
import os
import unittest

from tests.helpers import git
from tests.release_helpers import SuiteRepo

VALIDATE = {"FAKE_CLAUDE_FAIL": "validate"}  # step 5 fails: the run stops after step 3


class SuitePassedTest(SuiteRepo):
    def planted(self) -> list:
        """What the copy's `test_plant` does when it runs with PLANT_IN set."""
        return [p for repo in (self.engine, self.pub) for p in (
            *(["NOTES.txt"] if (repo / "NOTES.txt").exists() else []),
            *(r for r in git(repo, "for-each-ref", "--format=%(refname)").split()
              if r.endswith(("/hotfix", "/my-mark"))))]

    def skipped(self, channel: str, *argv: str, env: dict | None = None):
        tree = self.tree()
        before = self.both()
        proc = self.run_release(channel, "--suite-passed", tree, *argv, env={
            "PLANT_IN": os.pathsep.join(map(str, (self.engine, self.pub))), **(env or {})})
        self.assertEqual(self.recorded("start"), {})  # no unit-test process started
        self.assertEqual(self.planted(), [])
        self.assertTrue((self.records / "eval.ran").exists())  # the E-A always runs
        self.assertEqual(self.both(), before)
        self.assertEqual(list(self.tmpdir.iterdir()), [])
        return proc, tree

    def test_a_matching_tree_skips_the_unit_suite(self):
        for channel, argv in (("dev", ()), ("stable", ()), ("stable", ()), ("dev", ("--jobs",
                                                                                     "2"))):
            with self.subTest(channel=channel, argv=argv):  # stable twice: after a put-back
                proc, tree = self.skipped(channel, *argv, env=VALIDATE)  # it is accepted again
                self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
                self.assertIn(f"step 3 tests: the unit suite passed on tree {tree[:12]} before "
                              "(--suite-passed); the adoption eval passed\n", proc.stdout)
                self.assertTrue(proc.stderr.startswith("release.py: step 5 validate failed: "))
                self.assertTrue(proc.stderr.endswith(" — both repositories are as they were\n"))
        for channel in ("dev", "stable"):
            with self.subTest(channel=channel, eval="failing"):
                proc, _ = self.skipped(channel, env={"R1_EVAL_FAIL": "1"})
                self.assertEqual((proc.returncode, proc.stderr), (
                    1, "release.py: step 3 tests failed: the adoption eval failed: adoption "
                       "eval: planted failure — both repositories are as they were\n"))
                self.assertNotIn("step 3 tests:", proc.stdout)

    def test_another_tree_is_refused_in_step_2(self):
        other, tree = self.tree("HEAD~1"), self.tree()
        self.assertNotEqual(other, tree)
        for channel in ("dev", "stable"):
            with self.subTest(channel=channel):
                before = self.both()
                proc = self.run_release(channel, "--suite-passed", other)
                self.assertEqual((proc.returncode, proc.stderr), (
                    2, f"release.py: error: --suite-passed {other} is not this engine's tree "
                       f"{tree} — leave the flag out and the suite runs\n"))
                self.assertIn("step 1 leak guard: ", proc.stdout)
                self.assertNotIn("step 2", proc.stdout)
                self.assertEqual(self.both(), before)
                self.assertEqual(list(self.tmpdir.iterdir()), [])
                self.assertEqual(list(self.records.iterdir()), [])
        (self.engine / "scratch.txt").write_text("x\n")  # a dirty engine: step 2's own refusal
        proc = self.run_release("stable", "--suite-passed", tree)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertEqual(proc.stderr, "release.py: error: the engine is dirty: scratch.txt — "
                                      "commit or remove the changes\n")

    def test_a_malformed_tree_is_a_usage_error(self):
        tree = self.tree()
        for value in (tree[:39], tree + "0", tree.upper(), "g" + tree[1:], ""):
            with self.subTest(value=value):
                proc = self.run_release("dev", "--suite-passed", value)
                self.assertEqual((proc.returncode, proc.stdout), (2, ""), proc.stderr)
                self.assertTrue(proc.stderr.startswith("usage: release.py "), proc.stderr)
                self.assertIn("release.py: error: argument --suite-passed", proc.stderr)
                self.assertEqual(list(self.records.iterdir()), [])
                self.assertFalse((self.base / "claude.log").exists())

    def test_the_tree_before_a_finished_stable_release_is_refused(self):
        tree = self.tree()
        proc = self.run_release("stable", "--suite-passed", tree)
        self.assertEqual((proc.returncode, proc.stderr), (0, ""), proc.stdout)
        self.assertIn(f"the unit suite passed on tree {tree[:12]} before", proc.stdout)
        self.notes("- The next release.")  # step 1 passes: step 2 is what refuses
        proc = self.run_release("stable", "--suite-passed", tree)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertEqual(proc.stderr, f"release.py: error: --suite-passed {tree} is not this "
                                      f"engine's tree {self.tree()} — leave the flag out and the "
                                      "suite runs\n")


if __name__ == "__main__":
    unittest.main()
