"""`init run --executor CMD` (D1, driver 3): the executor contract, its failure modes, `[init]
max_parallel`, writes outside the staging dir, the module transitions of a run, Ctrl-C."""
import hashlib
import json
import os
import shlex
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import git, run
from tests.init_fake_executor import write_docs
from tests.init_helpers import (FAKE, SIX, WORK, executor, invented, ok, protected_sha, shop,
                                state, text, with_note)


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
        path = self.root / ".segmently-modules/config.toml"
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
        with mock.patch.dict(os.environ, {"SEGMENTLY_MODULES_TEST_MARK": "inherited"}):
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
                self.assertEqual(call["env"]["SEGMENTLY_MODULES_INIT_MODULE"], m)
                self.assertEqual(call["env"]["SEGMENTLY_MODULES_INIT_STAGING"],
                                 str(self.root / WORK / "staging" / m))
                self.assertEqual(call["env"]["SEGMENTLY_MODULES_INIT_WORK"],
                                 str(self.root / WORK / "work" / f"{m}.json"))
                self.assertEqual(call["env"]["SEGMENTLY_MODULES_TEST_MARK"], "inherited")
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
        self.assertIn("segmently-modules: cart failed: exit 3: cart: line 31 of the failure",
                      err.splitlines())
        self.assertTrue(data["failed"])
        self.assertEqual(state(self.root)["modules"]["cart"],
                         {"status": "failed", "attempts": 1, "error": rows["cart"]["error"]})
        self.assertEqual({m: r["attempts"] for m, r in rows.items() if r["status"] == "failed"},
                         {"cart": 1, "catalog": 2, "payments": 2})  # a refused output: 1 retry
        data, _ = self.run_init()  # a new run: the failed ones again
        self.assertEqual({r["module"]: (r["status"], r["attempts"]) for r in data["modules"]},
                         {"cart": ("done", 2), "catalog": ("done", 3), "payments": ("done", 3)})

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
                self.assertIn(".segmently-modules/config.toml: [init] max_parallel must be an integer >= 1",
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
        self.assertIn("segmently-modules: wrote outside the staging dir: modules/catalog/MODULE.md",
                      err.splitlines())
        self.assertEqual((data["outside"], data["failed"]), (["modules/catalog/MODULE.md"], True))
        self.assertEqual({r["status"] for r in data["modules"]}, {"done"})

    def test_a_staged_move_into_the_staging_dir(self):  # Task 6 review I1: the source counts
        self.config("[init]\nmax_parallel = 1\n")
        data, err = self.run_init("--git-mv", "packages/catalog/src/books.ts", code=1)
        self.assertIn("segmently-modules: wrote outside the staging dir: packages/catalog/src/books.ts",
                      err.splitlines())
        self.assertEqual(data["outside"], ["packages/catalog/src/books.ts"])

    def test_a_work_tree_rename(self):  # N-3: a rename in either column takes its source
        from segmently_modules.init_run import changed_paths
        src = self.root / "packages/catalog/src"
        (src / "books.ts").rename(src / "tomes.ts")
        git(self.root, "add", "-N", "packages/catalog/src/tomes.ts")  # a rename in column Y
        got = changed_paths(self.root)
        self.assertEqual({p for _, p in got if "catalog" in p},
                         {"packages/catalog/src/tomes.ts", "packages/catalog/src/books.ts"})
        self.assertTrue(all(code[0] in " MADRCU?!" and code[1] in " MADRCU?!"
                            for code, _ in got), got)

    def test_a_symlink_to_a_fifo_is_never_opened(self):  # M-7: lstat, the link text hashed
        from segmently_modules.init_run import outside_snapshot
        fifo = self.base / "pipe"
        os.mkfifo(fifo)
        (self.root / "notes.pipe").symlink_to(fifo)
        got = []
        worker = threading.Thread(target=lambda: got.append(
            outside_snapshot(self.root, f"{WORK}/")), daemon=True)
        worker.start()
        worker.join(timeout=20)
        self.assertFalse(worker.is_alive(), "outside_snapshot opened the FIFO")
        code, sha = got[0]["notes.pipe"]
        self.assertEqual(code, "??")
        self.assertTrue(sha.startswith("symlink:"))
        (self.root / "notes.pipe").unlink()
        (self.root / "notes.pipe").symlink_to(self.base / "elsewhere")
        self.assertNotEqual(outside_snapshot(self.root, f"{WORK}/")["notes.pipe"][1], sha)


class RaceTest(RunRepo):  # I-3 (T-1): init next racing init run
    CONFIG = "[init]\nmax_parallel = 1\n"

    def test_a_module_claimed_meanwhile_is_left_to_its_claimer(self):
        claimed = []

        def agent():  # while init run waits on its first module, an agent claims the next one
            if not claimed:
                claimed.append(ok(self.root, "init", "next")["item"]["module"])
            time.sleep(0.05)

        with mock.patch("segmently_modules.init_run.pause", side_effect=agent):
            data, err = self.run_init()
        (mine,) = claimed
        starts = [c["module"] for c in self.calls()]
        self.assertEqual(sorted(starts), [m for m in SIX if m != mine])  # each at most once
        self.assertNotIn(mine, [r["module"] for r in data["modules"]])
        self.assertEqual(state(self.root)["modules"][mine],
                         {"status": "running", "attempts": 1, "error": None})  # the agent's
        write_docs(self.root, json.loads((self.root / WORK / f"work/{mine}.json").read_text()))
        self.assertEqual(ok(self.root, "init", "done", mine)["status"], "done")


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

        with mock.patch("segmently_modules.init_run.pause", side_effect=interrupt):
            got = run("init", "run", "--executor", executor("--sleep", "30", "--pids", str(pids)),
                      "--root", str(self.root))
        self.assertEqual(got, (130, "", "segmently-modules: interrupted\n"))
        for pid in (int(p.name) for p in pids.iterdir()):
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)
        running = sorted(m for m, e in state(self.root)["modules"].items()
                         if e["status"] == "running")
        self.assertEqual(running, ["cart", "catalog", "payments"])
        got, _, err = run("init", "resume", "--executor", executor(), "--root", str(self.root))
        self.assertEqual((got, err), (0, ""))
        self.assertEqual({e["status"] for e in state(self.root)["modules"].values()}, {"done"})

    def test_one_deadline_for_every_child(self):  # Task 6 review M1: then SIGKILL the rest
        self.config("[init]\nmax_parallel = 3\n")
        pids, stopped = self.base / "pids", []

        def interrupt():
            if pids.is_dir() and len(list(pids.iterdir())) == 3:
                stopped.append(time.monotonic())
                raise KeyboardInterrupt
            time.sleep(0.05)

        with mock.patch("segmently_modules.init_run.pause", side_effect=interrupt), \
                mock.patch("segmently_modules.init_run.STOP_S", 1):
            got = run("init", "run", "--executor", executor("--sleep", "30", "--pids", str(pids),
                                                            "--ignore-term", "yes"),
                      "--root", str(self.root))
        elapsed = time.monotonic() - stopped[0]
        self.assertEqual(got, (130, "", "segmently-modules: interrupted\n"))
        self.assertLess(elapsed, 2.5)  # one second for all three, not one second each
        for pid in (int(p.name) for p in pids.iterdir()):
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


ENGINE = Path(__file__).resolve().parents[1]
BREAKER = '''"""A writer whose cart output the check refuses (argv: the engine root, the mode): `link` — its
staging dir replaced by a symlink; `read-only` — a path that does not exist and a read-only roles
dir; `dollar` — `${API_URL}` in its MODULE.md; `unlink` / `damage` / `shape` — clean docs, its
own work item removed / not JSON / `{}`. Every other module waits until cart is failed in the
state (so it runs while cart's retry is claimed or its check fails), then writes the fake
writer's docs."""
import json, os, shutil, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from tests.init_fake_executor import invent, write_docs
sys.stdin.buffer.read()
module, mode = os.environ["SEGMENTLY_MODULES_INIT_MODULE"], sys.argv[2]
staging = Path(os.environ["SEGMENTLY_MODULES_INIT_STAGING"])
item = json.loads(Path(os.environ["SEGMENTLY_MODULES_INIT_WORK"]).read_text(encoding="utf-8"))
if module != "cart":
    state, deadline = staging.parents[1] / "state.json", time.time() + 30
    while time.time() < deadline and json.loads(state.read_text(encoding="utf-8"))[
            "modules"]["cart"]["status"] != "failed":
        time.sleep(0.02)
    write_docs(Path.cwd(), item, staging)
elif mode == "link":
    real = staging.parents[1] / "cart-real"
    real.mkdir()
    write_docs(Path.cwd(), item, real)
    shutil.rmtree(staging)
    os.symlink(real, staging)
elif mode == "read-only":
    write_docs(Path.cwd(), item, staging)
    invent(staging, item)
    os.chmod(staging / "roles", 0o555)
elif mode in ("unlink", "damage", "shape"):
    write_docs(Path.cwd(), item, staging)
    work_item = Path(os.environ["SEGMENTLY_MODULES_INIT_WORK"])
    if mode == "unlink":
        work_item.unlink()
    else:
        work_item.write_text("{not json" if mode == "damage" else "{}", encoding="utf-8")
else:
    write_docs(Path.cwd(), item, staging)
    with open(staging / "MODULE.md", "a", encoding="utf-8") as fh:
        fh.write("\\nCall `${API_URL}` first.\\n")
'''


class RetryTest(RunRepo):  # P5C-AC-008, P5C-AC-009, P5C-AC-022 (D3, SI-4, SI-6, SI-8, SI-10)
    RETRY = "segmently-modules: cart: refused — retrying once"

    def stdins(self, module: str) -> list[str]:
        return [c["stdin_sha256"] for c in self.calls() if c["module"] == module]

    def prompt(self, module: str) -> str:
        return json.loads((self.root / WORK / f"work/{module}.json").read_text())["prompt"]

    def test_one_retry_with_the_problems_then_done(self):  # P5C-AC-008
        from segmently_modules.init_run import Runner
        self.config("[init]\nmax_parallel = 1\n")
        work_item = self.root / WORK / "work/cart.json"
        before = work_item.read_bytes()
        staging, seen, real = self.root / WORK / "staging/cart", [], Runner.start

        def start(runner, module, item):  # what the staging dir holds when a writer starts
            if module == "cart":
                seen.append(sorted(p.name for p in staging.rglob("*")))
            return real(runner, module, item)

        with mock.patch("segmently_modules.init_run.Runner.start", autospec=True, side_effect=start):
            data, err = self.run_init("--invent", "cart")
        self.assertEqual(err.splitlines(), [self.RETRY])
        self.assertEqual(seen, [[], []])  # the retry's claim cleared the first attempt's files
        self.assertEqual(self.stdins("cart"), [sha(self.prompt("cart")),
                                               sha(with_note(self.prompt("cart"),
                                                             invented("cart")))])
        self.assertEqual({m: len(self.stdins(m)) for m in SIX},
                         {m: 2 if m == "cart" else 1 for m in SIX})
        self.assertEqual(next(r for r in data["modules"] if r["module"] == "cart"),
                         {"module": "cart", "status": "done", "attempts": 2, "error": None})
        self.assertEqual(state(self.root)["modules"]["cart"],
                         {"status": "done", "attempts": 2, "error": None})
        self.assertEqual((data["failed"], [r["module"] for r in data["modules"]]), (False, SIX))
        self.assertEqual(work_item.read_bytes(), before)  # the fan-out digest holds

    def test_refused_twice_and_an_exit_failure(self):  # P5C-AC-008 (the table's last rows)
        data, err = self.run_init("--invent-always", "cart", "--fail", "catalog", code=1)
        rows = {r["module"]: r for r in data["modules"]}
        joined = "; ".join(invented("cart"))
        self.assertEqual(rows["cart"], {"module": "cart", "status": "failed", "attempts": 2,
                                        "error": joined})
        self.assertEqual(state(self.root)["modules"]["cart"],
                         {"status": "failed", "attempts": 2, "error": joined,
                          "problems": invented("cart")})
        self.assertEqual((len(self.stdins("cart")), len(self.stdins("catalog"))), (2, 1))
        self.assertTrue(rows["catalog"]["error"].startswith("exit 3: "))
        self.assertNotIn("problems", state(self.root)["modules"]["catalog"])
        self.assertEqual([l for l in err.splitlines() if "retrying" in l], [self.RETRY])
        self.assertIn(f"segmently-modules: cart failed: {joined}", err.splitlines())

    def test_bounds(self):  # P5C-AC-009 (SI-4): one retry per module per run
        self.run_init("--invent-always", "cart", code=1)
        self.run_init("--invent-always", "cart", code=1)  # a new run: a new retry
        self.assertEqual(len(self.stdins("cart")), 4)
        self.assertEqual(state(self.root)["modules"]["cart"]["attempts"], 4)
        self.setUp()
        data, err = self.run_init("--invent", "cart,payments")  # four at a time, the default
        self.assertEqual({m: len(self.stdins(m)) for m in SIX},
                         {m: 2 if m in ("cart", "payments") else 1 for m in SIX})
        self.assertEqual(sorted(err.splitlines()), [self.RETRY,
                                                    "segmently-modules: payments: refused — retrying once"])
        events = sorted([(c["time"], 1) for c in self.calls("start")]
                        + [(c["time"], -1) for c in self.calls("end")])
        live = [sum(step for _, step in events[:i + 1]) for i in range(len(events))]
        self.assertLessEqual(max(live), 4)
        self.assertEqual({r["status"] for r in data["modules"]}, {"done"})

    def test_a_retry_claimed_by_another_driver(self):  # P5C-AC-009 (SI-10)
        from segmently_modules.init_work import Work
        self.config("[init]\nmax_parallel = 1\n")
        real, taken = Work.claim, []

        def claim(work, module=None):  # the retry's claim: an agent's init next came first
            if module == "cart" and self.stdins("cart"):
                taken.append(ok(self.root, "init", "next"))
            return real(work, module)

        with mock.patch("segmently_modules.init_work.Work.claim", autospec=True, side_effect=claim):
            data, err = self.run_init("--invent", "cart")
        (agent,) = taken
        self.assertEqual((agent["item"]["module"], agent["item"]["previous_problems"]),
                         ("cart", invented("cart")))
        self.assertEqual(len(self.stdins("cart")), 1)  # no second writer on its staging dir
        self.assertNotIn("cart", [r["module"] for r in data["modules"]])
        self.assertEqual(state(self.root)["modules"]["cart"],
                         {"status": "running", "attempts": 2, "error": None})

    def test_a_module_taken_over_while_its_writer_ran(self):  # PR-18: the same attempt only
        self.config("[init]\nmax_parallel = 1\n")
        live, taken = self.base / "live", []

        def agent():  # cart's writer waits for it: another driver resumes and claims cart,
            if not taken and (live / "cart").exists():  # then lets the writer go on
                ok(self.root, "init", "resume")
                taken.append(ok(self.root, "init", "next")["item"]["module"])
                (live / "agent").write_text("")  # the handshake: no timing window (T-6)
            time.sleep(0.05)

        with mock.patch("segmently_modules.init_run.pause", side_effect=agent):  # each writer waits for
            data, err = self.run_init("--invent", "cart", "--peers", "2",  # two files in live/
                                      "--live", str(live))
        self.assertEqual((taken, err), (["cart"], ""))  # no retry of a module it lost
        self.assertEqual(len(self.stdins("cart")), 1)
        self.assertNotIn("cart", [r["module"] for r in data["modules"]])
        self.assertEqual(state(self.root)["modules"]["cart"],  # the other driver's claim
                         {"status": "running", "attempts": 2, "error": None})

    def test_ctrl_c_during_a_retry(self):  # P5C-AC-022
        self.config("[init]\nmax_parallel = 1\n")
        pids = self.base / "pids"

        def interrupt():
            if pids.is_dir() and [p.read_text() for p in pids.iterdir()].count("cart") == 2:
                raise KeyboardInterrupt
            time.sleep(0.05)

        with mock.patch("segmently_modules.init_run.pause", side_effect=interrupt):
            got = run("init", "run", "--executor", executor("--invent", "cart", "--sleep-retry",
                                                            "30", "--pids", str(pids)),
                      "--root", str(self.root))
        self.assertEqual(got, (130, "", f"{self.RETRY}\nsegmently-modules: interrupted\n"))
        for pid in (int(p.name) for p in pids.iterdir()):
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)
        self.assertEqual(state(self.root)["modules"]["cart"],  # the retry's claim dropped them
                         {"status": "running", "attempts": 2, "error": None})
        ok(self.root, "init", "resume")
        self.assertEqual(state(self.root)["modules"]["cart"]["status"], "pending")
        item = ok(self.root, "init", "next")["item"]
        self.assertEqual(item, json.loads((self.root / WORK / "work/cart.json").read_text()))

    def test_a_write_outside_on_both_attempts(self):  # P5C-AC-022: named once
        data, err = self.run_init("--invent", "cart", "--outside", "notes/outside.md", code=1)
        self.assertEqual(data["outside"], ["notes/outside.md"])
        self.assertEqual(err.count("segmently-modules: wrote outside the staging dir: notes/outside.md"), 1)
        self.assertEqual(len(self.stdins("cart")), 2)

    def breaker(self, mode: str) -> tuple[int, dict, str]:
        """`init run --json` with the `BREAKER` writer in `mode`: (exit code, data, stderr)."""
        script = self.base / "breaker.py"
        script.write_text(BREAKER, encoding="utf-8")
        exe = " ".join(shlex.quote(a) for a in (sys.executable, str(script), str(ENGINE), mode))
        code, out, err = run("init", "run", "--executor", exe, "--json", "--root", str(self.root))
        self.assertNotIn("Traceback", err)
        self.assertNotIn("segmently-modules: error", err)
        data = json.loads(out)["data"]
        self.assertEqual(set(data), {"action", "modules", "counts", "outside", "failed", "next"})
        return code, data, err

    def assert_only_cart_failed(self, data: dict, error: str) -> None:
        self.assertEqual(data["modules"], [
            {"module": m, "status": "failed" if m == "cart" else "done", "attempts": 1,
             "error": error if m == "cart" else None} for m in SIX])

    def test_a_retry_that_cannot_be_claimed(self):  # final review I-2 (P5C-AC-021: never 2)
        linked = (f"the staging dir {WORK}/staging/cart is a symlink (write the files into a "
                  f"real directory)")
        rows = [("link", [linked], f"{linked}; the retry could not start: {WORK}/staging/cart "
                                   f"is a symlink — remove it (its target is left alone)")]
        if os.geteuid() != 0:  # (a root user removes a read-only dir's files anyway)
            rows.append(("read-only", invented("cart"),
                         "; ".join(invented("cart")) + f"; the retry could not start: cannot "
                                                       f"write {WORK}/staging/cart/: Permission "
                                                       f"denied"))
        for mode, problems, error in rows:
            with self.subTest(mode=mode):
                self.setUp()
                roles = self.root / WORK / "staging/cart/roles"
                try:
                    code, data, err = self.breaker(mode)  # the peers wait for cart's failure
                finally:
                    if roles.is_dir():
                        roles.chmod(0o755)
                self.assertEqual((code, data["failed"]), (1, True))
                self.assertEqual(err.splitlines(), [self.RETRY, f"segmently-modules: cart failed: {error}"])
                self.assert_only_cart_failed(data, error)
                self.assertEqual(state(self.root)["modules"]["cart"],  # kept for the next claim
                                 {"status": "failed", "attempts": 1, "error": error,
                                  "problems": problems})

    def test_a_retry_whose_work_item_went_missing(self):  # final review M-2 under init run
        from segmently_modules.init_work import Work
        real = Work.claim
        for body, reason in (
                (None, f"{WORK}/work/cart.json is missing — start over: segmently-modules init map "
                       f"--restart"),
                ("{}", f"{WORK}/work/cart.json: module is not 'cart', roles is not a list of "
                       f"strings, prompt is not a string — fix it, or start over: segmently-modules init "
                       f"map --restart")):  # follow-up C: the wrong shape, as a missing one
            with self.subTest(body=body):
                self.setUp()
                self.config("[init]\nmax_parallel = 1\n")

                def claim(work, module=None):  # the retry's claim: its work item is gone
                    if module == "cart" and self.stdins("cart"):
                        path = self.root / WORK / "work/cart.json"
                        path.unlink() if body is None else path.write_text(body)
                    return real(work, module)

                with mock.patch("segmently_modules.init_work.Work.claim", autospec=True,
                                side_effect=claim):
                    data, err = self.run_init("--invent", "cart", code=1)
                error = "; ".join(invented("cart")) + f"; the retry could not start: {reason}"
                self.assertEqual(err.splitlines(), [self.RETRY, f"segmently-modules: cart failed: {error}"])
                self.assert_only_cart_failed(data, error)
                self.assertEqual(state(self.root)["modules"]["cart"],
                                 {"status": "failed", "attempts": 1, "error": error,
                                  "problems": invented("cart")})

    def test_a_first_claim_of_a_work_item_of_the_wrong_shape(self):  # follow-up C (P5b rule)
        path = self.root / WORK / "work/cart.json"
        path.write_text(json.dumps({**json.loads(path.read_text()), "prompt": None}))
        before = (self.root / WORK / "state.json").read_bytes()
        code, out, err = run("init", "run", "--executor", executor("--record", str(self.log)),
                             "--json", "--root", str(self.root))
        self.assertEqual((code, out), (2, ""))  # refused before any state write: nothing ran
        self.assertEqual(err, f"segmently-modules: error: {WORK}/work/cart.json: prompt is not a string — "
                              f"fix it, or start over: segmently-modules init map --restart\n")
        self.assertEqual((self.root / WORK / "state.json").read_bytes(), before)
        self.assertEqual(self.calls(), [])

    def test_a_template_the_check_cannot_read(self):  # final review M-3: one module fails
        override = self.root / ok(self.root, "templates", "override", "MODULE.md")["file"]
        override.write_bytes(b"\xe9" + override.read_bytes())  # edited after the fan-out
        code, data, err = self.breaker("dollar")  # cart's MODULE.md holds `${API_URL}`
        error = ("the check could not run: cannot read .segmently-modules/overrides/templates/MODULE.md: "
                 "not UTF-8 text")
        self.assertEqual((code, err.splitlines()), (1, [f"segmently-modules: cart failed: {error}"]))
        self.assert_only_cart_failed(data, error)  # no retry: the writer cannot fix a template
        self.assertEqual(state(self.root)["modules"]["cart"],
                         {"status": "failed", "attempts": 1, "error": error})

    def test_a_writer_that_removes_or_damages_its_work_item(self):  # extension, found 1–2
        for mode, start, end in (
                ("unlink", f"the check could not run: {WORK}/work/cart.json is missing — start "
                           f"over: segmently-modules init map --restart", ""),
                ("damage", f"the check could not run: {WORK}/work/cart.json: cannot read it as "
                           f"JSON (", ") — fix it, or start over: segmently-modules init map --restart"),
                ("shape", f"the check could not run: {WORK}/work/cart.json: module is not "
                          f"'cart', roles is not a list of strings, prompt is not a string — "
                          f"fix it, or start over: segmently-modules init map --restart", "")):  # follow-up C
            with self.subTest(mode=mode):
                self.setUp()
                code, data, err = self.breaker(mode)  # the peers wait for cart's failure
                error = state(self.root)["modules"]["cart"]["error"]
                self.assertTrue(error.startswith(start) and error.endswith(end), error)
                self.assertEqual((code, data["failed"], err.splitlines()),
                                 (1, True, [f"segmently-modules: cart failed: {error}"]))  # no retry
                self.assert_only_cart_failed(data, error)
                self.assertEqual(state(self.root)["modules"]["cart"],
                                 {"status": "failed", "attempts": 1, "error": error})


if __name__ == "__main__":
    unittest.main()
