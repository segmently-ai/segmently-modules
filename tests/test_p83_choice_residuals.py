"""P8.3 task 4 (D6, the choice path's residuals): N-1 a first signal in either window of
`agent.run` leaves nothing behind; N-2 a task text that is not UTF-8 is `cannot read <path>:
<reason>`, never an internal error; N-3 one reader for `choose --run`, `--apply FILE` and
`--apply -`; N-4 the `--top 0` wording of semantic `match` / `context`; N-6 card lines of the text
work order longer than 2,000 characters wrap; `catalog` with a malformed agent variable is exit 0
with one note."""
from __future__ import annotations

import contextlib
import errno
import hashlib
import io
import json
import locale
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from segmently_modules import agent as agent_mod
from tests.agent_helpers import AgentRepo, picks
from tests.helpers import changelog_since_first_release, mutate_registry, run, run_json

try:
    import resource
except ImportError:  # no rlimits here
    resource = None

ENGINE = Path(__file__).resolve().parents[1]
TASK = "partial refund for a returned book"
MATCH_TASK = "refund payment catalog"
TIMEOUT = 90
NO_AGENT = ("semantic matching needs your agent: set SEGMENTLY_MODULES_AGENT_COMMAND (a JSON array); "
            "in Claude Code / Codex the skills do it with segmently-modules choose")
SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)


def _utf8_locale() -> str | None:
    """A UTF-8 locale this machine has (the C locale is the other one the tests use)."""
    saved = locale.setlocale(locale.LC_CTYPE)
    try:
        for name in ("C.UTF-8", "en_US.UTF-8", "C.utf8", "en_US.utf8"):
            try:
                locale.setlocale(locale.LC_CTYPE, name)
            except locale.Error:
                continue
            return name
        return None
    finally:
        locale.setlocale(locale.LC_CTYPE, saved)


LOCALES = tuple(loc for loc in ("C", _utf8_locale()) if loc)


class Base(AgentRepo, unittest.TestCase):
    def spawn(self, argv, stdin=b"", loc="C"):
        """(exit code, stdout bytes, stderr text) of `python -m segmently_modules ARGV --root R` under
        `LC_ALL=loc`, with the test's (clean) environment."""
        env = {**os.environ, "PYTHONPATH": str(ENGINE), "PYTHONDONTWRITEBYTECODE": "1",
               "LC_ALL": loc}
        done = subprocess.run([sys.executable, "-m", "segmently_modules", *argv, *self.R], input=stdin,
                              capture_output=True, env=env, cwd=ENGINE, timeout=TIMEOUT)
        return done.returncode, done.stdout, done.stderr.decode("utf-8", "replace")


# ---- N-1: the two first-signal windows of agent.run (P83-AC-023) -------------------------------

class SignalWindowsTest(Base):
    """In-process, main thread, sentinel handlers installed before the run. (a) the signal lands
    as the outer `finally` enters `_ignore_signals` on a run that finished; (b) it lands inside
    `_set_signals`, right after segmently-modules installed its handler for that signal."""

    def setUp(self):
        super().setUp()
        saved = {s: signal.getsignal(s) for s in SIGNALS}
        self.addCleanup(lambda: [signal.signal(s, h) for s, h in saved.items() if h is not None])
        self.scratch = self.tmp / "tmpdir"
        self.scratch.mkdir()
        patcher = mock.patch.object(tempfile, "tempdir", str(self.scratch))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.hits: list = []
        self.sentinels = {s: self.sentinel() for s in SIGNALS}

    def sentinel(self):
        def handler(signum, frame):  # the caller's own handler: segmently-modules must not reach it
            self.hits.append(signum)
        return handler

    @contextlib.contextmanager
    def inject(self, window, sig):
        reached = []
        if window == "a":
            real_ignore = agent_mod._ignore_signals

            def entering(before):
                reached.append(sig)
                os.kill(os.getpid(), sig)  # delivered at once (os.kill checks signals)
                return real_ignore(before)
            with mock.patch.object(agent_mod, "_ignore_signals", entering):
                yield
        else:
            real_signal = signal.signal

            def installing(s, handler):
                previous = real_signal(s, handler)
                if s == sig and not reached and callable(handler) \
                        and handler not in self.sentinels.values():
                    reached.append(s)  # segmently-modules's own handler is in place: fire it now
                    os.kill(os.getpid(), s)
                return previous
            with mock.patch.object(signal, "signal", installing):
                yield
        self.assertEqual(reached, [sig], "the window was not reached")

    def assert_dead(self, pid: int) -> None:
        for _ in range(100):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.05)
        os.kill(pid, signal.SIGKILL)
        self.fail(f"process {pid} of the agent's group outlived the run")

    def scenario(self, window, sig, nohup=False):
        for leftover in self.scratch.iterdir():  # what an earlier case left (on 758d085)
            shutil.rmtree(leftover, ignore_errors=True)
        grand = self.tmp / f"grand-{window}-{sig.name}-{nohup}"
        self.agent(answer=picks(("payments", 0.9)), grandchild=str(grand))
        for s, h in self.sentinels.items():
            signal.signal(s, h)
        if nohup:
            signal.signal(signal.SIGHUP, signal.SIG_IGN)
        with self.inject(window, sig):
            code, out, err = run("choose", "--task", TASK, "--run", *self.R)
        self.assertEqual((code, out, err), (130, "", "segmently-modules: interrupted\n"))
        self.assertEqual([p.name for p in self.scratch.iterdir()], [])  # no segmently-modules-agent-* left
        for s, h in self.sentinels.items():
            want = signal.SIG_IGN if nohup and s == signal.SIGHUP else h
            self.assertIs(signal.getsignal(s), want, f"{s.name} not restored")
        self.assertEqual(self.hits, [])
        if window == "a":  # the run had finished: its agent and the agent's group are gone
            self.assertTrue(grand.exists())
            self.assert_dead(int(grand.read_text(encoding="utf-8")))

    def test_a_first_signal_as_the_cleanup_starts(self):  # P83-AC-023 (a)
        for sig in SIGNALS:
            with self.subTest(signal=sig.name):
                self.scenario("a", sig)

    def test_a_first_signal_inside_set_signals(self):  # P83-AC-023 (b)
        for sig in SIGNALS:
            with self.subTest(signal=sig.name):
                self.scenario("b", sig)

    def test_a_nohup_sighup_stays_ignored(self):  # P83-AC-023
        for window in ("a", "b"):
            for sig in (signal.SIGINT, signal.SIGTERM):
                with self.subTest(window=window, signal=sig.name):
                    self.scenario(window, sig, nohup=True)


# ---- N-2: a task text that is not UTF-8 (P83-AC-024) ----------------------------------------

class TaskTextTest(Base):
    VERBS = ("choose", "context", "discover")

    def refusals(self):
        latin = self.tmp / "latin1.txt"
        latin.write_bytes(b"r\xe9fund")
        folder = self.tmp / "taskdir"
        folder.mkdir(exist_ok=True)
        missing = self.tmp / "missing.txt"
        return [(str(latin), b"", f"cannot read {latin}: not valid UTF-8"),
                ("-", b"r\xe9fund", "cannot read <stdin>: not valid UTF-8"),
                (str(missing), b"", f"cannot read {missing}: {os.strerror(errno.ENOENT)}"),
                (str(folder), b"", f"cannot read {folder}: {os.strerror(errno.EISDIR)}")]

    def in_process(self, argv, stdin: bytes = b""):
        """`run(...)` with a byte stdin, as a real process has it."""
        with mock.patch("sys.stdin", io.TextIOWrapper(io.BytesIO(stdin), encoding="utf-8")):
            return run(*argv, *self.R)

    def test_refused_alike_under_both_locales(self):  # P83-AC-024
        # real processes, both locales, one verb; the reader works on bytes and never looks at
        # the locale, so every verb and form is checked below in process
        self.assertEqual(len(LOCALES), 2, "no UTF-8 locale on this machine")
        for loc in LOCALES:
            for path, stdin, reason in self.refusals():
                with self.subTest(locale=loc, path=Path(path).name):
                    got = self.spawn(("choose", "--task-file", path), stdin, loc)
                    self.assertEqual(got, (2, b"", f"segmently-modules: error: {reason}\n"))
        for verb in self.VERBS:
            for path, stdin, reason in self.refusals():
                for form in ((), ("--json",)):
                    with self.subTest(verb=verb, path=Path(path).name, json=bool(form)):
                        got = self.in_process((verb, "--task-file", path, *form), stdin)
                        self.assertEqual(got, (2, "", f"segmently-modules: error: {reason}\n"))

    def test_in_process_stdin_and_an_empty_file(self):  # P83-AC-024
        empty = self.tmp / "empty.txt"
        empty.write_bytes(b"")
        for verb in self.VERBS:
            with self.subTest(verb=verb):
                code, out, err = run(verb, "--task-file", str(empty), *self.R)
                self.assertEqual((code, out), (2, ""))
                self.assertTrue(err.startswith("segmently-modules: error: give the task: "), err)
                # a text stream without .buffer holding a lone surrogate: a refusal, never an
                # internal error (fix round 1, M-2)
                with mock.patch("sys.stdin", io.StringIO("refund " + chr(0xD800))):
                    got = run(verb, "--task-file", "-", *self.R)
                self.assertEqual(got, (2, "", "segmently-modules: error: cannot read <stdin>: "
                                              "not valid UTF-8\n"))

    def test_valid_text_reads_as_before(self):  # P83-AC-024
        text = "partial refund for a returned book — für Bücher, «remboursé»\n"
        path = self.tmp / "task.txt"
        path.write_bytes(text.encode("utf-8"))
        for loc in LOCALES:  # real processes, both locales, one verb
            with self.subTest(locale=loc):
                by_text = self.spawn(("choose", "--task", text), loc=loc)
                self.assertEqual(by_text[0], 0, by_text[2])
                self.assertEqual(self.spawn(("choose", "--task-file", str(path)), loc=loc),
                                 by_text)
                self.assertEqual(self.spawn(("choose", "--task-file", "-"),
                                            text.encode("utf-8"), loc), by_text)
        for verb in self.VERBS:
            for form in ((), ("--json",)):
                with self.subTest(verb=verb, json=bool(form)):
                    by_text = run(verb, "--task", text, *self.R, *form)
                    self.assertEqual(by_text[0], 0, by_text[2])
                    self.assertEqual(run(verb, "--task-file", str(path), *self.R, *form), by_text)
                    self.assertEqual(self.in_process((verb, "--task-file", "-", *form),
                                                     text.encode("utf-8")), by_text)

    def test_a_file_keeps_its_newline_translation(self):  # P83-AC-024, fix round 1 (I-1)
        """758d085 read a FILE in text mode (CRLF and a lone CR became LF) and stdin as it is."""
        raw = "refund the order\r\nsecond line\rthird line\n"
        translated = "refund the order\nsecond line\nthird line\n"
        path = self.tmp / "crlf.txt"
        path.write_bytes(raw.encode("utf-8"))
        loc = LOCALES[-1]  # real processes: the text order of a file and of a real stdin
        by_file = self.spawn(("choose", "--task-file", str(path)), loc=loc)
        self.assertEqual(by_file[0], 0, by_file[2])
        self.assertEqual(by_file, self.spawn(("choose", "--task", translated), loc=loc))
        by_stdin = self.spawn(("choose", "--task-file", "-"), raw.encode(), loc)
        self.assertEqual(by_stdin[0], 0, by_stdin[2])
        self.assertIn(b"Task:\nrefund the order\r\nsecond line\rthird line\n", by_stdin[1])
        self.assertIn(b"Task:\nrefund the order\nsecond line\nthird line\n", by_file[1])
        self.assertEqual(run_json("choose", "--task-file", str(path), *self.R)[1]["data"]["task"],
                         translated)
        self.assertEqual(self.in_process(("choose", "--task-file", "-", "--json"),
                                         raw.encode())[1],
                         run("choose", "--task", raw, "--json", *self.R)[1])
        for verb in self.VERBS:
            for form in ((), ("--json",)):
                with self.subTest(verb=verb, json=bool(form)):
                    self.assertEqual(run(verb, "--task-file", str(path), *self.R, *form),
                                     run(verb, "--task", translated, *self.R, *form))
                    self.assertEqual(self.in_process((verb, "--task-file", "-", *form),
                                                     raw.encode()),
                                     run(verb, "--task", raw, *self.R, *form))
        self.agent(answer=picks(("payments", 0.9)))  # the agent's stdin: the translated task
        self.assertEqual(run("choose", "--task-file", str(path), "--run", *self.R)[0], 0)
        (call,) = self.calls()
        self.assertEqual(json.loads(call["stdin"])["task"], translated)

    def test_match_is_unchanged(self):  # SI-P83-6: match takes its text as an argument
        code, out, _ = run("match", "--help")
        self.assertEqual(code, 0)
        self.assertNotIn("--task-file", out)


# ---- N-3: one reader for --run, --apply FILE, --apply - (P83-AC-025) ---------------------------

ANSWER = {"picks": [{"module": "orders/refunds", "confidence": 0.9, "reason": "r"}],
          "none": False}
RAW = json.dumps(ANSWER)
# the P8.1 re-review's 25 answer forms, each with its exit code (all three paths alike)
FORMS = [
    ("raw", RAW, 0),
    ("raw + trailing nbsp", RAW + "\u00a0", 0),  # 758d085: --apply refused it (exit 2)
    ("raw + trailing \\x1c", RAW + "\x1c", 0),  # 758d085: --apply refused it (exit 2)
    ("null", "null", 2), ("list", "[]", 2), ("string", '"x"', 2), ("number", "1", 2),
    ("envelope so", json.dumps({"structured_output": ANSWER, "result": "junk"}), 0),
    ("so not dict, result ok", json.dumps({"structured_output": "x", "result": RAW}), 0),
    ("result fenced w/ spaces", json.dumps({"result": "  ```json\n" + RAW + "\n```  "}), 0),
    ("result bare fence", json.dumps({"result": "```\n" + RAW + "\n```"}), 0),
    ("result JSON fence", json.dumps({"result": "```JSON\n" + RAW + "\n```"}), 2),
    ("result fence crlf", json.dumps({"result": "```json\r\n" + RAW + "\r\n```"}), 2),
    ("result list", json.dumps({"result": [ANSWER]}), 2),
    ("is_error + picks", json.dumps({"is_error": True, **ANSWER}), 0),
    ("is_error false, result", json.dumps({"is_error": False, "result": RAW}), 0),
    ("top-level fence", "```json\n" + RAW + "\n```", 2),
    ("picks only", json.dumps({"picks": ANSWER["picks"]}), 0),
    ("none only", json.dumps({"none": True}), 2),
    ("empty object", "{}", 2),
    ("whitespace", "   \n", 2),
    ("NaN confidence", RAW.replace("0.9", "NaN"), 2),
    ("dup keys", '{"picks": [], "picks": ' + json.dumps(ANSWER["picks"]) + ', "none": false}', 0),
    ("bom", "\ufeff" + RAW, 2),
    ("nested result envelope", json.dumps({"result": json.dumps({"structured_output": ANSWER})}),
     2),
]
NOT_OBJECT = "{who}: its output is not a JSON object"
NO_ANSWER = ("{who}: no answer in its output (expected `picks`/`none`, `structured_output` or "
             "`result`)")
NO_PICKS = "{who}: answer: picks: required, an array (may be empty)"


def run_refusal(label: str, text: str) -> str:
    """`choose --run`'s refusal of an answer form, as at 758d085 (`{who}` = `agent <argv[0]>`)."""
    if label in ("null", "list", "string", "number"):
        return NOT_OBJECT
    if label in ("result JSON fence", "result fence crlf"):
        body = json.loads(text)["result"].strip()
        return "{who}: its `result` is not JSON: " + repr(body[:120]).replace("{", "{{") \
            .replace("}", "}}")
    if label in ("result list", "empty object"):
        return NO_ANSWER
    if label in ("top-level fence", "bom"):
        return "{who}: its output is not JSON: " + repr(text.strip()[:120]).replace("{", "{{") \
            .replace("}", "}}")
    if label in ("none only", "nested result envelope"):
        return NO_PICKS
    if label == "whitespace":
        return "{who} printed nothing"
    if label == "NaN confidence":
        return "{who}: answer: picks[0].confidence: expected a number from 0 to 1, got nan"
    raise AssertionError(label)


class AnswerReaderTest(Base):
    def three(self, data: bytes, form=(), ran=None):
        """In process: (--run, --apply FILE, --apply -) of the answer bytes, and FILE; `ran`:
        a --run result already taken (a refusal never reaches the text or JSON form)."""
        if ran is None:
            self.agent(answer_hex=data.hex())
            ran = run("choose", "--task", TASK, "--run", *self.R, *form)
        path = self.tmp / "answer.json"
        path.write_bytes(data)
        applied = run("choose", "--apply", str(path), *self.R, *form)
        with mock.patch("sys.stdin", io.TextIOWrapper(io.BytesIO(data), encoding="utf-8")):
            piped = run("choose", "--apply", "-", *self.R, *form)
        return ran, applied, piped, str(path)

    def test_the_25_forms(self):  # P83-AC-025
        self.assertEqual(len(FORMS), 25)
        who = f"agent {sys.executable}"
        for label, text, code in FORMS:
            refused = None  # --run's refusal is taken once: it never reaches the output form
            for form in ((), ("--json",)):
                with self.subTest(form=label, json=bool(form)):
                    ran, applied, piped, path = self.three(text.encode("utf-8"), form, refused)
                    if ran[0] != 0:
                        refused = ran
                    self.assertEqual([ran[0], applied[0], piped[0]], [code] * 3,
                                     (ran[2], applied[2], piped[2]))
                    if code == 0:
                        self.assertEqual(applied, ran)
                        self.assertEqual(piped, ran)
                        continue
                    self.assertEqual([ran[1], applied[1], piped[1]], ["", "", ""])
                    message = run_refusal(label, text)
                    self.assertEqual(ran[2], "segmently-modules: error: " + message.format(who=who) + "\n")
                    for src, got in ((path, applied[2]), ("stdin", piped[2])):
                        if label == "whitespace":
                            want = f"{src}: the answer is empty (expected a JSON object)"
                        else:
                            want = message.replace("its output", "its text").format(who=src)
                        self.assertEqual(got, f"segmently-modules: error: {want}\n")

    def test_more_apply_refusals_start_with_the_source(self):  # P83-AC-025 / SI-P83-8
        missing = self.tmp / "missing.json"
        code, out, err = run("choose", "--apply", str(missing), *self.R)
        self.assertEqual((code, out, err), (2, "", f"segmently-modules: error: {missing}: cannot read the "
                                                   f"answer: {os.strerror(errno.ENOENT)}\n"))
        error = json.dumps({"is_error": True, "result": "rate limited"})
        with mock.patch("sys.stdin", io.StringIO(error)):
            code, out, err = run("choose", "--apply", "-", *self.R)
        self.assertEqual((code, out, err), (2, "", "segmently-modules: error: stdin reported an error: "
                                                   "rate limited\n"))
        self.agent(answer=error)
        code, out, err = run("choose", "--task", TASK, "--run", *self.R)  # as at 758d085
        self.assertEqual(err, f"segmently-modules: error: agent {sys.executable} reported an error: "
                              f"rate limited\n")

    def test_three_rows_under_both_locales(self):  # P83-AC-025, PRE-003(e)
        self.assertEqual(len(LOCALES), 2, "no UTF-8 locale on this machine")
        bad = RAW.encode("utf-8").replace(b'"reason": "r"', b'"reason": "r\xffr"')
        rows = [("nbsp", (RAW + "\u00a0").encode("utf-8")), ("x1c", (RAW + "\x1c").encode()),
                ("xff in reason", bad)]
        for label, data in rows:
            path = self.tmp / f"answer-{label.split()[0]}.json"
            path.write_bytes(data)
            self.agent(answer_hex=data.hex())
            replaced = "r" + chr(0xFFFD) + "r"  # the invalid byte, decoded with replacement
            for loc in LOCALES:  # real processes, both locales: the text form
                with self.subTest(row=label, locale=loc):
                    applied = self.spawn(("choose", "--apply", str(path)), loc=loc)
                    piped = self.spawn(("choose", "--apply", "-"), data, loc)
                    self.assertEqual(applied[0], 0, applied[2])
                    self.assertEqual(piped, applied)
                    if label == "xff in reason":  # the row whose result hung on the locale
                        ran = self.spawn(("choose", "--task", TASK, "--run"), loc=loc)
                        self.assertEqual(ran, applied)
                        self.assertIn(replaced.encode("utf-8"), ran[1])
                    else:  # --run reads bytes in any locale: its text form, in process
                        ran = run("choose", "--task", TASK, "--run", *self.R)
                        self.assertEqual((ran[0], ran[1].encode("utf-8"), ran[2]), applied)
            with self.subTest(row=label, json=True):  # the JSON form, in process
                ran, applied, piped, _ = self.three(data, ("--json",))
                self.assertEqual(ran[0], 0, ran[2])
                self.assertEqual(applied, ran)
                self.assertEqual(piped, ran)
                if label == "xff in reason":
                    pick = json.loads(ran[1])["data"]["picks"][0]
                    self.assertEqual(pick["reason"], replaced)

    def test_one_function_reads_every_answer(self):  # P83-AC-025
        self.agent(answer=RAW)
        path = self.tmp / "answer.json"
        path.write_text(RAW, encoding="utf-8")
        with mock.patch.object(agent_mod, "answer_from", wraps=agent_mod.answer_from) as spy:
            self.assertEqual(run("choose", "--task", TASK, "--run", *self.R)[0], 0)
            self.assertEqual(run("choose", "--apply", str(path), *self.R)[0], 0)
            with mock.patch("sys.stdin", io.StringIO(RAW)):
                self.assertEqual(run("choose", "--apply", "-", *self.R)[0], 0)
        self.assertEqual([c.args[1] for c in spy.call_args_list],
                         [f"agent {sys.executable}", str(path), "stdin"])


# ---- N-4: --top 0 with the semantic mode (P83-AC-026) -----------------------------------------

TOP_ZERO = "no module matched (--top 0)\n"


class TopZeroTest(Base):
    VERBS = (("match", MATCH_TASK), ("context", "--task", MATCH_TASK))
    MATCH_JSON = '{\n  "schema": "segmently-modules.match/1",\n  "data": {\n    "mode": "%s",\n    ' \
                 '"rows": [],\n    "notes": []\n  }\n}\n'
    CONTEXT_JSON = ('{\n  "schema": "segmently-modules.context/1",\n  "data": {\n    "task": '
                    '"refund payment catalog",\n    "role": null,\n    "all_roles": false,\n    '
                    '"modules": [],\n    "read": [],\n    "near_misses": [],\n    "mode": "%s",\n'
                    '    "notes": []\n  }\n}\n')

    def json_of(self, verb, mode):
        return (self.MATCH_JSON if verb == "match" else self.CONTEXT_JSON) % mode

    def test_semantic_top_zero_names_the_flag(self):  # P83-AC-026 row 1
        self.agent(answer=picks(("payments", 0.9)))
        for argv in self.VERBS:
            with self.subTest(verb=argv[0]):
                got = run(*argv, "--match", "semantic", "--top", "0", *self.R)
                self.assertEqual(got, (0, TOP_ZERO, ""))
                got = run(*argv, "--match", "semantic", "--top", "0", "--json", *self.R)
                self.assertEqual(got, (0, self.json_of(argv[0], "semantic"), ""))
        self.assertEqual(self.calls(), [])  # no agent call

    def test_without_an_agent_the_s4_sentence_first(self):  # P83-AC-026 row 2
        for argv in self.VERBS:
            for form in ((), ("--json",)):
                with self.subTest(verb=argv[0], json=bool(form)):
                    got = run(*argv, "--match", "semantic", "--top", "0", *form, *self.R)
                    self.assertEqual(got, (2, "", f"segmently-modules: error: {NO_AGENT}\n"))

    def test_hybrid_keeps_the_keyword_wording(self):  # P83-AC-026 row 3
        self.agent(answer=picks(("payments", 0.9)))
        texts = {"match": "no keyword matches (try rephrasing with domain terms, or use: list)\n",
                 "context": "no module matched (try domain terms, or: segmently-modules list)\n"}
        for argv in self.VERBS:
            with self.subTest(verb=argv[0]):
                self.assertEqual(run(*argv, "--match", "hybrid", "--top", "0", *self.R),
                                 (0, texts[argv[0]], ""))
                self.assertEqual(run(*argv, "--match", "hybrid", "--top", "0", "--json",
                                     *self.R), (0, self.json_of(argv[0], "hybrid"), ""))
        self.assertEqual(self.calls(), [])

    def test_an_agent_choosing_none_keeps_the_agent_wording(self):  # P83-AC-026 row 4
        self.agent(answer={"picks": [], "none": True})
        texts = {"match": "no matches (the agent chose no module; try rephrasing the task)\n",
                 "context": "no module matched (the agent chose no module; try rephrasing the "
                            "task)\n"}
        for argv in self.VERBS:
            with self.subTest(verb=argv[0]):
                self.assertEqual(run(*argv, "--match", "semantic", "--top", "3", *self.R),
                                 (0, texts[argv[0]], ""))
                self.assertEqual(run(*argv, "--match", "semantic", "--top", "3", "--json",
                                     *self.R), (0, self.json_of(argv[0], "semantic"), ""))
        self.assertEqual(len(self.calls()), 4)

    def test_discover_is_unchanged(self):  # P83-AC-026
        self.agent(answer=picks(("payments", 0.9)))
        argv = ("discover", "--task", MATCH_TASK, "--match", "semantic", "--top", "0", *self.R)
        self.assertEqual(run(*argv), (0, "", ""))
        code, env, err = run_json(*argv)
        self.assertEqual((code, err, env["data"]["modules"], env["data"]["notes"]),
                         (0, "", [], []))
        self.assertEqual(self.calls(), [])


# ---- N-6: long card lines of the text work order (P83-AC-027, P83-AC-028) -------------------

HEADING = "Candidates (one per line: module, description, keywords):"
LIMIT = 2000
KEYWORDS = ["rare book", "first edition"]


def card_line(card: dict) -> str:
    """A card line as 758d085 printed it, unwrapped."""
    parent = f"  (child of {card['parent']})" if "parent" in card else ""
    return f"{card['module']}  {card['description']}  [{', '.join(card['keywords'])}]{parent}"


def words(n: int) -> str:
    """`n` characters of words split by single spaces, not ending in a space."""
    text = ("binding folio quarto vellum " * (n // 10 + 2))[:n]
    return text[:-1] + "x" if text.endswith(" ") else text


def description_for(name: str, length: int, keywords=KEYWORDS) -> str:
    return words(length - len(f"{name}    [{', '.join(keywords)}]"))


class CardLinesBase(Base):
    LENGTHS = {"atlas": 1999, "bestsellers": 2000, "chapbooks": 2001, "dictionaries": 2500,
               "encyclopedias": 5000}
    NOSPACE = ("rarebooksandfirsteditions" * 200)[:4494]  # its card line: 4,500, no space early

    def setUp(self):
        super().setUp()
        gift = "gift-cards"
        head = words(LIMIT - len(f"{gift}  "))  # the 2,001st character is the space after it
        self.space_at_2001 = f"{head} wrapping paper and ribbons"

        def add(data):
            for name, length in self.LENGTHS.items():
                data["modules"][name] = {"name": name, "status": "active",
                                         "description": description_for(name, length),
                                         "keywords": KEYWORDS}
            data["modules"][self.NOSPACE] = {"status": "active", "description": "",
                                             "keywords": []}
            data["modules"][gift] = {"name": gift, "status": "active",
                                     "description": self.space_at_2001, "keywords": KEYWORDS}
        mutate_registry(self.root, add)
        self.task = self.tmp / "t.txt"
        self.task.write_text(TASK, encoding="utf-8")

    def order(self):
        code, env, err = run_json("choose", "--task-file", str(self.task), *self.R)
        self.assertEqual((code, err), (0, ""))
        return env["data"]

    def text(self):
        code, out, err = run("choose", "--task-file", str(self.task), *self.R)
        self.assertEqual((code, err), (0, ""))
        return out

    def card_block(self, out: str) -> list[list[str]]:
        """The printed card lines, each card's lines grouped (a continuation starts with four
        spaces)."""
        block = out.split(HEADING + "\n", 1)[1].split("\n\nAnswer schema:", 1)[0]
        groups: list[list[str]] = []
        for line in block.split("\n"):
            if line.startswith("    "):
                groups[-1].append(line)
            else:
                groups.append([line])
        return groups


class CardLinesTest(CardLinesBase):
    def test_lengths(self):  # P83-AC-027
        cards = {c["module"]: card_line(c) for c in self.order()["cards"]}
        for name, length in self.LENGTHS.items():
            self.assertEqual(len(cards[name]), length, name)
        self.assertEqual(len(cards[self.NOSPACE]), 4500)
        self.assertNotIn(" ", cards[self.NOSPACE][:LIMIT + 1])
        self.assertEqual(cards["gift-cards"][LIMIT], " ")

    def test_long_card_lines_wrap(self):  # P83-AC-027
        order, out = self.order(), self.text()
        groups = {g[0].split("  ", 1)[0]: g for g in self.card_block(out)}
        self.assertEqual(len(groups), len(order["cards"]))
        expect = {"atlas": 1, "bestsellers": 1, "chapbooks": 2, "dictionaries": 2,
                  "encyclopedias": 3, "gift-cards": 2}
        for card in order["cards"]:
            name = card["module"]
            lines = groups[name if name != self.NOSPACE else self.NOSPACE[:LIMIT]]
            with self.subTest(card=name[:20], length=len(card_line(card))):
                for line in lines:
                    self.assertLessEqual(len(line), LIMIT)
                for line in lines[1:]:
                    self.assertTrue(line.startswith("    ") and line[4] != " ", line[:10])
                if name == self.NOSPACE:  # no space: cut at exactly the limit, nothing dropped
                    self.assertEqual([len(ln) for ln in lines], [2000, 2000, 4 + 504])
                    self.assertEqual(lines[0] + "".join(ln[4:] for ln in lines[1:]),
                                     card_line(card))
                    continue
                self.assertEqual(len(lines), expect.get(name, 1))
                self.assertEqual(" ".join([lines[0]] + [ln[4:] for ln in lines[1:]]),
                                 card_line(card))  # a soft break: one space
                if name == "gift-cards":  # the space as the 2,001st character is the break
                    self.assertEqual(lines[0], card_line(card)[:LIMIT])
                if len(card_line(card)) <= LIMIT:
                    self.assertEqual(lines, [card_line(card)])


class WrapEdgesTest(unittest.TestCase):  # P83-AC-027, fix round 1 (M-3), with a limit of 10
    CASES = [  # (line, its parts, how a continuation joins back: " " soft break, "" hard cut)
        (" " + "x" * 12, [" xxxxxxxxx", "    xxx"], ""),  # a space at 0 is no break
        ("abcdefghij  xyz", ["abcdefghij", "     xyz"], " "),  # a break inside a run of spaces
        ("abcdefghij ", ["abcdefghij", "     "], ""),  # the space at the limit ends the line
        ("ab cd ef gh ij kl", ["ab cd ef", "    gh ij", "    kl"], " "),
        ("x" * 23, ["x" * 10, "    " + "x" * 6, "    " + "x" * 6, "    x"], ""),
    ]

    def test_no_empty_part_and_an_exact_join(self):
        from segmently_modules.workorder import wrap_card
        for line, parts, joiner in self.CASES:
            with self.subTest(line=line):
                got = wrap_card(line, 10)
                self.assertEqual(got, parts)
                self.assertTrue(all(len(p) <= 10 for p in got))
                self.assertTrue(got[0] and all(p.startswith("    ") and p[4:] for p in got[1:]))
                self.assertEqual(joiner.join([got[0]] + [p[4:] for p in got[1:]]), line)
        self.assertEqual(wrap_card("abcdefghij", 10), ["abcdefghij"])


class WhatDoesNotChangeTest(CardLinesBase):
    def test_json_digest_and_the_agents_stdin(self):  # P83-AC-028
        order = self.order()
        entries = json.loads((self.root / "modules/registry.json").read_text(encoding="utf-8"))
        for card in order["cards"]:  # the JSON form keeps every card whole
            if "parent" not in card:
                self.assertEqual(card["description"],
                                 entries["modules"][card["module"]].get("description", ""))
        canonical = json.dumps(order["cards"], sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False)
        self.assertEqual(order["catalog_digest"],
                         hashlib.sha256(canonical.encode("utf-8")).hexdigest())
        self.agent(answer=picks(("atlas", 0.9)))
        code, _, err = run("choose", "--task-file", str(self.task), "--run", *self.R)
        self.assertEqual((code, err), (0, ""))
        (call,) = self.calls()
        self.assertEqual(call["stdin"], json.dumps(order, ensure_ascii=False,
                                                   separators=(",", ":")))
        path = self.tmp / "a.json"
        path.write_text(json.dumps({**picks(("encyclopedias", 0.8)),
                                    "catalog_digest": order["catalog_digest"]}), encoding="utf-8")
        code, env, err = run_json("choose", "--apply", str(path), *self.R)
        self.assertEqual((code, err, env["data"]["notes"]), (0, "", []))  # the digest matches

    def test_two_runs_are_identical(self):  # P83-AC-028
        self.assertEqual(self.text(), self.text())
        self.assertEqual(run("choose", "--task-file", str(self.task), "--json", *self.R),
                         run("choose", "--task-file", str(self.task), "--json", *self.R))

    def test_heading_task_and_rules_print_as_written(self):  # P83-AC-028
        long_task = words(3000)
        self.task.write_text(long_task, encoding="utf-8")
        rule = words(2500)
        rules = self.root / ".segmently-modules/overrides/templates/choose/rules.md"
        rules.parent.mkdir(parents=True, exist_ok=True)
        rules.write_text(f"- {rule}\n- Give at most $max_picks picks.\n", encoding="utf-8")
        out = self.text()
        lines = out.split("\n")
        self.assertIn(HEADING, lines)
        self.assertEqual(lines[:2], ["Task:", long_task])
        self.assertIn(f"- {rule}", lines)

    def test_short_cards_print_as_before(self):  # P83-AC-028: no card above 2,000, no change
        self.task.write_text(TASK, encoding="utf-8")
        mutate_registry(self.root, lambda d: [d["modules"].pop(n) for n in
                                              (*self.LENGTHS, self.NOSPACE, "gift-cards")
                                              if n not in ("atlas", "bestsellers")])
        order, out = self.order(), self.text()
        before = ["Task:", order["task"], "", "Rules:", *[f"- {r}" for r in order["rules"]], "",
                  HEADING, *[card_line(c) for c in order["cards"]], "", "Answer schema:",
                  json.dumps(order["answer_schema"], indent=2), "",
                  f"catalog_digest: {order['catalog_digest']}", ""]
        self.assertEqual(out, "\n".join(before))


# ---- catalog with a malformed agent variable (P83-AC-029) -------------------------------------

def catalog_note(problem: str) -> str:
    return f"segmently-modules: note: {problem} — match.semantic is false\n"


class CatalogNoteTest(Base):
    NOT_JSON = "SEGMENTLY_MODULES_AGENT_COMMAND: expected a JSON array of strings, got 'not json'"
    EMPTY = "SEGMENTLY_MODULES_AGENT_COMMAND: expected a non-empty JSON array of strings, got '[]'"
    PLACEHOLDER = ("SEGMENTLY_MODULES_AGENT_COMMAND: item '{foo}': unknown placeholder {foo} (placeholders: "
                   "{claude_model}, {codex_model}, {effort}, {reasoning})")

    def timeout(self, value):
        return f"SEGMENTLY_MODULES_AGENT_TIMEOUT: expected an integer from 1 to 3600, got {value!r}"

    def setUp(self):
        super().setUp()
        self.good = json.dumps(self.behaviour(answer=picks(("payments", 0.9))))
        self.plain = (run("catalog", *self.R), run("catalog", "--json", *self.R))  # unset

    def env(self, command=None, timeout=None):
        for name, value in (("SEGMENTLY_MODULES_AGENT_COMMAND", command), ("SEGMENTLY_MODULES_AGENT_TIMEOUT", timeout)):
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def assert_catalog(self, semantic: bool, stderr: str):
        code, out, err = run("catalog", *self.R)
        self.assertEqual((code, out, err), (0, self.plain[0][1], stderr))
        code, out, err = run("catalog", "--json", *self.R)
        self.assertEqual((code, err), (0, stderr))
        data = json.loads(out)["data"]
        self.assertIs(data["match"]["semantic"], semantic)
        plain = json.loads(self.plain[1][1])["data"]
        data["match"]["semantic"] = plain["match"]["semantic"]
        self.assertEqual(data, plain)  # apart from `semantic`, the run with both unset

    def assert_agent_verbs_refuse(self, message: str):
        for argv in (("choose", "--task", TASK, "--run"),
                     ("match", MATCH_TASK, "--match", "semantic")):
            with self.subTest(argv=argv[0]):
                self.assertEqual(run(*argv, *self.R), (2, "", f"segmently-modules: error: {message}\n"))

    def test_the_decision_table(self):  # P83-AC-029
        rows = [(self.good, None, True, None, None),
                ("not json", None, False, self.NOT_JSON, self.NOT_JSON),
                ("[]", None, False, self.EMPTY, self.EMPTY),
                (json.dumps(["x", "{foo}"]), None, False, self.PLACEHOLDER, self.PLACEHOLDER),
                (self.good, "0", False, self.timeout("0"), self.timeout("0")),
                (self.good, "five", False, self.timeout("five"), self.timeout("five")),
                ("not json", "0", False, self.timeout("0"), self.timeout("0")),
                (" \t ", None, False, None, NO_AGENT)]
        for command, timeout, semantic, note, refusal in rows:
            with self.subTest(command=command[:20], timeout=timeout):
                self.env(command, timeout)
                self.assert_catalog(semantic, catalog_note(note) if note else "")
                if refusal:
                    self.assert_agent_verbs_refuse(refusal)
        self.assertEqual(self.calls(), [])

    def test_an_agent_table_in_a_file_is_still_refused(self):  # P83-AC-029
        self.config('[agent]\ntimeout_s = 10\n')
        for command, timeout in ((self.good, None), ("not json", "0"), (None, None)):
            self.env(command, timeout)
            for form in ((), ("--json",)):
                with self.subTest(command=command and command[:10], json=bool(form)):
                    code, out, err = run("catalog", *form, *self.R)
                    self.assertEqual((code, out), (2, ""))
                    self.assertEqual(len(err.splitlines()), 1)
                    self.assertTrue(err.startswith("segmently-modules: error: "), err)
                    self.assertIn("[agent] is not read from files", err)


class CatalogNoteStreamsTest(Base):
    """A real process: the note comes after stdout, only with exit 0 (P8.2 I-1)."""
    LIMIT = 60

    def setUp(self):
        super().setUp()
        os.environ["SEGMENTLY_MODULES_AGENT_COMMAND"] = "not json"
        self.note = catalog_note(CatalogNoteTest.NOT_JSON)
        self.env = {**os.environ, "PYTHONPATH": str(ENGINE), "PYTHONDONTWRITEBYTECODE": "1"}

    def shell(self, redirect, argv, preexec_fn=None, stdout=subprocess.PIPE,
              stderr=subprocess.PIPE):
        cmd = ["/bin/sh", "-c", f'exec "$@" {redirect}', "sh", sys.executable, "-m", "segmently_modules",
               *argv, *self.R]
        done = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                              env=self.env, cwd=ENGINE, preexec_fn=preexec_fn, timeout=TIMEOUT)
        return done.returncode, done.stdout or b"", (done.stderr or b"").decode("utf-8")

    def test_one_line_after_stdout(self):  # P83-AC-029
        for form in ((), ("--json",)):
            with self.subTest(json=bool(form)):
                code, out, err = self.shell("", ("catalog", *form))
                self.assertEqual((code, err), (0, self.note))
                code, merged, _ = self.shell("", ("catalog", *form), stderr=subprocess.STDOUT)
                self.assertEqual(code, 0)
                self.assertEqual(merged.decode("utf-8"), out.decode("utf-8") + self.note)

    def test_a_closed_stdout_exits_0(self):  # P83-AC-029
        for form in ((), ("--json",)):
            with self.subTest(json=bool(form)):
                self.assertEqual(self.shell(">&-", ("catalog", *form)), (0, b"", self.note))
                read_end, write_end = os.pipe()
                os.close(read_end)  # a reader that is gone
                try:
                    code, _, err = self.shell("", ("catalog", *form), stdout=write_end)
                finally:
                    os.close(write_end)
                self.assertEqual((code, err), (0, self.note))

    @unittest.skipIf(resource is None, "no resource module")
    def test_a_stdout_write_error_is_only_the_error_line(self):  # P83-AC-029 / P8.2 I-1
        def limit():
            signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
            resource.setrlimit(resource.RLIMIT_FSIZE, (self.LIMIT, self.LIMIT))
        out = self.tmp / "out.txt"
        for form in ((), ("--json",)):
            with self.subTest(json=bool(form)):
                with open(out, "wb") as f:
                    code, _, err = self.shell("", ("catalog", *form), limit, f)
                self.assertEqual(code, 2, err)
                lines = err.splitlines()
                self.assertEqual(len(lines), 1, err)
                self.assertTrue(lines[0].startswith("segmently-modules: error: cannot write stdout: "), err)
                self.assertNotIn("Traceback", err)


# ---- docs (P83-AC-030) -----------------------------------------------------------------------

def flat(rel: str) -> str:
    return " ".join((ENGINE / rel).read_text(encoding="utf-8").split())


class DocsTest(unittest.TestCase):
    def row(self, start: str) -> str:
        text = (ENGINE / "docs/cli-contract.md").read_text(encoding="utf-8")
        return next(ln for ln in text.splitlines() if ln.startswith(start))

    def test_catalog_cell(self):  # P83-AC-030
        cell = self.row("| `catalog` |")
        self.assertNotIn("is exit `2` here too", cell)
        self.assertIn("a malformed `SEGMENTLY_MODULES_AGENT_COMMAND` or `SEGMENTLY_MODULES_AGENT_TIMEOUT` keeps "
                      "`catalog` at exit `0` with `match.semantic` false and one stderr note "
                      "`segmently-modules: note: <variable>: <problem> — match.semantic is false`", cell)
        self.assertIn("an `[agent]` table in a config file is still exit `2`", cell)

    def test_the_note_list(self):  # P83-AC-030
        doc = flat("docs/cli-contract.md")
        self.assertIn("The `segmently-modules: note:` lines (stderr only, after stdout, only when the run "
                      "exits `0`): the one above and `catalog`'s `segmently-modules: note: <variable>: "
                      "<problem> — match.semantic is false`", doc)

    def test_choose_cell_and_the_task_file(self):  # P83-AC-030
        cell = self.row("| `choose ")
        self.assertIn("`--apply` reads the bytes of FILE or stdin and decodes them as UTF-8 "
                      "with replacement, as `--run` reads the agent's stdout", cell)
        self.assertIn("a card line longer than 2,000 characters goes on over following lines "
                      "indented by four spaces", cell)
        doc = flat("docs/cli-contract.md")
        self.assertIn("a task file that cannot be read or is not UTF-8 is exit `2` with "
                      "`segmently-modules: error: cannot read <path>: <reason>` (`<stdin>` for `-`; "
                      "`<reason>` is the system's reason or `not valid UTF-8`)", doc)
        self.assertNotIn("is exit 2 in `catalog` too", flat("docs/configuration.md"))

    def test_the_changelog(self):  # P83-AC-030
        text = (ENGINE / "CHANGELOG.md").read_text(encoding="utf-8")
        unreleased = " ".join(changelog_since_first_release(text).split())
        for needle in ("A first Ctrl-C, SIGTERM or SIGHUP at the very start or end of an agent "
                       "call no longer leaves the temp directory or a handler behind",  # N-1
                       "A task file or stdin that is not UTF-8 is exit 2 `cannot read <path>: "
                       "<reason>`",  # N-2
                       "`choose --apply` reads an answer as `choose --run` does",  # N-3
                       "`no module matched (--top 0)`",  # N-4
                       "card lines longer than 2,000 characters",  # N-6
                       "`catalog` with a malformed `MODSYS_AGENT_COMMAND` or "
                       "`MODSYS_AGENT_TIMEOUT` exits 0"):  # catalog (0.1.1, the old name)
            self.assertIn(needle, unreleased)


if __name__ == "__main__":
    unittest.main()
