"""`tools/release.py` step 3 runs the unit suite one process per test module, `--jobs N` at a
time (P8.3 D5 R-1): the command, cwd and environment of each module, its own process group,
the bound, the order (`test_release*` first), the step line and its singular forms, a failing
module named, output that does not stall the step (P83-AC-016, 017; the signals:
`test_release_signals.py`). Each run stops after step 3: a failing `claude plugin validate`
(step 5), a failing module or a failing E-A."""
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

from tests.helpers import git
from tests.plugin_helpers import ENGINE, load_tool
from tests.release_helpers import PLANTED, START_ORDER, SuiteRepo, failure

VALIDATE = {"FAKE_CLAUDE_FAIL": "validate"}  # step 5 fails: the run stops after step 3
STEP5 = "release.py: step 5 validate failed: "
AS_THEY_WERE = " — both repositories are as they were\n"


def step3(tests: int, modules: int, jobs: int, skipped: int = 0) -> str:
    plural = lambda n, word: f"{n} {word}{'s' * (n != 1)}"  # noqa: E731
    return (f"step 3 tests: Ran {plural(tests, 'test')} in {plural(modules, 'module')} "
            f"({plural(jobs, 'job')}), OK{f' (skipped={skipped})' if skipped else ''}; the "
            f"adoption eval passed\n")


def default_jobs() -> int:
    return min(4, os.cpu_count() or 1)


def overlap(spans: list[tuple[float, float]]) -> int:
    """The most spans open at one time."""
    edges = sorted([(start, 1) for start, _ in spans] + [(end, -1) for _, end in spans],
                   key=lambda e: (e[0], e[1]))
    most = now = 0
    for _, step in edges:
        now += step
        most = max(most, now)
    return most


class JobsTest(SuiteRepo):  # P83-AC-016
    def test_jobs_outside_1_to_32_is_a_usage_error(self):
        for argv in (["--jobs", "0"], ["--jobs", "33"], ["--jobs", "-1"], ["--jobs=-1"],
                     ["--jobs", "x"], ["--jobs", "4.5"], ["--jobs", ""], ["--jobs"]):
            with self.subTest(argv=argv):
                before = self.both()
                proc = self.run_release("dev", *argv)
                self.assertEqual((proc.returncode, proc.stdout), (2, ""), proc.stderr)
                self.assertTrue(proc.stderr.startswith("usage: release.py "), proc.stderr)
                self.assertIn("release.py: error: argument --jobs", proc.stderr)
                self.assertNotIn("Traceback", proc.stderr)
                self.assertEqual(list(self.records.iterdir()), [])  # nothing ran
                self.assertFalse((self.base / "claude.log").exists())
                self.assertEqual(self.both(), before)

    def test_one_process_per_module_at_most_n_at_a_time(self):
        engine = os.path.realpath(self.engine)
        for jobs in (None, 1, 4, 32):
            with self.subTest(jobs=jobs):
                argv = [] if jobs is None else ["--jobs", str(jobs)]
                loud = {"R1_LOUD": "test_m_middle"} if jobs == 4 else {}  # > 64 KiB each stream
                proc = self.run_release("dev", *argv, env={**VALIDATE, "R1_HOLD": "0.6", **loud})
                self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
                self.assertTrue(proc.stderr.startswith(STEP5), proc.stderr)
                self.assertTrue(proc.stderr.endswith(AS_THEY_WERE), proc.stderr)
                used = default_jobs() if jobs is None else jobs
                self.assertIn(step3(7, 6, used, skipped=1), proc.stdout)
                starts, ends = self.recorded("start"), self.recorded("end")  # one per module
                self.assertEqual(sorted(starts), list(PLANTED))  # each module once
                self.assertEqual(len(list(self.records.glob("*.*.start"))), len(PLANTED))
                self.assertEqual(sorted(ends), list(PLANTED))
                for stem, row in starts.items():
                    self.assertEqual(row["python"], sys.executable)  # the release's own
                    self.assertEqual(row["argv"], ["-m", "unittest", "discover", "-s", "tests",
                                                   "-p", f"{stem}.py"])
                    self.assertEqual(os.path.realpath(row["cwd"]), engine)
                    self.assertEqual(row["bytecode"], "1")
                    self.assertEqual(row["pgid"], row["pid"])  # its own process group
                    self.assertNotEqual(row["pgid"], row["parent_pgid"])
                self.assertEqual(len({row["parent"] for row in starts.values()}), 1)
                spans = [(starts[s]["time"], ends[s]["time"]) for s in PLANTED]
                self.assertLessEqual(overlap(spans), used)
                if used == 1:  # one after the other, in the start order
                    order = sorted(PLANTED, key=lambda s: starts[s]["time"])
                    self.assertEqual(order, [s for s in START_ORDER if s in PLANTED])
                    self.assertEqual(overlap(spans), 1)
                elif used >= 4:
                    self.assertGreaterEqual(overlap(spans), 2)
                self.assertEqual(list(self.engine.rglob("__pycache__")), [])
                self.assertEqual(list(self.tmpdir.iterdir()), [])  # the logs went with it
        direct = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"],
                                cwd=self.engine, capture_output=True, text=True,
                                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertIn("Ran 7 tests in ", direct.stderr)  # what the per-module counts add up to

    def test_the_default_and_the_bounds(self):
        release = load_tool("release")
        for count, want in ((None, 1), (1, 1), (2, 2), (4, 4), (10, 4)):
            with self.subTest(cpu_count=count), mock.patch.object(release.os, "cpu_count",
                                                                  return_value=count):
                self.assertEqual(release.default_jobs(), want)
        for text, want in (("1", 1), ("4", 4), ("32", 32)):
            self.assertEqual(release.jobs_value(text), want)
        for text in ("0", "33", "-1", "x", "4.5", "", " 4", "1e1"):
            with self.subTest(text=text), self.assertRaises(release.argparse.ArgumentTypeError):
                release.jobs_value(text)

    def test_the_modules_of_this_engine_add_up(self):
        release = load_tool("release")
        modules = release.test_modules(ENGINE)
        names = sorted(p.stem for p in (ENGINE / "tests").glob("test_*.py"))
        self.assertEqual(sorted(modules), names)
        first = [m for m in modules if m.startswith("test_release")]
        self.assertEqual(modules[:len(first)], sorted(first))  # test_release* first, by name
        self.assertEqual(modules[len(first):], sorted(set(names) - set(first)))
        count = subprocess.run([sys.executable, "-c", (
            "import json, sys, unittest\n"
            "loader = unittest.TestLoader()\n"
            "each = {m: loader.discover('tests', pattern=m + '.py').countTestCases() "
            "for m in json.loads(sys.argv[1])}\n"
            "print(json.dumps([each, loader.discover('tests').countTestCases()]))\n"),
            json.dumps(modules)], cwd=ENGINE, capture_output=True, text=True, check=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        each, total = json.loads(count.stdout)
        self.assertEqual(sum(each.values()), total)
        self.assertEqual([m for m, n in each.items() if n < 1], [])  # SI-P83-14: ≥ 1 test each


class StepLineTest(SuiteRepo):  # P83-AC-017
    def test_the_singular_and_plural_forms(self):
        release = load_tool("release")
        for args, want in (((3, 2, 4, 1), "Ran 3 tests in 2 modules (4 jobs), OK (skipped=1)"),
                           ((2, 2, 4, 0), "Ran 2 tests in 2 modules (4 jobs), OK"),
                           ((1, 1, 1, 0), "Ran 1 test in 1 module (1 job), OK"),
                           ((0, 1, 2, 0), "Ran 0 tests in 1 module (2 jobs), OK"),
                           ((5, 3, 32, 1), "Ran 5 tests in 3 modules (32 jobs), OK (skipped=1)")):
            self.assertEqual(release.suite_line(*args), want)

    def test_with_and_without_a_skip_and_one_module(self):
        proc = self.run_release("dev", "--jobs", "2", env={  # a second skip, in a module that
            **VALIDATE, "R1_SKIP": "test_z_last", "R1_TRAILER": "test_z_last"})  # prints a line
        self.assertIn(step3(7, 6, 2, skipped=2), proc.stdout)  # after unittest's verdict
        proc = self.run_release("dev", "--jobs", "2", env=VALIDATE)
        self.assertIn(step3(7, 6, 2, skipped=1), proc.stdout)
        self.commit(self.engine, "tests/test_ok.py", "import unittest\n\n\nclass OkTest("
                    "unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n",
                    "no skip")
        proc = self.run_release("dev", "--jobs", "4", env=VALIDATE)
        self.assertIn(step3(6, 6, 4), proc.stdout)
        git(self.engine, "rm", "-q", "--", "tests/test_plant.py",
            *(f"tests/{stem}.py" for stem in PLANTED))
        git(self.engine, "commit", "-q", "-m", "one module")
        proc = self.run_release("dev", "--jobs", "1", env=VALIDATE)
        self.assertIn(step3(1, 1, 1), proc.stdout)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)

    def test_a_failing_module_is_named(self):  # SI-P83-14: in start order, the tail of the first
        for failing, named in (("test_m_middle", "test_m_middle"),
                               ("test_z_last,test_release_zz", "test_release_zz, test_z_last"),
                               ("test_a_first,test_release_zz", "test_release_zz, test_a_first")):
            with self.subTest(failing=failing):
                before = self.both()
                late = {"R1_FAIL_LATE": "test_release_zz"} if "test_a_first" in failing else {}
                proc = self.run_release("dev", "--jobs", "3", env={"R1_FAIL": failing,
                                                                  "R1_HOLD": "0.3", **late})
                if late:  # started first, failed last, after test_a_first by name: only the
                    fails = self.recorded("fail")  # start order names test_release_zz first
                    self.assertGreater(fails["test_release_zz"]["time"],
                                       fails["test_a_first"]["time"])
                first = named.split(", ")[0]
                self.assertEqual((proc.returncode, proc.stderr), (
                    1, f"release.py: step 3 tests failed: the unit suite failed in {named}: "
                       f"{failure(first).strip()[-600:]}{AS_THEY_WERE}"))
                self.assertNotIn("step 3 tests:", proc.stdout)
                ran = set(PLANTED) - set(failing.split(","))
                self.assertEqual(sorted(self.recorded("end")), sorted(ran))  # each to its end
                self.assertFalse((self.records / "eval.ran").exists())  # the E-A did not run
                self.assertEqual(self.both(), before)
                self.assertEqual(list(self.tmpdir.iterdir()), [])

    def test_a_failing_eval_after_a_green_suite(self):
        proc = self.run_release("dev", env={"R1_EVAL_FAIL": "1"})
        self.assertEqual((proc.returncode, proc.stderr), (
            1, "release.py: step 3 tests failed: the adoption eval failed: adoption eval: "
               f"planted failure{AS_THEY_WERE}"))
        self.assertEqual(sorted(self.recorded("end")), list(PLANTED))
        self.assertTrue((self.records / "eval.ran").exists())


if __name__ == "__main__":
    unittest.main()
