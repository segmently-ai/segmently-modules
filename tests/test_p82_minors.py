"""P8.2 task 3 (D7): a closed stdout reader ends the run quietly with the verb's own exit code
(F19), `packs sync` probes each skill copy for the ignored note (F16), `code-map files` `via`
is documented as a list (F20)."""
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tests.agent_helpers import AgentRepo, picks
from tests.helpers import (FIXTURE, SPLIT_FIXTURE, changelog_release, copy_fixture,
                           init_git, make_repo, run, run_json)
from tests.test_p82_repo_mode import note

try:
    import resource
except ImportError:  # no rlimits here
    resource = None

ENGINE = Path(__file__).resolve().parents[1]
LAUNCHER = ENGINE / "tools/launcher.sh"
SCRIPT = "import sys; from segmently_modules.cli import main; sys.exit(main())"  # the console script
DOCS = (ENGINE / "docs/cli-contract.md").read_text(encoding="utf-8")
CHANGELOG = (ENGINE / "CHANGELOG.md").read_text(encoding="utf-8")
BAD = ("Exception ignored", "BrokenPipeError", "Traceback", "internal error")
TIMEOUT = 90


class Spawn(AgentRepo, unittest.TestCase):
    """Runs the CLI as a subprocess with stdout (and stderr) wired by state: `open` (read to
    the end), `B` (a pipe whose read end is closed), `A` (a reader that takes a prefix and
    closes)."""

    def setUp(self):
        super().setUp()
        self.env = {**os.environ, "PYTHONPATH": str(ENGINE), "PYTHONDONTWRITEBYTECODE": "1"}
        self.task = self.tmp / "t.txt"
        self.task.write_text("partial refund for a returned book", encoding="utf-8")
        plugin = self.tmp / "plugin"
        (plugin / "bin").mkdir(parents=True)
        (plugin / "runtime").mkdir()
        os.symlink(ENGINE / "segmently_modules", plugin / "runtime/segmently_modules")
        shutil.copy(LAUNCHER, plugin / "bin/segmently-modules")
        (plugin / "bin/segmently-modules").chmod(0o755)
        self.entries = {"module": [sys.executable, "-m", "segmently_modules"],
                        "script": [sys.executable, "-c", SCRIPT],
                        "launcher": [str(plugin / "bin/segmently-modules")]}

    def spawn(self, argv, state="open", entry="module", err_closed=False, env=None,
              cwd=None, prefix=64):
        """(exit code, stdout bytes read, stderr text)."""
        cmd = [*self.entries[entry], *argv]
        out_r = err_r = None
        if state == "B":
            out_r, out_w = os.pipe()
            os.close(out_r)
            stdout = out_w
        else:
            stdout = subprocess.PIPE
        if err_closed:
            err_r, err_w = os.pipe()
            os.close(err_r)
            stderr = err_w
        else:
            stderr = subprocess.PIPE
        with subprocess.Popen(cmd, stdout=stdout, stderr=stderr, stdin=subprocess.DEVNULL,
                              env=env or self.env, cwd=cwd or str(ENGINE)) as proc:
            if state == "B":
                os.close(out_w)
            if err_closed:
                os.close(err_w)
            got = b""
            try:
                if state == "A":
                    got = proc.stdout.read(prefix)
                    proc.stdout.close()
                    err = proc.stderr.read() if not err_closed else b""
                    proc.wait(timeout=TIMEOUT)
                else:
                    got, err = proc.communicate(timeout=TIMEOUT)
                    got, err = got or b"", err or b""
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
        return proc.returncode, got, err.decode("utf-8", "replace")

    def quiet(self, err):
        for bad in BAD:
            self.assertNotIn(bad, err)


class ClosedReaderTest(Spawn):
    def setUp(self):
        super().setUp()
        self.big = make_repo(self.tmp / "big", {f"module{i:03d}": [f"keyword{i}x{j}" for j in
                                                                     range(12)]
                                                for i in range(500)})
        self.R = ("--root", str(self.big))
        self.warn = copy_fixture(self.tmp / "warn")
        reg = self.warn / "modules" / "registry.json"
        data = json.loads(reg.read_text(encoding="utf-8"))
        data["modules"]["catalog"]["keywords"].append("")  # MS022: a warning
        reg.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def cases(self):
        t, R = str(self.task), self.R
        for form in ((), ("--json",)):
            yield ("catalog", ("catalog", *R, *form))
            yield ("choose", ("choose", "--task-file", t, *R, *form))
            yield ("match", ("match", "keyword7x1", *R, *form))
            yield ("list", ("list", *R, *form))
            yield ("templates", ("templates", "list", *R, *form))
        yield ("lint", ("lint", "--fail-on", "warning", "--root", str(self.warn)))
        yield ("lint-json", ("lint", "--fail-on", "warning", "--root", str(self.warn), "--json"))

    def test_the_closed_reader_ends_with_the_verbs_own_exit(self):  # P82-AC-022
        seen_lint = False
        for name, argv in self.cases():
            open_code, open_out, _ = self.spawn(argv)
            if name == "catalog":
                self.assertGreater(len(open_out), 70_000, "the catalog must overflow a pipe")
            if name.startswith("lint"):
                seen_lint = True
                self.assertEqual(open_code, 1, argv)
            for state in ("B", "A"):
                with self.subTest(argv=argv, state=state):
                    code, got, err = self.spawn(argv, state)
                    self.assertEqual((code, err), (open_code, ""))
                    self.assertTrue(open_out.startswith(got), "the reader got a prefix")
                    if state == "A":
                        self.assertTrue(0 < len(got) <= 64)
        self.assertTrue(seen_lint)

    def test_main_restores_the_streams(self):
        code, out, err = run("list", *self.R)
        self.assertEqual((code, err), (0, ""))
        self.assertIn("module000", out)


@unittest.skipIf(resource is None, "no resource module")
class WriteErrorTest(Spawn):  # I1
    def limited(self, argv):
        def limit():
            signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
            resource.setrlimit(resource.RLIMIT_FSIZE, (200, 200))
        out = self.tmp / "out.txt"
        with open(out, "wb") as f:
            proc = subprocess.run([sys.executable, "-m", "segmently_modules", *argv], stdout=f,
                                  stderr=subprocess.PIPE, env=self.env, cwd=ENGINE,
                                  preexec_fn=limit, timeout=TIMEOUT)
        return proc.returncode, proc.stderr.decode()

    def test_a_full_stdout_is_one_error_line_and_exit_2(self):
        for argv in (("list", "--root", str(FIXTURE)), ("--help",),
                     ("list", "--root", str(FIXTURE), "--json")):
            with self.subTest(argv=argv):
                code, err = self.limited(argv)
                self.assertEqual(code, 2)
                lines = err.splitlines()
                self.assertEqual(len(lines), 1, err)
                self.assertTrue(lines[0].startswith("segmently-modules: error: cannot write stdout: "), err)
                self.quiet(err)


class WriterTest(Spawn):
    def tree(self, root):
        out = {}
        for p in sorted(Path(root).rglob("*")):
            rel = p.relative_to(root)
            if ".git" in rel.parts or not p.is_file():
                continue
            out[str(rel)] = hashlib.sha256(p.read_bytes()).hexdigest()
        return out

    def fresh(self, name):
        root = copy_fixture(self.tmp / name, SPLIT_FIXTURE)
        pack = root / ".segmently-modules/packs/team"
        (pack / "skills/api-review").mkdir(parents=True)
        (pack / "pack.toml").write_text('id = "team"\nversion = "9.0.0"\npriority = 50\n'
                                        '[skills.api-review]\npath = "skills/api-review"\n')
        (pack / "skills/api-review/SKILL.md").write_text(SKILL.format(n="api-review"))
        init_git(root)
        return root

    def writers(self):
        words = [a for k in ("review", "reviews", "rating", "ratings", "moderation", "moderations")
                 for a in ("--keyword", k)]
        return {
            "create": ("create", "reviews", "--description",
                       "Customer reviews of books: ratings, moderation and display.",
                       *words, "--non-interactive"),
            "registry": ("registry", "set", "orders", "status", '"active"'),
            "roles": ("roles", "add", "qa", "--all"),
            "packs": ("packs", "sync", "--agent", "codex"),
            "templates": ("templates", "override", "choose/rules.md"),
        }

    def test_a_writer_still_writes(self):  # P82-AC-023
        for name, argv in self.writers().items():
            with self.subTest(writer=name):
                a, b = self.fresh(f"open-{name}"), self.fresh(f"closed-{name}")
                full = lambda root: (*argv, "--root", str(root))
                code_a, _, err_a = self.spawn(full(a))
                code_b, _, err_b = self.spawn(full(b), "B")
                self.assertEqual((code_a, err_a), (0, ""), err_a)
                self.assertEqual((code_b, err_b), (0, ""))
                self.assertEqual(self.tree(a), self.tree(b))
                self.assertNotEqual(self.tree(a), self.tree(self.fresh(f"untouched-{name}")))
                self.assertEqual(self.spawn(("registry", "set", "orders", "status",
                                             '"active"', "--root", str(b)))[0], 0)  # lock free

    def test_an_agent_run_cleans_up(self):  # P82-AC-023
        scratch = self.tmp / "scratch"
        scratch.mkdir()
        grand = self.tmp / "grand"
        os.environ["SEGMENTLY_MODULES_AGENT_COMMAND"] = json.dumps(self.behaviour(
            answer=picks(("orders/refunds", 0.9)), grandchild=str(grand)))
        env = {**os.environ, "PYTHONPATH": str(ENGINE), "TMPDIR": str(scratch)}
        argv = ("choose", "--task-file", str(self.task), "--run", *self.R)
        code, _, err = self.spawn(argv, "B", env=env)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(list(scratch.iterdir()), [])
        pid = int(grand.read_text())
        for _ in range(100):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            self.fail("the agent's process group is alive")


class RefusalAndEntryPointTest(Spawn):
    SEAM = ("import sys\nfrom segmently_modules import catalog_cmd\nfrom segmently_modules.cli import main\n"
            "from segmently_modules.output import UsageError\n"
            "def go(args):\n    print('partial ' * 20000)\n    raise UsageError('boom')\n"
            "catalog_cmd.run = go\nsys.exit(main(['catalog']))\n")

    def test_a_refusal_keeps_exit_2_and_its_line(self):  # P82-AC-024 (a) (e)
        for entry in self.entries:
            for state in ("B", "A"):
                with self.subTest(entry=entry, state=state):
                    code, out, err = self.spawn(("choose", "--top", "0", "--task", "x",
                                                 *self.R), state, entry)
                    self.assertEqual(code, 2)
                    self.assertEqual(out, b"")
                    self.assertEqual(len(err.splitlines()), 1, err)
                    self.assertTrue(err.startswith("segmently-modules: error: "), err)
                    self.quiet(err)

    def test_a_refusal_after_partial_output(self):  # P82-AC-024 (b) (c), through a seam
        self.entries["seam"] = [sys.executable, "-c", self.SEAM]
        code, _, err = self.spawn((), "B", "seam")
        self.assertEqual((code, err), (2, "segmently-modules: error: boom\n"))
        code, out, err = self.spawn((), "open", "seam")
        self.assertEqual((code, err), (2, "segmently-modules: error: boom\n"))
        self.assertGreater(len(out), 100_000)  # the partial output is there without a closed reader
        code, _, _ = self.spawn((), "B", "seam", err_closed=True)
        self.assertEqual(code, 2)

    def test_with_stderr_closed_too_the_exit_is_the_verbs_own(self):  # P82-AC-024 (c)
        for argv, want in ((("choose", "--top", "0", "--task", "x", *self.R), 2),
                           (("list", *self.R), 0)):
            for entry in self.entries:
                with self.subTest(argv=argv[0], entry=entry):
                    code, _, _ = self.spawn(argv, "B", entry, err_closed=True)
                    self.assertEqual(code, want)

    def test_help_and_version_exit_0_silently(self):  # P82-AC-024 (d) (e)
        for entry in self.entries:
            for argv in (("--help",), ("choose", "--help"), ("--version",)):
                for state, err_closed in (("B", False), ("A", False), ("B", True)):
                    with self.subTest(entry=entry, argv=argv, state=state, err=err_closed):
                        code, _, err = self.spawn(argv, state, entry, err_closed=err_closed)
                        self.assertEqual(code, 0)
                        self.assertEqual(err, "")

    def test_sigint_during_an_agent_call_is_still_130(self):  # P82-AC-024 (f)
        started = self.tmp / "started"
        os.environ["SEGMENTLY_MODULES_AGENT_COMMAND"] = json.dumps(self.behaviour(
            sleep=60, started=str(started), answer="{}"))
        env = {**os.environ, "PYTHONPATH": str(ENGINE)}
        out_r, out_w = os.pipe()
        os.close(out_r)
        proc = subprocess.Popen(
            [sys.executable, "-m", "segmently_modules", "choose", "--task", "x", "--run", *self.R],
            env=env, stdout=out_w, stderr=subprocess.PIPE, cwd=ENGINE,
            preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))
        os.close(out_w)
        self.addCleanup(proc.__exit__, None, None, None)
        try:
            for _ in range(400):
                if started.exists():
                    break
                time.sleep(0.05)
            self.assertTrue(started.exists())
            proc.send_signal(signal.SIGINT)
            err = proc.communicate(timeout=30)[1].decode()
        finally:
            if proc.poll() is None:
                proc.kill()
        self.assertEqual(proc.returncode, 130)
        self.assertIn("segmently-modules: interrupted", err)
        self.quiet(err)

    def test_a_note_run_with_a_closed_stdout_prints_the_note_once(self):  # D6 + D7
        (self.root / ".segmently-modules").mkdir(exist_ok=True)
        (self.root / ".segmently-modules/config.toml").write_text('[match]\nmode = "semantic"\n',
                                                       encoding="utf-8")
        argv = ("match", "partial refund", *self.R)
        code, _, err = self.spawn(argv, "B")
        want = self.spawn(argv)
        self.assertEqual(code, 0)
        self.assertEqual(err.count("segmently-modules: note: "), 1, err)
        self.assertEqual(err, want[2])
        self.quiet(err)


class DeferredNoteStreamsTest(Spawn):  # final review I-1: the D6 note under every stdout state
    """A run with a config `[match] mode` and no opt-in (D6 R3/R4: lexical + one note) whose
    stdout is CLOSED at start (`>&-`: fd 1 is not open, Python's `sys.stdout` is None) or fails
    with a real write error (a file size limit). The note comes only with exit 0."""
    LIMIT = 60  # bytes a file may grow to; every output below is larger

    def setUp(self):
        super().setUp()
        self.verbs = (("match", "partial refund for a returned book"),
                      ("context", "--task-file", str(self.task)),
                      ("discover", "--task-file", str(self.task)))

    def mode(self, mode):
        self.config(f'[match]\nmode = "{mode}"\n')

    def cases(self):
        for mode in ("hybrid", "semantic"):
            self.mode(mode)
            for argv in self.verbs:
                for form in ((), ("--json",)):
                    yield mode, (*argv, *self.R, *form)

    def shell(self, redirect, argv, preexec_fn=None, stdout=subprocess.PIPE):
        """(exit code, stdout bytes, stderr text) of segmently-modules run through `/bin/sh` with
        `redirect` applied."""
        cmd = ["/bin/sh", "-c", f'exec "$@" {redirect}', "sh", *self.entries["module"], *argv]
        proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=stdout,
                              stderr=subprocess.PIPE, env=self.env, cwd=ENGINE,
                              preexec_fn=preexec_fn, timeout=TIMEOUT)
        return proc.returncode, proc.stdout or b"", proc.stderr.decode("utf-8", "replace")

    def test_a_stdout_closed_at_start_is_exit_0_with_the_note(self):  # I-1 (a)
        for mode, argv in self.cases():
            with self.subTest(mode=mode, argv=argv[0], json="--json" in argv):
                lex = self.spawn((*argv, "--match", "lexical"))
                self.assertEqual(lex[::2], (0, ""))
                self.assertEqual(self.spawn(argv), (0, lex[1], note(mode)))  # the open run
                self.assertEqual(self.shell(">&-", argv), (0, b"", note(mode)))
                self.assertEqual(self.shell(">&-", (*argv, "--match", "lexical")), (0, b"", ""))
                # stderr closed at start instead: the note never falls back to stdout
                self.assertEqual(self.shell("2>&-", argv), (0, lex[1], ""))

    @unittest.skipIf(resource is None, "no resource module")
    def test_a_stdout_write_error_is_one_error_line_without_the_note(self):  # I-1 (b) (c)
        def limit():
            signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
            resource.setrlimit(resource.RLIMIT_FSIZE, (self.LIMIT, self.LIMIT))
        out = self.tmp / "out.txt"
        for mode, argv in self.cases():
            with self.subTest(mode=mode, argv=argv[0], json="--json" in argv):
                self.assertGreater(len(self.spawn(argv)[1]), self.LIMIT)
                for redirect in ("", "2>&-"):  # stderr open, then stderr closed too
                    with open(out, "wb") as f:
                        code, _, err = self.shell(redirect, argv, limit, f)
                    self.assertEqual(out.stat().st_size, self.LIMIT)
                    self.assertEqual(code, 2, (redirect, err))
                    if redirect:
                        continue
                    lines = err.splitlines()
                    self.assertEqual(len(lines), 1, err)
                    self.assertTrue(lines[0].startswith("segmently-modules: error: cannot write stdout: "),
                                    err)
                    self.assertNotIn("note", err)
                    self.quiet(err)


SKILL ="---\nname: {n}\ndescription: Skill {n}.\n---\n\n# {n}\n"
NOTE = ("git ignores {k} of the {m} skill copies in {d} ({names}) — they are written but will "
        "not be committed; take them out of .gitignore to share them with the team")
ALLOW = ".agents/skills/*\n!.agents/skills/module-*/\n"


class IgnoredCopiesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = copy_fixture(self._tmp.name)
        self.R = ("--root", str(self.root))
        self.skills: list[str] = []

    def fresh_root(self):
        self.root = copy_fixture(tempfile.mkdtemp(dir=self._tmp.name))
        self.R = ("--root", str(self.root))

    def pack(self, *names):
        d = self.root / ".segmently-modules/packs/team"
        shutil.rmtree(d, ignore_errors=True)
        text = 'id = "team"\nversion = "9.0.0"\npriority = 50\n'
        for n in names:
            (d / "skills" / n).mkdir(parents=True, exist_ok=True)
            (d / "skills" / n / "SKILL.md").write_text(SKILL.format(n=n), encoding="utf-8")
            text += f'[skills.{n}]\npath = "skills/{n}"\n'
        (d / "pack.toml").write_text(text, encoding="utf-8")

    def sync(self, *extra, json_out=True, git=True):
        if git and not (self.root / ".git").exists():
            init_git(self.root)
        if json_out:
            code, env, err = run_json("packs", "sync", *extra, *self.R)
            self.assertEqual(err, "")
            return code, env["data"]["notes"], env
        code, out, err = run("packs", "sync", *extra, *self.R)
        self.assertEqual(err, "")
        return code, [ln[len("note: "):] for ln in out.splitlines() if ln.startswith("note: ")], out

    def ignored_notes(self, notes):
        return [n for n in notes if n.startswith("git ignores")]

    def test_the_decision_table(self):  # P82-AC-025
        cases = [
            ("none", "", ("api-review",), (), None),
            ("dir", ".agents/\n", ("api-review",), (),
             NOTE.format(k=1, m=1, d=".agents/skills", names="api-review")),
            ("allow", ALLOW, ("module-a", "module-b", "api-review"), (),
             NOTE.format(k=1, m=3, d=".agents/skills", names="api-review")),
            ("allow-only-module", ALLOW, ("module-a", "module-b"), (), None),
        ]
        for name, gitignore, skills, extra, want in cases:
            for json_out in (True, False):
                with self.subTest(case=name, json=json_out):
                    self.fresh_root()
                    self.pack(*skills)
                    (self.root / ".gitignore").write_text(gitignore, encoding="utf-8")
                    code, notes, _ = self.sync("--agent", "codex", json_out=json_out)
                    self.assertEqual(code, 0)
                    self.assertEqual(self.ignored_notes(notes), [want] if want else [])
                    for s in skills:
                        self.assertTrue((self.root / f".agents/skills/{s}/SKILL.md").exists())

    def test_unchanged_copies_count(self):  # P82-AC-025
        self.pack("module-a", "module-b", "api-review")
        (self.root / ".gitignore").write_text(".agents/\n", encoding="utf-8")
        want = NOTE.format(k=3, m=3, d=".agents/skills", names="api-review, module-a, module-b")
        for _ in range(2):  # the second run: every row is unchanged
            _, notes, env = self.sync("--agent", "codex")
            self.assertEqual(self.ignored_notes(notes), [want])
        self.assertEqual({r["status"] for r in env["data"]["skills"]}, {"unchanged"})

    def test_each_directory_has_its_own_note(self):  # P82-AC-025
        self.pack("api-review")
        (self.root / ".gitignore").write_text(".claude/skills/\n", encoding="utf-8")
        _, notes, _ = self.sync("--agent", "claude", "--agent", "codex")
        self.assertEqual(self.ignored_notes(notes),
                         [NOTE.format(k=1, m=1, d=".claude/skills", names="api-review")])

    def test_a_shared_directory_counts_once(self):  # P82-AC-025
        self.pack("module-a", "module-b", "api-review")
        (self.root / ".gitignore").write_text(".agents/\n", encoding="utf-8")
        _, notes, env = self.sync("--agent", "codex", "--agent", "cursor")
        self.assertEqual(len(env["data"]["skills"]), 6)
        self.assertEqual(self.ignored_notes(notes), [NOTE.format(
            k=3, m=3, d=".agents/skills", names="api-review, module-a, module-b")])

    def test_no_note_outside_git_or_for_remove(self):  # P82-AC-025
        self.pack("api-review")
        (self.root / ".gitignore").write_text(".agents/\n", encoding="utf-8")
        _, notes, _ = self.sync("--agent", "codex", git=False)
        self.assertEqual(self.ignored_notes(notes), [])
        init_git(self.root)
        self.assertEqual(len(self.ignored_notes(self.sync("--agent", "codex")[1])), 1)
        code, notes, env = self.sync("--agent", "codex", "--remove")
        self.assertEqual((code, self.ignored_notes(notes)), (0, []))
        self.assertEqual({r["status"] for r in env["data"]["skills"]}, {"removed"})

    def test_removed_conflict_and_invalid_rows_do_not_count(self):  # P82-AC-025
        self.pack("api-review", "module-a")
        (self.root / ".gitignore").write_text(".agents/\n", encoding="utf-8")
        conflict = self.root / ".agents/skills/api-review"
        conflict.mkdir(parents=True)
        (conflict / "SKILL.md").write_text("mine\n", encoding="utf-8")  # no marker: conflict
        code, notes, env = self.sync("--agent", "codex")
        self.assertEqual(code, 1)
        self.assertEqual({r["skill"]: r["status"] for r in env["data"]["skills"]},
                         {"api-review": "conflict", "module-a": "created"})
        self.assertEqual(self.ignored_notes(notes), [NOTE.format(
            k=1, m=1, d=".agents/skills", names="module-a")])

    def test_removed_and_invalid_rows_do_not_count_either(self):  # P82-AC-025 (I3)
        self.pack("api-review", "module-a", "module-b")
        (self.root / ".gitignore").write_text(".agents/\n", encoding="utf-8")
        self.assertEqual(self.sync("--agent", "codex")[0], 0)
        self.pack("api-review", "module-a")  # module-b leaves the pack: its copy is `removed`
        (self.root / ".segmently-modules/packs/team/skills/api-review/SKILL.md").write_text(
            "no front matter\n", encoding="utf-8")  # an unloadable source: `invalid`
        code, notes, env = self.sync("--agent", "codex")
        self.assertEqual(code, 1)
        self.assertEqual({r["skill"]: r["status"] for r in env["data"]["skills"]},
                         {"api-review": "invalid", "module-a": "unchanged",
                          "module-b": "removed"})
        self.assertEqual(self.ignored_notes(notes), [NOTE.format(
            k=1, m=1, d=".agents/skills", names="module-a")])

    def test_one_git_process_per_skills_directory(self):  # I2
        from unittest import mock
        from segmently_modules import packs_cmd
        self.pack("module-a", "module-b", "api-review", "zeta")
        (self.root / ".gitignore").write_text(ALLOW, encoding="utf-8")
        init_git(self.root)
        calls = []
        real = subprocess.run
        def spy(cmd, *a, **k):
            if "check-ignore" in cmd:
                calls.append(cmd)
            return real(cmd, *a, **k)
        with mock.patch.object(packs_cmd.subprocess, "run", spy):
            _, notes, _ = self.sync("--agent", "claude", "--agent", "codex")
        self.assertEqual(len(calls), 2)  # .claude/skills and .agents/skills
        self.assertEqual(self.ignored_notes(notes), [NOTE.format(
            k=2, m=4, d=".agents/skills", names="api-review, zeta")])

    def test_the_old_sentence_is_gone(self):  # P82-AC-025
        self.assertNotIn("the synced skills are written there", (ENGINE / "segmently_modules/packs_cmd.py")
                         .read_text(encoding="utf-8"))
        self.assertNotIn("the synced skills are written there", DOCS)

    def test_the_note_is_true_before_the_copies_exist(self):  # P82-AC-026
        self.pack("module-a", "module-b")
        (self.root / ".gitignore").write_text(ALLOW, encoding="utf-8")
        init_git(self.root)
        for flags in (("--dry-run",), ("--check",), (), ("--dry-run",)):
            with self.subTest(flags=flags):
                _, notes, _ = self.sync("--agent", "codex", *flags)
                self.assertEqual(self.ignored_notes(notes), [])

    def test_dry_run_and_check_name_the_would_be_copies(self):  # P82-AC-026
        self.pack("module-a", "api-review")
        (self.root / ".gitignore").write_text(".agents/\n", encoding="utf-8")
        init_git(self.root)
        want = NOTE.format(k=2, m=2, d=".agents/skills", names="api-review, module-a")
        for flags in (("--dry-run",), ("--check",)):
            with self.subTest(flags=flags):
                _, notes, _ = self.sync("--agent", "codex", *flags)
                self.assertEqual(self.ignored_notes(notes), [want])
        self.assertFalse((self.root / ".agents").exists())


class DocsTest(unittest.TestCase):
    def row(self, start):
        return next(ln for ln in DOCS.splitlines() if ln.startswith(start))

    def test_code_map_via_is_a_list(self):  # P82-AC-027
        row = self.row("| `code-map list")
        self.assertIn("`via` is a list of sources", row)
        self.assertIn('`["docs"]`', row)
        self.assertIn('`["code_map:web", "docs"]`', row)

    def test_code_map_files_via_items(self):  # P82-AC-027
        root = copy_fixture(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root.parent, True)
        init_git(root)
        code, env, err = run_json("code-map", "files", "catalog", "--root", str(root))
        self.assertEqual((code, err), (0, ""))
        for f in env["data"]["files"]:
            self.assertIsInstance(f["via"], list)
            for item in f["via"]:
                self.assertTrue(item == "docs" or item.startswith(("code_pointer:", "code_map:")),
                                item)

    def test_closed_reader_in_the_headless_rules(self):  # P82-AC-028
        head = DOCS.split("- **A closed stdout reader**", 1)[1].split("\n- **", 1)[0]
        head = " ".join(head.split())
        self.assertIn("the rest of the output is dropped silently — no extra stderr line", head)
        self.assertNotIn("a closed stdout reader ends the output", head)  # final review M-4
        self.assertIn("the verb's own exit code", head)

    def test_packs_sync_cell_quotes_the_note(self):  # P82-AC-028
        cell = self.row("| `packs new")
        self.assertIn("git ignores <n> of the <m> skill copies in <dir> (<skill>, …) — they are "
                      "written but will not be committed; take them out of .gitignore to share "
                      "them with the team", cell)

    def test_changelog_names_both_fixes(self):  # P82-AC-028
        fixed = changelog_release(CHANGELOG, "0.1.1").split("### Fixed", 1)[1]
        self.assertIn("closed stdout reader", fixed)
        self.assertIn("skill copies", fixed)


if __name__ == "__main__":
    unittest.main()
