"""The shared part of the release tests (`tests/test_release*.py`, split from one module by class
in P8.3 D5 R-3): the constants, the base `ReleaseRepo`, the helpers of `AllOrNothingTest` and the
release-notes messages. The tests cover `tools/release.py` (P6 D7, rows 6.2–6.5): a dev and a
stable release into a local publish repository, push only with --push, the publish repository's
foreign content kept, the smoke install through a `claude` stand-in (tests/claude_shim.py — never
a model), no repository slug outside the publish README, the refusals and all-or-nothing — the
put-back restores what the run wrote and nothing else; the release notes (P6.1 D6): the engine's
CHANGELOG.md, a stable release refused without notes under `## [Unreleased]`, the release commit
dating them, the publish entry carrying them; step 3's parallel unit suite and --suite-passed
(P8.3 D5 R-1, R-2). Each test releases a throw-away git copy of this engine (its unit suite =
three small tests, its E-A a stub, its CHANGELOG.md planted: the heavy steps are the
rehearsal's) with a stub leak guard. Shared helpers live here, outside `test_*.py`: every
`tests/test_*.py` module holds tests (SI-P83-14)."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import engine_version, git, next_dev, next_release, release_version
from tests.plugin_helpers import ENGINE, copy_engine, run_tool

ENG = engine_version()  # the engine copies under test carry this version
REL = release_version(ENG)  # what the first stable run releases
NXT = next_release(ENG)  # the release after it
NXT_DEV = next_dev(ENG)  # the engine after the first stable run
SLUG = "example-org/segmently-modules-plugins"
DATE = "2026-10-15"  # SEGMENTLY_MODULES_RELEASE_DATE of every run (SI-P61-9): never the clock
CHANGELOG = ("# Changelog\n\nAll notable changes to this copy are documented in this file.\n\n"
             "## [Unreleased]\n\n- First planted note.\n- Second planted note.\n\n"
             "## [0.0.1] - 2026-01-01\n\n- The first planted release.\n")  # the copies' notes
LOG_BEGIN, LOG_END = "<!-- segmently-modules:changelog:begin -->", "<!-- segmently-modules:changelog:end -->"
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
         "README.md": "# segmently-modules (a test copy)\n", "CHANGELOG.md": CHANGELOG}
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
SKILL = "segmently_modules/defaults/packs/ui/skills/designer/SKILL.md"
TAGS = ["segmently-modules--v{0}", "segmently-modules-qa--v{0}", "segmently-modules-ui--v{0}", "v{0}"]


def tree_hash(root: Path) -> str:
    """One hash of everything below `root`: each path, its kind and mode, a file's bytes, a
    symlink's target — what a test must never change in a snapshot."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        body = (os.readlink(path).encode() if path.is_symlink() else
                path.read_bytes() if path.is_file() else b"")
        digest.update(f"{path.relative_to(root).as_posix()}\0{info.st_mode:o}\0{len(body)}\0"
                      .encode() + body)
    return digest.hexdigest()


def copy_repos(source: Path, dest: Path) -> list[str]:
    """Copy every repository below the snapshot directory `source` — each top-level directory
    that is a work tree (`.git` inside) or a bare remote (`HEAD` and `objects/`) — into `dest`,
    symlinks as symlinks; a remote URL of a copy that points into `source` then points at the
    copy. The names copied, sorted. `source` is only read."""
    names = sorted(p.name for p in source.iterdir() if p.is_dir() and not p.is_symlink() and (
        (p / ".git").exists() or ((p / "HEAD").is_file() and (p / "objects").is_dir())))
    for name in names:
        shutil.copytree(source / name, dest / name, symlinks=True)
    for name in names:
        urls = subprocess.run(["git", "-C", str(dest / name), "config", "--get-regexp",
                               r"^remote\..*\.url$"], capture_output=True, text=True,
                              env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull,
                                   "GIT_CONFIG_NOSYSTEM": "1"}).stdout
        for line in urls.splitlines():
            key, _, url = line.partition(" ")
            inside = Path(url) == source or source in Path(url).parents
            if inside:
                git(dest / name, "config", key, str(dest / Path(url).relative_to(source)))
    return names


class ReleaseRepo(unittest.TestCase):
    """Every release runs through `run_tool`: SIGINT, SIGTERM and SIGHUP at their defaults in
    the release, however the suite itself was started (a detached suite ignores two of them).

    A test named in the class's `FROM_DEV_RELEASE` starts from a finished dev release without
    running it (P8.3 D5 R-3): `setUpClass` makes that release once in a snapshot directory the
    tests never write (its `tree_hash` is checked again in `tearDownClass`); the test copies the
    snapshot's repositories and remotes (`copy_repos`), and its first plain `release("dev")`
    returns the snapshot's run."""

    FROM_DEV_RELEASE: tuple[str, ...] = ()  # the tests that start from the class's snapshot
    snapshot: Path | None = None  # the snapshot directory (a `base`), while the class runs

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.snapshot = cls.snapshot_run = cls.snapshot_hash = cls.snapshot_maker = None
        if not cls.FROM_DEV_RELEASE:
            return
        maker = cls(cls.FROM_DEV_RELEASE[0])
        maker.setUp()  # no snapshot yet: fresh copies
        try:
            run = maker.release("dev")
            maker.assert_ok(run)
        except BaseException:
            maker.tearDown()
            raise
        cls.snapshot_maker, cls.snapshot, cls.snapshot_run = maker, maker.base, run
        cls.snapshot_hash = tree_hash(maker.base)

    @classmethod
    def tearDownClass(cls):
        try:
            if cls.snapshot is not None and tree_hash(cls.snapshot) != cls.snapshot_hash:
                raise AssertionError(f"{cls.__name__}: a test wrote into the class's snapshot "
                                     f"{cls.snapshot}")
        finally:
            if cls.snapshot_maker is not None:
                cls.snapshot_maker.tearDown()
            cls.snapshot = cls.snapshot_run = cls.snapshot_hash = cls.snapshot_maker = None
            super().tearDownClass()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name).resolve()
        self.started = None  # the snapshot's dev release, until the test's first release
        self.pub = self.base / "publish repo"  # a space: every printed command is quoted
        if self.snapshot is not None and self._testMethodName in self.FROM_DEV_RELEASE:
            copy_repos(self.snapshot, self.base)
            self.engine, self.started = self.base / "engine", self.snapshot_run
        else:
            self.engine = copy_engine(self.base / "engine", EXTRA,
                                      prefixes=("segmently_modules/", "tools/", "tests/fixtures/bookshop/"))
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
                    "SEGMENTLY_MODULES_GUARD": str(self.base / "guard.py"),
                    "FAKE_CLAUDE_LOG": str(self.base / "claude.log"), "TMPDIR": str(self.tmpdir),
                    "SEGMENTLY_MODULES_PYTHON": sys.executable, "SEGMENTLY_MODULES_RELEASE_DATE": DATE,
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
        started, self.started = self.started, None
        if started is not None and (channel, argv, env, slug, pub) == ("dev", (), None, SLUG,
                                                                       None):
            return started  # the class's snapshot: this test starts from that finished release
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
        """The segmently-modules entries of the publish repository's CHANGELOG.md on `branch`, newest
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
                self.assertIn(line, ("## segmently-modules", ""), section)
        return found

    def refs(self, repo: Path) -> list[str]:
        return git(repo, "for-each-ref", "--format=%(refname)").split()


class AllOrNothingBase(ReleaseRepo):
    """The helpers of `AllOrNothingTest` (P6-AC-031), split over two modules."""

    def failed(self, channel: str, step: str, env: dict | None = None, code: int = 1) -> str:
        before = self.both()
        notes = (self.engine / "CHANGELOG.md").read_bytes()
        readme = (self.engine / "README.md").read_bytes()
        proc = self.last = self.release(channel, env=env)
        self.assertEqual(proc.returncode, code, proc.stdout + proc.stderr)
        self.assertIn(step, proc.stderr)
        self.assertTrue(proc.stderr.startswith("release.py: "), proc.stderr)  # no traceback
        self.assertTrue(proc.stderr.rstrip().endswith("both repositories are as they were"),
                        proc.stderr)
        self.assertEqual(self.both(), before)
        # P61-AC-036: a stable run past step 4 had dated the notes — the put-back restores them
        self.assertEqual((self.engine / "CHANGELOG.md").read_bytes(), notes)
        self.assertEqual((self.engine / "README.md").read_bytes(), readme)  # and its install pin
        self.assertEqual(list(self.tmpdir.iterdir()), [])
        return proc.stderr

    def planted(self, repo: Path) -> list:
        return [(repo / "NOTES.txt").is_file(),
                sorted(r for r in self.refs(repo) if r.endswith(("/hotfix", "/my-mark")))]


NO_NOTE = ("CHANGELOG.md: `## [Unreleased]` holds no note (no line starting with `- ` or `* ` "
           "before the next `## ` heading) — write the notes of this release there first")
NO_HEADING = ("CHANGELOG.md has no `## [Unreleased]` heading — a stable release publishes the "
              "notes under it: add one above the released versions, with the notes of this "
              "release")
NO_FILE = ("CHANGELOG.md is missing in the engine — a stable release publishes the notes under "
           "its `## [Unreleased]` heading: add the file (Keep a Changelog) with the notes of "
           "this release")
MARKER = ("CHANGELOG.md: the note '- `<!-- segmently-modules:changelog:end -->` closes our section.' "
          "under `## [Unreleased]` holds `<!-- segmently-modules:changelog:` — the marker of the publish "
          "repository's changelog section, which the entry would damage: reword the note")
UNTRACKED = ("CHANGELOG.md is not tracked in the engine — commit it: the release commit dates "
             "its `## [Unreleased]` heading")


def two_headings(count: int, lines: str) -> str:
    return (f"CHANGELOG.md has {count} `## [Unreleased]` headings (lines {lines}) — keep one: "
            f"the notes of a release are the lines under it")


# --- step 3's parallel unit suite and --suite-passed (P8.3 D5 R-1, R-2) ----------------------
SUITE_MODULE = '''"""A planted test module of the release tests (P8.3 D5 R-1): it records
its process in $R1_RECORD (one file per process and event) -- argv, cwd, pid, process group,
its parent's, whether SIGHUP is ignored -- and does what the R1_* variables ask: hold, print a
lot, skip, print after unittest's verdict, fail (late), ignore SIGINT, keep a temp directory
(removed by its finalizer), or be the slow module that signals the release, starts a grandchild
in its process group and leaves a marker after a delay."""
import atexit, json, os, signal, subprocess, sys, tempfile, time, unittest
from pathlib import Path

STEM = Path(__file__).stem
RECORD = os.environ.get("R1_RECORD")


def note(event, **more):
    if RECORD:
        row = {"stem": STEM, "time": time.time(), "pid": os.getpid(), "pgid": os.getpgid(0)}
        (Path(RECORD) / f"{STEM}.{os.getpid()}.{event}").write_text(json.dumps({**row, **more}))


def failure(stem):
    return "".join(f"{stem}: planted failure, line {n:02d}\\n" for n in range(40))


def named(variable):
    return STEM in os.environ.get(variable, "").split(",")


if named("R1_DEAF"):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
if named("R1_TEMP"):  # removed at exit by its finalizer -- never after a SIGKILL
    TEMP = tempfile.TemporaryDirectory()
    note("temp", path=TEMP.name)
if named("R1_TRAILER"):  # a line on stderr after unittest's verdict
    atexit.register(print, "planted: a line after the verdict", file=sys.stderr)
note("start", python=sys.executable, argv=sys.orig_argv[1:], cwd=os.getcwd(), parent=os.getppid(),
     parent_pgid=os.getpgid(os.getppid()), bytecode=os.environ.get("PYTHONDONTWRITEBYTECODE"),
     hup_ignored=signal.getsignal(signal.SIGHUP) is signal.SIG_IGN)


class PlantedTest(unittest.TestCase):
    def test_planted(self):
        env = os.environ
        if named("R1_FAIL"):
            if STEM == env.get("R1_FAIL_LATE"):  # the first started fails last
                time.sleep(1.0)
            note("fail")
            sys.stderr.write(failure(STEM))
            sys.stderr.flush()
            os._exit(1)
        if named("R1_LOUD"):
            for stream in (sys.stdout, sys.stderr):
                stream.write(("x" * 99 + "\\n") * 2000)
                stream.flush()
        if STEM == env.get("R1_SLOW"):
            self.slow(env)
        time.sleep(float(env.get("R1_HOLD", "0")))
        note("end")
        if named("R1_SKIP"):
            self.skipTest("planted")

    def slow(self, env):
        deadline = time.time() + 30
        while (len(list(Path(RECORD).glob("*.start"))) < int(env.get("R1_WAIT_FOR", "1"))
               and time.time() < deadline):
            time.sleep(0.02)
        delay = env.get("R1_DELAY", "0")
        code = "import sys, time; time.sleep(float(sys.argv[1])); open(sys.argv[2], 'w').close()"
        child = subprocess.Popen([sys.executable, "-c", code, delay,
                                  str(Path(RECORD) / f"{STEM}.grandchild")])
        note("slow", child=child.pid)
        for _ in range(int(env.get("R1_SIGNALS", "0"))):
            os.kill(os.getppid(), getattr(signal, "SIG" + env["R1_SIGNAL"]))
        time.sleep(float(delay))
        note("marker")
        child.wait()
'''
EVAL_STUB = '''import os, sys
from pathlib import Path

if os.environ.get("R1_RECORD"):
    (Path(os.environ["R1_RECORD"]) / "eval.ran").write_text("")
if os.environ.get("R1_EVAL_FAIL"):
    print("adoption eval: planted failure", file=sys.stderr)
    sys.exit(1)
print("adoption eval: stub ok", file=sys.stderr)
'''
PLANTED = ("test_a_first", "test_m_middle", "test_release_zz", "test_z_last")
START_ORDER = ["test_release_zz", "test_a_first", "test_m_middle", "test_ok", "test_plant",
               "test_z_last"]  # the copy's six modules as step 3 starts them: test_release* first


def failure(stem: str) -> str:
    """The stderr of a planted module that fails (`R1_FAIL`): all it prints."""
    return "".join(f"{stem}: planted failure, line {n:02d}\n" for n in range(40))


class SuiteRepo(ReleaseRepo):
    """A copy whose unit suite holds four more planted modules (`SUITE_MODULE`: 7 tests in 6
    modules, one skipped) and whose E-A stub records that it ran and fails with `R1_EVAL_FAIL`
    (`EVAL_STUB`); `run_release` gives each run a fresh record directory."""

    def setUp(self):
        super().setUp()
        for stem in PLANTED:
            (self.engine / "tests" / f"{stem}.py").write_text(SUITE_MODULE)
        (self.engine / "evals/adoption/run_eval.py").write_text(EVAL_STUB)
        git(self.engine, "add", "-A")
        git(self.engine, "commit", "-q", "-m", "planted modules")
        self.records = self.base / "records"

    def run_release(self, channel: str, *argv: str, env: dict | None = None,
                    **kw) -> subprocess.CompletedProcess:
        if self.records.exists():
            shutil.rmtree(self.records)
        self.records.mkdir()
        return run_tool(self.engine, "release", "--publish-repo", str(self.pub), "--channel",
                        channel, "--publish-slug", SLUG, *argv,
                        env={**self.env, "R1_RECORD": str(self.records), **(env or {})},
                        **{"timeout": 120, **kw})

    def recorded(self, event: str) -> dict[str, dict]:
        """{module: its `event` record} of the last run — one per module: a module that
        recorded `event` from two processes (started twice) fails the test."""
        rows = {}
        for path in sorted(self.records.glob(f"*.*.{event}")):
            rows.setdefault(path.name.split(".", 1)[0], []).append(json.loads(path.read_text()))
        for stem, found in rows.items():
            self.assertEqual(len(found), 1, f"{stem}: {len(found)} `{event}` records")
        return {stem: found[0] for stem, found in rows.items()}

    def tree(self, rev: str = "HEAD") -> str:
        return git(self.engine, "rev-parse", f"{rev}^{{tree}}").strip()
