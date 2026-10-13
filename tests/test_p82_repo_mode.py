"""P8.2 task 2 (D6): a `[match] mode` from a config file runs the user's agent command only with
`SEGMENTLY_MODULES_AGENT_ALLOW_REPO_MODE=1`; otherwise the run is lexical (stdout byte-identical to
`--match lexical`) with one stderr note, printed only when the run exits 0."""
import json
import os
import re
import unittest
from pathlib import Path

from segmently_modules.agent import NESTED
from tests.agent_helpers import AgentRepo, picks
from tests.helpers import changelog_release, git, run

OPT = "SEGMENTLY_MODULES_AGENT_ALLOW_REPO_MODE"
TASK = "partial refund for a returned book"
NO_AGENT = ("semantic matching needs your agent: set SEGMENTLY_MODULES_AGENT_COMMAND (a JSON array); "
            "in Claude Code / Codex the skills do it with segmently-modules choose")
NO_AGENT_NOTE = "semantic part skipped: no agent command configured"
NESTED_NOTE = "semantic part skipped: nested agent call"
ENGINE = Path(__file__).resolve().parents[1]


def note(mode: str) -> str:
    return (f'segmently-modules: note: [match] mode "{mode}" is set in a config file; it runs your agent '
            f'command only with {OPT}=1 (or pass --match {mode}) — ran lexical\n')


class Repo(AgentRepo, unittest.TestCase):
    def setUp(self):
        super().setUp()
        os.environ.pop(OPT, None)
        self.task_file = self.tmp / "task.txt"
        self.task_file.write_text(TASK, encoding="utf-8")

    def verbs(self):
        """(name, argv without --match/--json) for the three verbs."""
        tf = str(self.task_file)
        return (("match", ("match", TASK)),
                ("context", ("context", "--task-file", tf)),
                ("discover", ("discover", "--task-file", tf)))

    def go(self, argv, *extra, json_out=False):
        return run(*argv, *self.R, *extra, *(("--json",) if json_out else ()))

    def mode(self, mode: str, name: str = "config.toml") -> None:
        self.config(f'[match]\nmode = "{mode}"\n', name)

    def good_agent(self):
        return self.agent(answer=picks(("orders/refunds", 0.9)))

    def lex(self, argv, json_out=False):
        code, out, err = self.go(argv, "--match", "lexical", json_out=json_out)
        self.assertEqual((code, err), (0, ""))
        return out


class DecisionTableTest(Repo):  # P82-AC-015
    def test_r1_the_flag_never_reads_the_opt_in(self):
        self.good_agent()
        for name, argv in self.verbs():
            for js in (False, True):
                for flag in ("lexical", "semantic", "hybrid"):
                    for cmd in ("valid", "malformed"):
                        results = []
                        for cfg in (None, "lexical", "semantic", "hybrid"):
                            (self.root / ".segmently-modules" / "config.toml").unlink(missing_ok=True)
                            if cfg:
                                self.mode(cfg)
                            for value in (None, "garbage", "1", "0"):
                                os.environ.pop(OPT, None)
                                if value is not None:
                                    os.environ[OPT] = value
                                if cmd == "malformed":
                                    os.environ["SEGMENTLY_MODULES_AGENT_COMMAND"] = "not json"
                                else:
                                    self.good_agent()
                                results.append(self.go(argv, "--match", flag, json_out=js))
                        with self.subTest(verb=name, json=js, flag=flag, cmd=cmd):
                            self.assertEqual(len(set(results)), 1)
                            code, _, err = results[0]
                            self.assertNotIn("note:", err)
                            if cmd == "malformed" and flag != "lexical":
                                self.assertEqual(code, 2)
                                self.assertTrue(
                                    err.startswith("segmently-modules: error: SEGMENTLY_MODULES_AGENT_COMMAND:"), err)
                            else:
                                self.assertEqual((code, err), (0, ""))

    def test_r2_a_lexical_or_absent_config_reads_nothing(self):
        os.environ["SEGMENTLY_MODULES_AGENT_COMMAND"] = "not json"
        os.environ[OPT] = "garbage"
        for cfg in (None, "lexical"):
            if cfg:
                self.mode(cfg)
            for name, argv in self.verbs():
                for js in (False, True):
                    with self.subTest(cfg=cfg, verb=name, json=js):
                        plain = self.go(argv, json_out=js)
                        os.environ.pop("SEGMENTLY_MODULES_AGENT_COMMAND")
                        os.environ.pop(OPT)
                        again = self.go(argv, json_out=js)
                        os.environ["SEGMENTLY_MODULES_AGENT_COMMAND"] = "not json"
                        os.environ[OPT] = "garbage"
                        self.assertEqual(plain, again)
                        self.assertEqual((plain[0], plain[2]), (0, ""))

    def test_r3_r4_not_opted_in_runs_lexical_with_one_note(self):
        self.good_agent()
        for mode in ("semantic", "hybrid"):
            self.mode(mode)
            for value in (None, "", "0"):
                os.environ.pop(OPT, None)
                if value is not None:
                    os.environ[OPT] = value
                for name, argv in self.verbs():
                    for js in (False, True):
                        with self.subTest(mode=mode, opt=value, verb=name, json=js):
                            code, out, err = self.go(argv, json_out=js)
                            self.assertEqual(out, self.lex(argv, js))
                            self.assertEqual((code, err), (0, note(mode)))
                            self.assertEqual(self.calls(), [])  # the agent never ran

    def test_r3_r4_malformed_agent_variables_are_not_read(self):
        os.environ["SEGMENTLY_MODULES_AGENT_COMMAND"] = "[]"
        os.environ["SEGMENTLY_MODULES_AGENT_TIMEOUT"] = "five"
        for mode in ("semantic", "hybrid"):
            self.mode(mode)
            for name, argv in self.verbs():
                with self.subTest(mode=mode, verb=name):
                    code, out, err = self.go(argv)
                    self.assertEqual((code, err), (0, note(mode)))
                    self.assertEqual(out, self.lex(argv))

    def test_the_note_is_one_line_after_stdout_and_only_on_exit_0(self):
        self.mode("hybrid")
        for name, argv in self.verbs():
            with self.subTest(verb=name):
                _, _, err = self.go(argv)
                self.assertEqual(err.count("\n"), 1)
        # a refusal later in the run: the single error line, no note
        for mode in ("semantic", "hybrid"):
            self.mode(mode)
            for verb in ("context", "discover"):
                for js in (False, True):
                    code, out, err = self.go((verb, "--task-file", str(self.tmp / "missing.txt")),
                                             json_out=js)
                    with self.subTest(mode=mode, verb=verb, json=js):
                        self.assertEqual((code, out), (2, ""))
                        self.assertEqual(err.count("\n"), 1)
                        self.assertTrue(err.startswith("segmently-modules: error:"), err)
                        self.assertNotIn("note:", err)
        # nothing leaks into the next run in the same process
        code, out, err = run("list", *self.R)
        self.assertEqual((code, err), (0, ""))

    def test_the_note_comes_after_stdout(self):
        import contextlib
        import io
        from segmently_modules.cli import main
        self.mode("semantic")
        events = []

        class Stream(io.StringIO):
            def __init__(self, tag):
                super().__init__()
                self.tag = tag

            def write(self, s):
                events.append(self.tag)
                return super().write(s)

        out, err = Stream("out"), Stream("err")
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(main(["match", TASK, *self.R]), 0)
        self.assertEqual(events[-1], "err")
        self.assertNotIn("err", events[:-1 - events[::-1].index("out")])

    def test_the_note_is_the_last_line_of_a_merged_pipe(self):  # SI-P82-9, stdout is buffered
        import subprocess
        import sys
        for mode in ("semantic", "hybrid"):
            self.mode(mode)
            for name, argv in self.verbs():
                for js in (False, True):
                    cmd = [sys.executable, "-m", "segmently_modules", *argv, *self.R,
                           *(("--json",) if js else ())]
                    env = {**os.environ, "PYTHONPATH": str(ENGINE)}
                    merged = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                            text=True, env=env, cwd=self.tmp).stdout
                    with self.subTest(mode=mode, verb=name, json=js):
                        self.assertTrue(merged.endswith(note(mode)), merged[-300:])
                        self.assertEqual(merged[:-len(note(mode))], self.lex(argv, js))

    def test_r5_an_invalid_opt_in_with_a_non_lexical_config_is_exit_2(self):
        self.good_agent()
        os.environ[OPT] = "true"
        for mode in ("semantic", "hybrid"):
            self.mode(mode)
            for name, argv in self.verbs():
                for js in (False, True):
                    with self.subTest(mode=mode, verb=name, json=js):
                        self.assertEqual(
                            self.go(argv, json_out=js),
                            (2, "", f"segmently-modules: error: {OPT}: expected 1 or 0, got 'true'\n"))
        os.environ["SEGMENTLY_MODULES_AGENT_COMMAND"] = "not json"  # the opt-in is validated first
        for name, argv in self.verbs():
            self.assertEqual(
                self.go(argv),
                (2, "", f"segmently-modules: error: {OPT}: expected 1 or 0, got 'true'\n"))

    def test_r6_semantic_opted_in_asks_the_agent_once(self):
        os.environ[OPT] = "1"
        for name, argv in self.verbs():
            for js in (False, True):
                with self.subTest(verb=name, json=js):
                    self.mode("semantic")
                    self.good_agent()
                    self.calls_log.unlink(missing_ok=True)
                    flagged = self.go(argv, "--match", "semantic", json_out=js)
                    self.assertEqual(len(self.calls()), 1)
                    self.calls_log.unlink()
                    configured = self.go(argv, json_out=js)
                    self.assertEqual(configured, flagged)
                    self.assertEqual((configured[0], configured[2]), (0, ""))
                    self.assertEqual(len(self.calls()), 1)
                    self.calls_log.unlink()

    def test_r7_semantic_opted_in_without_a_command_is_refused(self):
        os.environ[OPT] = "1"
        self.mode("semantic")
        for name, argv in self.verbs():
            for js in (False, True):
                with self.subTest(verb=name, json=js):
                    self.assertEqual(self.go(argv, json_out=js),
                                     (2, "", f"segmently-modules: error: {NO_AGENT}\n"))

    def test_r8_hybrid_opted_in_without_a_command_runs_lexically_with_a_stdout_note(self):
        os.environ[OPT] = "1"
        self.mode("hybrid")
        for name, argv in self.verbs():
            with self.subTest(verb=name):
                code, out, err = self.go(argv)
                self.assertEqual((code, err), (0, ""))
                self.assertIn(NO_AGENT_NOTE, out)
                _, env, _ = (lambda r: (r[0], json.loads(r[1]), r[2]))(
                    self.go(argv, json_out=True))
                self.assertEqual(env["data"]["notes"], [NO_AGENT_NOTE])
                self.assertEqual(out, self.go(argv, "--match", "hybrid")[1])

    def test_r9_r10_nested(self):
        os.environ[OPT] = "1"
        os.environ["SEGMENTLY_MODULES_WORK_ORDER"] = "/nonexistent"
        self.good_agent()
        for name, argv in self.verbs():
            for js in (False, True):
                self.mode("semantic")
                with self.subTest(verb=name, mode="semantic", json=js):
                    self.assertEqual(self.go(argv, json_out=js),
                                     (2, "", f"segmently-modules: error: {NESTED}\n"))
                self.mode("hybrid")
                with self.subTest(verb=name, mode="hybrid", json=js):
                    code, out, err = self.go(argv, json_out=js)
                    self.assertEqual((code, err), (0, ""))
                    self.assertIn(NESTED_NOTE, out)
                    self.assertEqual(out, self.go(argv, "--match", "hybrid", json_out=js)[1])
        self.assertEqual(self.calls(), [])

    def test_r11_malformed_agent_variables_opted_in_are_refused(self):
        os.environ[OPT] = "1"
        for mode in ("semantic", "hybrid"):
            self.mode(mode)
            os.environ["SEGMENTLY_MODULES_AGENT_COMMAND"] = "not json"
            for name, argv in self.verbs():
                for js in (False, True):
                    with self.subTest(mode=mode, verb=name, json=js):
                        code, out, err = self.go(argv, json_out=js)
                        self.assertEqual((code, out), (2, ""))
                        self.assertTrue(
                            err.startswith("segmently-modules: error: SEGMENTLY_MODULES_AGENT_COMMAND:"), err)

    def test_r12_hybrid_opted_in_with_a_command(self):
        os.environ[OPT] = "1"
        self.mode("hybrid")
        self.good_agent()
        for name, argv in self.verbs():
            for js in (False, True):
                with self.subTest(verb=name, json=js):
                    self.calls_log.unlink(missing_ok=True)
                    flagged = self.go(argv, "--match", "hybrid", json_out=js)
                    self.calls_log.unlink()
                    configured = self.go(argv, json_out=js)
                    self.assertEqual(configured, flagged)
                    self.assertEqual((configured[0], configured[2]), (0, ""))
                    self.assertEqual(len(self.calls()), 1)
                    self.calls_log.unlink()


class NotReadingAgentVariablesTest(Repo):  # P82-AC-016
    def test_malformed_agent_variables_do_not_matter_when_not_opted_in(self):
        self.mode("hybrid")
        text = ("match", "refund a partial refund")
        lex = self.lex(text)
        for var, value in (("SEGMENTLY_MODULES_AGENT_COMMAND", "not json"), ("SEGMENTLY_MODULES_AGENT_COMMAND", "[]"),
                           ("SEGMENTLY_MODULES_AGENT_TIMEOUT", "0"), ("SEGMENTLY_MODULES_AGENT_TIMEOUT", "five")):
            for opted in (False, True):
                with self.subTest(var=var, value=value, opted=opted):
                    self.no_agent()
                    os.environ.pop(OPT, None)
                    os.environ[var] = value
                    if var == "SEGMENTLY_MODULES_AGENT_TIMEOUT":
                        os.environ["SEGMENTLY_MODULES_AGENT_COMMAND"] = json.dumps(["true"])
                    if not opted:
                        self.assertEqual(self.go(text), (0, lex, note("hybrid")))
                    else:
                        os.environ[OPT] = "1"
                        code, out, err = self.go(text)
                        self.assertEqual((code, out), (2, ""))
                        self.assertTrue(err.startswith(f"segmently-modules: error: {var}:"), err)

    def test_an_invalid_opt_in_with_a_lexical_config_changes_nothing(self):
        self.mode("lexical")
        os.environ[OPT] = "garbage"
        os.environ["SEGMENTLY_MODULES_AGENT_COMMAND"] = "not json"
        code, out, err = self.go(("match", TASK))
        self.assertEqual((code, err), (0, ""))
        os.environ.pop(OPT)
        os.environ.pop("SEGMENTLY_MODULES_AGENT_COMMAND")
        self.assertEqual(out, self.lex(("match", TASK)))


class OptInValuesTest(Repo):  # P82-AC-017
    def test_values(self):
        self.mode("semantic")
        self.good_agent()
        for value in (None, "", "0"):
            with self.subTest(value=value):
                os.environ.pop(OPT, None)
                if value is not None:
                    os.environ[OPT] = value
                self.assertEqual(self.go(("match", "x"))[2], note("semantic"))
        os.environ[OPT] = "1"
        self.calls_log.unlink(missing_ok=True)
        code, _, err = self.go(("match", "x"))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(len(self.calls()), 1)

    def test_every_other_value_is_refused_showing_40_characters(self):
        self.mode("semantic")
        self.good_agent()
        cases = ("true", " 1 ", "  ", "00", "1\n", "2", "a" * 41, "b" * 80, "it's")
        for value in cases:
            with self.subTest(value=value):
                os.environ[OPT] = value
                code, out, err = self.go(("match", "x"))
                self.assertEqual((code, out), (2, ""))
                self.assertEqual(err, f"segmently-modules: error: {OPT}: expected 1 or 0, "
                                      f"got {value[:40]!r}\n")
        os.environ[OPT] = "a" * 41
        self.assertIn("got '" + "a" * 40 + "'\n", self.go(("match", "x"))[2])
        os.environ[OPT] = "it's"
        self.assertIn('got "it\'s"\n', self.go(("match", "x"))[2])
        self.assertEqual(self.calls(), [])


class LayersTest(Repo):  # P82-AC-018
    def write_layer(self, layer: str, mode: str) -> None:
        for p in (self.root / ".segmently-modules").glob("config*.toml"):
            p.unlink()
        pack = self.root / ".segmently-modules" / "packs" / "team"
        if pack.exists():
            (pack / "pack.toml").unlink()
        if layer == "pack":
            pack.mkdir(parents=True, exist_ok=True)
            (pack / "pack.toml").write_text(
                f'id = "team"\nversion = "1.0.0"\npriority = 50\n[match]\nmode = "{mode}"\n',
                encoding="utf-8")
        elif layer == "config.user.tracked.toml":  # a personal config the repository tracks
            self.mode(mode, "config.user.toml")
            git(self.root, "add", "-f", ".segmently-modules/config.user.toml")
            git(self.root, "commit", "-q", "-m", "track the personal config")
        else:
            self.mode(mode, layer)

    def test_every_layer_verb_and_form_is_lexical_byte_for_byte(self):
        self.good_agent()
        (self.root / "extra.txt").write_text("x\n", encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "second")
        verbs = self.verbs() + (("discover-diff", ("discover", "--from-diff", "HEAD~1..HEAD",
                                                   "--task-file", str(self.task_file))),)
        for layer in ("config.toml", "config.user.toml", "config.user.tracked.toml", "pack"):
            for mode in ("semantic", "hybrid"):
                self.write_layer(layer, mode)
                for name, argv in verbs:
                    for js in (False, True):
                        with self.subTest(layer=layer, mode=mode, verb=name, json=js):
                            code, out, err = self.go(argv, json_out=js)
                            self.assertEqual((code, err), (0, note(mode)))
                            self.assertEqual(out, self.lex(argv, js))
                            if js:
                                for key in ("mode", "notes", "sources", "confidence", "rrf"):
                                    if name == "match":
                                        self.assertNotIn(f'"{key}"', out)
        self.assertEqual(self.calls(), [])


class OutsideD6Test(Repo):  # P82-AC-019
    def test_flag_choose_run_and_catalog_need_no_opt_in(self):
        self.mode("semantic")
        self.good_agent()
        (self.root / "t.txt").write_text(TASK, encoding="utf-8")
        reference = {}
        for value in (None, "garbage"):
            os.environ.pop(OPT, None)
            if value:
                os.environ[OPT] = value
            for tag, argv in (("sem", ("match", "--match", "semantic", "x")),
                              ("hyb", ("match", "--match", "hybrid", "x")),
                              ("choose", ("choose", "--task-file", str(self.root / "t.txt"),
                                          "--run")),
                              ("catalog", ("catalog", "--json"))):
                with self.subTest(opt=value, verb=tag):
                    self.calls_log.unlink(missing_ok=True)
                    code, out, err = self.go(argv)
                    self.assertEqual((code, err), (0, ""))
                    if tag != "catalog":
                        self.assertEqual(len(self.calls()), 1)
                    else:
                        self.assertEqual(json.loads(out)["data"]["match"],
                                         {"mode": "semantic", "semantic": True})
                    reference.setdefault(tag, out)
                    self.assertEqual(out, reference[tag])


class NotApplicableTest(Repo):  # P82-AC-020
    def test_other_verbs_never_read_the_opt_in(self):
        self.mode("hybrid")
        argvs = (("discover", "--files", "src/orders/service.py"),
                 ("discover", "--from-diff", "HEAD..HEAD"),
                 ("show", "orders"), ("related", "orders"), ("next",), ("list",), ("lint",),
                 ("sync-instructions", "--files", "src/orders/service.py"),
                 ("agents-md", "--check"))
        for argv in argvs:
            with self.subTest(argv=argv):
                os.environ.pop(OPT, None)
                first = self.go(argv)
                os.environ[OPT] = "garbage"
                second = self.go(argv)
                self.assertEqual(first, second)
                self.assertNotIn("note:", first[2])


class DocsTest(unittest.TestCase):  # P82-AC-021
    def text(self, rel):
        return (ENGINE / rel).read_text(encoding="utf-8")

    def test_configuration_doc(self):
        doc = self.text("docs/configuration.md")
        row = next(line for line in doc.splitlines() if line.startswith(f"| `{OPT}`"))
        for needle in ("environment", "`1`", "`0`", "exit 2", "non-lexical", "unset", "empty",
                       '`" 1 "`'):
            self.assertIn(needle, row)
        flat = " ".join(doc.split())
        self.assertNotIn("decide WHETHER the command runs", flat)
        self.assertIn("only with your opt-in", flat)
        self.assertIn("`--match` and `choose --run` are your own requests", flat)
        # final review M-1: what a repository cannot do, and what its sync hooks can
        self.assertNotIn("and it cannot make it run:", flat)
        self.assertIn("A repository cannot choose or change the command, and it cannot make "
                      "`match`, `context` or `discover --task` run it:", flat)
        self.assertIn("A repository can still run commands of its own: a `[[hooks.post_sync]]` "
                      "hook", flat)
        hooks = " ".join(doc.split("## `[[hooks.post_sync]]`", 1)[1].split("\n## ", 1)[0].split())
        self.assertIn("A hook is a command the repository or a pack commits: it runs with your "
                      "environment, the agent variables included — in a repository you do not "
                      "trust, `sync --dry-run` runs none.", hooks)
        mode_row = next(line for line in doc.splitlines() if line.startswith("| `mode` |"))
        self.assertNotIn("a contributor without the variable gets exit 2", mode_row)
        self.assertIn(OPT, mode_row)

    def test_cli_contract(self):
        doc = " ".join(self.text("docs/cli-contract.md").split())
        self.assertIn(note("<mode>").rstrip("\n"), doc)
        self.assertIn(f"segmently-modules: error: {OPT}: expected 1 or 0, got '<value>'", doc)
        self.assertIn("only when the run exits `0`", doc)

    def test_skills_doc_no_longer_promises_exit_2_for_a_plain_call(self):
        doc = " ".join(self.text("docs/skills.md").split())
        self.assertNotIn("then refuses (exit 2)", doc)
        self.assertIn(OPT, doc)

    def test_readme_and_changelog(self):
        readme = " ".join(self.text("README.md").split())
        self.assertNotIn("its `[match] mode` decides whether", readme)
        self.assertIn(OPT, readme)
        unreleased = changelog_release(self.text("CHANGELOG.md"), "0.1.1")
        self.assertIn("MODSYS_AGENT_ALLOW_REPO_MODE", unreleased)  # 0.1.1 named it before the rename
        self.assertIn("checked only when a config file sets a non-lexical mode",
                      " ".join(unreleased.split()))
        self.assertTrue(re.search(r"\[match\] mode", unreleased))
        heads = [ln for ln in unreleased.splitlines() if ln.startswith("### ")]
        self.assertEqual(heads, ["### Added", "### Changed", "### Fixed"])  # Keep a Changelog


if __name__ == "__main__":
    unittest.main()
