"""`tools/release.py` (P6 D7): a dev and then a stable release into a local publish
repository, both channels from the same commit, the push only with --push, a release
without `claude` on PATH; the release commit holds the build whatever git is told (ignore
rules, filters, `core.fileMode`). Split from `test_release.py` (P8.3 D5 R-3)."""
import json
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import git
from tests.release_helpers import (ALLOWED, CHANGELOG, DATE, ENG, LOG_BEGIN, LOG_END, NXT, NXT_DEV,
                                   REL, ReleaseRepo, SLUG, STEPS, TAGS)


class RunTest(ReleaseRepo):  # P6-AC-014, 015, 017
    def test_dev_then_stable(self):
        engine_before = self.state(self.engine)
        proc = self.release("dev")
        self.assert_ok(proc)
        lines = proc.stdout.splitlines()
        self.assertEqual([re.match(r"step (\d) ([a-z ]+):", l).groups() for l in lines
                          if l.startswith("step ")],
                         [(str(n), name) for n, name in enumerate(STEPS, start=1)])
        self.assertRegex(proc.stdout, r"step 3 tests: Ran 3 tests in 2 modules \(\d+ jobs?\), "
                                      r"OK \(skipped=1\); "
                                      r"the adoption eval passed")  # the skip stays visible
        version = re.search(r"done: segmently-modules (\S+) \(dev\)", proc.stdout).group(1)
        self.assertRegex(version, rf"^{re.escape(REL)}-dev\.h[0-9a-f]{{8}}$")
        self.assertEqual(self.state(self.engine), engine_before)  # dev: no commit, no tag
        self.assertFalse((self.engine / "tools/__pycache__").exists())
        self.assertEqual(self.log(self.pub, "dev"), [f"release segmently-modules {version} (dev)"])
        self.assertEqual(git(self.pub, "tag", "-l"), "")
        self.assertIn("push: not requested — the release is committed locally; to publish it "
                      f"(an owner command), run:\n  git -C {shlex.quote(str(self.pub))} push "
                      "--atomic origin refs/heads/dev\n", proc.stdout)
        self.assertIn(" -C '", proc.stdout)  # the path with a space, quoted for the shell
        with tempfile.TemporaryDirectory() as tmp:
            build = Path(tmp) / "build"
            subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); "
                            "import publish; from pathlib import Path; "
                            "print(publish.build_channel(Path(sys.argv[2]), Path(sys.argv[3]), "
                            "'dev'))", str(self.engine / "tools"), str(self.engine),
                            str(build)], check=True, capture_output=True)
            for name in ("segmently-modules", "segmently-modules-ui", "segmently-modules-qa"):
                self.assertEqual(self.files(build / name), self.files(self.pub / "plugins" / name))
            self.assertEqual(self.committed("dev"), {
                f"plugins/{name}/{rel}": "100755" if mode & 0o111 else "100644"
                for name in ("segmently-modules", "segmently-modules-ui", "segmently-modules-qa")
                for rel, (mode, _) in self.files(build / name).items()})
        claude = json.loads((self.pub / ".claude-plugin/marketplace.json").read_text())
        codex = json.loads((self.pub / ".agents/plugins/marketplace.json").read_text())
        self.assertEqual((claude["name"], codex["name"]), ("segmently-modules-dev", "segmently-modules-dev"))
        self.assertIn(f"`claude plugin marketplace add {SLUG}#stable`",
                      (self.pub / "README.md").read_text())
        self.assertEqual(self.entries("dev"), [(version, "dev", git(
            self.engine, "rev-parse", "HEAD"), ["- First planted note.",
                                                "- Second planted note."])])
        calls = self.calls()
        self.assertIn(["--version"], [c["argv"] for c in calls])
        for call in calls:  # only the allowed calls, each with a fresh throw-away config and
            self.assertTrue(any(call["argv"][:len(a)] == a for a in ALLOWED), call)  # without
            self.assertNotIn("forbidden", call)  # the credential variables this test sets
            self.assertEqual(call["secrets"], [])
            self.assertTrue(call["config"].startswith(str(self.tmpdir)), call)
        installs = [c["argv"][2] for c in calls if c["argv"][:2] == ["plugin", "install"]]
        self.assertEqual(installs, ["segmently-modules-ui@segmently-modules-dev", "segmently-modules-qa@segmently-modules-dev"])
        self.assertIn(f"bin/segmently-modules --version = segmently-modules {ENG}", proc.stdout)

        proc = self.release("stable")
        self.assert_ok(proc)
        self.assertEqual(git(self.engine, "log", "--format=%s", "-3").splitlines(),
                         [f"start segmently-modules {NXT_DEV}", f"release segmently-modules {REL}", "engine"])
        self.assertEqual(git(self.engine, "tag", "--points-at", "HEAD~1").split(), [f"v{REL}"])
        self.assertIn(f'__version__ = "{REL}"', git(self.engine, "show",
                                                   "HEAD~1:segmently_modules/__init__.py"))
        self.assertIn(f'version = "{REL}"', git(self.engine, "show", "HEAD~1:pyproject.toml"))
        self.assertIn(f'version = "{NXT_DEV}"', (self.engine / "pyproject.toml").read_text())
        # ONE commit (P6-AC-015): a channel never starts on the other channel's release
        self.assertEqual(self.log(self.pub, "stable"), [f"release segmently-modules {REL} (stable)"])
        self.assertEqual(sorted(git(self.pub, "tag", "--points-at", "stable").split()),
                         [t.format(REL) for t in TAGS])
        self.assertEqual(self.log(self.pub, "dev"), [f"release segmently-modules {version} (dev)"])
        self.assertEqual(git(self.pub, "symbolic-ref", "HEAD").strip(), "refs/heads/stable")
        self.assertEqual(json.loads((self.pub / ".claude-plugin/marketplace.json")
                                    .read_text())["name"], "segmently-modules")
        log = (self.pub / "CHANGELOG.md").read_text()
        self.assertIn(f"- {REL} (stable): engine ", log)
        self.assertNotIn("(dev)", log)  # the channel's own entries only
        # P61-AC-021: the release commit dates the notes, the start commit leaves them, the
        # publish entry carries them (the engine sha = the release commit)
        self.assertEqual(git(self.engine, "show", "HEAD~1:CHANGELOG.md"), CHANGELOG.replace(
            "## [Unreleased]\n\n", f"## [Unreleased]\n\n## [{REL}] - {DATE}\n\n", 1))
        self.assertEqual(git(self.engine, "show", "--name-only", "--format=", "HEAD~1").split(),
                         ["CHANGELOG.md", "pyproject.toml", "segmently_modules/__init__.py"])
        self.assertEqual(git(self.engine, "show", "--name-only", "--format=", "HEAD").split(),
                         ["pyproject.toml", "segmently_modules/__init__.py"])
        self.assertEqual((self.engine / "CHANGELOG.md").read_text(),
                         git(self.engine, "show", "HEAD~1:CHANGELOG.md"))
        self.assertEqual(self.entries("stable"), [(REL, "stable", git(
            self.engine, "rev-parse", "HEAD~1"), ["- First planted note.",
                                                  "- Second planted note."])])
        self.assertTrue(log.startswith(f"{LOG_BEGIN}\n## segmently-modules\n\n- {REL} (stable): engine "))
        self.assertTrue(log.endswith("\n  - First planted note.\n  - Second planted note.\n"
                                     f"{LOG_END}\n"), log)
        self.assertIn(f"step 4 build: segmently-modules {REL} (segmently-modules, segmently-modules-ui, segmently-modules-qa); CHANGELOG.md "
                      f"[Unreleased] dated [{REL}] - {DATE}\n", proc.stdout)
        self.assertIn(f"bin/segmently-modules --version = segmently-modules {REL}", proc.stdout)
        self.assertIn(f"  git -C {shlex.quote(str(self.pub))} push --atomic origin "
                      "refs/heads/stable "
                      f"refs/tags/v{REL} refs/tags/segmently-modules--v{REL} refs/tags/segmently-modules-ui--v{REL} "
                      f"refs/tags/segmently-modules-qa--v{REL}\n  git -C {self.engine} push --atomic "
                      f"origin refs/heads/main refs/tags/v{REL}\n", proc.stdout)
        self.assertEqual(list(self.pub.rglob("__pycache__")), [])
        self.assertNotIn("push", (self.base / "git.log").read_text().split())
        self.assertNotIn("example-org", git(self.engine, "log", "-p", "HEAD~2..HEAD"))  # D13
        self.assertNotIn("example-org", git(self.pub, "log", "--all", "--format=%B"))

    def files(self, root: Path) -> dict:
        return {p.relative_to(root).as_posix(): (p.stat().st_mode & 0o777, p.read_bytes())
                for p in root.rglob("*") if p.is_file()}

    def committed(self, ref: str) -> dict:
        """{path: git mode} of the plugin files in the commit `ref` of the publish repository."""
        rows = git(self.pub, "ls-tree", "-r", ref, "--", "plugins").splitlines()
        return {row.split("\t")[1]: row.split()[0] for row in rows}

    def test_both_channels_start_from_the_same_main_commit(self):
        self.commit(self.pub, "plugins/other-tool/plugin.json", '{"name": "other-tool"}\n',
                    "the owner's content")
        self.assert_ok(self.release("dev"))  # leaves the repository on `dev`
        self.assert_ok(self.release("stable"))
        dev, stable = self.log(self.pub, "dev"), self.log(self.pub, "stable")
        self.assertEqual(dev[1:], ["the owner's content"])
        self.assertEqual(stable, [f"release segmently-modules {REL} (stable)", "the owner's content"])
        self.assertRegex(dev[0], rf"^release segmently-modules {re.escape(REL)}-dev\.h[0-9a-f]{{8}} \(dev\)$")
        for branch in ("dev", "stable"):
            self.assertEqual(git(self.pub, "show", f"{branch}:plugins/other-tool/plugin.json"),
                             '{"name": "other-tool"}\n')
        self.assertEqual(self.log(self.pub, "main"), ["the owner's content"])

    def test_push_only_with_push(self):
        remotes = self.remotes()
        before = {k: git(r, "for-each-ref") for k, r in remotes.items()}
        self.assert_ok(self.release("stable"))
        self.assertEqual({k: git(r, "for-each-ref") for k, r in remotes.items()}, before)
        self.assertNotIn(" push", " " + (self.base / "git.log").read_text())
        git(self.engine, "tag", "-d", f"v{REL}")  # a second stable run to push: the next release
        self.notes("- The next release.")  # the first one dated the notes (D6)
        proc = self.release("stable", "--push")
        self.assert_ok(proc)
        self.assertEqual(sorted(self.refs(remotes["publish"])),
                         ["refs/heads/stable", f"refs/tags/segmently-modules--v{NXT}",
                          f"refs/tags/segmently-modules-qa--v{NXT}", f"refs/tags/segmently-modules-ui--v{NXT}",
                          f"refs/tags/v{NXT}"])
        self.assertEqual(sorted(self.refs(remotes["engine"])),
                         ["refs/heads/main", f"refs/tags/v{NXT}"])
        self.assertIn(f"push: publish repo stable, v{NXT}, segmently-modules--v{NXT}, segmently-modules-ui--v{NXT}, "
                      f"segmently-modules-qa--v{NXT}; engine main, v{NXT}\n", proc.stdout)
        pushes = [l for l in (self.base / "git.log").read_text().splitlines() if " push " in
                  f" {l} "]
        self.assertEqual(len(pushes), 2, pushes)
        self.assertFalse((self.base / "gh.log").exists())  # no GitHub call, ever

    def test_without_claude(self):
        self.claude_on_path(False)
        proc = self.release("dev")
        self.assert_ok(proc)
        self.assertIn("step 5 validate: our checks passed; claude plugin validate skipped: "
                      "claude not on PATH", proc.stdout)
        self.assertIn("step 8 smoke install: skipped: claude not on PATH", proc.stdout)
        before = self.both()
        proc = self.release("stable", "--push")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--push needs claude on PATH", proc.stderr)
        self.assertEqual(self.both(), before)


class CommitTest(ReleaseRepo):  # final review I-1: the commit is the build, whatever git is told
    def test_ignore_rules_and_a_repository_without_modes(self):
        (self.pub / "README.md").write_bytes(b"# Plugins\r\n\r\nIntro.\r\n")
        (self.pub / "CHANGELOG.md").write_bytes(b"# Changes\r\n\r\n- theirs\r\n")
        (self.pub / ".gitignore").write_text("bin/\n")  # the owner's: it matches bin/segmently-modules
        git(self.pub, "add", "--", "README.md", "CHANGELOG.md", ".gitignore")
        git(self.pub, "commit", "-q", "-m", "the owner's files")
        git(self.pub, "config", "core.fileMode", "false")
        (self.base / "ignore").write_text("runtime/\n")  # the maintainer's own excludes file
        (self.base / "gitconfig").write_text(f"[core]\n\texcludesFile = {self.base}/ignore\n")
        env = {"GIT_CONFIG_GLOBAL": str(self.base / "gitconfig")}
        self.assert_ok(self.release("dev", env=env))
        rows = git(self.pub, "ls-tree", "-r", "dev", "--", "plugins").splitlines()
        held = {row.split("\t")[1]: row.split()[0] for row in rows}
        self.assertEqual(held["plugins/segmently-modules/bin/segmently-modules"], "100755")
        self.assertEqual([p for p, mode in held.items() if mode != "100644"],
                         ["plugins/segmently-modules/bin/segmently-modules"])
        on_disk = sorted(p.relative_to(self.pub).as_posix()
                         for p in (self.pub / "plugins").rglob("*") if p.is_file())
        self.assertEqual(sorted(held), on_disk)  # every built file is in the commit
        self.assertGreater(sum(p.startswith("plugins/segmently-modules/runtime/") for p in held), 50)
        for rel, ours in (("README.md", "<!-- segmently-modules:begin -->"),
                          ("CHANGELOG.md", "<!-- segmently-modules:changelog:begin -->")):
            data = (self.pub / rel).read_bytes()  # a CRLF file stays CRLF, inside our section
            self.assertIn(ours.encode(), data)  # too; the owner's bytes are unchanged
            self.assertNotIn(b"\n", data.replace(b"\r\n", b""), rel)
        self.assertTrue((self.pub / "README.md").read_bytes().startswith(
            b"# Plugins\r\n\r\nIntro.\r\n\r\n<!-- segmently-modules:begin -->\r\n## Segmently Modules\r\n"))
        self.assertTrue((self.pub / "CHANGELOG.md").read_bytes().startswith(
            b"# Changes\r\n\r\n- theirs\r\n\r\n<!-- segmently-modules:changelog:begin -->\r\n"))
        proc = self.release("dev", env=env)  # and the same tree again is no change
        self.assert_ok(proc)
        self.assertIn("nothing to release", proc.stdout)

    def test_a_commit_that_is_not_the_build_fails_step_7(self):
        self.commit(self.pub, ".gitattributes", "*.md filter=upper\n", "the owner's filter")
        git(self.pub, "config", "filter.upper.clean", "tr a-z A-Z")
        before = self.both()
        proc = self.release("dev")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("step 7 commit failed: the commit does not hold the build: ", proc.stderr)
        self.assertIn("README.md has other content", proc.stderr)
        self.assertIn(" more — an ignore rule, a filter or a mode setting", proc.stderr)
        self.assertTrue(proc.stderr.rstrip().endswith("both repositories are as they were"))
        self.assertEqual(self.both(), before)


if __name__ == "__main__":
    unittest.main()
