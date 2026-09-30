"""`tools/release.py` (P6 D7, rows 6.2–6.5): a dev and a stable release into a local publish
repository, push only with --push, the publish repository's foreign content kept, the smoke
install through a `claude` stand-in (tests/claude_shim.py — never a model), no repository slug
outside the publish README, the refusals and all-or-nothing. Each test releases a throw-away
git copy of this engine (its unit suite = one test, its E-A a stub: the heavy steps are the
rehearsal's) with a stub leak guard."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import git
from tests.plugin_helpers import ENGINE, copy_engine, load_tool, run_tool

SLUG = "example-org/modsys-plugins"
EXTRA = {"tests/__init__.py": "",
         "tests/test_ok.py": "import unittest\n\n\nclass OkTest(unittest.TestCase):\n"
                             "    def test_ok(self):\n        self.assertTrue(True)\n",
         "evals/adoption/run_eval.py": "import sys\n\nprint('adoption eval: stub ok', "
                                       "file=sys.stderr)\n",
         "README.md": "# modsys (a test copy)\n"}
GUARD = """import os, sys
target = sys.argv[sys.argv.index("--target") + 1]
if os.environ.get("FAKE_GUARD_ERROR"):
    print("guard: error: planted", file=sys.stderr)
    sys.exit(2)
hit = os.environ.get("FAKE_GUARD_HIT")
if hit and hit in target:
    print("LEAK  'secret'  in file a.md")
    print("LEAK  'secret'  in file b.md")
    print("guard: 2 hit(s)")
    sys.exit(1)
print("guard: CLEAN")
"""
ALLOWED = (["--version"], ["plugin", "validate"], ["plugin", "marketplace", "add"],
           ["plugin", "install"], ["plugin", "list", "--json"], ["plugin", "details"])
IDENTITY = {"GIT_AUTHOR_NAME": "r", "GIT_AUTHOR_EMAIL": "r@example.com",
            "GIT_COMMITTER_NAME": "r", "GIT_COMMITTER_EMAIL": "r@example.com"}
MACHINE_PATHS = ("/" + "Users/", "/" + "home/")  # joined here: this file holds no such path
STEPS = ["leak guard", "clean trees", "tests", "build", "validate", "publish repo", "commit",
         "smoke install"]


class ReleaseRepo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name).resolve()
        self.engine = copy_engine(self.base / "engine", EXTRA,
                                  prefixes=("modsys/", "tools/", "tests/fixtures/bookshop/"))
        self.pub = self.base / "publish"
        self.pub.mkdir()
        git(self.pub, "init", "-q", "-b", "main")
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.claude_on_path(True)
        (self.bin / "git").write_text(f'#!/bin/sh\necho "$*" >> "{self.base}/git.log"\n'
                                      f'exec "{shutil.which("git")}" "$@"\n')
        (self.bin / "git").chmod(0o755)
        (self.bin / "gh").write_text(f'#!/bin/sh\necho "$*" >> "{self.base}/gh.log"\nexit 1\n')
        (self.bin / "gh").chmod(0o755)  # the release never calls it: no log may appear
        (self.base / "guard.py").write_text(GUARD)
        self.tmpdir = self.base / "tmp"
        self.tmpdir.mkdir()
        self.env = {**IDENTITY, "PATH": f"{self.bin}:/usr/bin:/bin",
                    "MODSYS_GUARD": str(self.base / "guard.py"),
                    "FAKE_CLAUDE_LOG": str(self.base / "claude.log"), "TMPDIR": str(self.tmpdir),
                    "MODSYS_PYTHON": sys.executable}

    def tearDown(self):
        self._tmp.cleanup()

    def claude_on_path(self, present: bool) -> None:
        shim = self.bin / "claude"
        if not present and shutil.which("claude", path="/usr/bin:/bin"):
            self.skipTest("a claude in /usr/bin or /bin: the release would find it")
        if present:
            shim.write_text(f"#!{sys.executable}\n"
                            + (ENGINE / "tests/claude_shim.py").read_text(encoding="utf-8"))
            shim.chmod(0o755)
        else:
            shim.unlink(missing_ok=True)

    def release(self, channel: str = "dev", *argv: str, env: dict | None = None,
                slug: str = SLUG) -> subprocess.CompletedProcess:
        return run_tool(self.engine, "release", "--publish-repo", str(self.pub), "--channel",
                        channel, "--publish-slug", slug, *argv, env={**self.env, **(env or {})})

    def state(self, repo: Path) -> tuple:
        """What all-or-nothing keeps: status, HEAD, tags, branches (git itself, no wrapper)."""
        def out(*args):
            return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                                  text=True).stdout
        return (out("status", "--short"), out("rev-parse", "HEAD"), out("tag", "-l"),
                out("branch", "-a"), out("symbolic-ref", "-q", "HEAD"))

    def calls(self) -> list[dict]:
        log = self.base / "claude.log"
        return [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []

    def assert_ok(self, proc) -> None:
        self.assertEqual((proc.returncode, proc.stderr), (0, ""), proc.stdout)
        self.assertEqual(list(self.tmpdir.iterdir()), [])  # every temp directory removed


class RunTest(ReleaseRepo):  # P6-AC-014, 015, 017
    def test_dev_then_stable(self):
        engine_before = self.state(self.engine)
        proc = self.release("dev")
        self.assert_ok(proc)
        lines = proc.stdout.splitlines()
        self.assertEqual([re.match(r"step (\d) ([a-z ]+):", l).groups() for l in lines
                          if l.startswith("step ")],
                         [(str(n), name) for n, name in enumerate(STEPS, start=1)])
        version = re.search(r"done: modsys (\S+) \(dev\)", proc.stdout).group(1)
        self.assertRegex(version, r"^0\.1\.0-dev\.h[0-9a-f]{8}$")
        self.assertEqual(self.state(self.engine), engine_before)  # dev: no commit, no tag
        self.assertEqual(git(self.pub, "log", "--format=%s", "dev").splitlines(),
                         [f"release modsys {version} (dev)"])
        self.assertEqual(git(self.pub, "tag", "-l"), "")
        with tempfile.TemporaryDirectory() as tmp:
            build = Path(tmp) / "build"
            subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); "
                            "import publish; from pathlib import Path; "
                            "print(publish.build_channel(Path(sys.argv[2]), Path(sys.argv[3]), "
                            "'dev'))", str(self.engine / "tools"), str(self.engine),
                            str(build)], check=True, capture_output=True)
            for name in ("modsys", "modsys-ui", "modsys-qa"):
                self.assertEqual(self.files(build / name), self.files(self.pub / "plugins" / name))
        claude = json.loads((self.pub / ".claude-plugin/marketplace.json").read_text())
        codex = json.loads((self.pub / ".agents/plugins/marketplace.json").read_text())
        self.assertEqual((claude["name"], codex["name"]), ("modsys-dev", "modsys-dev"))
        self.assertIn(f"`claude plugin marketplace add {SLUG}#stable`",
                      (self.pub / "README.md").read_text())
        self.assertIn(f"- {version} (dev): engine ", (self.pub / "CHANGELOG.md").read_text())
        calls = self.calls()
        for call in calls:  # only the allowed calls, each with a fresh throw-away config
            self.assertTrue(any(call["argv"][:len(a)] == a for a in ALLOWED), call)
            self.assertNotIn("forbidden", call)
            self.assertEqual(call["secrets"], [])
            if call["argv"] != ["--version"]:
                self.assertTrue(call["config"].startswith(str(self.tmpdir)), call)
        installs = [c["argv"][2] for c in calls if c["argv"][:2] == ["plugin", "install"]]
        self.assertEqual(installs, ["modsys-ui@modsys-dev", "modsys-qa@modsys-dev"])
        self.assertIn("bin/modsys --version = modsys 0.1.0.dev0", proc.stdout)

        proc = self.release("stable")
        self.assert_ok(proc)
        self.assertEqual(git(self.engine, "log", "--format=%s", "-3").splitlines(),
                         ["start modsys 0.1.1.dev0", "release modsys 0.1.0", "engine"])
        self.assertEqual(git(self.engine, "tag", "--points-at", "HEAD~1").split(), ["v0.1.0"])
        self.assertIn('__version__ = "0.1.0"', git(self.engine, "show",
                                                   "HEAD~1:modsys/__init__.py"))
        self.assertIn('version = "0.1.0"', git(self.engine, "show", "HEAD~1:pyproject.toml"))
        self.assertIn('version = "0.1.1.dev0"', (self.engine / "pyproject.toml").read_text())
        self.assertEqual(git(self.pub, "log", "--format=%s", "stable").splitlines()[0],
                         "release modsys 0.1.0 (stable)")
        self.assertEqual(sorted(git(self.pub, "tag", "--points-at", "stable").split()),
                         ["modsys--v0.1.0", "modsys-qa--v0.1.0", "modsys-ui--v0.1.0", "v0.1.0"])
        self.assertEqual(git(self.pub, "log", "--format=%s", "dev").splitlines(),
                         [f"release modsys {version} (dev)"])  # dev unchanged
        self.assertEqual(json.loads((self.pub / ".claude-plugin/marketplace.json")
                                    .read_text())["name"], "modsys")
        self.assertIn("bin/modsys --version = modsys 0.1.0", proc.stdout)
        self.assertEqual(list(self.pub.rglob("__pycache__")), [])
        self.assertNotIn("push", (self.base / "git.log").read_text().split())
        self.assertNotIn("example-org", git(self.engine, "log", "-p", "HEAD~2..HEAD"))  # D13
        self.assertNotIn("example-org", git(self.pub, "log", "--all", "--format=%B"))

    def files(self, root: Path) -> dict:
        return {p.relative_to(root).as_posix(): (p.stat().st_mode & 0o777, p.read_bytes())
                for p in root.rglob("*") if p.is_file()}

    def test_push_only_with_push(self):
        remotes = {}
        for label, repo in (("engine", self.engine), ("publish", self.pub)):
            remotes[label] = self.base / f"{label}.git"
            subprocess.run(["git", "init", "-q", "--bare", str(remotes[label])], check=True)
            git(repo, "remote", "add", "origin", str(remotes[label]))
        git(self.engine, "push", "-q", "origin", "main")
        before = {k: git(r, "for-each-ref") for k, r in remotes.items()}
        self.assert_ok(self.release("stable"))
        self.assertEqual({k: git(r, "for-each-ref") for k, r in remotes.items()}, before)
        self.assertNotIn(" push", " " + (self.base / "git.log").read_text())
        git(self.engine, "tag", "-d", "v0.1.0")  # a second stable run to push: 0.1.1
        proc = self.release("stable", "--push")
        self.assert_ok(proc)
        self.assertEqual(sorted(git(remotes["publish"], "for-each-ref", "--format=%(refname)")
                                .split()),
                         ["refs/heads/stable", "refs/tags/modsys--v0.1.1",
                          "refs/tags/modsys-qa--v0.1.1", "refs/tags/modsys-ui--v0.1.1",
                          "refs/tags/v0.1.1"])
        self.assertEqual(sorted(git(remotes["engine"], "for-each-ref", "--format=%(refname)")
                                .split()), ["refs/heads/main", "refs/tags/v0.1.1"])
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
        before = (self.state(self.engine), self.state(self.pub))
        proc = self.release("stable", "--push")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--push needs claude on PATH", proc.stderr)
        self.assertEqual((self.state(self.engine), self.state(self.pub)), before)


class OwnershipTest(ReleaseRepo):  # P6-AC-016 (SI-17), P6-AC-021
    def test_foreign_content_is_kept(self):
        git(self.pub, "checkout", "-q", "-b", "dev")
        files = {
            "plugins/other-tool/plugin.json": '{"name": "other-tool"}\n',
            "plugins/modsys-extra/README.md": "not ours\n",
            "plugins/modsys/old.txt": "stale\n",
            ".claude-plugin/marketplace.json": json.dumps({"name": "x", "owner": {"name": "y"},
                                                           "plugins": [{"name": "other-tool",
                                                                        "source": "./plugins/"
                                                                                  "other-tool"}]}),
            ".agents/plugins/marketplace.json": json.dumps({"name": "x", "plugins": [
                {"name": "other-tool", "source": {"source": "local",
                                                  "path": "./plugins/other-tool"}}]}),
            "README.md": "# Plugins\n\nIntro text.\n\n<!-- modsys:begin -->\nold\n"
                         "<!-- modsys:end -->\n\nOutro text.\n",
            "CHANGELOG.md": "# Changes\n\n## other-tool\n\n- 1.0.0\n"}
        for rel, text in files.items():
            (self.pub / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.pub / rel).write_text(text)
        git(self.pub, "add", "-A")
        git(self.pub, "commit", "-q", "-m", "foreign")
        proc = self.release("dev")
        self.assert_ok(proc)
        self.assertFalse((self.pub / "plugins/modsys/old.txt").exists())
        for rel in ("plugins/other-tool/plugin.json", "plugins/modsys-extra/README.md"):
            self.assertEqual((self.pub / rel).read_text(), files[rel])
        for rel in (".claude-plugin/marketplace.json", ".agents/plugins/marketplace.json"):
            doc = json.loads((self.pub / rel).read_text())
            self.assertEqual(doc["plugins"][0], json.loads(files[rel])["plugins"][0])
            self.assertEqual([e["name"] for e in doc["plugins"]],
                             ["other-tool", "modsys", "modsys-qa", "modsys-ui"])
        readme = (self.pub / "README.md").read_text()
        self.assertTrue(readme.startswith("# Plugins\n\nIntro text.\n\n<!-- modsys:begin -->\n"))
        self.assertTrue(readme.endswith("<!-- modsys:end -->\n\nOutro text.\n"))
        self.assertNotIn("\nold\n", readme)
        log = (self.pub / "CHANGELOG.md").read_text()
        self.assertTrue(log.startswith(files["CHANGELOG.md"]))
        self.assertEqual(log.count("(dev): engine "), 1)
        written = git(self.pub, "show", "--name-only", "--format=", "HEAD").split()
        for rel in written:
            text = (self.pub / rel).read_bytes() if (self.pub / rel).is_file() else b""
            for bad in (*MACHINE_PATHS, str(self.base), str(self.tmpdir),
                        self.env["MODSYS_GUARD"]):
                self.assertNotIn(bad.encode(), text, rel)
            if rel != "README.md":
                self.assertNotIn(b"example-org", text, rel)  # D13: the README section only
        self.assertIn("example-org", readme)
        self.assertNotIn("example-org", git(self.pub, "log", "-1", "--format=%B"))

    def test_the_organisation_anywhere_in_the_engine(self):
        doc = self.engine / "modsys/defaults/templates/roles/po.md"
        original = doc.read_text()
        doc.write_text(original + "\nSee example-org/modsys.\n")
        proc = self.release("dev")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("appears in the engine: file modsys/defaults/templates/roles/po.md",
                      proc.stderr)
        git(self.engine, "commit", "-q", "-am", "planted")
        doc.write_text(original)
        git(self.engine, "commit", "-q", "-am", "removed")
        proc = self.release("dev")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("appears in the engine: history", proc.stderr)


class NoopTest(ReleaseRepo):  # P6-AC-029
    def test_twice_then_a_change(self):
        self.assert_ok(self.release("dev"))
        before = self.state(self.pub)
        proc = self.release("dev")
        self.assert_ok(proc)
        self.assertIn("nothing to release", proc.stdout)
        self.assertEqual(self.state(self.pub), before)
        first = git(self.pub, "log", "--format=%s", "dev").splitlines()
        skill = self.engine / "modsys/defaults/packs/ui/skills/designer-review/SKILL.md"
        skill.write_text(skill.read_text() + "\nOne more line.\n")
        git(self.engine, "commit", "-q", "-am", "a skill changed")
        proc = self.release("dev")
        self.assert_ok(proc)
        after = git(self.pub, "log", "--format=%s", "dev").splitlines()
        self.assertEqual(after[1:], first)
        self.assertNotEqual(after[0], first[0])
        self.assertRegex(after[0], r"^release modsys 0\.1\.0-dev\.h[0-9a-f]{8} \(dev\)$")

    def test_stable_again_is_refused(self):
        self.assert_ok(self.release("stable"))
        subprocess.run(["git", "-C", str(self.engine), "reset", "-q", "--hard", "HEAD~1"],
                       check=True)  # back at the 0.1.0 release commit: v0.1.0 exists
        proc = self.release("stable")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("v0.1.0 already exists", proc.stderr)


class RefusalTest(ReleaseRepo):  # P6-AC-030 (SI-1, SI-16, SI-17)
    def refused(self, *argv: str, channel: str = "stable", env: dict | None = None,
                slug: str = SLUG) -> str:
        before = (self.state(self.engine), self.state(self.pub))
        proc = self.release(channel, *argv, env=env, slug=slug)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertEqual((self.state(self.engine), self.state(self.pub)), before)
        self.assertEqual(list(self.tmpdir.iterdir()), [])
        return proc.stderr

    def test_the_guard(self):
        self.assertIn("MODSYS_GUARD is not set", self.refused(env={"MODSYS_GUARD": ""}))
        self.assertIn("MODSYS_GUARD: /nonexistent/guard.py not found",
                      self.refused(env={"MODSYS_GUARD": "/nonexistent/guard.py"}))
        err = self.refused(env={"FAKE_GUARD_HIT": str(self.engine)})
        self.assertIn("the leak guard found 2 hit(s) in the engine", err)
        self.assertIn("LEAK  'secret'  in file a.md", err)  # the operator's terminal only
        self.assertIn("the leak guard failed on the engine (exit 2): guard: error: planted",
                      self.refused(env={"FAKE_GUARD_ERROR": "1"}))
        err = self.refused(env={"FAKE_GUARD_HIT": "modsys-release-build-"})
        self.assertIn("in the build directory", err)
        vendored = self.engine / "dist/guard.py"  # git-ignored: the tree stays clean
        vendored.parent.mkdir()
        vendored.write_text(GUARD)
        self.assertIn("MODSYS_GUARD points into the engine",
                      self.refused(env={"MODSYS_GUARD": str(vendored)}))

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
        git(self.engine, "tag", "v0.1.0")
        self.assertIn("v0.1.0 already exists in the engine", self.refused())
        git(self.engine, "tag", "-d", "v0.1.0")
        (self.pub / "x.txt").write_text("x\n")
        git(self.pub, "add", "x.txt")
        git(self.pub, "commit", "-q", "-m", "x")
        for tag in ("v0.1.0", "modsys-ui--v0.1.0"):
            git(self.pub, "tag", tag)
            self.assertIn(f"{tag} already exists in the publish repo", self.refused())
            git(self.pub, "tag", "-d", tag)

    def test_flags(self):
        self.claude_on_path(False)
        self.assertIn("--push needs claude on PATH", self.refused("--push"))
        self.claude_on_path(True)
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

    def test_an_unknown_flag(self):  # P6-AC-033
        proc = run_tool(self.engine, "release", "--frobnicate", env=self.env)
        self.assertEqual((proc.returncode, proc.stdout), (2, ""))
        self.assertIn("usage:", proc.stderr)


class AllOrNothingTest(ReleaseRepo):  # P6-AC-031 (SI-16)
    def failed(self, channel: str, step: str, env: dict | None = None, code: int = 1) -> str:
        before = (self.state(self.engine), self.state(self.pub))
        proc = self.release(channel, env=env)
        self.assertEqual(proc.returncode, code, proc.stdout + proc.stderr)
        self.assertIn(step, proc.stderr)
        self.assertEqual((self.state(self.engine), self.state(self.pub)), before)
        self.assertEqual(list(self.tmpdir.iterdir()), [])
        return proc.stderr

    def test_each_failing_step(self):
        self.assert_ok(self.release("dev"))  # the publish repo has a dev branch to put back
        self.failed("stable", "step 5 validate failed", env={"FAKE_CLAUDE_FAIL": "validate"})
        self.failed("stable", "step 8 smoke install failed", env={"FAKE_CLAUDE_FAIL": "install"})
        for seam in ("6", "7"):  # in the middle of step 6; after the commit, before the tags
            self.failed("stable", "interrupted", env={"MODSYS_RELEASE_INTERRUPT": seam},
                        code=130)
        (self.engine / "tests/test_broken.py").write_text(
            "import unittest\n\n\nclass BrokenTest(unittest.TestCase):\n"
            "    def test_broken(self):\n        self.fail('planted')\n")
        git(self.engine, "add", "tests/test_broken.py")
        git(self.engine, "commit", "-q", "-m", "a failing test")
        self.failed("stable", "step 3 tests failed")

    def test_a_publish_file_the_release_cannot_use(self):
        git(self.pub, "checkout", "-q", "-b", "dev")
        (self.pub / ".claude-plugin").mkdir()
        (self.pub / ".claude-plugin/marketplace.json").write_text("{not json")
        outside = self.base / "outside.md"
        outside.write_text("not the release's\n")
        os.symlink(outside, self.pub / "CHANGELOG.md")
        git(self.pub, "add", "-A")
        git(self.pub, "commit", "-q", "-m", "damaged")
        err = self.failed("dev", "step 6 publish repo failed")
        self.assertIn(".claude-plugin/marketplace.json in the publish repo is not valid JSON",
                      err)
        (self.pub / ".claude-plugin/marketplace.json").write_text('{"name": "x", "plugins": []}')
        git(self.pub, "commit", "-q", "-am", "valid again")
        err = self.failed("dev", "step 6 publish repo failed")
        self.assertIn("CHANGELOG.md in the publish repo is not a regular file", err)
        self.assertEqual(outside.read_text(), "not the release's\n")


class SectionsTest(unittest.TestCase):  # P6-AC-016: only our sections change
    def test_the_readme_and_the_changelog(self):
        release = load_tool("release")
        begin, end = release.README_BEGIN, release.README_END
        self.assertEqual(release.replace_section("", begin, end, "body\n"),
                         f"{begin}\nbody\n{end}\n")
        self.assertEqual(release.replace_section("Intro.", begin, end, "body\n"),
                         f"Intro.\n\n{begin}\nbody\n{end}\n")
        self.assertEqual(release.replace_section(f"a\n{begin}\nold\n{end}\nz\n", begin, end,
                                                 "new\n"), f"a\n{begin}\nnew\n{end}\nz\n")
        log = release.changelog("# Changes\n\n- theirs\n", "- 0.1.0 (stable): engine abc")
        self.assertTrue(log.startswith("# Changes\n\n- theirs\n\n"))
        log = release.changelog(log, "- 0.1.1 (stable): engine def")
        self.assertIn("## modsys\n\n- 0.1.1 (stable): engine def\n- 0.1.0 (stable): engine "
                      "abc\n", log)
        self.assertEqual(log.count(release.LOG_BEGIN), 1)


if __name__ == "__main__":
    unittest.main()
