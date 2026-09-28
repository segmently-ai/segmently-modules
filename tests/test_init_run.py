"""`init run --executor CMD` (D1, driver 3): the executor contract, its failure modes, `[init]
max_parallel`, writes outside the staging dir, the module transitions of a run, Ctrl-C."""
import json
import os
import shlex
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import run
from tests.init_helpers import FAKE, SIX, WORK, executor, ok, protected_sha, shop, state, text


class RunRepo(unittest.TestCase):
    CONFIG = ""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.template = shop(Path(cls._tmp.name).resolve(), name="template", config=cls.CONFIG)
        ok(cls.template, "init", "fanout")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(dir=self._tmp.name)).resolve()
        self.root = self.base / "shop"
        shutil.copytree(self.template, self.root, symlinks=True)
        self.log = self.base / "calls.jsonl"

    def config(self, text: str) -> None:
        path = self.root / ".modsys/config.toml"
        path.write_text(path.read_text() + "\n" + text)

    def run_init(self, *flags: str, code: int = 0, argv=("init", "run")) -> tuple:
        got, out, err = run(*argv, "--executor", executor("--record", str(self.log), *flags),
                            "--json", "--root", str(self.root))
        self.assertEqual(got, code, err)
        return json.loads(out)["data"], err

    def calls(self, event: str = "start") -> list[dict]:
        if not self.log.exists():
            return []
        return [json.loads(l) for l in self.log.read_text().splitlines()
                if json.loads(l)["event"] == event]


class ExecutorContractTest(RunRepo):  # P5B-AC-007
    def test_what_the_executor_receives(self):
        with mock.patch.dict(os.environ, {"MODSYS_TEST_MARK": "inherited"}):
            data, err = self.run_init("--non-interactive")
        self.assertEqual(err, "")
        self.assertEqual(set(data), {"action", "modules", "counts", "outside", "failed", "next"})
        self.assertEqual(([r["module"] for r in data["modules"]], data["failed"]), (SIX, False))
        self.assertEqual({r["status"] for r in data["modules"]}, {"done"})
        self.assertEqual(data["counts"], {"pending": 0, "running": 0, "done": 6, "failed": 0})
        calls = self.calls()
        self.assertEqual(sorted(c["module"] for c in calls), SIX)
        for call in calls:
            m = call["module"]
            item = json.loads((self.root / WORK / "work" / f"{m}.json").read_text())
            with self.subTest(module=m):
                import hashlib
                self.assertEqual(call["stdin_sha256"],
                                 hashlib.sha256(item["prompt"].encode("utf-8")).hexdigest())
                self.assertEqual(call["env"]["MODSYS_INIT_MODULE"], m)
                self.assertEqual(call["env"]["MODSYS_INIT_STAGING"],
                                 str(self.root / WORK / "staging" / m))
                self.assertEqual(call["env"]["MODSYS_INIT_WORK"],
                                 str(self.root / WORK / "work" / f"{m}.json"))
                self.assertEqual(call["env"]["MODSYS_TEST_MARK"], "inherited")
                self.assertEqual(Path(call["cwd"]).resolve(), self.root.resolve())
        self.assertEqual(self.run_init()[0]["modules"], [])  # nothing pending: nothing runs
        self.assertEqual(len(self.calls()), 6)

    def test_the_command_is_split_never_a_shell(self):
        spaced = self.base / "a dir"
        spaced.mkdir()
        shutil.copy(FAKE, spaced / "fake.py")
        cmd = (f"{shlex.quote(sys.executable)} '{spaced}/fake.py' --record {self.log} --tag 'a b' "
               f"> out.txt $HOME")
        got, _, err = run("init", "run", "--executor", cmd, "--root", str(self.root))
        self.assertEqual((got, err), (0, ""))
        argv = self.calls()[0]["argv"]
        self.assertEqual(argv[0], str(spaced / "fake.py"))
        self.assertEqual(argv[1:], ["--record", str(self.log), "--tag", "a b", ">", "out.txt",
                                    "$HOME"])
        self.assertFalse((self.root / "out.txt").exists())


class ExecutorFailuresTest(RunRepo):  # P5B-AC-008
    def test_failed_items(self):
        data, err = self.run_init("--fail", "cart", "--keywords4", "catalog", "--nothing",
                                  "payments", code=1)
        rows = {r["module"]: r for r in data["modules"]}
        self.assertEqual({m: r["status"] for m, r in rows.items()},
                         {"cart": "failed", "catalog": "failed", "payments": "failed",
                          "recommendations": "done", "storefront": "done", "ui-kit": "done"})
        lines = [f"cart: line {i} of the failure" for i in range(31, 51)]
        self.assertEqual(rows["cart"]["error"], "exit 3: " + "\n".join(lines))
        self.assertLessEqual(len(rows["cart"]["error"]), 2000 + len("exit 3: "))
        self.assertEqual(rows["catalog"]["error"],
                         "at least 5 distinct keywords (a list of non-empty strings)")
        self.assertTrue(rows["payments"]["error"].startswith("missing MODULE.md; "))
        self.assertIn("modsys: cart failed: exit 3: cart: line 31 of the failure",
                      err.splitlines())
        self.assertTrue(data["failed"])
        self.assertEqual(state(self.root)["modules"]["cart"],
                         {"status": "failed", "attempts": 1, "error": rows["cart"]["error"]})
        data, _ = self.run_init()  # a new run: the failed ones again (attempt 2)
        self.assertEqual({r["module"]: (r["status"], r["attempts"]) for r in data["modules"]},
                         {"cart": ("done", 2), "catalog": ("done", 2), "payments": ("done", 2)})

    def test_argument_problems_run_nothing(self):
        for value, needle in (("", "--executor is empty"), ("  ", "--executor is empty"),
                              ("python3 'unbalanced", "--executor: No closing quotation"),
                              ("no-such-binary-x", "executor not found: no-such-binary-x"),
                              ("./missing.py", "executor not found: ./missing.py")):
            with self.subTest(value=value):
                got, out, err = run("init", "run", "--executor", value, "--json", "--root",
                                    str(self.root))
                self.assertEqual((got, out), (2, ""))
                self.assertIn(needle, err)
        self.assertEqual(set(m["status"] for m in state(self.root)["modules"].values()),
                         {"pending"})
        self.assertEqual(self.calls(), [])

    def test_a_relative_executor_resolves_against_the_root(self):
        script = self.root / "fake.py"
        script.write_text(f"#!{sys.executable}\nimport runpy, sys\n"
                          f"sys.argv[0] = {str(FAKE)!r}\nrunpy.run_path({str(FAKE)!r}, "
                          f"run_name='__main__')\n")
        script.chmod(0o755)
        elsewhere = self.base / "elsewhere"
        elsewhere.mkdir()
        cwd = os.getcwd()
        os.chdir(elsewhere)
        try:
            got, _, err = run("init", "run", "--executor", "./fake.py", "--root", str(self.root))
        finally:
            os.chdir(cwd)
        self.assertEqual((got, err), (0, ""))
        self.assertEqual(set(m["status"] for m in state(self.root)["modules"].values()), {"done"})
        script.chmod(0o644)
        self.assertIn("executor is not executable: ./fake.py",
                      run("init", "run", "--executor", "./fake.py", "--root", str(self.root))[2])


class MaxParallelTest(RunRepo):  # P5B-AC-009 (SI-7)
    def peak(self, max_parallel) -> tuple[int, list[str]]:
        if max_parallel is not None:
            self.config(f"[init]\nmax_parallel = {max_parallel}\n")
        peers = min(max_parallel or 4, 6)
        self.run_init("--peers", str(peers), "--live", str(self.base / "live"))
        events = sorted([(c["time"], 1) for c in self.calls("start")]
                        + [(c["time"], -1) for c in self.calls("end")],
                        key=lambda e: (e[0], e[1]))
        live = best = 0
        for _, step in events:
            live += step
            best = max(best, live)
        return best, [c["module"] for c in sorted(self.calls(), key=lambda c: c["time"])]

    def test_the_boundaries(self):
        for value, expected in ((1, 1), (None, 4), (4, 4), (6, 6), (10, 6)):
            with self.subTest(max_parallel=value):
                self.setUp()
                peak, order = self.peak(value)
                self.assertEqual(peak, expected)
                if value == 1:
                    self.assertEqual(order, SIX)  # one at a time, in name order

    def test_bad_values_run_nothing(self):
        for value in ("0", "-1", "true", "2.5", '"4"'):
            with self.subTest(value=value):
                self.setUp()
                self.config(f"[init]\nmax_parallel = {value}\n")
                got, out, err = run("init", "run", "--executor", executor(), "--json", "--root",
                                    str(self.root))
                self.assertEqual((got, out), (2, ""))
                self.assertIn(".modsys/config.toml: [init] max_parallel must be an integer >= 1",
                              err)
                self.assertEqual({m["status"] for m in state(self.root)["modules"].values()},
                                 {"pending"})


class StagingOnlyTest(RunRepo):  # P5B-AC-011 (phase 4; the later phases: test_init_chain)
    def test_the_protected_files_stay_until_finish(self):
        before = protected_sha(self.root)
        ok(self.root, "init", "next")
        self.run_init()
        ok(self.root, "init", "resume")
        self.assertEqual(protected_sha(self.root), before)

    def test_a_write_outside_the_staging_dir(self):
        data, err = self.run_init("--outside", "modules/catalog/MODULE.md", code=1)
        self.assertIn("modsys: wrote outside the staging dir: modules/catalog/MODULE.md",
                      err.splitlines())
        self.assertEqual((data["outside"], data["failed"]), (["modules/catalog/MODULE.md"], True))
        self.assertEqual({r["status"] for r in data["modules"]}, {"done"})


class RunTransitionsTest(RunRepo):  # P5B-AC-003 (the executor rows; claims: test_init_state)
    def test_running_failed_pending_done(self):
        ok(self.root, "init", "next")  # cart running, then the run resets it
        stale = self.root / WORK / "staging/cart/partial.tmp"
        stale.write_text("half")
        data, _ = self.run_init("--fail", "catalog", code=1)
        self.assertFalse(stale.exists())
        rows = {r["module"]: (r["status"], r["attempts"]) for r in data["modules"]}
        self.assertEqual((rows["cart"], rows["catalog"]), (("done", 2), ("failed", 1)))
        data = ok(self.root, "init", "resume")
        self.assertEqual(data["message"], "back to pending (their staging cleared): catalog")
        self.assertEqual(state(self.root)["modules"]["catalog"]["status"], "pending")
        self.assertFalse((self.root / WORK / "staging/catalog").exists())
        self.assertIn("exit 3", state(self.root)["modules"]["catalog"]["error"])  # kept till a claim
        data, _ = self.run_init(argv=("init", "resume"))
        self.assertEqual(data["ran"][0], "run")
        self.assertEqual(state(self.root)["modules"]["catalog"],
                         {"status": "done", "attempts": 2, "error": None})


class RunInterruptTest(RunRepo):  # P5B-AC-038 (Ctrl-C during init run)
    def test_ctrl_c_stops_the_children_and_resume_finishes(self):
        self.config("[init]\nmax_parallel = 3\n")
        pids = self.base / "pids"

        def interrupt():
            if pids.is_dir() and len(list(pids.iterdir())) == 3:
                raise KeyboardInterrupt
            time.sleep(0.05)

        with mock.patch("modsys.init_run.pause", side_effect=interrupt):
            got = run("init", "run", "--executor", executor("--sleep", "30", "--pids", str(pids)),
                      "--root", str(self.root))
        self.assertEqual(got, (130, "", "modsys: interrupted\n"))
        for pid in (int(p.name) for p in pids.iterdir()):
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)
        running = sorted(m for m, e in state(self.root)["modules"].items()
                         if e["status"] == "running")
        self.assertEqual(running, ["cart", "catalog", "payments"])
        got, _, err = run("init", "resume", "--executor", executor(), "--root", str(self.root))
        self.assertEqual((got, err), (0, ""))
        self.assertEqual({e["status"] for e in state(self.root)["modules"].values()}, {"done"})


if __name__ == "__main__":
    unittest.main()
