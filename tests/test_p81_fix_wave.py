"""P8.1 final fix wave: repeated signals against an agent that ignores SIGTERM (deferred 1),
`choose --task-file` (deferred 3), the agent command's wording (deferred 4), the length of
`MODSYS_AGENT_TIMEOUT` (deferred 19), the variables the test package clears (deferred 21),
`choose --apply` unwraps an answer as `--run` does (M-1), no cards means no agent call and the
texts of an empty catalog and of a semantic `context` without a pick (M-2), the compact work
order the agent reads (M-3)."""
import io
import json
import os
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from modsys import semantic
from tests.agent_helpers import AgentRepo, picks
from tests.helpers import run, run_json
from tests.test_p81_agent import ENGINE, MATCH_TASK, TASK

ODD = "the customer's \"refund\" for $order and `useCart` \\ back\nsecond line"


class Base(AgentRepo, unittest.TestCase):
    def alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True

    def task_file(self, text: str, name: str = "task.txt") -> str:
        path = self.tmp / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def empty_registry(self) -> None:
        (self.root / "modules" / "registry.json").write_text('{"modules": {}}\n',
                                                             encoding="utf-8")


class RepeatedSignalsTest(Base):  # deferred 1 (3b m7)
    def test_three_signals_against_an_agent_that_ignores_sigterm(self):
        for sig in (signal.SIGTERM, signal.SIGINT):
            with self.subTest(signal=sig.name):
                self.three_times(sig)

    def three_times(self, sig):
        started = self.tmp / f"started-{sig.name}"
        scratch = self.tmp / f"tmpdir-{sig.name}"
        scratch.mkdir()
        self.agent(sleep=60, started=str(started), ignore_term=True, answer="{}")
        env = {**os.environ, "PYTHONPATH": str(ENGINE), "TMPDIR": str(scratch)}
        proc = subprocess.Popen([sys.executable, "-m", "modsys", "choose", "--task", TASK,
                                 "--run", *self.R], env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, cwd=ENGINE,
                                preexec_fn=lambda: [signal.signal(x, signal.SIG_DFL) for x in
                                                    (signal.SIGINT, signal.SIGTERM,
                                                     signal.SIGHUP)])
        try:
            for _ in range(400):
                if started.exists():
                    break
                time.sleep(0.05)
            self.assertTrue(started.exists(), "the agent never started")
            pid = int(started.read_text())
            for _ in range(3):  # the 2nd and 3rd land while the run stops the agent
                proc.send_signal(sig)
                time.sleep(0.3)
            out, err = proc.communicate(timeout=30)
        finally:
            if proc.poll() is None:
                proc.kill()
        self.assertEqual((proc.returncode, out), (130, ""), err)
        self.assertNotIn("Traceback", err)
        for _ in range(40):
            if not self.alive(pid):
                break
            time.sleep(0.05)
        if self.alive(pid):
            os.kill(pid, signal.SIGKILL)
            self.fail("the agent outlived the run")
        self.assertEqual(list(scratch.iterdir()), [])  # the temp dir (the task text) is gone


class ChooseTaskFileTest(Base):  # deferred 3, M-6
    def test_the_file_gives_the_same_work_order_as_the_text(self):
        path = self.task_file(ODD)
        for extra in ((), ("--json",)):
            with self.subTest(json=extra):
                by_text = run("choose", "--task", ODD, *self.R, *extra)
                by_file = run("choose", "--task-file", path, *self.R, *extra)
                self.assertEqual(by_file[0], 0, by_file[2])
                self.assertEqual(by_file, by_text)
        self.assertEqual(run_json("choose", "--task-file", path, *self.R)[1]["data"]["task"], ODD)

    def test_stdin(self):
        with mock.patch("sys.stdin", io.StringIO(ODD)):
            code, env, err = run_json("choose", "--task-file", "-", *self.R)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(env["data"]["task"], ODD)

    def test_run_reads_the_file(self):
        self.agent(answer=picks(("payments", 0.9)))
        code, env, err = run_json("choose", "--task-file", self.task_file(ODD), "--run",
                                  *self.R)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(env["data"]["picks"][0]["module"], "payments")
        (call,) = self.calls()
        self.assertEqual(json.loads(call["stdin"])["task"], ODD)

    def test_refusals(self):
        empty = self.task_file("  \n", "empty.txt")
        for argv, needle in ((("--task-file", empty), "--task-file"),
                             (("--task-file", empty, "--run"), "--task-file"),
                             (("--task-file", str(self.tmp / "missing.txt")), "missing.txt"),
                             (("--task", "t", "--task-file", empty), "not allowed with"),
                             (("--run",), "--task-file")):
            with self.subTest(argv=argv):
                code, out, err = run("choose", *argv, *self.R)
                self.assertEqual((code, out), (2, ""))
                self.assertIn(needle, err)
                self.assertNotIn("Traceback", err)
        self.assertEqual(self.calls(), [])


class AgentWordingTest(Base):  # deferred 4: the command lives in the environment, not in [agent]
    def test_help_names_the_variable(self):
        code, out, _ = run("choose", "--help")
        self.assertEqual(code, 0)
        flat = " ".join(out.split())
        self.assertNotIn("[agent]", flat)
        self.assertIn("MODSYS_AGENT_COMMAND", flat)
        self.assertIn("--task-file", flat)

    def test_errors_name_the_variable_only(self):
        for argv, needle in ((["x", "{foo}"], "unknown placeholder"),
                             (["x", "a{"], "unmatched brace"),
                             (["{effort}", "x"], "argv[0]")):
            with self.subTest(argv=argv):
                os.environ["MODSYS_AGENT_COMMAND"] = json.dumps(argv)
                code, out, err = run("catalog", *self.R)
                self.assertEqual((code, out), (2, ""))
                self.assertTrue(err.startswith("modsys: error: MODSYS_AGENT_COMMAND: "), err)
                self.assertIn(needle, err)
                self.assertNotIn("[agent]", err)

    def test_no_stale_wording_in_the_engine(self):
        for path in sorted((ENGINE / "modsys").rglob("*.py")):
            text = " ".join(path.read_text(encoding="utf-8").split())
            for stale in ("[agent] command", "of [agent]", "(`[agent]`",
                          "the environment variable or `config.user.toml`",
                          "personal config may hold the user's own agent command"):
                self.assertFalse(stale in text, f"{path.name}: {stale}")


class TimeoutLengthTest(Base):  # deferred 19
    def test_a_long_value_is_refused_before_it_is_read(self):
        for bad in ("9" * 5000, "00300"):
            with self.subTest(length=len(bad)):
                self.agent(answer=picks(), timeout_s=bad)
                for argv in (("catalog",), ("choose", "--task", "t", "--run")):
                    code, out, err = run(*argv, *self.R)
                    self.assertEqual((code, out), (2, ""))
                    self.assertIn("MODSYS_AGENT_TIMEOUT: expected an integer from 1 to 3600", err)
                    self.assertNotIn("internal error", err)
        self.assertEqual(self.calls(), [])


class TestPackageEnvironmentTest(unittest.TestCase):  # deferred 21
    def test_importing_the_package_clears_the_agent_variables(self):
        names = ("MODSYS_AGENT_COMMAND", "MODSYS_AGENT_TIMEOUT", "MODSYS_WORK_ORDER")
        env = {**os.environ, "PYTHONPATH": str(ENGINE), **{n: "x" for n in names}}
        code = (f"import os, tests; print(sorted(n for n in {names!r} if n in os.environ))")
        done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                              env=env, cwd=ENGINE)
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "[]"), done.stderr)


class ApplyUnwrapsTest(Base):  # M-1: --apply takes what --run takes
    ANSWER = picks(("orders/refunds", 0.9, "returns"), ("payments", 0.4))
    OTHER = picks(("catalog", 0.5))

    def forms(self):
        raw = json.dumps(self.ANSWER)
        fence = "```json\n" + raw + "\n```"
        return {"raw": raw,
                "envelope": json.dumps({"type": "result", "is_error": False,
                                        "structured_output": self.ANSWER,
                                        "result": json.dumps(self.OTHER)}),
                "result string": json.dumps({"is_error": False, "result": raw}),
                "fenced result": json.dumps({"result": fence}),
                "result object": json.dumps({"result": self.ANSWER})}

    def test_every_form_run_accepts(self):
        for label, text in self.forms().items():
            for extra in ((), ("--json",)):
                with self.subTest(form=label, json=extra):
                    self.agent(answer=text)
                    ran = run("choose", "--task", TASK, "--run", *self.R, *extra)
                    path = self.tmp / "answer.json"
                    path.write_text(text, encoding="utf-8")
                    applied = run("choose", "--apply", str(path), *self.R, *extra)
                    with mock.patch("sys.stdin", io.StringIO(text)):
                        piped = run("choose", "--apply", "-", *self.R, *extra)
                    self.assertEqual(applied[0], 0, applied[2])
                    self.assertEqual(applied, ran)
                    self.assertEqual(piped, ran)

    def test_refusals_name_the_answer(self):
        for text, needle in ((json.dumps({"is_error": True, "result": "rate limited"}),
                              "rate limited"),
                             (json.dumps({"result": "prose, not JSON"}), "not JSON"),
                             (json.dumps({"result": "[1]"}), "not a JSON object"),
                             (json.dumps({"structured_output": None}), "picks"),
                             ("```json\n{}\n```", "not JSON")):  # a bare fence: no scraping
            with self.subTest(text=text):
                with mock.patch("sys.stdin", io.StringIO(text)):
                    code, out, err = run("choose", "--apply", "-", *self.R)
                self.assertEqual((code, out), (2, ""))
                self.assertTrue(err.startswith("modsys: error: "), err)
                self.assertIn(needle, err)
                self.assertNotIn("agent ", err)  # no agent ran: the answer is named
                self.assertNotIn("Traceback", err)


class NoCardsTest(Base):  # M-2
    def test_no_agent_call_on_an_empty_registry(self):
        self.empty_registry()
        self.agent(answer=picks(("payments", 0.9)))
        for argv in (("match", MATCH_TASK), ("context", "--task", MATCH_TASK),
                     ("discover", "--task", MATCH_TASK)):
            for mode in ("semantic", "hybrid"):
                with self.subTest(verb=argv[0], mode=mode):
                    code, env, err = run_json(*argv, "--match", mode, *self.R)
                    self.assertEqual((code, err), (0, ""))
                    data = env["data"]
                    self.assertEqual(data["rows"] if argv[0] == "match" else data["modules"], [])
                    self.assertEqual(data["notes"], [semantic.NO_CARDS_NOTE])
                    code, out, _ = run(*argv, "--match", mode, *self.R)
                    self.assertEqual(code, 0)
                    self.assertIn(semantic.NO_CARDS_NOTE, out)
                    self.assertNotIn("the agent chose", out)
        code, env, err = run_json("choose", "--task", TASK, "--run", *self.R)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual((env["data"]["picks"], env["data"]["notes"]),
                         ([], [semantic.NO_CARDS_NOTE]))
        self.assertEqual(self.calls(), [])

    def test_catalog_text_on_an_empty_registry(self):
        self.empty_registry()
        code, out, err = run("catalog", *self.R)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(len(out.splitlines()), 1)
        self.assertIn("no module", out)

    def test_semantic_context_without_a_pick(self):
        self.agent(answer={"picks": [], "none": True})
        code, out, err = run("context", "--task", MATCH_TASK, "--match", "semantic", *self.R)
        self.assertEqual((code, err), (0, ""))
        self.assertNotIn("try domain terms", out)
        self.assertIn("the agent chose no module", out)
        lexical = run("context", "--task", "zzz nothing", *self.R)[1]
        self.assertIn("no module matched (try domain terms, or: modsys list)", lexical)


class CompactWorkOrderTest(Base):  # M-3
    def test_stdin_and_file_are_compact_and_equal_in_content(self):
        self.agent(answer=picks(("payments", 0.9)))
        self.assertEqual(run("choose", "--task", TASK, "--run", *self.R)[0], 0)
        (call,) = self.calls()
        code, out, _ = run("choose", "--task", TASK, *self.R, "--json")
        self.assertIn('\n    "task": ', out)  # the CLI's --json keeps its usual layout
        order = json.loads(out)["data"]
        compact = json.dumps(order, ensure_ascii=False, separators=(",", ":"))
        self.assertEqual(call["stdin"], compact)
        self.assertEqual(call["work_order_file"]["content"], compact)
        self.assertLess(len(compact), len(json.dumps(order, indent=2, ensure_ascii=False)))


if __name__ == "__main__":
    unittest.main()
