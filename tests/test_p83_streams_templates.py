"""P8.3 task 5: no line meant for stderr reaches stdout when fd 2 is closed at start, and the
sink is fd 2 itself (P83-AC-031, 032); template resolution refuses a candidate that exists but
cannot be read (P83-AC-033); the README and docs (P83-AC-034). Every stream and resolution
check runs a real subprocess."""
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path

from segmently_modules.agent import validate_command
from tests.agent_helpers import AgentRepo
from tests.helpers import changelog_since_first_release, copy_fixture, make_repo
from tests.test_p82_minors import ENGINE, LAUNCHER, SCRIPT, Spawn

TIMEOUT = 90
README = (ENGINE / "README.md").read_text(encoding="utf-8")
DOCS = (ENGINE / "docs/cli-contract.md").read_text(encoding="utf-8")
CHANGELOG = (ENGINE / "CHANGELOG.md").read_text(encoding="utf-8")
CODEX = ('export SEGMENTLY_MODULES_AGENT_COMMAND=\'["sh", "-c", "codex exec -m {codex_model} -c '
         'model_reasoning_effort={reasoning} --sandbox read-only --output-schema '
         '\\"$SEGMENTLY_MODULES_SCHEMA\\" -"]\'')
PYTHONS = [p for p in (shutil.which("python3"), "/usr/local/bin/python3.11")
           if p and os.path.exists(p)]

# a seam: patch one verb, then run the CLI as the console script does
DRIVER = r"""
import json, os, stat, subprocess, sys
from unittest import mock
import segmently_modules.cli as cli
mode, report = sys.argv[1], sys.argv[2]
def boom(args):
    raise RuntimeError("boom")
def probe(args):
    null = os.stat(os.devnull)
    st = os.fstat(2)
    fh = open(report + ".probe", "w")          # a file the run opens: never fd 2
    # a child that inherits stderr: it opens a file first (a closed fd 2 would become that file)
    child = subprocess.run([sys.executable, "-c", "import os, sys; f = open(sys.argv[1], 'w'); "
                            "os.write(2, b'CHILD-TEXT'); f.close()", report + ".child"],
                           stdout=subprocess.DEVNULL, check=False)
    json.dump({"fd2_is_null": stat.S_ISCHR(st.st_mode) and st.st_rdev == null.st_rdev,
               "ino": [st.st_dev, st.st_ino], "opened_fd": fh.fileno(),
               "child": child.returncode}, open(report, "w"))
    fh.close()
    return 0
target = {"boom": boom, "probe": probe}[mode]
with mock.patch("segmently_modules.catalog_cmd.run", target):
    sys.exit(cli.main(["catalog"]))
"""


def tree(root):
    out = {}
    for p in sorted(Path(root).rglob("*")):
        if ".git" not in p.relative_to(root).parts and p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


class ClosedStderrTest(Spawn):
    def shell(self, redirect, argv, entry="module", env=None):
        cmd = ["/bin/sh", "-c", f'exec "$@" {redirect}', "sh", *self.entries[entry], *argv]
        proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, env=env or self.env, cwd=str(ENGINE),
                              timeout=TIMEOUT)
        return proc.returncode, proc.stdout, proc.stderr.decode("utf-8", "replace")

    def matrix(self):
        (self.root / ".segmently-modules").mkdir(exist_ok=True)
        (self.root / ".segmently-modules/config.toml").write_text('[match]\nmode = "semantic"\n',
                                                       encoding="utf-8")
        R = self.R
        return [("refusal", ("choose", "--top", "0", "--task", "x", *R), 2),
                ("unknown verb", ("nosuchverb",), 2),
                ("help", ("--help",), 0), ("version", ("--version",), 0),
                ("catalog", ("catalog", "--json", *R), 0),
                ("note run", ("match", "partial refund", *R), 0),
                ("registry set", ("registry", "set", "orders", "status", '"active"', *R), 0)]

    def test_a_closed_stderr_leaves_stdout_clean_for_every_entry(self):  # P83-AC-031
        for entry in self.entries:
            for name, argv, want in self.matrix():
                open_code, open_out, open_err = self.shell("", argv, entry)
                self.assertEqual(open_code, want, (name, entry))
                if name == "note run":
                    self.assertIn("segmently-modules: note:", open_err)
                for redirect in ("2>&-", "1>&- 2>&-"):
                    with self.subTest(case=name, entry=entry, redirect=redirect):
                        code, out, err = self.shell(redirect, argv, entry)
                        self.assertEqual(code, want)
                        if redirect == "1>&- 2>&-":
                            self.assertEqual(out, b"")
                        elif want == 2:
                            self.assertEqual(out, b"")
                        else:
                            self.assertEqual(out, open_out)

    def test_an_internal_error_leaves_stdout_empty(self):  # P83-AC-031
        for redirect in ("", "2>&-", "1>&- 2>&-"):
            cmd = ["/bin/sh", "-c", f'exec "$@" {redirect}', "sh", sys.executable, "-c", DRIVER,
                   "boom", str(self.tmp / "r.json")]
            proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, env=self.env, cwd=str(ENGINE),
                                  timeout=TIMEOUT)
            with self.subTest(redirect=redirect):
                self.assertEqual(proc.returncode, 2)
                self.assertEqual(proc.stdout, b"")
                if not redirect:
                    self.assertIn("segmently-modules: internal error: RuntimeError: boom",
                                  proc.stderr.decode())
                else:
                    self.assertEqual(proc.stderr, b"")
                self.assertNotIn("Traceback", proc.stderr.decode())

    def test_a_sigint_during_an_agent_call_is_130_with_empty_stdout(self):  # P83-AC-031
        started = self.tmp / "started"
        os.environ["SEGMENTLY_MODULES_AGENT_COMMAND"] = json.dumps(self.behaviour(
            sleep=60, started=str(started), answer="{}"))
        env = {**os.environ, "PYTHONPATH": str(ENGINE)}

        def child():
            os.close(2)
            signal.signal(signal.SIGINT, signal.SIG_DFL)
        proc = subprocess.Popen([sys.executable, "-m", "segmently_modules", "choose", "--task", "x",
                                 "--run", *self.R], env=env, stdout=subprocess.PIPE,
                                cwd=str(ENGINE), preexec_fn=child)
        self.addCleanup(proc.__exit__, None, None, None)
        try:
            for _ in range(400):
                if started.exists():
                    break
                time.sleep(0.05)
            self.assertTrue(started.exists())
            proc.send_signal(signal.SIGINT)
            out = proc.communicate(timeout=30)[0]
        finally:
            if proc.poll() is None:
                proc.kill()
        self.assertEqual((proc.returncode, out), (130, b""))

    def probe(self, redirect, report):
        cmd = ["/bin/sh", "-c", f'exec "$@" {redirect}', "sh", sys.executable, "-c", DRIVER,
               "probe", str(report)]
        return subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, env=self.env, cwd=str(ENGINE),
                              timeout=TIMEOUT)

    def test_the_sink_is_fd_2_itself(self):  # P83-AC-032
        # the child inherits the null device on fd 2 (final review I-2): it exits 0 and its own
        # file stays empty, also when the null device landed on fd 2 without a dup2
        for redirect in ("2>&-", "0<&- 2>&-", "1>&- 2>&-"):
            with self.subTest(redirect=redirect):
                report = self.tmp / "r.json"
                proc = self.probe(redirect, report)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                got = json.loads(report.read_text(encoding="utf-8"))
                self.assertTrue(got["fd2_is_null"])
                self.assertNotEqual(got["opened_fd"], 2)
                self.assertEqual(got["child"], 0)
                child = Path(str(report) + ".child")
                self.assertEqual(child.read_bytes(), b"")  # CHILD-TEXT went to the null device
                self.assertEqual((proc.stdout, proc.stderr), (b"", b""))  # CHILD-TEXT nowhere
                for path in (report, Path(str(report) + ".probe"), child):
                    path.unlink()

    def test_an_open_fd_2_is_untouched(self):  # P83-AC-032
        report, errfile = self.tmp / "r.json", self.tmp / "err.txt"
        with open(errfile, "wb") as f:
            proc = subprocess.run([sys.executable, "-c", DRIVER, "probe", str(report)],
                                  stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=f,
                                  env=self.env, cwd=str(ENGINE), timeout=TIMEOUT)
        got = json.loads(report.read_text(encoding="utf-8"))
        st = errfile.stat()
        self.assertEqual(got["ino"], [st.st_dev, st.st_ino])
        self.assertFalse(got["fd2_is_null"])
        self.assertEqual(errfile.read_bytes(), b"CHILD-TEXT")
        self.assertEqual((got["child"], Path(str(report) + ".child").read_bytes()), (0, b""))
        self.assertEqual(proc.stdout, b"")

    def test_writers_write_the_same_bytes_with_fd_2_closed(self):  # P83-AC-032
        words = [a for k in ("review", "reviews", "rating", "ratings", "moderation",
                             "moderations") for a in ("--keyword", k)]
        for name, argv in {
                "create": ("create", "reviews", "--description",
                           "Customer reviews of books: ratings, moderation and display.",
                           *words, "--non-interactive"),
                "registry": ("registry", "set", "catalog", "status", '"active"')}.items():
            with self.subTest(writer=name):
                a = copy_fixture(self.tmp / f"a-{name}")
                b = copy_fixture(self.tmp / f"b-{name}")
                self.assertEqual(self.shell("", (*argv, "--root", str(a)))[0], 0)
                code, out, err = self.shell("2>&-", (*argv, "--root", str(b)))
                self.assertEqual((code, err), (0, ""))
                self.assertEqual(tree(a), tree(b))


class ResolutionTest(unittest.TestCase):
    """Every candidate state, run on each Python the engine supports that is installed."""
    SHOWN = ".segmently-modules/overrides/templates/choose/rules.md"

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.n = 0
        self.env = {**os.environ, "PYTHONPATH": str(ENGINE), "PYTHONDONTWRITEBYTECODE": "1"}

    def fresh(self):
        """A new fixture copy: (root, overrides dir)."""
        self.n += 1
        root = copy_fixture(self.tmp / f"c{self.n}")
        return root, root / ".segmently-modules/overrides/templates"

    def cli(self, py, root, *argv, extra=()):
        proc = subprocess.run([py, "-m", "segmently_modules", *argv, "--root", str(root), *extra],
                              stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              env=self.env, cwd=str(ENGINE), timeout=30)
        return proc.returncode, proc.stdout, proc.stderr

    def make(self, over, kind, rel="choose/rules.md"):
        """Put a candidate of this kind at `over/rel`; the caller's cleanup restores modes."""
        path = over / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        real = self.tmp / "real.md"
        real.write_text("- A rule.\n", encoding="utf-8")
        if kind == "dir":
            path.mkdir()
        elif kind == "dangling":
            os.symlink(self.tmp / "nowhere", path)
        elif kind == "loop":
            os.symlink(path, path)
        elif kind == "fifo":
            os.mkfifo(path)
        elif kind == "mode000":
            shutil.copy(real, path)
            path.chmod(0)
            self.addCleanup(path.chmod, 0o644)
        elif kind == "dir000":
            shutil.copy(real, path)
            path.parent.chmod(0)
            self.addCleanup(path.parent.chmod, 0o755)
        elif kind == "file":
            shutil.copy(real, path)
        elif kind == "symlink":
            os.symlink(real, path)
        return path

    def test_what_exists_but_cannot_be_read_is_refused(self):  # P83-AC-033
        kinds = ["dir", "dangling", "loop", "fifo"]
        if os.geteuid() != 0:
            kinds += ["mode000", "dir000"]
        for py in PYTHONS:
            for kind in kinds:
                with self.subTest(python=py, kind=kind):
                    root, over = self.fresh()
                    self.make(over, kind)
                    code, out, err = self.cli(py, root, "templates", "list")
                    self.assertEqual(code, 2, err)
                    self.assertEqual(out, "")
                    lines = err.splitlines()
                    self.assertEqual(len(lines), 1, err)
                    self.assertTrue(
                        lines[0].startswith(f"segmently-modules: error: cannot read {self.SHOWN}: "), err)

    def test_a_missing_candidate_falls_through(self):  # P83-AC-033
        for py in PYTHONS:
            for state in ("missing", "enotdir"):
                with self.subTest(python=py, state=state):
                    root, over = self.fresh()
                    if state == "enotdir":  # the override's parent directory is a file
                        (root / ".segmently-modules").mkdir(exist_ok=True)
                        (root / ".segmently-modules/overrides").write_text("a file", encoding="utf-8")
                    code, out, err = self.cli(py, root, "templates", "list", extra=("--json",))
                    self.assertEqual((code, err), (0, ""))
                    self.assertEqual({r["source"] for r in json.loads(out)["data"]
                                      if r["template"] == "choose/rules.md"}, {"engine"})

    def test_a_symlink_to_a_regular_file_is_used(self):  # P83-AC-033
        for py in PYTHONS:
            root, over = self.fresh()
            self.make(over, "symlink")
            code, out, err = self.cli(py, root, "templates", "list", extra=("--json",))
            self.assertEqual((code, err), (0, ""))
            rows = {r["template"]: r["source"] for r in json.loads(out)["data"]}
            self.assertEqual(rows["choose/rules.md"], "override")

    def broken_pack(self, root):
        """A repository pack `books` whose `templates/choose/rules.md` is a directory."""
        base = root / ".segmently-modules/packs/books"
        (base / "templates/choose/rules.md").mkdir(parents=True)
        (base / "pack.toml").write_text('id = "books"\nversion = "0.1.0"\n', encoding="utf-8")
        return base

    def test_the_layers_below_the_winner_are_never_examined(self):  # P83-AC-033
        # the winner is an override; the pack layer below it holds a directory at the same path
        for py in PYTHONS:
            root, over = self.fresh()
            self.make(over, "file")
            pack = self.broken_pack(root)
            code, out, err = self.cli(py, root, "templates", "list", extra=("--json",))
            self.assertEqual((code, err), (0, ""), out)
            rows = {r["template"]: r["source"] for r in json.loads(out)["data"]}
            self.assertEqual(rows["choose/rules.md"], "override")

    def test_a_broken_pack_candidate_below_a_missing_override_is_refused(self):  # P83-AC-033
        for py in PYTHONS:
            root, over = self.fresh()
            pack = self.broken_pack(root)
            code, out, err = self.cli(py, root, "templates", "list")
            self.assertEqual((code, out), (2, ""), err)
            self.assertIn("segmently-modules: error: cannot read .segmently-modules/packs/books/templates/choose/rules.md: ",
                          err)

    def test_every_template_and_verb_refuses_alike(self):  # P83-AC-033
        words = [a for k in ("review", "reviews", "rating", "ratings", "mod", "mods")
                 for a in ("--keyword", k)]
        specs = [("MODULE.md", ("create", "reviews", "--description",
                                "Customer reviews of books: ratings, moderation and display.",
                                *words, "--non-interactive")),
                 ("agents-md.md", ("agents-md", "--target", "CLAUDE.md")),
                 ("choose/rules.md", ("choose", "--task", "x")),
                 ("choose/rules.md", ("templates", "override", "choose/rules.md")),
                 ("roles/qa.md", ("roles", "add", "qa", "--all"))]
        for py, kind in [(p, k) for p in PYTHONS for k in ("dangling", "dir", "fifo")]:
            for template, argv in specs:
                with self.subTest(python=py, kind=kind, template=template, verb=argv[0]):
                    root, over = self.fresh()
                    self.make(over, kind, template)
                    base = tree(root)
                    code, out, err = self.cli(py, root, *argv)
                    self.assertEqual(code, 2, err)
                    self.assertEqual(out, "")
                    self.assertTrue(err.startswith(
                        f"segmently-modules: error: cannot read .segmently-modules/overrides/templates/{template}: "),
                        err)
                    self.assertEqual(tree(root), base)  # nothing written
                    self.assertEqual(list(root.rglob("*.lock")), [])  # the lock is released

    def test_a_template_that_is_not_utf8_is_a_refusal(self):  # final review M-3
        words = [a for k in ("review", "reviews", "rating", "ratings", "mod", "mods")
                 for a in ("--keyword", k)]
        specs = [("MODULE.md", ("create", "reviews", "--description",
                                "Customer reviews of books: ratings, moderation and display.",
                                *words, "--non-interactive", "--dry-run")),
                 ("agents-md.md", ("agents-md", "--target", "CLAUDE.md", "--dry-run"))]
        for py in PYTHONS:
            for template, argv in specs:
                with self.subTest(python=py, template=template, verb=argv[0]):
                    root, over = self.fresh()
                    path = over / template
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"# ${title}\n\nR\xe9views of the books.\n")  # latin-1
                    base = tree(root)
                    code, out, err = self.cli(py, root, *argv)
                    self.assertEqual((code, out, err), (2, "", (
                        f"segmently-modules: error: cannot read .segmently-modules/overrides/templates/{template}: "
                        f"not valid UTF-8\n")))
                    self.assertEqual(tree(root), base)

    def role_template(self, template):
        """A repository pack whose role `designer` names this `template` file."""
        root, _ = self.fresh()
        base = root / ".segmently-modules/packs/books"
        base.mkdir(parents=True)
        (base / "pack.toml").write_text(
            'id = "books"\nversion = "0.1.0"\n[roles.designer]\n'
            f'description = "Designs"\ntemplate = {json.dumps(template)}\n', encoding="utf-8")
        return root

    def test_a_nul_in_a_role_template_is_a_refusal(self):  # P83-AC-033 (review I-1)
        for py in PYTHONS:
            root = self.role_template("a\u0000b")
            for argv in (("templates", "list"), ("roles", "add", "designer", "--all")):
                with self.subTest(python=py, verb=argv[0]):
                    code, out, err = self.cli(py, root, *argv)
                    self.assertEqual((code, out), (2, ""), err)
                    lines = err.splitlines()
                    self.assertEqual(len(lines), 1, err)
                    self.assertTrue(lines[0].startswith("segmently-modules: error: cannot read "), err)
                    self.assertTrue(lines[0].endswith("a\\0b: embedded null byte"), err)
                    self.assertNotIn("internal error", err)

    def test_a_name_too_long_to_exist_falls_through(self):  # P83-AC-033 (review M-1)
        for py in PYTHONS:
            root = self.role_template("x" * 300 + ".md")
            code, out, err = self.cli(py, root, "templates", "list", extra=("--json",))
            self.assertEqual((code, err), (0, ""))
            rows = {r["template"]: r["source"] for r in json.loads(out)["data"]}
            self.assertEqual(rows["roles/designer.md"], "engine-fallback")

    def test_a_path_outside_the_root_is_absolute(self):  # P83-AC-033
        cfg = Path(os.path.realpath(self.tmp)) / "cfg"
        (cfg / "overrides/templates/choose/rules.md").mkdir(parents=True)
        for py in PYTHONS:
            root, _ = self.fresh()
            code, out, err = self.cli(py, root, "templates", "list", extra=("--config-dir",
                                                                            str(cfg)))
            self.assertEqual((code, out), (2, ""))
            self.assertIn(f"cannot read {cfg / 'overrides/templates/choose/rules.md'}: ", err)


class DocsTest(unittest.TestCase):
    def test_the_codex_example_has_the_sandbox_flag(self):  # P83-AC-034
        self.assertIn(CODEX, README)
        self.assertEqual(README.count("codex exec -m {codex_model}"), 1)
        command = json.loads(CODEX[len("export SEGMENTLY_MODULES_AGENT_COMMAND='"):-1])
        validate_command(command, "SEGMENTLY_MODULES_AGENT_COMMAND")
        self.assertIn('claude -p --model {claude_model} --output-format json --json-schema',
                      README)

    def test_configuration_names_the_refusal(self):  # final review M-2 (2)
        doc = (ENGINE / "docs/configuration.md").read_text(encoding="utf-8")
        para = next(p for p in doc.split("\n\n") if p.startswith("`create` resolves a template"))
        flat = " ".join(para.split())
        for needle in ("exists but cannot be read", "exit 2", "cli-contract.md"):
            self.assertIn(needle, flat)

    def test_the_stream_bullets(self):  # final review M-2 (3, 4), I-2, M-3
        bullets = {b.split("**", 1)[0]: "- **" + b for b in DOCS.split("\n- **")[1:]}
        stdout, stderr = bullets["A closed stdout reader"], bullets["stderr closed at start"]
        sentence = ("With stderr open, any other stdout write error (a full disk, a file size "
                    "limit) is exit `2` with one stderr line `segmently-modules: error: cannot write "
                    "stdout: <reason>`.")
        self.assertIn(sentence, " ".join(stdout.split()))
        self.assertNotIn("cannot write stdout", stderr)
        self.assertIn("a child that inherits stderr writes to the null device",
                      " ".join(stderr.split()))
        for line in [*stdout.splitlines(), *stderr.splitlines()]:
            self.assertLessEqual(len(line), 100, line)
        self.assertIn("a template that is not UTF-8 is `cannot read <path>: not valid UTF-8`",
                      " ".join(DOCS.split()))

    def test_the_contract_and_the_changelog_name_the_changes(self):  # P83-AC-034
        for needle in ("fd 2 is closed at start", "the null device", "exists but cannot be read"):
            self.assertIn(needle, DOCS)
        unreleased = changelog_since_first_release(CHANGELOG)
        for needle in ("stderr closed at start", "cannot read", "--sandbox read-only"):
            self.assertIn(needle, unreleased)


if __name__ == "__main__":
    unittest.main()
