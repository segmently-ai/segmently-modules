"""`tools/release.py` (P6 D7, rows 6.2–6.5): a dev and a stable release into a local publish
repository, push only with --push, the publish repository's foreign content kept, the smoke
install through a `claude` stand-in (tests/claude_shim.py — never a model), no repository slug
outside the publish README, the refusals and all-or-nothing — the put-back restores what the
run wrote and nothing else; the release notes (P6.1 D6): the engine's CHANGELOG.md, a stable
release refused without notes under `## [Unreleased]`, the release commit dating them, the
publish entry carrying them. Each test releases a throw-away git copy of this engine (its unit
suite = three small tests, its E-A a stub, its CHANGELOG.md planted: the heavy steps are the
rehearsal's) with a stub leak guard."""
import datetime
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import engine_version, git, next_dev, next_release, release_version
from tests.plugin_helpers import ENGINE, copy_engine, default_signals, load_tool, run_tool

ENG = engine_version()  # the engine copies under test carry this version
REL = release_version(ENG)  # what the first stable run releases
NXT = next_release(ENG)  # the release after it
NXT_DEV = next_dev(ENG)  # the engine after the first stable run
SLUG = "example-org/modsys-plugins"
DATE = "2026-10-15"  # MODSYS_RELEASE_DATE of every run (SI-P61-9): never the clock
CHANGELOG = ("# Changelog\n\nAll notable changes to this copy are documented in this file.\n\n"
             "## [Unreleased]\n\n- First planted note.\n- Second planted note.\n\n"
             "## [0.0.1] - 2026-01-01\n\n- The first planted release.\n")  # the copies' notes
LOG_BEGIN, LOG_END = "<!-- modsys:changelog:begin -->", "<!-- modsys:changelog:end -->"
PLANT = """import os, subprocess, unittest
from pathlib import Path


class PlantTest(unittest.TestCase):
    def test_plant(self):  # what another terminal does while the suite runs (PLANT_IN set)
        for repo in filter(None, os.environ.get("PLANT_IN", "").split(os.pathsep)):
            (Path(repo) / "NOTES.txt").write_text("mine\\n")
            subprocess.run(["git", "-C", repo, "branch", "hotfix"], check=True)
            subprocess.run(["git", "-C", repo, "tag", "my-mark"], check=True)
"""
EXTRA = {"tests/__init__.py": "",
         "tests/test_ok.py": "import unittest\n\n\nclass OkTest(unittest.TestCase):\n"
                             "    def test_ok(self):\n        self.assertTrue(True)\n\n"
                             "    @unittest.skip('planted: the release shows the skip')\n"
                             "    def test_skipped(self):\n        pass\n",
         "tests/test_plant.py": PLANT,
         "evals/adoption/run_eval.py": "import sys\n\nprint('adoption eval: stub ok', "
                                       "file=sys.stderr)\n",
         "README.md": "# modsys (a test copy)\n", "CHANGELOG.md": CHANGELOG}
GUARD = """import os, signal, sys, time
target = sys.argv[sys.argv.index("--target") + 1]
mode = os.environ.get("FAKE_GUARD_MODE")
if os.environ.get("FAKE_GUARD_ERROR"):
    print("guard: error: planted", file=sys.stderr)
    sys.exit(2)
if mode == "crash":
    raise RuntimeError("boom")
if mode == "clean-exit-1":
    print("guard: CLEAN")
    sys.exit(1)
if mode == "no-verdict":
    print("all fine")
    sys.exit(0)
if mode == "hangup":  # the terminal closes while step 1 runs
    os.kill(os.getppid(), signal.SIGHUP)
    time.sleep(5)
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
CREDENTIALS = {"ANTHROPIC_API_KEY": "dummy-key", "ANTHROPIC_AUTH_TOKEN": "dummy-token",
               "CLAUDE_CODE_OAUTH_TOKEN": "dummy-oauth"}  # never real: the release drops them
MACHINE_PATHS = ("/" + "Users/", "/" + "home/")  # joined here: this file holds no such path
STEPS = ["leak guard", "clean trees", "tests", "build", "validate", "publish repo", "commit",
         "smoke install"]
SKILL = "modsys/defaults/packs/ui/skills/designer-review/SKILL.md"
TAGS = ["modsys--v{0}", "modsys-qa--v{0}", "modsys-ui--v{0}", "v{0}"]


class ReleaseRepo(unittest.TestCase):
    """Every release runs through `run_tool`: SIGINT, SIGTERM and SIGHUP at their defaults in
    the release, however the suite itself was started (a detached suite ignores two of them)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name).resolve()
        self.engine = copy_engine(self.base / "engine", EXTRA,
                                  prefixes=("modsys/", "tools/", "tests/fixtures/bookshop/"))
        self.pub = self.base / "publish repo"  # a space: every printed command is quoted
        self.pub.mkdir()
        git(self.pub, "init", "-q", "-b", "main")
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.claude_on_path(True)
        self.real_git = shutil.which("git")
        self.git_wrapper()
        (self.bin / "gh").write_text(f'#!/bin/sh\necho "$*" >> "{self.base}/gh.log"\nexit 1\n')
        (self.bin / "gh").chmod(0o755)  # the release never calls it: no log may appear
        (self.base / "guard.py").write_text(GUARD)
        self.tmpdir = self.base / "tmp"
        self.tmpdir.mkdir()
        self.env = {**IDENTITY, **CREDENTIALS, "PATH": f"{self.bin}:/usr/bin:/bin",
                    "MODSYS_GUARD": str(self.base / "guard.py"),
                    "FAKE_CLAUDE_LOG": str(self.base / "claude.log"), "TMPDIR": str(self.tmpdir),
                    "MODSYS_PYTHON": sys.executable, "MODSYS_RELEASE_DATE": DATE,
                    # as under a git hook: the tools drop git's location variables
                    "GIT_INDEX_FILE": str(self.base / "another-index")}

    def tearDown(self):
        self._tmp.cleanup()

    def git_wrapper(self, snippet: str = "") -> None:
        """`git` on the release's PATH: logs every call, runs `snippet` (sh; `$real` is git,
        `$PPID` the release), then git itself."""
        (self.bin / "git").write_text(f'#!/bin/sh\necho "$*" >> "{self.base}/git.log"\n'
                                      f'real="{self.real_git}"\n{snippet}\nexec "$real" "$@"\n')
        (self.bin / "git").chmod(0o755)

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
                slug: str = SLUG, pub: Path | None = None) -> subprocess.CompletedProcess:
        return run_tool(self.engine, "release", "--publish-repo", str(pub or self.pub),
                        "--channel", channel, "--publish-slug", slug, *argv,
                        env={**self.env, **(env or {})})

    def state(self, repo: Path) -> tuple:
        """What all-or-nothing keeps: every ref with its object, HEAD, and what git status
        shows, ignored files too (git itself, no wrapper)."""
        def out(*args):
            return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                                  text=True).stdout
        return (out("status", "--porcelain", "--ignored"), out("rev-parse", "-q", "--verify",
                                                               "HEAD"),
                out("for-each-ref"), out("symbolic-ref", "-q", "HEAD"))

    def both(self) -> tuple:
        return self.state(self.engine), self.state(self.pub)

    def calls(self) -> list[dict]:
        log = self.base / "claude.log"
        return [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []

    def assert_ok(self, proc) -> None:
        self.assertEqual((proc.returncode, proc.stderr), (0, ""), proc.stdout)
        self.assertEqual(list(self.tmpdir.iterdir()), [])  # every temp directory removed

    def commit(self, repo: Path, rel: str, text: str, message: str) -> None:
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
        git(repo, "add", "--", rel)
        git(repo, "commit", "-q", "-m", message)

    def change_a_skill(self) -> None:
        skill = self.engine / SKILL
        self.commit(self.engine, SKILL, skill.read_text() + "\nOne more line.\n",
                    "a skill changed")

    def notes(self, *lines: str) -> None:
        """`lines` under the engine copy's `## [Unreleased]`, committed — what the next stable
        release needs once the last one has dated the notes (D6)."""
        text = (self.engine / "CHANGELOG.md").read_text()
        head = "## [Unreleased]\n\n"
        self.commit(self.engine, "CHANGELOG.md",
                    text.replace(head, head + "".join(f"{l}\n" for l in lines) + "\n", 1),
                    "notes")

    def remotes(self) -> dict[str, Path]:
        """A local bare `origin` for the engine copy and the publish repository."""
        made = {}
        for label, repo in (("engine", self.engine), ("publish", self.pub)):
            made[label] = self.base / f"{label}.git"
            subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(made[label])],
                           check=True)
            git(repo, "remote", "add", "origin", str(made[label]))
        git(self.engine, "push", "-q", "origin", "main")
        return made

    def log(self, repo: Path, ref: str) -> list[str]:
        return git(repo, "log", "--format=%s", ref).splitlines()

    def entries(self, branch: str) -> list[tuple]:
        """The modsys entries of the publish repository's CHANGELOG.md on `branch`, newest
        first: (version, channel, the engine commit its short sha names, its indented lines)."""
        text = git(self.pub, "show", f"{branch}:CHANGELOG.md")
        section = text.split(LOG_BEGIN + "\n", 1)[1].split(LOG_END, 1)[0]
        found = []
        for line in section.split("\n"):
            head = re.fullmatch(r"- (\S+) \((dev|stable)\): engine ([0-9a-f]{7,})", line)
            if head:
                found.append((head[1], head[2], git(self.engine, "rev-parse", head[3]), []))
            elif line.startswith("  "):
                found[-1][3].append(line[2:])
            else:
                self.assertIn(line, ("## modsys", ""), section)
        return found

    def refs(self, repo: Path) -> list[str]:
        return git(repo, "for-each-ref", "--format=%(refname)").split()


class RunTest(ReleaseRepo):  # P6-AC-014, 015, 017
    def test_dev_then_stable(self):
        engine_before = self.state(self.engine)
        proc = self.release("dev")
        self.assert_ok(proc)
        lines = proc.stdout.splitlines()
        self.assertEqual([re.match(r"step (\d) ([a-z ]+):", l).groups() for l in lines
                          if l.startswith("step ")],
                         [(str(n), name) for n, name in enumerate(STEPS, start=1)])
        self.assertRegex(proc.stdout, r"step 3 tests: Ran 3 tests in [\d.]+s, OK \(skipped=1\); "
                                      r"the adoption eval passed")  # the skip stays visible
        version = re.search(r"done: modsys (\S+) \(dev\)", proc.stdout).group(1)
        self.assertRegex(version, rf"^{re.escape(REL)}-dev\.h[0-9a-f]{{8}}$")
        self.assertEqual(self.state(self.engine), engine_before)  # dev: no commit, no tag
        self.assertFalse((self.engine / "tools/__pycache__").exists())
        self.assertEqual(self.log(self.pub, "dev"), [f"release modsys {version} (dev)"])
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
            for name in ("modsys", "modsys-ui", "modsys-qa"):
                self.assertEqual(self.files(build / name), self.files(self.pub / "plugins" / name))
            self.assertEqual(self.committed("dev"), {
                f"plugins/{name}/{rel}": "100755" if mode & 0o111 else "100644"
                for name in ("modsys", "modsys-ui", "modsys-qa")
                for rel, (mode, _) in self.files(build / name).items()})
        claude = json.loads((self.pub / ".claude-plugin/marketplace.json").read_text())
        codex = json.loads((self.pub / ".agents/plugins/marketplace.json").read_text())
        self.assertEqual((claude["name"], codex["name"]), ("modsys-dev", "modsys-dev"))
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
        self.assertEqual(installs, ["modsys-ui@modsys-dev", "modsys-qa@modsys-dev"])
        self.assertIn(f"bin/modsys --version = modsys {ENG}", proc.stdout)

        proc = self.release("stable")
        self.assert_ok(proc)
        self.assertEqual(git(self.engine, "log", "--format=%s", "-3").splitlines(),
                         [f"start modsys {NXT_DEV}", f"release modsys {REL}", "engine"])
        self.assertEqual(git(self.engine, "tag", "--points-at", "HEAD~1").split(), [f"v{REL}"])
        self.assertIn(f'__version__ = "{REL}"', git(self.engine, "show",
                                                   "HEAD~1:modsys/__init__.py"))
        self.assertIn(f'version = "{REL}"', git(self.engine, "show", "HEAD~1:pyproject.toml"))
        self.assertIn(f'version = "{NXT_DEV}"', (self.engine / "pyproject.toml").read_text())
        # ONE commit (P6-AC-015): a channel never starts on the other channel's release
        self.assertEqual(self.log(self.pub, "stable"), [f"release modsys {REL} (stable)"])
        self.assertEqual(sorted(git(self.pub, "tag", "--points-at", "stable").split()),
                         [t.format(REL) for t in TAGS])
        self.assertEqual(self.log(self.pub, "dev"), [f"release modsys {version} (dev)"])
        self.assertEqual(git(self.pub, "symbolic-ref", "HEAD").strip(), "refs/heads/stable")
        self.assertEqual(json.loads((self.pub / ".claude-plugin/marketplace.json")
                                    .read_text())["name"], "modsys")
        log = (self.pub / "CHANGELOG.md").read_text()
        self.assertIn(f"- {REL} (stable): engine ", log)
        self.assertNotIn("(dev)", log)  # the channel's own entries only
        # P61-AC-021: the release commit dates the notes, the start commit leaves them, the
        # publish entry carries them (the engine sha = the release commit)
        self.assertEqual(git(self.engine, "show", "HEAD~1:CHANGELOG.md"), CHANGELOG.replace(
            "## [Unreleased]\n\n", f"## [Unreleased]\n\n## [{REL}] - {DATE}\n\n", 1))
        self.assertEqual(git(self.engine, "show", "--name-only", "--format=", "HEAD~1").split(),
                         ["CHANGELOG.md", "modsys/__init__.py", "pyproject.toml"])
        self.assertEqual(git(self.engine, "show", "--name-only", "--format=", "HEAD").split(),
                         ["modsys/__init__.py", "pyproject.toml"])
        self.assertEqual((self.engine / "CHANGELOG.md").read_text(),
                         git(self.engine, "show", "HEAD~1:CHANGELOG.md"))
        self.assertEqual(self.entries("stable"), [(REL, "stable", git(
            self.engine, "rev-parse", "HEAD~1"), ["- First planted note.",
                                                  "- Second planted note."])])
        self.assertTrue(log.startswith(f"{LOG_BEGIN}\n## modsys\n\n- {REL} (stable): engine "))
        self.assertTrue(log.endswith("\n  - First planted note.\n  - Second planted note.\n"
                                     f"{LOG_END}\n"), log)
        self.assertIn(f"step 4 build: modsys {REL} (modsys, modsys-ui, modsys-qa); CHANGELOG.md "
                      f"[Unreleased] dated [{REL}] - {DATE}\n", proc.stdout)
        self.assertIn(f"bin/modsys --version = modsys {REL}", proc.stdout)
        self.assertIn(f"  git -C {shlex.quote(str(self.pub))} push --atomic origin "
                      "refs/heads/stable "
                      f"refs/tags/v{REL} refs/tags/modsys--v{REL} refs/tags/modsys-ui--v{REL} "
                      f"refs/tags/modsys-qa--v{REL}\n  git -C {self.engine} push --atomic "
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
        self.assertEqual(stable, [f"release modsys {REL} (stable)", "the owner's content"])
        self.assertRegex(dev[0], rf"^release modsys {re.escape(REL)}-dev\.h[0-9a-f]{{8}} \(dev\)$")
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
                         ["refs/heads/stable", f"refs/tags/modsys--v{NXT}",
                          f"refs/tags/modsys-qa--v{NXT}", f"refs/tags/modsys-ui--v{NXT}",
                          f"refs/tags/v{NXT}"])
        self.assertEqual(sorted(self.refs(remotes["engine"])),
                         ["refs/heads/main", f"refs/tags/v{NXT}"])
        self.assertIn(f"push: publish repo stable, v{NXT}, modsys--v{NXT}, modsys-ui--v{NXT}, "
                      f"modsys-qa--v{NXT}; engine main, v{NXT}\n", proc.stdout)
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
        (self.pub / ".gitignore").write_text("bin/\n")  # the owner's: it matches bin/modsys
        git(self.pub, "add", "--", "README.md", "CHANGELOG.md", ".gitignore")
        git(self.pub, "commit", "-q", "-m", "the owner's files")
        git(self.pub, "config", "core.fileMode", "false")
        (self.base / "ignore").write_text("runtime/\n")  # the maintainer's own excludes file
        (self.base / "gitconfig").write_text(f"[core]\n\texcludesFile = {self.base}/ignore\n")
        env = {"GIT_CONFIG_GLOBAL": str(self.base / "gitconfig")}
        self.assert_ok(self.release("dev", env=env))
        rows = git(self.pub, "ls-tree", "-r", "dev", "--", "plugins").splitlines()
        held = {row.split("\t")[1]: row.split()[0] for row in rows}
        self.assertEqual(held["plugins/modsys/bin/modsys"], "100755")
        self.assertEqual([p for p, mode in held.items() if mode != "100644"],
                         ["plugins/modsys/bin/modsys"])
        on_disk = sorted(p.relative_to(self.pub).as_posix()
                         for p in (self.pub / "plugins").rglob("*") if p.is_file())
        self.assertEqual(sorted(held), on_disk)  # every built file is in the commit
        self.assertGreater(sum(p.startswith("plugins/modsys/runtime/") for p in held), 50)
        for rel, ours in (("README.md", "<!-- modsys:begin -->"),
                          ("CHANGELOG.md", "<!-- modsys:changelog:begin -->")):
            data = (self.pub / rel).read_bytes()  # a CRLF file stays CRLF, inside our section
            self.assertIn(ours.encode(), data)  # too; the owner's bytes are unchanged
            self.assertNotIn(b"\n", data.replace(b"\r\n", b""), rel)
        self.assertTrue((self.pub / "README.md").read_bytes().startswith(
            b"# Plugins\r\n\r\nIntro.\r\n\r\n<!-- modsys:begin -->\r\n## modsys\r\n"))
        self.assertTrue((self.pub / "CHANGELOG.md").read_bytes().startswith(
            b"# Changes\r\n\r\n- theirs\r\n\r\n<!-- modsys:changelog:begin -->\r\n"))
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


class CloneTest(ReleaseRepo):  # final review I-3: a fresh clone of the publish repository
    def test_a_channel_that_exists_only_on_origin(self):
        self.commit(self.pub, "README.md", "# Plugins\n", "root")
        bare = self.remotes()["publish"]
        self.assert_ok(self.release("dev"))
        git(self.pub, "push", "-q", "origin", "main", "dev")
        clone = self.base / "clone"
        subprocess.run(["git", "clone", "-q", str(bare), str(clone)], check=True)
        self.assertEqual([r for r in self.refs(clone) if r.startswith("refs/heads/")],
                         ["refs/heads/main"])  # `dev` only as origin/dev
        before = self.state(clone)
        proc = self.release("dev", pub=clone)  # the engine's plugins are unchanged
        self.assert_ok(proc)
        self.assertIn("nothing to release", proc.stdout)
        self.assertEqual(self.state(clone), before)
        self.assertEqual(git(clone, "config", "--get-regexp", "^branch\\.").count("dev"), 0)
        self.assert_ok(self.release("stable"))  # the release, from the first clone
        git(self.pub, "push", "-q", "origin", "stable", "--tags")
        git(clone, "fetch", "-q", "--tags", "origin")
        self.notes("- The next release.")  # the first one dated the notes (D6)
        proc = self.release("stable", pub=clone)  # the next release, on top of what is published
        self.assert_ok(proc)
        self.assertEqual(self.log(clone, "stable"), [f"release modsys {NXT} (stable)",
                                                     f"release modsys {REL} (stable)", "root"])
        self.assertEqual(git(clone, "rev-parse", "stable~1"),
                         git(clone, "rev-parse", "origin/stable"))
        self.assertEqual(git(clone, "config", "branch.stable.merge").strip(),
                         "refs/heads/stable")  # it tracks origin's
        git(clone, "push", "-q", "--atomic", "origin", "refs/heads/stable",
            *(f"refs/tags/{t.format(NXT)}" for t in TAGS))  # a fast-forward: accepted
        git(self.pub, "fetch", "-q", "origin")  # the first clone is now behind origin/stable
        self.notes("- One more release.")  # step 1 passes: step 2 is what refuses
        before = self.both()
        proc = self.release("stable")
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("the publish repo's branch stable is behind origin/stable or has "
                      "diverged from it — run `git pull` there first", proc.stderr)
        self.assertEqual(self.both(), before)


class PushTest(ReleaseRepo):  # final review I-4, M-9: the push is never put back
    def test_a_failed_push_leaves_the_release_and_names_the_commands(self):
        self.remotes()
        git(self.pub, "remote", "set-url", "origin", str(self.base / "missing.git"))
        proc = self.release("stable", "--push")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("release.py: step 10 push failed: publish repo: git push --atomic origin "
                      "refs/heads/stable", proc.stderr)
        self.assertIn("— nothing is put back: the release is committed and tagged locally; "
                      "pushed: nothing; left to push by hand:\n"
                      f"  git -C {shlex.quote(str(self.pub))} push --atomic origin "
                      f"refs/heads/stable refs/tags/v{REL} ", proc.stderr)
        self.assertIn(f"\n  git -C {self.engine} push --atomic origin refs/heads/main "
                      f"refs/tags/v{REL}\n", proc.stderr)
        self.assertNotIn("as they were", proc.stderr)
        self.assertEqual(git(self.engine, "log", "--format=%s", "-3").splitlines(),
                         [f"start modsys {NXT_DEV}", f"release modsys {REL}", "engine"])
        self.assertEqual(git(self.engine, "tag", "-l").split(), [f"v{REL}"])
        self.assertEqual(sorted(git(self.pub, "tag", "--points-at", "stable").split()),
                         [t.format(REL) for t in TAGS])
        self.assertEqual(list(self.tmpdir.iterdir()), [])

    def test_ctrl_c_during_the_engine_push_resets_nothing(self):
        remotes = self.remotes()
        self.git_wrapper(f'case "$*" in *"-C {self.engine} push "*) '  # the operator's Ctrl-C
                         'kill -INT $PPID; sleep 5; exit 1 ;; esac')  # while this push runs
        proc = self.release("stable", "--push")
        self.assertEqual(proc.returncode, 130, proc.stdout + proc.stderr)
        self.assertIn("release.py: interrupted during the push — nothing is put back", proc.stderr)
        self.assertIn("pushed: publish repo; left to push by hand:\n"
                      f"  git -C {self.engine} push --atomic origin refs/heads/main "
                      f"refs/tags/v{REL}\n", proc.stderr)
        self.assertNotIn(f"git -C {shlex.quote(str(self.pub))} push", proc.stderr)
        self.assertEqual(sorted(self.refs(remotes["publish"])),
                         ["refs/heads/stable"] + [f"refs/tags/{t.format(REL)}" for t in TAGS])
        self.assertEqual(self.refs(remotes["engine"]), ["refs/heads/main"])
        self.assertEqual(git(self.engine, "log", "--format=%s", "-3").splitlines(),
                         [f"start modsys {NXT_DEV}", f"release modsys {REL}", "engine"])
        self.assertEqual(git(self.engine, "tag", "-l").split(), [f"v{REL}"])
        self.assertEqual(self.log(self.pub, "stable"), [f"release modsys {REL} (stable)"])
        self.assertEqual(git(self.pub, "rev-parse", "stable"),
                         git(remotes["publish"], "rev-parse", "stable"))


class OwnershipTest(ReleaseRepo):  # P6-AC-016 (SI-17), P6-AC-021
    def test_foreign_content_is_kept(self):
        git(self.pub, "checkout", "-q", "-b", "dev")
        extra = {"name": "modsys-extra", "source": "./plugins/modsys-extra"}
        files = {
            "plugins/other-tool/plugin.json": '{"name": "other-tool"}\n',
            "plugins/modsys-extra/README.md": "not ours\n",
            "plugins/modsys/old.txt": "stale\n",
            ".claude-plugin/marketplace.json": json.dumps({"name": "x", "owner": {"name": "y"},
                                                           "plugins": [{"name": "other-tool",
                                                                        "source": "./plugins/"
                                                                                  "other-tool"},
                                                                       extra]}),
            ".agents/plugins/marketplace.json": json.dumps({"name": "x", "plugins": [
                {"name": "other-tool", "source": {"source": "local",
                                                  "path": "./plugins/other-tool"}},
                {"name": "modsys-extra", "source": {"source": "local",
                                                    "path": "./plugins/modsys-extra"}}]}),
            "README.md": "# Plugins\n\nIntro text.\n\n<!-- modsys:begin -->\nold\n"
                         "<!-- modsys:end -->\n\nOutro text.\n",
            "CHANGELOG.md": "# Changes\n\n## other-tool\n\n- 1.0.0\n"}
        for rel, text in files.items():
            (self.pub / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.pub / rel).write_text(text)
        git(self.pub, "add", "--", *files)
        git(self.pub, "commit", "-q", "-m", "foreign")
        proc = self.release("dev")
        self.assert_ok(proc)
        self.assertFalse((self.pub / "plugins/modsys/old.txt").exists())
        for rel in ("plugins/other-tool/plugin.json", "plugins/modsys-extra/README.md"):
            self.assertEqual((self.pub / rel).read_text(), files[rel])
        for rel in (".claude-plugin/marketplace.json", ".agents/plugins/marketplace.json"):
            doc = json.loads((self.pub / rel).read_text())
            self.assertEqual(doc["plugins"][:2], json.loads(files[rel])["plugins"])
            self.assertEqual([e["name"] for e in doc["plugins"]],
                             ["other-tool", "modsys-extra", "modsys", "modsys-qa", "modsys-ui"])
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

    def test_the_organisation_scan_names_places_not_hashes(self):
        git(self.engine, "tag", "-a", "a-note", "-m", "as agreed with tag-org")
        proc = self.release("dev", slug="tag-org/modsys-plugins")  # an annotated tag's message
        self.assertEqual(proc.returncode, 2)
        self.assertIn("appears in the engine: history — no repository slug", proc.stderr)
        proc = self.release("dev", slug="a/modsys-plugins")  # in almost every file: one line
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stderr.count("\n"), 1)
        self.assertEqual(proc.stderr.count("file "), 10)
        self.assertRegex(proc.stderr, r"file \S+ … and \d+ more — no repository slug")
        self.assertLess(len(proc.stderr), 900)
        (self.pub / "scratch.txt").write_text("x\n")  # step 2 refuses: step 1 has passed
        commit = git(self.engine, "rev-parse", "HEAD").strip()
        blob = re.search(r"^index 0+\.\.([0-9a-f]{7,})", git(
            self.engine, "log", "-p", "--format=%B", "--", "pyproject.toml"), re.M).group(1)
        for hexlike in (commit[:12], blob):  # only a commit id / an `index` line holds it
            with self.subTest(organisation=hexlike):
                proc = self.release("dev", slug=f"{hexlike}/modsys-plugins")
                self.assertEqual(proc.returncode, 2)
                self.assertIn("the publish repo is dirty: scratch.txt", proc.stderr)


class NoopTest(ReleaseRepo):  # P6-AC-029
    def test_twice_then_a_change(self):
        self.assert_ok(self.release("dev"))
        before = self.state(self.pub)
        proc = self.release("dev")
        self.assert_ok(proc)
        self.assertIn("nothing to release", proc.stdout)
        self.assertEqual(self.state(self.pub), before)
        first = self.log(self.pub, "dev")
        self.change_a_skill()
        proc = self.release("dev")
        self.assert_ok(proc)
        after = self.log(self.pub, "dev")
        self.assertEqual(after[1:], first)
        self.assertNotEqual(after[0], first[0])
        self.assertRegex(after[0], rf"^release modsys {re.escape(REL)}-dev\.h[0-9a-f]{{8}} \(dev\)$")

    def test_stable_again_is_refused(self):
        self.assert_ok(self.release("stable"))
        subprocess.run(["git", "-C", str(self.engine), "reset", "-q", "--hard", "HEAD~1"],
                       check=True)  # back at the release commit: its tag exists
        self.notes("- Again.")  # notes: step 1 passes, the tag is what refuses
        proc = self.release("stable")
        self.assertEqual(proc.returncode, 2)
        self.assertIn(f"v{REL} already exists", proc.stderr)


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
        err = self.refused(channel="dev", env={"MODSYS_GUARD": str(script)})
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
        for tag in (f"v{REL}", f"modsys-ui--v{REL}"):
            git(self.pub, "tag", tag)
            self.assertIn(f"{tag} already exists in the publish repo", self.refused())
            git(self.pub, "branch", tag)  # a branch of the same name hides nothing
            self.assertIn(f"{tag} already exists in the publish repo", self.refused())
            git(self.pub, "branch", "-q", "-D", tag)
            git(self.pub, "tag", "-d", tag)

    def test_a_version_without_devn_and_a_symlinked_directory(self):  # final M-7, M-5
        outside = self.base / "outside"
        (outside / "modsys").mkdir(parents=True)
        (outside / "modsys/THEIRS.txt").write_text("not the release's\n")
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
        self.assertEqual(sorted(p.name for p in outside.rglob("*")), ["THEIRS.txt", "modsys"])
        git(self.pub, "rm", "-q", "--", ".agents/plugins")
        git(self.pub, "commit", "-q", "-m", "no file")
        for rel, old, new in (("modsys/__init__.py", f'__version__ = "{ENG}"',
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


class AllOrNothingTest(ReleaseRepo):  # P6-AC-031 (SI-16)
    def failed(self, channel: str, step: str, env: dict | None = None, code: int = 1) -> str:
        before = self.both()
        notes = (self.engine / "CHANGELOG.md").read_bytes()
        proc = self.last = self.release(channel, env=env)
        self.assertEqual(proc.returncode, code, proc.stdout + proc.stderr)
        self.assertIn(step, proc.stderr)
        self.assertTrue(proc.stderr.startswith("release.py: "), proc.stderr)  # no traceback
        self.assertTrue(proc.stderr.rstrip().endswith("both repositories are as they were"),
                        proc.stderr)
        self.assertEqual(self.both(), before)
        # P61-AC-036: a stable run past step 4 had dated the notes — the put-back restores them
        self.assertEqual((self.engine / "CHANGELOG.md").read_bytes(), notes)
        self.assertEqual(list(self.tmpdir.iterdir()), [])
        return proc.stderr

    def test_each_failing_step(self):
        self.assert_ok(self.release("dev"))  # the publish repo has a dev branch to put back
        git(self.pub, "switch", "-q", "-c", "main")  # and is on another one,
        self.commit(self.pub, "notes.md", "the owner's\n", "main work")
        for name in ("dev", "stable"):  # with a tag named like each channel branch
            git(self.pub, "tag", name)
        hook = self.engine / ".git/hooks/commit-msg"  # FAIL_COMMIT: that commit is refused
        hook.write_text('#!/bin/sh\n[ -n "$FAIL_COMMIT" ] && grep -q "^$FAIL_COMMIT" "$1" && '
                        'exit 1\nexit 0\n')
        hook.chmod(0o755)
        self.change_a_skill()
        self.failed("dev", "step 8 smoke install failed", env={"FAKE_CLAUDE_FAIL": "install"})
        self.failed("stable", "step 4 build failed", env={"FAIL_COMMIT": "release modsys"})
        self.failed("stable", "step 5 validate failed", env={"FAKE_CLAUDE_FAIL": "validate"})
        self.failed("stable", "step 8 smoke install failed", env={"FAKE_CLAUDE_FAIL": "install"})
        err = self.failed("stable", "step 8 smoke install failed",
                          env={"FAKE_CLAUDE_FAIL": "details"})  # whole names, not substrings
        self.assertIn("claude plugin details modsys does not name module-", err)
        self.failed("stable", "step 9 next version failed", env={"FAIL_COMMIT": "start modsys"})
        for seam in ("6", "7"):  # in the middle of step 6; after the commit, before the tags
            self.failed("stable", "interrupted", env={"MODSYS_RELEASE_INTERRUPT": seam},
                        code=130)  # P61-AC-036: the notes it dated in step 4 are put back
            self.assertIn(f"CHANGELOG.md [Unreleased] dated [{REL}] - {DATE}\n",
                          self.last.stdout)
        (self.engine / "tests/test_broken.py").write_text(
            "import unittest\n\n\nclass BrokenTest(unittest.TestCase):\n"
            "    def test_broken(self):\n        self.fail('planted')\n")
        git(self.engine, "add", "tests/test_broken.py")
        git(self.engine, "commit", "-q", "-m", "a failing test")
        self.failed("stable", "step 3 tests failed")

    def test_an_empty_repository_and_a_detached_head(self):
        (self.pub / ".git/info/exclude").write_text("keep.me\n")
        (self.pub / "keep.me").write_text("ignored, the owner's\n")
        self.failed("dev", "step 8 smoke install failed", env={"FAKE_CLAUDE_FAIL": "install"})
        self.assertEqual(sorted(p.name for p in self.pub.iterdir()), [".git", "keep.me"])
        self.assert_ok(self.release("dev"))
        git(self.pub, "checkout", "-q", "--detach")
        self.failed("stable", "interrupted", env={"MODSYS_RELEASE_INTERRUPT": "7"}, code=130)
        self.assertEqual((self.pub / "keep.me").read_text(), "ignored, the owner's\n")

    def test_a_publish_file_the_release_cannot_use(self):
        git(self.pub, "checkout", "-q", "-b", "dev")
        (self.pub / ".claude-plugin").mkdir()
        (self.pub / ".claude-plugin/marketplace.json").write_text("{not json")
        outside = self.base / "outside.md"
        outside.write_text("not the release's\n")
        os.symlink(outside, self.pub / "CHANGELOG.md")
        lost = ("# Plugins\n\n<!-- modsys:begin -->\nold text\n\n## Other tool\n\n"
                "KEEP THIS PARAGRAPH.\n")  # the end marker was lost in a hand edit
        (self.pub / "README.md").write_text(lost)
        git(self.pub, "add", "--", ".claude-plugin", "CHANGELOG.md", "README.md")
        git(self.pub, "commit", "-q", "-m", "damaged")
        err = self.failed("dev", "step 6 publish repo failed")
        self.assertIn(".claude-plugin/marketplace.json in the publish repo is not valid JSON",
                      err)
        (self.pub / ".claude-plugin/marketplace.json").write_text('{"name": "x", "plugins": {}}')
        git(self.pub, "commit", "-q", "-am", "valid JSON, no list")
        err = self.failed("dev", "step 6 publish repo failed")
        self.assertIn(".claude-plugin/marketplace.json: plugins is not a list", err)
        (self.pub / ".claude-plugin/marketplace.json").write_text('{"name": "x", "plugins": []}')
        git(self.pub, "commit", "-q", "-am", "valid again")
        err = self.failed("dev", "step 6 publish repo failed")
        self.assertIn("README.md: the markers of the modsys section are damaged (1 "
                      "`<!-- modsys:begin -->`, 0 `<!-- modsys:end -->`)", err)
        self.assertEqual((self.pub / "README.md").read_text(), lost)
        (self.pub / "README.md").write_text("# Plugins\n")
        git(self.pub, "commit", "-q", "-am", "markers gone")
        err = self.failed("dev", "step 6 publish repo failed")
        self.assertIn("CHANGELOG.md in the publish repo is not a regular file", err)
        self.assertEqual(outside.read_text(), "not the release's\n")

    def test_a_symlinked_directory_on_the_channel_branch(self):  # re-review N-1
        outside = self.base / "outside"
        (outside / "modsys").mkdir(parents=True)
        (outside / "modsys/THEIRS.txt").write_text("not the release's\n")
        self.commit(self.pub, "README.md", "# Plugins\n", "root")
        git(self.pub, "switch", "-q", "-c", "dev")
        os.symlink(outside, self.pub / "plugins")  # on `dev` only: step 2 sees `main`
        git(self.pub, "add", "--", "plugins")
        git(self.pub, "commit", "-q", "-m", "plugins is a link")
        git(self.pub, "switch", "-q", "main")
        err = self.failed("dev", "step 6 publish repo failed")  # a local dev, not checked out
        self.assertIn("plugins is a symlink or a file on the dev branch of the publish repo", err)
        bare = self.base / "clone-origin.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
        git(self.pub, "remote", "add", "origin", str(bare))
        git(self.pub, "push", "-q", "origin", "main", "dev")
        clone = self.base / "clone"  # dev only as origin/dev
        subprocess.run(["git", "clone", "-q", str(bare), str(clone)], check=True,
                       capture_output=True)
        before = self.state(clone)
        proc = self.release("dev", pub=clone)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("step 6 publish repo failed: plugins is a symlink or a file on the dev "
                      "branch", proc.stderr)
        self.assertTrue(proc.stderr.rstrip().endswith("both repositories are as they were"))
        self.assertEqual(self.state(clone), before)
        self.assertEqual(sorted(p.relative_to(outside).as_posix() for p in outside.rglob("*")),
                         ["modsys", "modsys/THEIRS.txt"])  # nothing written outside
        self.assertEqual((outside / "modsys/THEIRS.txt").read_text(), "not the release's\n")

    def planted(self, repo: Path) -> list:
        return [(repo / "NOTES.txt").is_file(),
                sorted(r for r in self.refs(repo) if r.endswith(("/hotfix", "/my-mark")))]

    def test_what_appears_beside_the_run_is_never_put_back(self):  # final review I-2
        kept = [True, ["refs/heads/hotfix", "refs/tags/my-mark"]]
        self.commit(self.pub, "README.md", "# Plugins\n", "root")
        before = self.state(self.pub)  # 1. in the engine, while step 3 runs: a refusal at the
        proc = self.release("stable", env={"PLANT_IN": str(self.engine)})  # first write there
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("release.py: error: the engine changed since step 2 checked it: "
                      "refs/heads/hotfix appeared, refs/tags/my-mark appeared, NOTES.txt — "
                      "nothing was written to it", proc.stderr)
        self.assertEqual(self.planted(self.engine), kept)
        self.assertEqual(self.log(self.engine, "main"), ["engine"])
        self.assertEqual(self.state(self.pub), before)
        (self.engine / "NOTES.txt").unlink()
        git(self.engine, "branch", "-q", "-D", "hotfix")
        git(self.engine, "tag", "-d", "my-mark")
        before = self.state(self.engine)  # 2. in the publish repository: the engine's release
        proc = self.release("stable", env={"PLANT_IN": str(self.pub)})  # commit is put back
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("the publish repo changed since step 2 checked it: refs/heads/hotfix "
                      "appeared, refs/tags/my-mark appeared, NOTES.txt — nothing was written "
                      "to it", proc.stderr)
        self.assertEqual(self.planted(self.pub), kept)
        self.assertEqual(self.state(self.engine), before)
        (self.pub / "NOTES.txt").unlink()
        git(self.pub, "branch", "-q", "-D", "hotfix")
        git(self.pub, "tag", "-d", "my-mark")
        plant = " ".join(f'echo mine > "{repo}/NOTES.txt"; "$real" -C "{repo}" branch hotfix; '
                         f'"$real" -C "{repo}" tag my-mark;' for repo in (self.engine, self.pub))
        self.git_wrapper('case "$*" in *"commit -q -m release modsys"*"(stable)"*) '
                         f'"$real" "$@"; rc=$?; {plant} exit $rc ;; esac')
        proc = self.release("stable", env={"FAKE_CLAUDE_FAIL": "install"})  # 3. after the
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)  # writes: step 8 fails
        self.assertIn("step 8 smoke install failed", proc.stderr)
        self.assertTrue(proc.stderr.rstrip().endswith("both repositories are as they were"))
        for repo in (self.engine, self.pub):  # theirs survives, the run's own is gone
            self.assertEqual(self.planted(repo), kept)
            self.assertEqual(git(repo, "status", "--porcelain"), "?? NOTES.txt\n")
            self.assertEqual(git(repo, "symbolic-ref", "HEAD").strip(), "refs/heads/main")
            self.assertEqual(self.refs(repo), ["refs/heads/hotfix", "refs/heads/main",
                                               "refs/tags/my-mark"])
        self.assertEqual(self.log(self.engine, "main"), ["engine"])
        self.assertEqual(self.log(self.pub, "main"), ["root"])
        self.assertEqual(sorted(p.name for p in self.pub.iterdir()),
                         [".git", "NOTES.txt", "README.md"])

    def test_the_put_back_finishes_and_says_what_is_true(self):  # task-8 review C2
        self.git_wrapper('case "$*" in *update-ref*) kill -INT $PPID ;; esac')  # Ctrl-C again,
        self.failed("stable", "interrupted", env={"MODSYS_RELEASE_INTERRUPT": "7"},  # inside
                    code=130)  # the put-back: ignored, both repositories are put back
        self.git_wrapper()
        self.commit(self.pub, "README.md", "# Plugins\n", "root")
        hook = self.pub / ".git/hooks/post-commit"  # another git process holds the index
        hook.write_text('#!/bin/sh\n: > "$(git rev-parse --git-dir)/index.lock"\n')
        hook.chmod(0o755)
        engine = self.state(self.engine)
        proc = self.release("stable", env={"FAKE_CLAUDE_FAIL": "install"})
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("release.py: step 8 smoke install failed", proc.stderr)
        self.assertIn("release.py: the put-back is incomplete — finish it by hand:\n"
                      "  publish repo: git reset -q --hard failed: ", proc.stderr)
        self.assertIn("\n  publish repo: still changed: ", proc.stderr)
        self.assertNotIn("as they were", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertEqual(self.state(self.engine), engine)  # the other one is put back
        self.assertEqual(self.refs(self.pub), ["refs/heads/main"])

    def test_sigterm_and_a_closed_terminal_are_an_interrupt(self):
        self.failed("dev", "release.py: interrupted", env={"FAKE_GUARD_MODE": "hangup"},
                    code=130)
        self.git_wrapper('case "$*" in *"commit -q -m release modsys"*"(dev)"*) '
                         'kill -TERM $PPID; sleep 5; exit 1 ;; esac')
        self.failed("dev", "release.py: interrupted", code=130)


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
        log = release.changelog("# Changes\n\n- theirs\n", f"- {REL} (stable): engine abc")
        self.assertTrue(log.startswith("# Changes\n\n- theirs\n\n"))
        log = release.changelog(log, f"- {NXT} (stable): engine def")
        self.assertIn(f"## modsys\n\n- {NXT} (stable): engine def\n- {REL} (stable): engine "
                      "abc\n", log)
        self.assertEqual(log.count(release.LOG_BEGIN), 1)

    def test_a_crlf_file_keeps_its_line_endings(self):
        release = load_tool("release")
        begin, end = release.README_BEGIN, release.README_END
        self.assertEqual(release.replace_section("Intro.\r\n", begin, end, "a\n\nb\n"),
                         f"Intro.\r\n\r\n{begin}\r\na\r\n\r\nb\r\n{end}\r\n")
        self.assertEqual(release.replace_section(f"a\r\n{begin}\r\nold\r\n{end}\r\nz\r\n",
                                                 begin, end, "new\n"),
                         f"a\r\n{begin}\r\nnew\r\n{end}\r\nz\r\n")
        log = release.changelog("# Changes\r\n\r\n- theirs\r\n", f"- {REL} (dev): engine abc")
        log = release.changelog(log, f"- {NXT} (dev): engine def")
        self.assertEqual(log, "# Changes\r\n\r\n- theirs\r\n\r\n"
                              f"{release.LOG_BEGIN}\r\n## modsys\r\n\r\n- {NXT} (dev): engine "
                              f"def\r\n- {REL} (dev): engine abc\r\n{release.LOG_END}\r\n")

    def test_damaged_markers_fail_naming_the_file(self):
        release = load_tool("release")
        for begin, end, where in ((release.README_BEGIN, release.README_END, "README.md"),
                                  (release.LOG_BEGIN, release.LOG_END, "CHANGELOG.md")):
            for text in (f"a\n{begin}\nold\n\n## theirs\n", f"a\nold\n{end}\n## theirs\n",
                         f"{begin}\nx\n{end}\n\n{begin}\ny\n{end}\n",
                         f"{begin}\nx\n{end}\ny\n{end}\n", f"{end}\nintro\n{begin}\nx\n"):
                with self.subTest(file=where, text=text):
                    with self.assertRaises(release.Failed) as caught:
                        if where == "README.md":
                            release.replace_section(text, begin, end, "new\n")
                        else:
                            release.changelog(text, f"- {REL} (dev): engine abc")
                    self.assertIn(f"{where}: the markers of the modsys section are damaged",
                                  str(caught.exception))


NO_NOTE = ("CHANGELOG.md: `## [Unreleased]` holds no note (no line starting with `- ` or `* ` "
           "before the next `## ` heading) — write the notes of this release there first")
NO_HEADING = ("CHANGELOG.md has no `## [Unreleased]` heading — a stable release publishes the "
              "notes under it: add one above the released versions, with the notes of this "
              "release")
NO_FILE = ("CHANGELOG.md is missing in the engine — a stable release publishes the notes under "
           "its `## [Unreleased]` heading: add the file (Keep a Changelog) with the notes of "
           "this release")
UNTRACKED = ("CHANGELOG.md is not tracked in the engine — commit it: the release commit dates "
             "its `## [Unreleased]` heading")


def two_headings(count: int, lines: str) -> str:
    return (f"CHANGELOG.md has {count} `## [Unreleased]` headings (lines {lines}) — keep one: "
            f"the notes of a release are the lines under it")


class NotesTest(unittest.TestCase):  # P61-AC-021, 022, 031, 036 (D6, SI-P61-9/10): pure parts
    def setUp(self):
        self.r = load_tool("release")

    def refused(self, text: str | None, channel: str = "stable") -> str:
        with self.assertRaises(self.r.Refused) as caught:
            self.r.pending_notes(text, channel)
        return str(caught.exception)

    def test_the_unreleased_section(self):
        text = ("# Changelog\n\n## [Unreleased]\n\n### Added\n\n- One.\n  more of one\n"
                "<!-- a comment\n- not a note\n-->\n* Two. <!-- why -->\n\n"
                "## [0.0.1] - 2026-01-01\n\n- Old.\n")
        notes = ["### Added", "- One.", "  more of one", "* Two."]  # no blank line, no comment
        self.assertEqual(self.r.unreleased(text), (2, notes))
        for channel in ("stable", "dev"):
            self.assertEqual(self.r.pending_notes(text, channel), notes)
        self.assertEqual(self.r.unreleased("## [Unreleased]\r\n- a\r\n### Sub\r\n- b"),
                         (0, ["- a", "### Sub", "- b"]))  # `### ` does not end it; the file does
        self.assertEqual(self.r.unreleased("# Changelog\n\n## [0.0.1] - 2026-01-01\n\n- a\n"),
                         (None, []))

    def test_empty_is_no_item_line(self):  # SI-P61-10
        for body in ("", "\n\n\n", "\n<!-- the notes of the next release -->\n\n",
                     "\n<!--\n- a template line\n-->\n\n", "\n### Added\n\n### Fixed\n\n",
                     "\n### Added\n<!-- none yet -->\n\n"):
            text = f"# Changelog\n\n## [Unreleased]\n{body}## [0.0.1] - 2026-01-01\n\n- Old.\n"
            with self.subTest(body=body):
                self.assertEqual(self.refused(text), NO_NOTE)
                self.assertEqual(self.r.pending_notes(text, "dev"), [])  # dev: no notes yet
        for item in ("- One.", "* One."):
            text = f"## [Unreleased]\n\n{item}\n\n## [0.0.1] - 2026-01-01\n"
            self.assertEqual(self.r.pending_notes(text, "stable"), [item])

    def test_no_heading_two_headings_no_file(self):  # P61-AC-031
        self.assertEqual(self.refused("# Changelog\n\n## [0.0.1] - 2026-01-01\n\n- a\n"),
                         NO_HEADING)
        self.assertEqual(self.r.pending_notes("# Changelog\n", "dev"), [])
        two = "# Changelog\n\n## [Unreleased]\n\n- a\n\n## [Unreleased]\r\n\n- b\n"
        three = "## [Unreleased]\n- a\n## [Unreleased]\n- b\n## [Unreleased]\n"
        for channel in ("stable", "dev"):  # ambiguous on either channel: never a guess
            self.assertEqual(self.refused(two, channel), two_headings(2, "3 and 7"))
            self.assertEqual(self.refused(three, channel), two_headings(3, "1, 3 and 5"))
        self.assertEqual(self.refused(None), NO_FILE)
        self.assertEqual(self.r.pending_notes(None, "dev"), [])
        for message in (NO_NOTE, NO_HEADING, NO_FILE, UNTRACKED, two_headings(2, "3 and 7")):
            self.assertIn("CHANGELOG.md", message)  # P61-AC-036: both named
            self.assertIn("[Unreleased]", message)

    def test_the_release_commit_dates_the_section(self):  # P61-AC-021, AC-031 (CRLF)
        text = ("# Changelog\n\nIntro.\n\n## [Unreleased]\n\n- One.\n- Two.\n\n"
                "## [0.0.1] - 2026-01-01\n\n- Old.\n")
        want = text.replace("## [Unreleased]\n\n", f"## [Unreleased]\n\n## [{REL}] - {DATE}\n\n")
        self.assertEqual(self.r.dated(text, REL, DATE), want)
        self.assertEqual(self.r.dated(text.replace("\n", "\r\n"), REL, DATE),
                         want.replace("\n", "\r\n"))
        with tempfile.TemporaryDirectory() as tmp:  # the release's own read and write, as bytes
            root = Path(tmp)
            (root / "CHANGELOG.md").write_bytes(text.replace("\n", "\r\n").encode())
            self.assertEqual(self.r.date_notes(root, REL, DATE), ["- One.", "- Two."])
            self.assertEqual((root / "CHANGELOG.md").read_bytes(),
                             want.replace("\n", "\r\n").encode())

    def test_the_publish_entry(self):  # P61-AC-021, AC-022
        r, dev = self.r, f"{REL}-dev.h0123abcd"
        self.assertEqual(r.log_entry(REL, "stable", "abc1234", ["- One.", "- Two."]),
                         f"- {REL} (stable): engine abc1234\n  - One.\n  - Two.")
        self.assertEqual(r.log_entry(dev, "dev", "abc1234", ["- One."]),
                         f"- {dev} (dev): engine abc1234\n  - One.")
        self.assertEqual(r.log_entry(dev, "dev", "abc1234", []),
                         f"- {dev} (dev): engine abc1234\n  no notes yet")
        log = r.changelog("# Changes\r\n\r\n- theirs\r\n",
                          r.log_entry(REL, "stable", "abc", ["- One.", "### Fixed", "- Two."]))
        log = r.changelog(log, r.log_entry(NXT, "stable", "def", ["- Three."]))
        self.assertEqual(log, "# Changes\r\n\r\n- theirs\r\n\r\n"  # the newest first, CRLF kept
                              f"{LOG_BEGIN}\r\n## modsys\r\n\r\n- {NXT} (stable): engine def\r\n"
                              f"  - Three.\r\n- {REL} (stable): engine abc\r\n  - One.\r\n"
                              f"  ### Fixed\r\n  - Two.\r\n{LOG_END}\r\n")

    def test_the_date(self):  # SI-P61-9
        r = self.r
        with mock.patch.dict(os.environ, {"MODSYS_RELEASE_DATE": DATE}):
            self.assertEqual(r.release_date(), DATE)
        for bad in ("2026-02-30", "2026-13-01", "20261015", "2026-1-5", "2026-10-15T00:00",
                    "tomorrow"):
            with self.subTest(value=bad), mock.patch.dict(os.environ,
                                                          {"MODSYS_RELEASE_DATE": bad}):
                with self.assertRaises(r.Refused) as caught:
                    r.release_date()
                self.assertEqual(str(caught.exception),
                                 f"MODSYS_RELEASE_DATE={bad!r}: not a date YYYY-MM-DD")
        for unset in ({"MODSYS_RELEASE_DATE": ""}, {}):
            with mock.patch.dict(os.environ, unset):
                if not unset:
                    os.environ.pop("MODSYS_RELEASE_DATE", None)
                before = datetime.date.today().isoformat()
                got = r.release_date()
                after = datetime.date.today().isoformat()
            self.assertIn(got, (before, after))  # the local date (across midnight: either)


class NotesRunTest(ReleaseRepo):  # P61-AC-022, 031, 036: the notes through whole runs
    def test_a_dev_release_writes_the_pending_notes(self):  # P61-AC-022, AC-031 (no file)
        one = CHANGELOG.replace("- Second planted note.\n", "")
        self.commit(self.engine, "CHANGELOG.md", one, "one note")
        want = []
        for case in ("one line", "empty", "no file"):
            if case != "one line":
                self.change_a_skill()  # a new build: the same one is nothing to release
            if case == "empty":
                self.commit(self.engine, "CHANGELOG.md",
                            one.replace("- First planted note.\n", ""), "no note")
            if case == "no file":
                git(self.engine, "rm", "-q", "--", "CHANGELOG.md")
                git(self.engine, "commit", "-q", "-m", "no changelog")
            path = self.engine / "CHANGELOG.md"
            notes = path.read_bytes() if path.exists() else None
            engine = self.state(self.engine)
            proc = self.release("dev")
            self.assert_ok(proc)
            self.assertEqual(self.state(self.engine), engine)  # dev changes nothing here
            self.assertEqual(path.read_bytes() if path.exists() else None, notes)
            self.assertIn("; CHANGELOG.md [Unreleased]: " + (
                "1 line\n" if case == "one line" else "no notes yet\n"), proc.stdout)
            version = re.search(r"done: modsys (\S+) \(dev\)", proc.stdout).group(1)
            want.insert(0, (version, "dev", git(self.engine, "rev-parse", "HEAD"),
                            ["- First planted note."] if case == "one line"
                            else ["no notes yet"]))
        self.assertEqual(self.entries("dev"), want)

    def index(self) -> list:
        return [(repo / ".git/index").read_bytes() if (repo / ".git/index").exists() else None
                for repo in (self.engine, self.pub)]

    def refused_at_step_1(self, message: str, env: dict | None = None) -> None:
        before, index = self.both(), self.index()
        proc = self.release("stable", env={"FAKE_GUARD_ERROR": "1", **(env or {})})
        self.assertEqual((proc.returncode, proc.stderr), (2, f"release.py: error: {message}\n"))
        self.assertEqual(proc.stdout, "release modsys: channel stable (marketplace modsys), "
                                      f"publish repo {self.pub}\n")  # no step finished
        self.assertEqual((self.both(), self.index()), (before, index))
        self.assertEqual(list(self.tmpdir.iterdir()), [])
        self.assertFalse((self.base / "claude.log").exists())  # no build, no validate

    def test_stable_without_notes_is_refused_before_any_work(self):  # P61-AC-036, AC-031
        # FAKE_GUARD_ERROR: had the guard run (or the suite after it), stderr would say so
        self.refused_at_step_1("MODSYS_RELEASE_DATE='2026-02-30': not a date YYYY-MM-DD",
                               env={"MODSYS_RELEASE_DATE": "2026-02-30"})
        head = "# Changelog\n\nAll notable changes to this copy are documented in this file.\n\n"
        old = "## [0.0.1] - 2026-01-01\n\n- The first planted release.\n"
        for case, text, message in (
                ("blank lines and a comment",
                 head + "## [Unreleased]\n\n\n<!-- the notes of the next release -->\n\n" + old,
                 NO_NOTE),
                ("two headings", head + "## [Unreleased]\n\n- a\n\n## [Unreleased]\n\n- b\n\n"
                 + old, two_headings(2, "5 and 9")),
                ("no heading", head + old, NO_HEADING),
                ("no file", None, NO_FILE)):
            with self.subTest(case=case):
                if text is None:
                    git(self.engine, "rm", "-q", "--", "CHANGELOG.md")
                    git(self.engine, "commit", "-q", "-m", case)
                else:
                    self.commit(self.engine, "CHANGELOG.md", text, case)
                self.refused_at_step_1(message)
        (self.engine / "CHANGELOG.md").write_text(CHANGELOG)  # notes, but git ignores the file
        (self.engine / ".git/info/exclude").write_text("CHANGELOG.md\n")
        self.refused_at_step_1(UNTRACKED)

    def test_a_crlf_changelog_stays_crlf(self):  # P61-AC-031
        crlf = CHANGELOG.replace("\n", "\r\n")
        (self.engine / "CHANGELOG.md").write_bytes(crlf.encode())
        git(self.engine, "commit", "-q", "-am", "CRLF")
        self.assert_ok(self.release("stable"))
        dated = crlf.replace("## [Unreleased]\r\n\r\n",
                             f"## [Unreleased]\r\n\r\n## [{REL}] - {DATE}\r\n\r\n", 1).encode()
        blob = subprocess.run(  # bytes: the helper's text mode would turn CRLF into LF
            ["git", "-C", str(self.engine), "show", "HEAD~1:CHANGELOG.md"], capture_output=True,
            check=True, env={k: v for k, v in os.environ.items()
                             if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}).stdout
        self.assertEqual((blob, (self.engine / "CHANGELOG.md").read_bytes()), (dated, dated))
        self.assertNotIn(b"\r", (self.pub / "CHANGELOG.md").read_bytes())  # the publish file's
        self.assertEqual(self.entries("stable")[0][3],  # own line endings, no CR in a note
                         ["- First planted note.", "- Second planted note."])


class ChangelogFileTest(unittest.TestCase):  # P61-AC-020: the engine's own CHANGELOG.md
    HEADER = ("# Changelog\n\nAll notable changes to this project will be documented in this "
              "file.\n\nThe format is based on [Keep a Changelog]"
              "(https://keepachangelog.com/en/1.1.0/),\nand this project adheres to [Semantic "
              "Versioning](https://semver.org/spec/v2.0.0.html).\n\n")
    BACKFILL = "## [0.1.0] - 2026-10-01"  # the first release (D6): always the last section

    def setUp(self):
        self.text = (ENGINE / "CHANGELOG.md").read_text(encoding="utf-8")

    def test_keep_a_changelog_down_to_the_first_release(self):
        self.assertTrue(self.text.startswith(self.HEADER + "## [Unreleased]\n"),
                        self.text[:400])
        heads = [line for line in self.text.split("\n") if line.startswith("## ")]
        self.assertEqual((heads[0], heads[-1]), ("## [Unreleased]", self.BACKFILL))
        for head in heads[1:]:  # every release after it, dated by its release commit
            self.assertRegex(head, r"^## \[\d+\.\d+\.\d+\] - \d{4}-\d{2}-\d{2}$")
        first = self.text.split(self.BACKFILL + "\n", 1)[1].split("\n")
        self.assertTrue(any(line.startswith("- ") for line in first), first)
        self.assertEqual(load_tool("release").unreleased(self.text)[0],
                         self.HEADER.count("\n"))  # the one the release reads
        self.assertNotIn("\r", self.text)

    def test_no_host_organisation_slug_or_machine_path(self):  # D13
        self.assertEqual(sorted(set(re.findall(r"https?://[^\s)]+", self.text))),
                         ["https://keepachangelog.com/en/1.1.0/",
                          "https://semver.org/spec/v2.0.0.html"])
        for bad in (*MACHINE_PATHS, "github.com", "example-org", "<owner>"):
            self.assertNotIn(bad, self.text)


if __name__ == "__main__":
    unittest.main()
