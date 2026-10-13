"""`tools/release.py` (P6 D7): the refusals before any write — the guard, dirty trees,
taken tags, a version without .devN, symlinked directories, the flags, an export of the
engine — and the default signals of a tool the tests start. Split from
`test_release.py` (P8.3 D5 R-3)."""
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import git
from tests.plugin_helpers import default_signals, run_tool
from tests.release_helpers import ENG, GUARD, REL, ReleaseRepo, SLUG


class RefusalTest(ReleaseRepo):  # P6-AC-030 (SI-1, SI-16, SI-17)
    def refused(self, *argv: str, channel: str = "stable", env: dict | None = None,
                slug: str = SLUG) -> str:
        before = self.both()
        proc = self.release(channel, *argv, env=env, slug=slug)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertEqual(self.both(), before)
        self.assertEqual(list(self.tmpdir.iterdir()), [])
        self.assertNotIn("Traceback", proc.stderr)
        return proc.stderr

    def test_the_guard(self):
        self.assertIn("SEGMENTLY_MODULES_GUARD is not set", self.refused(env={"SEGMENTLY_MODULES_GUARD": ""}))
        self.assertIn("SEGMENTLY_MODULES_GUARD: /nonexistent/guard.py not found",
                      self.refused(env={"SEGMENTLY_MODULES_GUARD": "/nonexistent/guard.py"}))
        err = self.refused(env={"FAKE_GUARD_HIT": str(self.engine)})
        self.assertIn("the leak guard found 2 hit(s) in the engine", err)
        self.assertIn("LEAK  'secret'  in file a.md", err)  # the operator's terminal only
        self.assertIn("the leak guard failed on the engine (exit 2): guard: error: planted",
                      self.refused(env={"FAKE_GUARD_ERROR": "1"}))
        err = self.refused(env={"FAKE_GUARD_HIT": "segmently-modules-release-build-"})
        self.assertIn("in the build directory", err)
        vendored = self.engine / "dist/guard.py"  # git-ignored: the tree stays clean
        vendored.parent.mkdir()
        vendored.write_text(GUARD)
        self.assertIn("SEGMENTLY_MODULES_GUARD points into the engine",
                      self.refused(env={"SEGMENTLY_MODULES_GUARD": str(vendored)}))

    def test_a_guard_that_fails_is_not_a_guard_with_hits(self):  # final review M-3
        for mode, line in (
                ("crash", "the leak guard failed on the engine (exit 1): RuntimeError: boom"),
                ("clean-exit-1", "the leak guard failed on the engine (exit 1): guard: CLEAN"),
                ("no-verdict", "the leak guard failed on the engine (exit 0): no `… CLEAN` "
                               "line in its output")):
            with self.subTest(guard=mode):
                err = self.refused(channel="dev", env={"FAKE_GUARD_MODE": mode})
                self.assertEqual(err, f"release.py: error: {line}\n")
        script = self.base / "guard.sh"  # not Python at all
        script.write_text("#!/bin/sh\necho 'guard: CLEAN'\n")
        err = self.refused(channel="dev", env={"SEGMENTLY_MODULES_GUARD": str(script)})
        self.assertIn("the leak guard failed on the engine (exit 1): ", err)
        self.assertNotIn("hit(s)", err)
        self.assertEqual(err.count("\n"), 1)

    def test_dirty_trees_and_tags(self):
        (self.engine / "README.md").write_text("changed\n")
        self.assertIn("the engine is dirty: README.md", self.refused())
        git(self.engine, "checkout", "--", "README.md")
        (self.engine / "notes.txt").write_text("new\n")
        self.assertIn("the engine is dirty: notes.txt", self.refused())
        (self.engine / "notes.txt").unlink()
        (self.pub / "scratch.txt").write_text("x\n")
        self.assertIn("the publish repo is dirty: scratch.txt", self.refused())
        (self.pub / "scratch.txt").unlink()
        git(self.engine, "tag", f"v{REL}")
        self.assertIn(f"v{REL} already exists in the engine", self.refused())
        git(self.engine, "tag", "-d", f"v{REL}")
        self.commit(self.pub, "x.txt", "x\n", "x")
        for tag in (f"v{REL}", f"segmently-modules-ui--v{REL}"):
            git(self.pub, "tag", tag)
            self.assertIn(f"{tag} already exists in the publish repo", self.refused())
            git(self.pub, "branch", tag)  # a branch of the same name hides nothing
            self.assertIn(f"{tag} already exists in the publish repo", self.refused())
            git(self.pub, "branch", "-q", "-D", tag)
            git(self.pub, "tag", "-d", tag)

    def test_a_version_without_devn_and_a_symlinked_directory(self):  # final M-7, M-5
        outside = self.base / "outside"
        (outside / "segmently-modules").mkdir(parents=True)
        (outside / "segmently-modules/THEIRS.txt").write_text("not the release's\n")
        for rel in ("plugins", ".claude-plugin", ".agents"):
            with self.subTest(link=rel):
                os.symlink(outside, self.pub / rel)
                git(self.pub, "add", "--", rel)
                git(self.pub, "commit", "-q", "-m", f"{rel} is a link")
                self.assertIn(f"{rel} in the publish repo is a symlink or a file",
                              self.refused(channel="dev"))
                git(self.pub, "rm", "-q", "--", rel)
                git(self.pub, "commit", "-q", "-m", "no link")
        self.commit(self.pub, ".agents/plugins", "a file\n", "a file where a directory goes")
        self.assertIn(".agents/plugins in the publish repo is a symlink or a file",
                      self.refused(channel="dev"))
        self.assertEqual(sorted(p.name for p in outside.rglob("*")), ["THEIRS.txt", "segmently-modules"])
        git(self.pub, "rm", "-q", "--", ".agents/plugins")
        git(self.pub, "commit", "-q", "-m", "no file")
        for rel, old, new in (("segmently_modules/__init__.py", f'__version__ = "{ENG}"',
                               f'__version__ = "{REL}"'),
                              ("pyproject.toml", f'version = "{ENG}"', f'version = "{REL}"')):
            path = self.engine / rel
            path.write_text(path.read_text().replace(old, new))
        git(self.engine, "commit", "-q", "-am", f"{REL} by hand")
        err = self.refused()
        self.assertIn(f"the engine's __version__ is {REL}, without .devN — a stable release "
                      "makes the release commit itself", err)
        self.assertFalse((self.base / "claude.log").exists())  # before the suite, the build

    def test_a_release_under_nohup_keeps_running(self):  # re-review N-4
        (self.pub / "scratch.txt").write_text("x\n")  # step 2 refuses: step 1 got through
        proc = subprocess.run(  # SIGHUP (and SIGTERM) ignored by the caller, as nohup does;
            ["/bin/sh", "-c", 'trap "" HUP TERM; exec "$0" "$@"', sys.executable,  # the
             str(self.engine / "tools/release.py"), "--publish-repo", str(self.pub),  # guard
             "--channel", "dev", "--publish-slug", SLUG], capture_output=True, text=True,
            env={**os.environ, **self.env, "FAKE_GUARD_MODE": "hangup"},  # sends SIGHUP
            preexec_fn=default_signals)  # the defaults first; the trap then ignores the two
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("the publish repo is dirty: scratch.txt", proc.stderr)
        self.assertNotIn("interrupted", proc.stderr)

    def test_flags(self):
        self.claude_on_path(False)
        self.assertIn("--push needs claude on PATH", self.refused("--push"))
        self.claude_on_path(True)
        self.assertIn("--push: the publish repo has no remote named origin",
                      self.refused("--push"))
        git(self.pub, "remote", "add", "origin", str(self.base / "publish.git"))
        self.assertIn("--push: the engine has no remote named origin", self.refused("--push"))
        self.assertFalse((self.base / "claude.log").exists())  # refused before step 1
        self.assertIn("invalid choice: 'beta'", self.refused(channel="beta"))
        for slug in ("a/b/c", "a b/c", "a;b/c"):
            self.assertIn("--publish-slug", self.refused(slug=slug))
        proc = run_tool(self.engine, "release", "--channel", "dev", "--publish-slug", SLUG,
                        env=self.env)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--publish-repo", proc.stderr)
        plain = self.base / "plain"
        plain.mkdir()
        proc = run_tool(self.engine, "release", "--publish-repo", str(plain), "--channel",
                        "dev", "--publish-slug", SLUG, env=self.env)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not the top of a git work tree", proc.stderr)

    def test_an_export_of_the_engine_and_no_git(self):  # never a traceback before step 1
        export = self.base / "export"
        shutil.copytree(self.engine, export, ignore=shutil.ignore_patterns(".git"))
        proc = run_tool(export, "release", "--publish-repo", str(self.pub), "--channel", "dev",
                        "--publish-slug", SLUG, env=self.env)
        self.assertEqual((proc.returncode, proc.stdout), (2, ""))
        self.assertEqual(proc.stderr, f"release.py: error: {export} is not the top of a git "
                                      "work tree — release from a clone of the engine, not an "
                                      "export\n")
        empty = self.base / "empty-path"
        empty.mkdir()
        proc = self.release("dev", env={"PATH": str(empty)})
        self.assertEqual((proc.returncode, proc.stdout), (2, ""))
        self.assertTrue(proc.stderr.startswith("release.py: error: git is not installed or "
                                               "cannot run"), proc.stderr)
        self.assertEqual(proc.stderr.count("\n"), 1)

    def test_an_unknown_flag(self):  # P6-AC-033
        proc = run_tool(self.engine, "release", "--frobnicate", env=self.env)
        self.assertEqual((proc.returncode, proc.stdout), (2, ""))
        self.assertIn("usage:", proc.stderr)


class SignalDefaultsTest(unittest.TestCase):  # the gate runs the suite detached: nohup … &
    def test_a_tool_the_tests_start_gets_the_default_signals(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = Path(tmp)
            (engine / "tools").mkdir()
            (engine / "tools/probe.py").write_text(
                "import signal\nprint(*(signal.getsignal(s) is signal.SIG_IGN for s in "
                "(signal.SIGINT, signal.SIGTERM, signal.SIGHUP)))\n")
            held = {s: signal.signal(s, signal.SIG_IGN)  # what `nohup … &` leaves the suite
                    for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
            try:
                ignored = run_tool(engine, "probe").stdout.split()
                nohup = subprocess.run([sys.executable, str(engine / "tools/probe.py")],
                                       capture_output=True, text=True).stdout.split()
            finally:
                for sig, handler in held.items():
                    signal.signal(sig, handler)
        self.assertEqual(nohup, ["True", "True", "True"])  # the case this helper exists for
        self.assertEqual(ignored, ["False", "False", "False"])


if __name__ == "__main__":
    unittest.main()
