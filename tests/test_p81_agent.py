"""P8.1 task 3b, the user's own agent: the `[agent]` trust boundary and running (P81-AC-058…064),
`choose --run` (065), `--match semantic|hybrid` through the agent (066…068), no network or model
code (071), no writes and no cache (073)."""
import ast
import io
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from modsys import agent as agent_mod
from tests.agent_helpers import AgentRepo, picks
from tests.helpers import run, run_json
from tests.test_p81_catalog_modes import NO_EMBEDDER as NO_AGENT, tree_hash

ENGINE = Path(__file__).resolve().parents[1]
TASK = "возврат платежа за заказ"
MATCH_TASK = "refund payment catalog"  # lexical rows: catalog, orders/refunds, payments


def rows_of(env):
    data = env["data"]
    return data["rows"] if isinstance(data, dict) and "rows" in data else data


class Base(AgentRepo, unittest.TestCase):
    def choose(self, *extra, task=TASK):
        return run("choose", "--task", task, "--run", *self.R, *extra)

    def alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True


class TrustBoundaryTest(Base):
    GOOD = picks(("payments", 0.9))

    def test_committed_config_is_refused(self):  # P81-AC-058
        argv = self.behaviour(answer=self.GOOD)
        self.config(f"[agent]\ncommand = {json.dumps(argv)}\n")
        for argv_ in (("choose", "--task", "t", "--run"), ("catalog",), ("lint",)):
            code, out, err = run(*argv_, *self.R)
            self.assertEqual((code, out), (2, ""), argv_)
            self.assertIn("config.toml", err)
            self.assertIn("[agent] command", err)
            self.assertNotIn("Traceback", err)
        self.assertEqual(self.calls(), [])

    def test_committed_timeout_is_refused(self):  # P81-AC-058
        self.config("[agent]\ntimeout_s = 10\n")
        code, out, err = run("catalog", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("timeout_s", err)

    def test_pack_setting_is_refused(self):  # P81-AC-058
        pack = self.root / ".modsys" / "packs" / "evil"
        pack.mkdir(parents=True)
        (pack / "pack.toml").write_text('id = "evil"\nversion = "0.1.0"\n\n[agent]\n'
                                        f'command = {json.dumps(self.behaviour())}\n',
                                        encoding="utf-8")
        code, out, err = run("choose", "--task", "t", "--run", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("pack.toml", err)
        self.assertIn("[agent] command", err)
        self.assertEqual(self.calls(), [])

    def test_user_config_and_env_run(self):  # P81-AC-058
        self.agent(answer=self.GOOD)
        self.assertEqual(self.choose()[0], 0)
        self.assertEqual(len(self.calls()), 1)
        (self.root / ".modsys" / "config.user.toml").unlink()
        with mock.patch.dict(os.environ, {"MODSYS_AGENT_COMMAND":
                                          json.dumps(self.behaviour(answer=self.GOOD))}):
            self.assertEqual(self.choose()[0], 0)
        self.assertEqual(len(self.calls()), 2)

    def test_env_beats_the_user_config(self):  # P81-AC-058 / SI-P81-16
        self.agent(answer=picks(("payments", 0.9)))
        env_argv = self.behaviour(answer=picks(("catalog", 0.8)))
        with mock.patch.dict(os.environ, {"MODSYS_AGENT_COMMAND": json.dumps(env_argv)}):
            code, out, _ = self.choose("--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["data"]["picks"][0]["module"], "catalog")

    def test_invalid_env_has_no_fallback(self):  # P81-AC-058
        self.agent(answer=self.GOOD)
        for bad in ("nope", '"a string"', '["ok", 3]', "[]", '{"a": 1}'):
            with self.subTest(bad=bad), mock.patch.dict(os.environ,
                                                        {"MODSYS_AGENT_COMMAND": bad}):
                for argv in (("choose", "--task", "t", "--run"), ("catalog",)):
                    code, out, err = run(*argv, *self.R)
                    self.assertEqual((code, out), (2, ""))
                    self.assertIn("MODSYS_AGENT_COMMAND", err)
        self.assertEqual(self.calls(), [])
        with mock.patch.dict(os.environ, {"MODSYS_AGENT_COMMAND": "  "}):  # empty = unset
            self.assertEqual(self.choose()[0], 0)

    def test_env_timeout_comes_from_the_user_config(self):  # SI-P81-15
        self.config("[agent]\ntimeout_s = 0\n", "config.user.toml")
        with mock.patch.dict(os.environ, {"MODSYS_AGENT_COMMAND":
                                          json.dumps(self.behaviour(answer=self.GOOD))}):
            code, _, err = self.choose()
        self.assertEqual(code, 2)
        self.assertIn("[agent] timeout_s", err)


class RunningTest(Base):
    def test_argv_stdin_files_and_environment(self):  # P81-AC-059
        items = ["a;b", "$(x)", "*", "two words", "{{x}}"]
        self.agent(items, answer=picks(("payments", 0.9)))
        before = dict(os.environ)
        code, out, err = self.choose()
        self.assertEqual((code, err), (0, ""))
        (call,) = self.calls()
        self.assertEqual(call["argv"], ["a;b", "$(x)", "*", "two words", "{x}"])
        order = run_json("choose", "--task", TASK, *self.R)[1]["data"]
        self.assertEqual(json.loads(call["stdin"]), order)
        self.assertTrue(call["work_order_file"]["exists"])
        self.assertEqual(json.loads(call["work_order_file"]["content"]), order)
        self.assertEqual(json.loads(call["schema_file"]["content"]), order["answer_schema"])
        child = {k: v for k, v in call["env"].items()
                 if k not in ("MODSYS_WORK_ORDER", "MODSYS_SCHEMA")}
        self.assertEqual(child, before)
        self.assertFalse(Path(call["work_order_file"]["path"]).exists())  # removed afterwards

    def test_placeholders(self):  # P81-AC-060
        items = ["{claude_model}", "--m={codex_model}", "{effort}", "{reasoning}", "{{literal}}"]
        for effort, reasoning in (("quick", "low"), ("standard", "medium"), ("deep", "high")):
            self.calls_log.unlink(missing_ok=True)
            self.agent(items, answer=picks(), search=f'[search]\neffort = "{effort}"\n')
            self.assertEqual(self.choose()[0], 0)
            self.assertEqual(self.calls()[0]["argv"],
                             ["sonnet", "--m=gpt-5.6-luna", effort, reasoning, "{literal}"])
        self.calls_log.unlink()
        self.agent(["{claude_model}"], answer=picks(),
                   search='[search]\nclaude_model = "a{effort}b"\n')  # not re-scanned
        self.assertEqual(self.choose()[0], 0)
        self.assertEqual(self.calls()[0]["argv"], ["a{effort}b"])

    def test_bad_placeholders_fail_at_config_load(self):  # P81-AC-060
        for item, needle in (("{foo}", "{foo}"), ("a{", "unmatched"), ("}x", "unmatched"),
                             ("{ effort}", "unmatched"), ("{claude_model", "unmatched")):
            self.agent([item], answer=picks())
            for argv in (("lint",), ("catalog",), ("choose", "--task", "t", "--run")):
                code, out, err = run(*argv, *self.R)
                self.assertEqual((code, out), (2, ""), (item, argv))
                self.assertIn(needle, err)
                self.assertIn(repr(item), err)
        self.config(f'[agent]\ncommand = ["{{effort}}", "x"]\n', "config.user.toml")
        code, _, err = run("catalog", *self.R)
        self.assertEqual(code, 2)
        self.assertIn("argv[0]", err)
        for bad in ("[]", '[1]', '"string"'):
            self.config(f"[agent]\ncommand = {bad}\n", "config.user.toml")
            self.assertEqual(run("catalog", *self.R)[0], 2, bad)

    def test_answer_parsing_order(self):  # P81-AC-061
        raw = picks(("payments", 0.9))
        other = picks(("catalog", 0.5))
        fence = "```json\n" + json.dumps(raw) + "\n```"
        cases = [("raw", json.dumps(raw), "payments"),
                 ("structured wins", json.dumps({"structured_output": raw,
                                                 "result": json.dumps(other)}), "payments"),
                 ("result string", json.dumps({"result": json.dumps(raw)}), "payments"),
                 ("fenced", json.dumps({"result": fence}), "payments"),
                 ("result object", json.dumps({"result": raw}), "payments"),
                 ("is_error", json.dumps({"is_error": True, "result": json.dumps(raw)}), None),
                 ("prose", "Sure! The module is payments.", None),
                 ("empty envelope", json.dumps({"structured_output": None}), None),
                 ("array", "[1]", None), ("empty", "", None),
                 ("result prose", json.dumps({"result": "payments"}), None),
                 ("bad answer", json.dumps({"picks": [{"module": "payments"}]}), None)]
        for label, text, expected in cases:
            with self.subTest(label):
                self.agent(answer=text)
                code, out, err = self.choose("--json")
                if expected is None:
                    self.assertEqual((code, out), (2, ""))
                    self.assertIn("agent", err)
                    self.assertNotIn("Traceback", err)
                else:
                    self.assertEqual(code, 0)
                    self.assertEqual(json.loads(out)["data"]["picks"][0]["module"], expected)

    def test_timeout_values(self):  # P81-AC-062
        for ok in (1, 300, 3600):
            self.agent(answer=picks(), timeout_s=ok)
            self.assertEqual(run("catalog", *self.R)[0], 0, ok)
        for bad in ("0", "3601", "-1", "1.5", '"5"', "true"):
            self.agent(answer=picks())
            self.config(f"[agent]\ncommand = {json.dumps(self.behaviour())}\n"
                        f"timeout_s = {bad}\n", "config.user.toml")
            code, out, err = run("catalog", *self.R)
            self.assertEqual((code, out), (2, ""), bad)
            self.assertIn("[agent] timeout_s", err)

    def test_expiry_kills_the_child(self):  # P81-AC-062
        started = self.tmp / "started"
        self.agent(sleep=30, started=str(started), answer=json.dumps(picks()), timeout_s=1)
        with mock.patch.object(agent_mod, "TIMEOUT_UNIT", 0.5):
            t0 = time.monotonic()
            code, out, err = self.choose()
        self.assertEqual((code, out), (2, ""))
        self.assertIn("agent timed out after 1 s", err)
        self.assertNotIn("ResourceWarning", err)
        self.assertLess(time.monotonic() - t0, 20)
        self.assertFalse(self.alive(int(started.read_text())))

    def test_agent_failures(self):  # P81-AC-063
        argv = self.agent(exit=1, stderr="e" * 2000)
        code, out, err = self.choose()
        self.assertEqual((code, out), (2, ""))
        self.assertIn(argv[0], err)
        self.assertIn("exited 1", err)
        self.assertIn("e" * 500, err)
        self.assertNotIn("e" * 501, err)
        self.agent(answer="")
        code, out, err = self.choose()
        self.assertEqual((code, out), (2, ""))
        self.assertIn("printed nothing", err)
        self.config('[agent]\ncommand = ["/nonexistent/agent-x", "--y"]\n', "config.user.toml")
        code, out, err = self.choose()
        self.assertEqual((code, out), (2, ""))
        self.assertIn("/nonexistent/agent-x", err)
        self.assertNotIn("Traceback", err)

    def test_stderr_is_not_forwarded_on_success(self):  # SI-P81-22
        self.agent(answer=picks(("payments", 0.9)), stderr="noise")
        code, out, err = self.choose()
        self.assertEqual((code, err), (0, ""))
        self.assertNotIn("noise", out)

    def test_temp_files_are_removed(self):  # P81-AC-064
        scratch = self.tmp / "tmpdir"
        scratch.mkdir()
        cases = [dict(answer=json.dumps(picks(("payments", 1)))), dict(exit=1),
                 dict(sleep=30, answer="{}", timeout_s=1)]
        with mock.patch.object(tempfile, "tempdir", str(scratch)), \
                mock.patch.object(agent_mod, "TIMEOUT_UNIT", 0.3):
            for cfg in cases:
                timeout = cfg.pop("timeout_s", None)
                self.agent(timeout_s=timeout, **cfg)
                self.choose()
                self.assertEqual(list(scratch.iterdir()), [], cfg)
        self.assertEqual(tree_hash(self.root).count("agent"), 0)

    def test_interrupt_kills_the_child_and_group(self):  # P81-AC-064 / AC-045
        started, grand = self.tmp / "started", self.tmp / "grand"
        scratch = self.tmp / "tmpdir"
        scratch.mkdir()
        self.agent(sleep=60, started=str(started), grandchild=str(grand), answer="{}")
        env = {**os.environ, "PYTHONPATH": str(ENGINE), "TMPDIR": str(scratch)}
        proc = subprocess.Popen([sys.executable, "-m", "modsys", "choose", "--task", TASK,
                                 "--run", *self.R], env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, cwd=ENGINE,
                                preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))
        try:
            for _ in range(200):
                if started.exists() and grand.exists():
                    break
                time.sleep(0.05)
            self.assertTrue(started.exists() and grand.exists(), "the agent never started")
            child, grandchild = int(started.read_text()), int(grand.read_text())
            proc.send_signal(signal.SIGINT)
            out, err = proc.communicate(timeout=30)
        finally:
            if proc.poll() is None:
                proc.kill()
        self.assertEqual((proc.returncode, out), (130, ""))
        self.assertNotIn("Traceback", err)
        time.sleep(0.2)
        self.assertFalse(self.alive(child))
        self.assertFalse(self.alive(grandchild))
        self.assertEqual(list(scratch.iterdir()), [])


class ChooseRunTest(Base):
    ANSWER = {"picks": [{"module": "orders/refunds", "confidence": 0.9, "reason": "r"},
                        {"module": "payments", "confidence": 0.4}], "none": False}

    def test_same_picks_as_apply(self):  # P81-AC-065
        self.agent(answer=self.ANSWER)
        for extra in ((), ("--json",)):
            ran = self.choose(*extra)
            path = self.tmp / "a.json"
            path.write_text(json.dumps(self.ANSWER), encoding="utf-8")
            applied = run("choose", "--apply", str(path), *self.R, *extra)
            self.assertEqual(ran[0], 0)
            self.assertEqual(ran, applied)

    def test_top_truncates_with_a_note(self):  # P81-AC-065 / SI-P81-20
        self.agent(answer=self.ANSWER)
        data = json.loads(self.choose("--top", "1", "--json")[1])["data"]
        self.assertEqual([p["module"] for p in data["picks"]], ["orders/refunds"])
        self.assertEqual(len(data["notes"]), 1)
        code, out, _ = self.choose("--top", "1")
        self.assertIn("note: ", out)

    def test_without_an_agent_and_with_top_zero(self):  # P81-AC-065
        code, out, err = self.choose()
        self.assertEqual((code, out, err), (2, "", f"modsys: error: {NO_AGENT}\n"))
        self.agent(answer=self.ANSWER)
        code, out, err = self.choose("--top", "0")
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(self.calls(), [])
        code, out, err = run("choose", "--run", *self.R)
        self.assertEqual((code, out), (2, ""))


class ModesThroughTheAgentTest(Base):
    VERBS = {"match": ("match", MATCH_TASK), "context": ("context", "--task", MATCH_TASK),
             "discover": ("discover", "--task", MATCH_TASK)}
    PICKS = picks(("orders/refunds", 0.9, "returns"), ("payments", 0.5))

    def modules(self, name, env):
        data = env["data"]
        return [r["module"] for r in (rows_of(env) if name == "match" else data["modules"])]

    def test_rows_come_from_the_agent(self):  # P81-AC-066 and the carried 3a finding
        for name, argv in self.VERBS.items():
            for mode in ("semantic", "hybrid"):
                with self.subTest(verb=name, mode=mode):
                    self.calls_log.unlink(missing_ok=True)
                    self.agent(answer=self.PICKS)
                    code, env, err = run_json(*argv, "--match", mode, *self.R)
                    self.assertEqual((code, err), (0, ""))
                    self.assertEqual(len(self.calls()), 1)  # exactly once per run
                    self.assertEqual(env["data"]["mode"] if name != "match"
                                     else env["data"]["mode"], mode)
                    rows = rows_of(env) if name == "match" else env["data"]["modules"]
                    by = {r["module"]: r for r in rows}
                    self.assertEqual(by["orders/refunds"]["confidence"], 0.9)
                    self.assertEqual(by["payments"]["confidence"], 0.5)
                    self.assertNotIn("similarity", json.dumps(env))
                    if mode == "semantic":
                        self.assertEqual(list(by), ["orders/refunds", "payments"])
                        for r in rows:
                            if name != "discover":
                                self.assertEqual(r["sources"], ["semantic"])
                    else:
                        self.assertIn("catalog", by)  # the lexical row the agent did not pick
                        self.assertNotIn("confidence", by["catalog"])

    def test_text_output_shows_agent_rows(self):  # P81-AC-066
        self.agent(answer=self.PICKS)
        for argv in self.VERBS.values():
            code, out, err = run(*argv, "--match", "semantic", *self.R)
            self.assertEqual((code, err), (0, ""))
            self.assertIn("orders/refunds", out)
            self.assertNotIn("keyword matches", out)

    def test_discover_classifies_as_in_lexical_mode(self):  # P81-AC-066
        self.agent(answer=self.PICKS)
        files = ("--files", "src/orders/service.py")
        lexical = run_json("discover", "--task", MATCH_TASK, *files, *self.R)[1]["data"]
        sem = run_json("discover", "--task", MATCH_TASK, *files, "--match", "semantic",
                       *self.R)[1]["data"]
        usage = {m["module"]: m["usage"] for m in lexical["modules"]}
        for m in sem["modules"]:
            if m["module"] in usage:
                self.assertEqual(m["usage"], usage[m["module"]])
        self.assertEqual({m["module"] for m in sem["modules"] if m["usage"] == "modify"},
                         {m["module"] for m in lexical["modules"] if m["usage"] == "modify"})

    def test_rrf(self):  # P81-AC-067
        self.agent(answer=picks(("payments", 0.9), ("catalog", 0.8), ("orders/invoices", 0.5)))
        _, env, _ = run_json("match", MATCH_TASK, "--match", "hybrid", *self.R)
        rows = rows_of(env)
        self.assertEqual([r["module"] for r in rows],
                         ["catalog", "payments", "orders/refunds", "orders/invoices"])
        by = {r["module"]: r for r in rows}
        self.assertEqual(by["catalog"]["sources"], ["keyword", "semantic"])
        self.assertEqual(by["payments"]["sources"], ["keyword", "semantic"])
        self.assertEqual(by["orders/refunds"]["sources"], ["keyword"])
        self.assertEqual(by["orders/invoices"]["sources"], ["semantic"])
        self.assertNotIn("confidence", by["orders/refunds"])
        self.assertEqual(by["payments"]["confidence"], 0.9)
        self.assertAlmostEqual(by["catalog"]["rrf"], 1 / 61 + 1 / 62, places=6)
        self.assertAlmostEqual(by["payments"]["rrf"], 1 / 63 + 1 / 61, places=6)
        _, env, _ = run_json("match", MATCH_TASK, "--match", "hybrid", "--top", "2", *self.R)
        self.assertEqual([r["module"] for r in rows_of(env)], ["catalog", "payments"])

    def test_rrf_tie_breaks_by_lexical_rank(self):  # P81-AC-067 / SI-P81-3
        self.agent(answer=picks(("orders/refunds", 0.9), ("catalog", 0.8)))
        _, env, _ = run_json("match", "refund catalog", "--match", "hybrid", *self.R)
        self.assertEqual([r["module"] for r in rows_of(env)], ["catalog", "orders/refunds"])

    def test_empty_picks_leave_the_lexical_rows(self):  # P81-AC-067
        _, lexical, _ = run_json("match", MATCH_TASK, *self.R)
        for answer in ({"picks": [], "none": True}, picks(), picks(("ghost", 1))):
            self.agent(answer=answer)
            code, env, err = run_json("match", MATCH_TASK, "--match", "hybrid", *self.R)
            self.assertEqual((code, err), (0, ""))
            self.assertEqual([r["module"] for r in rows_of(env)],
                             [r["module"] for r in lexical["data"]])
            code, out, _ = run("match", MATCH_TASK, "--match", "semantic", *self.R)
            self.assertEqual(code, 0)
            self.assertIn("no matches", out)

    def test_failures_do_not_fall_back(self):  # P81-AC-068
        failing = [dict(exit=1), dict(answer="prose"), dict(answer=json.dumps({"picks": 3})),
                   dict(sleep=30, answer="{}", timeout_s=1)]
        for cfg in failing:
            timeout = cfg.pop("timeout_s", None)
            self.agent(timeout_s=timeout, **cfg)
            before = tree_hash(self.root)
            for mode in ("semantic", "hybrid"):
                for name, argv in self.VERBS.items():
                    with self.subTest(cfg=cfg, mode=mode, verb=name), \
                            mock.patch.object(agent_mod, "TIMEOUT_UNIT", 0.2):
                        code, out, err = run(*argv, "--match", mode, *self.R, "--json")
                        self.assertEqual((code, out), (2, ""))
                        self.assertIn("agent", err)
                        self.assertNotIn("Traceback", err)
                        self.assertNotIn("ResourceWarning", err)
            self.assertEqual(tree_hash(self.root), before)

    def test_no_command_wording_holds(self):  # P81-AC-068
        self.agent(answer=picks())
        (self.root / ".modsys" / "config.user.toml").unlink()
        code, out, err = run("match", MATCH_TASK, "--match", "semantic", *self.R)
        self.assertEqual((code, out, err), (2, "", f"modsys: error: {NO_AGENT}\n"))
        self.assertEqual(self.calls(), [])


class NothingWrittenTest(Base):
    def test_no_writes_no_cache(self):  # P81-AC-073
        self.agent(answer=picks(("orders/refunds", 0.9), ("payments", 0.5)))
        before = tree_hash(self.root)
        for mode in ("lexical", "semantic", "hybrid"):
            for argv in (("match", MATCH_TASK), ("context", "--task", MATCH_TASK),
                         ("discover", "--task", MATCH_TASK)):
                self.assertEqual(run(*argv, "--match", mode, *self.R)[0], 0)
        for argv in (("catalog",), ("choose", "--task", TASK), ("choose", "--task", TASK, "--run"),
                     ("show", "orders"), ("related", "orders"), ("roles", "list"), ("next",)):
            self.assertEqual(run(*argv, *self.R)[0], 0, argv)
        path = self.tmp / "a.json"
        path.write_text(json.dumps(picks(("payments", 1))), encoding="utf-8")
        self.assertEqual(run("choose", "--apply", str(path), *self.R)[0], 0)
        self.assertEqual(tree_hash(self.root), before)
        self.assertFalse(list(self.root.rglob("*.lock")))
        self.assertFalse(list(self.root.rglob("semantic-index.json")))
        self.assertFalse((self.root / ".modsys" / "cache").exists())

    def test_init_adds_no_cache_entry(self):  # P81-AC-073
        repo = self.tmp / "fresh"
        repo.mkdir()
        self.assertEqual(run("init", "--root", str(repo))[0], 0)
        gi = repo / ".gitignore"
        self.assertNotIn("cache", gi.read_text(encoding="utf-8") if gi.exists() else "")


class NoNetworkNoModelTest(Base):
    def test_source_scan(self):  # P81-AC-071
        banned = {"urllib", "http", "socket", "ssl"}
        for path in sorted((ENGINE / "modsys").rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for node in ast.walk(ast.parse(text)):
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                elif isinstance(node, ast.Call) and getattr(node.func, "id", "") == "__import__":
                    names = [str(getattr(node.args[0], "value", ""))] if node.args else []
                elif isinstance(node, ast.Call) and getattr(node.func, "attr", "") == \
                        "import_module":
                    names = [str(getattr(node.args[0], "value", ""))] if node.args else []
                else:
                    continue
                for n in names:
                    self.assertNotIn(n.split(".")[0], banned, f"{path}: imports {n}")
            for word in ("api_key_env", "min_similarity", "[match.semantic]", "embedder"):
                self.assertNotIn(word, text, f"{path}: {word}")

    def test_no_connection_in_any_run(self):  # P81-AC-071
        self.agent(answer=picks(("payments", 0.9)))
        def boom(*a, **k):
            raise AssertionError("a network connection was attempted")
        with mock.patch.object(socket.socket, "connect", boom):
            for argv in (("match", MATCH_TASK), ("match", MATCH_TASK, "--match", "hybrid"),
                         ("context", "--task", MATCH_TASK, "--match", "semantic"),
                         ("choose", "--task", TASK, "--run"), ("catalog",)):
                self.assertEqual(run(*argv, *self.R)[0], 0, argv)

    def test_sentinel_cli_is_first_on_path(self):  # P81-AC-072
        import shutil
        for name in ("claude", "codex"):
            self.assertEqual(Path(shutil.which(name)).parent, self.bin)


if __name__ == "__main__":
    unittest.main()
