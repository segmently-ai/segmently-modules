"""Release the modsys plugins from this engine tree into a publish repository (P6 D7).

    MODSYS_GUARD=<the private leak guard> python3 tools/release.py \\
        --publish-repo DIR --channel dev|stable --publish-slug OWNER/REPO [--push]

Steps, in this order (each printed with its result):
  1 leak guard   the private guard `MODSYS_GUARD` names (run as `<python> <guard> --target
                 DIR` from the caller's working directory) exits 0 with a `… CLEAN` line on
                 this engine (files and history), and the organisation of --publish-slug
                 appears nowhere in it (files, commit and tag messages, patch text — the guard
                 allows the engine's own slug phrase, this scan allows nothing); the guard is
                 never copied or vendored
  2 clean trees  this engine and the publish repository have no change git would see; the
                 publish repository's `plugins`, `.claude-plugin`, `.agents` and
                 `.agents/plugins` are directories (or absent), never symlinks; its channel
                 branch is not behind `origin/<channel>`; for `stable`, `__version__` is
                 X.Y.Z.devN, `v<version>` is in neither and no `<plugin>--v<version>` in the
                 publish repository
  3 tests        the unit suite and the adoption eval (E-A) of this engine
  4 build        `stable`: first the release commit here (`__version__` and pyproject.toml
                 X.Y.Z.devN → X.Y.Z); then tools/build_plugins.py with the channel's version
                 (tools/publish.py) into a temp directory
  5 validate     the guard and the organisation scan over the build; our checks of the laid-out
                 publish tree; `claude plugin validate --strict` of each plugin and of the
                 marketplace (skipped when `claude` is not on PATH)
  6 publish repo the channel's branch gets exactly `plugins/modsys`, `plugins/modsys-ui`,
                 `plugins/modsys-qa` replaced, both marketplace files merged by plugin name
                 (entries it does not own are kept), and its own sections of README.md (the
                 install lines with --publish-slug) and CHANGELOG.md; when git sees no change
                 in them it is "nothing to release" (exit 0, nothing committed). A missing
                 branch is created from `origin/<channel>` when the clone has it, else from
                 the first commit behind HEAD that is not a release commit of this tool (an
                 orphan branch when there is none)
  7 commit       `release modsys <version> (<channel>)` in the publish repository — the commit
                 must hold the build, path by path, mode and content; `stable` tags
                 `v<version>` and `<plugin>--v<version>` there and `v<version>` here
  8 smoke install a throw-away CLAUDE_CONFIG_DIR: marketplace add, install modsys-ui (its
                 dependency modsys comes with it) and modsys-qa, list, details, the installed
                 `bin/modsys --version` and `lint` on a copy of the bookshop fixture — no model
                 call (skipped when `claude` is not on PATH; then --push is refused)
  then, for `stable`, the commit that starts the next version here (X.Y.(Z+1).dev0), and only
  with --push: `git push --atomic origin` of the channel branch and its tags, then of this
  engine's branch and `v<version>`; without it the two commands are printed.
All or nothing up to the push: a failed step or Ctrl-C (SIGTERM and SIGHUP too) puts back what
the run wrote — the branches and tags it made or moved, HEAD, the index, the files it writes —
and removes every temp directory; a branch, a tag or an untracked file that appeared beside the
run stays, and a repository that changed between step 2 and the run's first write to it is a
refusal that writes nothing there. The put-back is checked: "as they were" is printed only
when it is true. A failed or interrupted push is never put back: the release stands locally
and the commands left to run are printed. Exit 0 done (or nothing to release) · 1 a step
failed · 2 a refusal (stderr names it) · 130 interrupted. Test seam:
MODSYS_RELEASE_INTERRUPT=6 raises Ctrl-C in the middle of step 6, =7 in step 7 between the
commit and the tags."""
import argparse
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True  # running a tool never leaves tools/__pycache__ in the engine
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_plugins  # noqa: E402  (sibling scripts)
import publish  # noqa: E402

ENGINE = build_plugins.ENGINE
PROG = "release.py"
SLUG = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?/[A-Za-z0-9._-]+$")
README_BEGIN, README_END = "<!-- modsys:begin -->", "<!-- modsys:end -->"
LOG_BEGIN, LOG_END = "<!-- modsys:changelog:begin -->", "<!-- modsys:changelog:end -->"
OWNED = [f"plugins/{name}" for name in build_plugins.PLUGINS]
MARKETPLACE_FILES = [publish.CLAUDE_MARKETPLACE, publish.CODEX_MARKETPLACE]
WRITTEN = [*OWNED, *MARKETPLACE_FILES, "README.md", "CHANGELOG.md"]  # all step 6 writes
PARENTS = ["plugins", ".claude-plugin", ".agents", ".agents/plugins"]  # never a symlink
VERSION_FILES = ["modsys/__init__.py", "pyproject.toml"]  # all the run writes in the engine
RELEASE_SUBJECT = re.compile(r"^release modsys \S+ \((?:dev|stable)\)$")  # step 7's commits
GUARD = "MODSYS_GUARD"  # the environment variable naming the private leak guard
CLEAN = re.compile(r"^\S+: CLEAN$", re.M)  # its verdict line (its name is never spelled here)
HITS = re.compile(r"(\d+) hit\(s\)")
INTERRUPT = "MODSYS_RELEASE_INTERRUPT"
SECRETS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")
CLAUDE_TIMEOUT = 300  # seconds per `claude` call: a hanging CLI fails the step, never the run
NAMES = {1: "leak guard", 2: "clean trees", 3: "tests", 4: "build", 5: "validate",
         6: "publish repo", 7: "commit", 8: "smoke install", 9: "next version", 10: "push"}
SHOWN = 10  # places a message names before `… and <n> more`


class Refused(Exception):
    """Exit 2: a precondition does not hold (what the run wrote is put back)."""


class Failed(Exception):
    """Exit 1: a step failed (what the run wrote is put back)."""


class NothingToRelease(Exception):
    """Exit 0: the channel already holds this build (what the run wrote is put back)."""


def say(text: str) -> None:
    print(text, flush=True)


def listed(places: list[str]) -> str:
    """The first places of a list, and how many more there are."""
    more = f" … and {len(places) - SHOWN} more" if len(places) > SHOWN else ""
    return ", ".join(places[:SHOWN]) + more


class Repo:
    """A git repository the release may write to, with a snapshot to put it back."""

    def __init__(self, path: Path, label: str):
        self.path, self.label = path, label

    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        proc = build_plugins.run_git(self.path, *args)
        if check and proc.returncode:
            raise Failed(f"{self.label}: git {' '.join(args)} failed: "
                         f"{(proc.stderr or proc.stdout).strip()}")
        return proc

    def out(self, *args: str) -> str:
        return self.git(*args).stdout

    def refs(self, prefix: str = "refs") -> dict[str, str]:
        """{full ref name: object id} below `prefix` — full names: a tag and a branch may
        share their short one."""
        text = self.out("for-each-ref", "--format=%(refname) %(objectname)", prefix)
        return dict(line.split(" ", 1) for line in text.splitlines() if line)

    def has(self, ref: str) -> bool:
        return self.git("show-ref", "--verify", "-q", ref, check=False).returncode == 0

    def head(self) -> str | None:
        proc = self.git("rev-parse", "--verify", "-q", "HEAD", check=False)
        return proc.stdout.strip() or None

    def branch(self) -> str | None:
        proc = self.git("symbolic-ref", "-q", "HEAD", check=False)
        return proc.stdout.strip() or None

    def dirty(self, *paths: str) -> list[str]:
        return self.out("status", "--porcelain", "--untracked-files=all",
                        *(["--", *paths] if paths else [])).splitlines()

    def snapshot(self) -> dict:
        return {"branch": self.branch(), "head": self.head(),
                "refs": {**self.refs("refs/heads"), **self.refs("refs/tags")}}

    def changes(self, snap: dict) -> list[str]:
        """What differs from `snap` (taken when the tree was clean): refs that appeared, moved
        or went, a moved HEAD, and what git status shows."""
        now = self.snapshot()
        found = [f"{ref} appeared" for ref in sorted(set(now["refs"]) - set(snap["refs"]))]
        found += [f"{ref} is gone" for ref in sorted(set(snap["refs"]) - set(now["refs"]))]
        found += [f"{ref} moved" for ref in sorted(set(snap["refs"]) & set(now["refs"]))
                  if snap["refs"][ref] != now["refs"][ref]]
        if (now["branch"], now["head"]) != (snap["branch"], snap["head"]) and not found:
            found.append("HEAD moved")
        return found + [line[3:] for line in self.dirty()]


def run_guard(guard: Path, target: Path, where: str) -> None:
    """The private leak guard over `target`: exit 0 with its CLEAN line, or a refusal — hits
    only when its output holds the `<n> hit(s)` line (its own lines go to the operator's
    terminal only); anything else is a guard that failed, with its last line."""
    try:
        proc = subprocess.run([sys.executable, str(guard), "--target", str(target)],
                              capture_output=True, encoding="utf-8", errors="replace",
                              env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    except OSError as e:
        raise Refused(f"the leak guard cannot run: {e.strerror or e}") from None
    if proc.returncode == 0 and CLEAN.search(proc.stdout):
        return
    count = HITS.search(proc.stdout)
    if proc.returncode and count:
        for line in proc.stdout.splitlines():
            print(line, file=sys.stderr)
        raise Refused(f"the leak guard found {count.group(1)} hit(s) in {where} — fix them in "
                      f"the engine")
    tail = (proc.stderr.strip() or proc.stdout.strip()).splitlines()[-1:]
    why = "no `… CLEAN` line in its output" if proc.returncode == 0 else \
        (tail[0].strip() if tail else "no output")
    raise Refused(f"the leak guard failed on {where} (exit {proc.returncode}): {why}")


def org_hits(engine: Repo, org: str) -> list[str]:
    """Where the organisation appears in the engine (any case): `file <path>` for a tracked
    file, `history` for a commit message, an annotated tag's message or patch text in its
    history — never a commit id or an `index` line: a short or hex-like name is not a hit
    there."""
    needle = org.lower()
    hits = []
    for rel in engine.out("ls-files", "-z").split("\0"):
        path = engine.path / rel
        if rel and path.is_file() and not path.is_symlink():
            try:
                if needle.encode() in path.read_bytes().lower():
                    hits.append(f"file {rel}")
            except OSError as e:
                raise Refused(f"cannot read {rel}: {e.strerror or e}") from None
    log = engine.git("log", "--all", "-p", "--text", "--format=%B", check=False)
    tags = engine.git("for-each-ref", "--format=%(contents)", "refs/tags", check=False)
    for proc in (log, tags):
        if proc.returncode:
            raise Refused(f"cannot read the engine's history: {proc.stderr.strip()}")
    if any(needle in line.lower() for text in (log.stdout, tags.stdout)
           for line in text.splitlines() if not line.startswith("index ")):
        hits.append("history")
    return hits


def dir_hits(root: Path, org: str) -> list[str]:
    needle = org.lower().encode()
    return [f"build {p.relative_to(root).as_posix()}" for p in sorted(root.rglob("*"))
            if p.is_file() and needle in p.read_bytes().lower()]


def linked_parents(root: Path) -> list[str]:
    """The directories the release writes below (`plugins`, `.claude-plugin`, `.agents`,
    `.agents/plugins`) that are a symlink or a file in the work tree at `root` — a write through
    one would leave the repository."""
    return [rel for rel in PARENTS if (root / rel).is_symlink()
            or (os.path.lexists(root / rel) and not (root / rel).is_dir())]


def newline_of(text: str) -> str:
    """The file's own line ending: CRLF when it uses it."""
    return "\r\n" if "\r\n" in text else "\n"


def markers(text: str, begin: str, end: str, where: str) -> bool:
    """True when `text` holds our section (one begin marker before one end marker), False when
    it holds neither; any other shape — one without the other, more than one, the end first —
    is a failed step naming the file: a hand edit damaged it, and rewriting would lose text."""
    found = (text.count(begin), text.count(end))
    if found == (0, 0):
        return False
    if found != (1, 1) or text.index(begin) > text.index(end):
        raise Failed(f"{where}: the markers of the modsys section are damaged ({found[0]} "
                     f"`{begin}`, {found[1]} `{end}`"
                     f"{', the end first' if found == (1, 1) else ''}) — fix the file: one "
                     f"begin marker before one end marker, or neither")
    return True


def replace_section(text: str, begin: str, end: str, body: str,
                    where: str = "README.md") -> str:
    """`text` with the part between the markers replaced by `body` (appended with the markers
    when absent); the text outside them unchanged, the file's line endings kept."""
    nl = newline_of(text)
    block = f"{begin}\n{body}{end}\n".replace("\n", nl)
    if markers(text, begin, end, where):
        head, rest = text.split(begin, 1)
        tail = rest.split(end, 1)[1]
        return head + block[:-len(nl)] + tail
    return text + (nl if text and not text.endswith("\n") else "") + (nl if text else "") + block


def readme_section(slug: str, channel: str, version: str) -> str:
    return (f"## modsys\n\n"
            f"Module-registry skills for coding agents and the modsys CLI: the plugins "
            f"`modsys`, `modsys-ui` and `modsys-qa`. This branch: `{channel}`, modsys "
            f"{version}.\n\n"
            f"- Claude Code: `claude plugin marketplace add {slug}#stable`, then `claude plugin "
            f"install modsys@modsys` (and `modsys-ui@modsys`, `modsys-qa@modsys`).\n"
            f"- Codex: `codex plugin marketplace add {slug} --ref stable`, then `codex plugin "
            f"add modsys@modsys`; install the modsys CLI first (`uv tool install` or `pipx "
            f"install` from the engine repository — its README says how).\n"
            f"- The dev channel: `#dev` / `--ref dev` and the marketplace `modsys-dev`.\n")


def changelog(text: str, entry: str, where: str = "CHANGELOG.md") -> str:
    """CHANGELOG.md with `entry` added at the top of the modsys section (the file's line
    endings kept)."""
    nl = newline_of(text)
    if markers(text, LOG_BEGIN, LOG_END, where):
        head, rest = text.split(LOG_BEGIN, 1)
        body, tail = rest.split(LOG_END, 1)
        lines = body.strip("\r\n").splitlines()
        at = next((i for i, line in enumerate(lines) if line.startswith("- ")), len(lines))
        if at == len(lines) and lines and lines[-1].strip():
            lines.append("")  # a section without an entry yet: a blank line after its heading
            at += 1
        lines.insert(at, entry)  # the newest first
        return head + LOG_BEGIN + nl + nl.join(lines) + nl + LOG_END + tail
    return replace_section(text, LOG_BEGIN, LOG_END, f"## modsys\n\n{entry}\n", where)


def read_text(root: Path, rel: str, where: str = "publish repo") -> str:
    """A text file the release rewrites ("" when missing), its line endings as they are; a
    symlink, a directory or a file that is not UTF-8 is a failed step naming it — never
    written through, never guessed."""
    path = root / rel
    if path.is_symlink() or (os.path.lexists(path) and not path.is_file()):
        raise Failed(f"{rel} in the {where} is not a regular file — the release writes "
                     f"regular files only")
    if not path.exists():
        return ""
    try:
        with path.open(encoding="utf-8", newline="") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError) as e:
        raise Failed(f"cannot read {rel}: {getattr(e, 'strerror', None) or e}") from None


def read_json(root: Path, rel: str):
    """A marketplace file of the publish repository (None when missing); one that is not a
    JSON object is a failed step: its entries could not be kept."""
    text = read_text(root, rel)
    if not text:
        return None
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as e:
        raise Failed(f"{rel} in the publish repo is not valid JSON ({e}) — fix it: the "
                     f"release merges its entries into it") from None
    if not isinstance(doc, dict):
        raise Failed(f"{rel} in the publish repo is not a JSON object — fix it")
    return doc


def write_text(root: Path, rel: str, text: str) -> None:
    try:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        with (root / rel).open("w", encoding="utf-8", newline="") as fh:
            fh.write(text)
    except OSError as e:
        raise Failed(f"cannot write {rel}: {e.strerror or e}") from None


class Release:
    def __init__(self, args, publish_repo: Path):
        self.args, self.channel = args, args.channel
        self.engine = Repo(ENGINE, "engine")
        self.pub = Repo(publish_repo, "publish repo")
        self.org = args.publish_slug.split("/")[0]
        self.market = publish.MARKETPLACES[self.channel]
        self.claude = shutil.which("claude")
        self.temps: list[Path] = []
        self.version = None
        self.snaps: dict[str, dict] = {}
        self.touched: set[str] = set()  # the repositories written to: only these are put back
        # the refs the run makes or moves, named BEFORE each write: only these are put back
        self.own: dict[str, set[str]] = {self.engine.label: set(), self.pub.label: set()}
        self.made_dirs: list[Path] = []  # step 6's parent directories that were not there
        self.tracking = False  # step 6 made the channel branch track origin's
        self.pushed: list[str] = []  # the push commands that went through

    def temp(self, prefix: str) -> Path:
        path = Path(tempfile.mkdtemp(prefix=prefix))
        self.temps.append(path)
        return path

    def first_write(self, repo: Repo) -> None:
        """Right before the run's first write to `repo`: it is still as step 2 saw it, or a
        refusal naming what appeared — nothing is written to it and nothing of it put back."""
        found = repo.changes(self.snaps[repo.label])
        if found:
            raise Refused(f"the {repo.label} changed since step 2 checked it: {listed(found)} "
                          f"— nothing was written to it; run again when nothing else works "
                          f"in it")
        self.touched.add(repo.label)

    # --- the steps --------------------------------------------------------------------------

    def step1(self) -> str:
        guard = os.environ.get(GUARD)
        if not guard:
            raise Refused(f"{GUARD} is not set — name the private leak guard (the script the "
                          f"host project keeps outside this repository)")
        if not Path(guard).is_file():
            raise Refused(f"{GUARD}: {guard} not found")
        self.guard = Path(guard)
        if ENGINE in Path(os.path.realpath(guard)).parents:
            raise Refused(f"{GUARD} points into the engine — the guard is private: it is "
                          f"never copied or vendored here")
        run_guard(self.guard, ENGINE, "the engine")
        hits = org_hits(self.engine, self.org)
        if hits:
            raise Refused(f"the organisation of --publish-slug appears in the engine: "
                          f"{listed(hits)} — no repository slug before the public release")
        return "CLEAN (files and history); the organisation appears nowhere"

    def step2(self) -> str:
        for repo in (self.engine, self.pub):
            dirty = repo.dirty()
            if dirty:
                raise Refused(f"the {repo.label} is dirty: " + "; ".join(
                    line[3:] for line in dirty[:10]) + " — commit or remove the changes")
            self.snaps[repo.label] = repo.snapshot()  # what the first write compares with
        try:
            current = build_plugins.engine_version(ENGINE)
            version = publish.base_version(current)
        except build_plugins.BuildError as e:
            raise Refused(str(e)) from None
        if self.channel == "stable":
            if not self.engine.branch():
                raise Refused("the engine is not on a branch — a stable release commits there")
            tags = [f"v{version}"] + [f"{name}--v{version}" for name in build_plugins.PLUGINS]
            for repo, names in ((self.engine, tags[:1]), (self.pub, tags)):
                taken = sorted(n for n in names if f"refs/tags/{n}" in repo.refs("refs/tags"))
                if taken:
                    raise Refused(f"{taken[0]} already exists in the {repo.label} — "
                                  f"{version} is released; bump the engine version")
            if current == version:
                raise Refused(f"the engine's __version__ is {current}, without .devN — a "
                              f"stable release makes the release commit itself ({version}"
                              f".devN → {version}): set __version__ and pyproject.toml to the "
                              f".devN version to release")
        for rel in linked_parents(self.pub.path):
            raise Refused(f"{rel} in the publish repo is a symlink or a file — the release "
                          f"writes below it: make it a directory of the repository")
        local, remote = f"refs/heads/{self.channel}", f"refs/remotes/origin/{self.channel}"
        if self.pub.has(local) and self.pub.has(remote) and self.pub.git(
                "merge-base", "--is-ancestor", remote, local, check=False).returncode:
            raise Refused(f"the publish repo's branch {self.channel} is behind origin/"
                          f"{self.channel} or has diverged from it — run `git pull` there "
                          f"first: a release adds to what is published")
        return "the engine and the publish repo are clean"

    def step3(self) -> str:
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        suite = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"],
                               cwd=ENGINE, capture_output=True, text=True, env=env)
        lines = [line for line in suite.stderr.splitlines() if line.strip()]
        ran = next((line for line in lines if line.startswith("Ran ")), "no tests")
        if suite.returncode:
            raise Failed(f"the unit suite failed ({ran}): {suite.stderr.strip()[-600:]}")
        eval_ = subprocess.run([sys.executable, "evals/adoption/run_eval.py"], cwd=ENGINE,
                               capture_output=True, text=True, env=env)
        if eval_.returncode:
            raise Failed(f"the adoption eval failed: {eval_.stderr.strip()[-600:]}")
        verdict = lines[-1] if lines else "OK"  # unittest's own last line: `OK (skipped=1)`
        return f"{ran}, {verdict}; the adoption eval passed"

    def step4(self) -> str:
        if self.channel == "stable":
            self.first_write(self.engine)
            self.bump(publish.base_version(build_plugins.engine_version(ENGINE)),
                      "release modsys {}")
        self.build = self.temp("modsys-release-build-")
        self.version = publish.build_channel(ENGINE, self.build, self.channel)
        return f"modsys {self.version} ({', '.join(build_plugins.PLUGINS)})"

    def bump(self, version: str, message: str) -> None:
        """Set `__version__` and pyproject.toml's version, and commit them here."""
        self.own[self.engine.label].add(self.engine.branch())
        for rel, pattern, line in (
                ("modsys/__init__.py", r'^__version__ = "[^"]*"$', f'__version__ = "{version}"'),
                ("pyproject.toml", r'^version = "[^"]*"$', f'version = "{version}"')):
            text, n = re.subn(pattern, line, read_text(ENGINE, rel, "engine"), count=1,
                              flags=re.M)
            if n != 1:
                raise Failed(f"{rel}: no version line to set")
            write_text(ENGINE, rel, text)
        self.engine.git("add", "--", *VERSION_FILES)
        self.engine.git("commit", "-q", "-m", message.format(version), "--", *VERSION_FILES)

    def step5(self) -> str:
        run_guard(self.guard, self.build, f"the build directory {self.build}")
        hits = dir_hits(self.build, self.org)
        if hits:
            raise Refused(f"the organisation of --publish-slug appears in the build directory: "
                          f"{listed(hits)}")
        tree = self.temp("modsys-release-tree-") / "publish"
        publish.layout(self.build, tree, self.channel)
        problems = publish.codex_problems(tree) + publish.plugin_problems(tree, self.version)
        if problems:
            raise Failed("the laid-out publish tree: " + "; ".join(problems))
        if not self.claude:
            return "our checks passed; claude plugin validate skipped: claude not on PATH"
        config = self.temp("modsys-release-claude-")
        for target in [*(self.build / name for name in build_plugins.PLUGINS), tree]:
            proc = subprocess.run([self.claude, "plugin", "validate", "--strict", "--json",
                                   str(target)], capture_output=True, text=True,
                                  env=self.claude_env(config), timeout=CLAUDE_TIMEOUT)
            if proc.returncode:
                raise Failed(f"claude plugin validate --strict {target.name}: exit "
                             f"{proc.returncode} {proc.stdout.strip()[-600:]}")
        return "our checks passed; claude plugin validate --strict: 3 plugins and the marketplace"

    def base_commit(self) -> str | None:
        """Where a channel branch that exists nowhere starts: the first commit behind the
        publish repository's HEAD (first-parent) that is not a release commit of this tool —
        so a channel never starts on the other channel's releases. None: there is none."""
        log = self.pub.out("log", "--first-parent", "--format=%H %s", "HEAD")
        for line in log.splitlines():
            sha, _, subject = line.partition(" ")
            if not RELEASE_SUBJECT.fullmatch(subject):
                return sha
        return None

    def checkout_channel(self) -> None:
        """HEAD on the channel's branch: the local one; else one made from `origin/<channel>`
        (tracking it); else one made from `base_commit` — an orphan branch when there is none
        (the first branch of a repository without a commit)."""
        pub, channel = self.pub, self.channel
        local, remote = f"refs/heads/{channel}", f"refs/remotes/origin/{channel}"
        self.own[pub.label].add(local)
        if pub.has(local):
            if pub.branch() != local:
                pub.git("switch", "-q", channel)
        elif pub.has(remote):
            self.tracking = True
            if pub.git("switch", "-q", "-c", channel, "--track", f"origin/{channel}",
                       check=False).returncode:  # a ref without its remote: no tracking
                pub.git("switch", "-q", "-c", channel, remote)
        elif not pub.head():
            pub.git("symbolic-ref", "HEAD", local)
        else:
            base = self.base_commit()
            if base:
                pub.git("switch", "-q", "-c", channel, base)
            else:  # only release commits behind HEAD: start empty, not on the other channel
                pub.git("switch", "-q", "--orphan", channel)

    def built(self) -> dict[str, tuple[str, Path]]:
        """{path in the publish repository: (git mode, the built file)} of the three plugins."""
        return {f"plugins/{name}/{path.relative_to(self.build / name).as_posix()}":
                ("100755" if path.stat().st_mode & 0o111 else "100644", path)
                for name in build_plugins.PLUGINS
                for path in sorted((self.build / name).rglob("*")) if path.is_file()}

    def step6(self) -> str:
        pub = self.pub
        self.first_write(pub)
        root = pub.path
        self.made_dirs = [root / rel for rel in reversed(PARENTS) if not (root / rel).exists()]
        self.checkout_channel()
        for rel in linked_parents(root):  # the channel's tree, not the one step 2 saw
            raise Failed(f"{rel} is a symlink or a file on the {self.channel} branch of the "
                         f"publish repo — the release writes below it: make it a directory "
                         f"there; nothing was written")
        old = {rel: read_json(root, rel) for rel in MARKETPLACE_FILES}
        claude, codex = publish.marketplaces(self.channel, old[MARKETPLACE_FILES[0]],
                                             old[MARKETPLACE_FILES[1]])
        new_json = {MARKETPLACE_FILES[0]: publish.dump(claude),
                    MARKETPLACE_FILES[1]: publish.dump(codex)}
        readme_new = replace_section(read_text(root, "README.md"), README_BEGIN, README_END,
                                     readme_section(self.args.publish_slug, self.channel,
                                                    self.version), "README.md")
        log_old = read_text(root, "CHANGELOG.md")
        markers(log_old, LOG_BEGIN, LOG_END, "CHANGELOG.md")  # damaged: fail before a write
        for name in build_plugins.PLUGINS:
            dest = root / "plugins" / name
            try:
                if dest.is_symlink() or dest.is_file():
                    dest.unlink()
                elif dest.exists():
                    shutil.rmtree(dest)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(self.build / name, dest)
            except OSError as e:
                raise Failed(f"cannot write plugins/{name}: {e.strerror or e}") from None
            if os.environ.get(INTERRUPT) == "6":
                raise KeyboardInterrupt
        for rel, text in new_json.items():
            write_text(root, rel, text)
        write_text(root, "README.md", readme_new)
        # -f: no ignore rule — the repository's, the maintainer's — may drop a file of ours
        pub.git("add", "-A", "-f", "--", *OWNED, *MARKETPLACE_FILES, "README.md")
        want = self.built()
        for entry in pub.out("ls-files", "-s", "-z", "--", *OWNED).split("\0"):
            meta, _, path = entry.partition("\t")
            if path in want and meta.split()[0] != want[path][0]:  # core.fileMode=false: the
                flag = "+x" if want[path][0] == "100755" else "-x"  # mode through the index
                pub.git("update-index", f"--chmod={flag}", "--", path)
        if pub.git("diff", "--cached", "--quiet", check=False).returncode == 0:
            raise NothingToRelease(f"the {self.channel} branch already holds modsys "
                                   f"{self.version} — nothing to release")  # git sees no change
        engine_head = self.engine.out("rev-parse", "--short", "HEAD").strip()
        write_text(root, "CHANGELOG.md", changelog(log_old, f"- {self.version} "
                                                            f"({self.channel}): engine "
                                                            f"{engine_head}"))
        pub.git("add", "-f", "--", "CHANGELOG.md")
        return (f"branch {self.channel}: {', '.join(OWNED)} replaced, both marketplace files "
                f"({self.market}), the README and CHANGELOG sections")

    def committed(self) -> None:
        """The release commit holds the build — every path, its mode, its content — or the
        step fails: the published plugins are what was validated, not what git kept of it."""
        want = self.built()
        ids = self.pub.out("hash-object", "--no-filters", "--",
                           *(str(path) for _, path in want.values())).split()
        want = {rel: (mode, oid) for (rel, (mode, _)), oid in zip(want.items(), ids)}
        got = {}
        for entry in self.pub.out("ls-tree", "-r", "-z", "HEAD", "--", *OWNED).split("\0"):
            meta, _, rel = entry.partition("\t")
            if rel:
                mode, _, oid = meta.split()
                got[rel] = (mode, oid)
        wrong = [f"{rel} is missing" for rel in sorted(set(want) - set(got))]
        wrong += [f"{rel} is not of the build" for rel in sorted(set(got) - set(want))]
        wrong += [f"{rel} has mode {got[rel][0]}, not {want[rel][0]}" if got[rel][0] !=
                  want[rel][0] else f"{rel} has other content"
                  for rel in sorted(set(want) & set(got)) if got[rel] != want[rel]]
        if wrong:
            raise Failed(f"the commit does not hold the build: {listed(wrong)} — an ignore "
                         f"rule, a filter or a mode setting of the publish repository changed "
                         f"what git stored")

    def step7(self) -> str:
        pub = self.pub
        pub.git("commit", "-q", "-m", f"release modsys {self.version} ({self.channel})")
        self.committed()
        if os.environ.get(INTERRUPT) == "7":  # the seam: Ctrl-C after the commit, before a tag
            raise KeyboardInterrupt
        sha = pub.out("rev-parse", "--short", "HEAD").strip()
        if self.channel != "stable":
            return f"{sha} release modsys {self.version} ({self.channel}); no tag"
        tags = {f"v{self.version}": "modsys"}
        tags.update({f"{name}--v{self.version}": name for name in build_plugins.PLUGINS})
        for tag, what in tags.items():  # annotated, as `claude plugin tag` makes them
            self.own[pub.label].add(f"refs/tags/{tag}")
            pub.git("tag", "-a", tag, "-m", f"{what} {self.version}")
        self.own[self.engine.label].add(f"refs/tags/v{self.version}")
        self.engine.git("tag", "-a", f"v{self.version}", "-m", f"modsys {self.version}")
        return (f"{sha} release modsys {self.version} (stable); tags {', '.join(tags)}; the "
                f"engine's release commit tagged v{self.version}")

    def step8(self) -> str:
        if not self.claude:
            return "skipped: claude not on PATH"
        config = self.temp("modsys-release-smoke-")
        env = self.claude_env(config)

        def claude(*argv: str) -> str:
            proc = subprocess.run([self.claude, *argv], capture_output=True, text=True, env=env,
                                  timeout=CLAUDE_TIMEOUT)
            if proc.returncode:
                raise Failed(f"claude {' '.join(argv)}: exit {proc.returncode} "
                             f"{(proc.stderr or proc.stdout).strip()[-400:]}")
            return proc.stdout

        claude("--version")
        claude("plugin", "marketplace", "add", str(self.pub.path))
        claude("plugin", "install", f"modsys-ui@{self.market}", "--scope", "user")
        enabled = self.enabled(claude)
        if not {f"modsys@{self.market}", f"modsys-ui@{self.market}"} <= set(enabled):
            raise Failed(f"installing modsys-ui did not install its dependency modsys: "
                         f"{sorted(enabled)}")
        claude("plugin", "install", f"modsys-qa@{self.market}", "--scope", "user")
        enabled = self.enabled(claude)
        missing = sorted({f"{n}@{self.market}" for n in build_plugins.PLUGINS} - set(enabled))
        if missing:
            raise Failed(f"not installed and enabled: {', '.join(missing)}")
        installed = Path(enabled[f"modsys@{self.market}"])
        core = sorted(build_plugins.pack_skills(ENGINE, "core"))
        found = sorted(p.parent.name for p in installed.glob("skills/*/SKILL.md"))
        if found != core:
            raise Failed(f"the installed modsys holds the skills {found}, not {core}")
        details = claude("plugin", "details", f"modsys@{self.market}")
        named = set(re.findall(r"[\w-]+", details))  # whole names: `module` is not `module-init`
        absent = [s for s in core if s not in named]
        if absent:
            raise Failed(f"claude plugin details modsys does not name {', '.join(absent)}")
        launcher = str(installed / "bin/modsys")
        version = build_plugins.engine_version(ENGINE)
        proc = subprocess.run([launcher, "--version"], capture_output=True, text=True)
        if proc.returncode or proc.stdout.strip() != f"modsys {version}":
            raise Failed(f"bin/modsys --version: exit {proc.returncode} "
                         f"{(proc.stdout + proc.stderr).strip()} (want modsys {version})")
        shop = self.temp("modsys-release-shop-") / "bookshop"
        shutil.copytree(ENGINE / "tests/fixtures/bookshop", shop)
        proc = subprocess.run([launcher, "lint", "--root", str(shop)], capture_output=True,
                              text=True)
        if proc.returncode:
            raise Failed(f"bin/modsys lint on the bookshop fixture: exit {proc.returncode} "
                         f"{(proc.stdout + proc.stderr).strip()[-400:]}")
        caches = [p for root in (installed, self.pub.path) for p in root.rglob("__pycache__")]
        if caches:
            raise Failed(f"__pycache__ written: {caches[0]}")
        return (f"modsys, modsys-ui (its dependency modsys installed with it) and modsys-qa "
                f"from {self.market}: {len(core)} core skills, bin/modsys --version = modsys "
                f"{version}, lint exit 0")

    def enabled(self, claude) -> dict[str, str]:
        """{plugin id: installPath} of the enabled plugins (`claude plugin list --json`)."""
        try:
            rows = json.loads(claude("plugin", "list", "--json"))
            return {r["id"]: r["installPath"] for r in rows if r.get("enabled")}
        except (ValueError, KeyError, TypeError) as e:
            raise Failed(f"claude plugin list --json: unexpected output: {e}") from None

    def claude_env(self, config: Path) -> dict:
        env = {k: v for k, v in os.environ.items() if k not in SECRETS}
        return {**env, "CLAUDE_CONFIG_DIR": str(config)}

    def next_version(self) -> str:
        """`stable`: the commit that starts the next version here."""
        if self.channel != "stable":
            return "the engine keeps its version (dev)"
        major, minor, patch = self.version.split(".")
        following = f"{major}.{minor}.{int(patch) + 1}.dev0"
        self.bump(following, "start modsys {}")
        return f"the engine is at {following}"

    def pushes(self) -> list[tuple[Repo, list[str]]]:
        """The push of a finished release, as git arguments per repository (full ref names: a
        tag may be named like the branch): the channel branch and its tags, then — `stable` —
        the engine's branch and `v<version>`."""
        refs = [f"refs/heads/{self.channel}"]
        if self.channel != "stable":
            return [(self.pub, ["push", "--atomic", "origin", *refs])]
        refs += [f"refs/tags/v{self.version}"] + [f"refs/tags/{n}--v{self.version}"
                                                   for n in build_plugins.PLUGINS]
        return [(self.pub, ["push", "--atomic", "origin", *refs]),
                (self.engine, ["push", "--atomic", "origin", self.engine.branch(),
                               f"refs/tags/v{self.version}"])]

    def by_hand(self) -> str:
        """The push commands that did not run (or did not go through), one per line."""
        return "\n".join("  " + shlex.join(["git", "-C", str(repo.path), *args])
                         for repo, args in self.pushes() if repo.label not in self.pushed)

    def push(self) -> str:
        """Only with --push: the channel branch (and its tags), then the engine (stable)."""
        if not self.args.push:
            return ("not requested — the release is committed locally; to publish it (an "
                    "owner command), run:\n" + self.by_hand())
        for repo, args in self.pushes():
            repo.git(*args)
            self.pushed.append(repo.label)
        return "; ".join(f"{repo.label} {', '.join(a.split('/', 2)[2] for a in args[3:])}"
                         for repo, args in self.pushes())

    def run(self) -> int:
        step = 0
        try:
            for repo in (self.engine, self.pub):
                self.snaps[repo.label] = repo.snapshot()
            for step in range(1, 9):
                say(f"step {step} {NAMES[step]}: {getattr(self, f'step{step}')()}")
            step = 9
            say(f"{NAMES[step]}: {self.next_version()}")
            step = 10
            say(f"{NAMES[step]}: {self.push()}")
            say(f"done: modsys {self.version} ({self.channel})")
            return 0
        except NothingToRelease as e:
            return self.stop(step, 0, str(e))
        except Refused as e:
            return self.stop(step, 2, f"error: {e}")
        except (Failed, build_plugins.BuildError, OSError, subprocess.TimeoutExpired) as e:
            return self.stop(step, 1, f"step {step} {NAMES.get(step, 'start')} failed: {e}")
        except KeyboardInterrupt:
            return self.stop(step, 130, "interrupted")
        except Exception as e:  # never a half release, never a traceback
            return self.stop(step, 1, f"step {step} {NAMES.get(step, 'start')} failed: "
                                      f"internal error: {type(e).__name__}: {e}")
        finally:
            for path in self.temps:
                shutil.rmtree(path, ignore_errors=True)

    def stop(self, step: int, code: int, text: str) -> int:
        """End a run that did not finish: put back what it wrote (never at the push — what is
        pushed cannot be taken back) and say what is true. Ctrl-C, SIGTERM and SIGHUP are
        ignored meanwhile: the put-back always finishes."""
        held = set_signals((signal.SIGINT, *TERMINATE), signal.SIG_IGN)
        try:
            if step == 10:
                print(f"{PROG}: {text}{' during the push' if code == 130 else ''} — nothing "
                      f"is put back: the release is committed and tagged locally; pushed: "
                      f"{', '.join(self.pushed) or 'nothing'}; left to push by hand:\n"
                      f"{self.by_hand()}", file=sys.stderr)
                return 130 if code == 130 else 1
            problems = self.put_back()
            if problems:
                print(f"{PROG}: {text}", file=sys.stderr)
                print(f"{PROG}: the put-back is incomplete — finish it by hand:\n"
                      + "\n".join(f"  {line}" for line in problems), file=sys.stderr)
                return 1
            if code == 0:
                say(f"step {step} {NAMES[step]}: {text}")
            elif code == 2:
                print(f"{PROG}: {text}", file=sys.stderr)
            else:
                print(f"{PROG}: {text} — both repositories are as they were", file=sys.stderr)
            return code
        finally:
            for sig, handler in held.items():
                signal.signal(sig, handler)

    def put_back(self) -> list[str]:
        """Put back what the run wrote, in each repository it wrote to (both were clean at its
        first write), both even when one fails; what could not be put back, as lines naming
        the repository and the command or the ref."""
        problems = []
        for repo in (self.engine, self.pub):
            if repo.label in self.touched:
                try:
                    problems += self.restore(repo)
                except (Failed, build_plugins.BuildError, OSError) as e:
                    problems.append(f"{repo.label}: {e}")
        return problems

    def restore(self, repo: Repo) -> list[str]:
        """The refs the run made or moved, HEAD, the index and the files the run writes as in
        the snapshot — nothing else: a ref or an untracked file that appeared beside the run
        stays. Every command runs; the result is then compared with the snapshot."""
        snap, failed = self.snaps[repo.label], []

        def git(*args: str) -> None:
            proc = repo.git(*args, check=False)
            if proc.returncode:
                failed.append(f"{repo.label}: git {' '.join(args)} failed: "
                              f"{(proc.stderr or proc.stdout).strip()}")

        def refs() -> dict[str, str]:
            return {**repo.refs("refs/heads"), **repo.refs("refs/tags")}

        mine = repo is self.pub and not snap["head"]
        if mine:  # no commit before the run: every tracked file is the run's
            git("rm", "-rfq", "--ignore-unmatch", "--", ".")
        now = refs()
        for ref in sorted(self.own[repo.label]):
            was = snap["refs"].get(ref)
            if now.get(ref) != was:
                git("update-ref", *([ref, was] if was else ["-d", ref]))
        if repo is self.pub:
            if snap["branch"]:
                git("symbolic-ref", "HEAD", snap["branch"])
            else:
                git("update-ref", "--no-deref", "HEAD", snap["head"])
            if not mine:
                git("reset", "-q", "--hard")
            git("clean", "-fdqx", "--", *WRITTEN)  # only the paths step 6 writes
            for made in self.made_dirs:
                try:
                    made.rmdir()
                except OSError:
                    pass  # not empty, or not there: not ours to remove
            if self.tracking and f"refs/heads/{self.channel}" not in snap["refs"]:
                repo.git("config", "--remove-section", f"branch.{self.channel}", check=False)
            paths = WRITTEN
        else:
            git("checkout", "-q", "HEAD", "--", *VERSION_FILES)
            paths = VERSION_FILES
        now = refs()
        for ref in sorted(self.own[repo.label]):
            was = snap["refs"].get(ref)
            if now.get(ref) != was:
                failed.append(f"{repo.label}: {ref} is at {now.get(ref) or 'nothing'}, was "
                              f"{was or 'absent'} — git -C {repo.path} update-ref "
                              + (f"{ref} {was}" if was else f"-d {ref}"))
        if (repo.branch(), repo.head()) != (snap["branch"], snap["head"]):
            failed.append(f"{repo.label}: HEAD is {repo.branch() or repo.head()}, was "
                          f"{snap['branch'] or snap['head']}")
        left = repo.dirty(*paths)
        if repo is self.pub:
            left += [line for line in repo.out("status", "--porcelain",
                                               "--untracked-files=no").splitlines()
                     if line not in left]
        if left:
            failed.append(f"{repo.label}: still changed: {listed([l[3:] for l in left])}")
        return failed


TERMINATE = tuple(s for s in (signal.SIGTERM, getattr(signal, "SIGHUP", None)) if s)


def set_signals(signals: tuple, handler, keep_ignored: bool = False) -> dict:
    """Set `handler` for `signals`; {signal: the handler before} to put them back (nothing in
    a thread that is not the main one: signals are the main thread's). `keep_ignored`: a signal
    the caller ignores stays ignored (`nohup` keeps a release running when the terminal
    closes)."""
    before = {}
    for sig in signals:
        try:
            if keep_ignored and signal.getsignal(sig) is signal.SIG_IGN:
                continue
            before[sig] = signal.signal(sig, handler)
        except ValueError:
            pass
    return before


def as_interrupt(signum, frame) -> None:
    raise KeyboardInterrupt  # SIGTERM, SIGHUP (a closed terminal): put back, exit 130


def top_of(path: Path) -> bool:
    """`path` is the top of a git work tree."""
    proc = build_plugins.run_git(path, "rev-parse", "--show-toplevel")
    return not proc.returncode and os.path.realpath(proc.stdout.strip()) == \
        os.path.realpath(path)


def refusal(args, repo: Path) -> str | None:
    """Why the run cannot start (before step 1, nothing run), or None."""
    if not SLUG.fullmatch(args.publish_slug):
        return f"--publish-slug {args.publish_slug!r}: expected OWNER/REPO"
    if not top_of(ENGINE):
        return (f"{ENGINE} is not the top of a git work tree — release from a clone of the "
                f"engine, not an export")
    if not top_of(repo):
        return f"--publish-repo {repo}: not the top of a git work tree"
    if os.path.realpath(repo) == os.path.realpath(ENGINE):
        return "--publish-repo is this engine — give the publish repository"
    if not args.push:
        return None
    if not shutil.which("claude"):
        return "--push needs claude on PATH: the smoke install (step 8) must run before a push"
    pushed = [("the publish repo", repo)] + ([("the engine", ENGINE)]
                                             if args.channel == "stable" else [])
    for label, path in pushed:
        if build_plugins.run_git(path, "remote", "get-url", "origin").returncode:
            return (f"--push: {label} has no remote named origin — add it, or release "
                    f"without --push and push by hand")
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=PROG, description="Release the modsys plugins of "
                                     "this engine into a publish repository.")
    parser.add_argument("--publish-repo", required=True, type=Path,
                        help="the publish repository's local clone")
    parser.add_argument("--channel", required=True, choices=["dev", "stable"])
    parser.add_argument("--publish-slug", required=True, metavar="OWNER/REPO",
                        help="the publish repository on GitHub (only its README section and "
                             "the organisation scan use it)")
    parser.add_argument("--push", action="store_true",
                        help="push the channel branch and the tags (an owner command)")
    args = parser.parse_args(argv)
    held = set_signals(TERMINATE, as_interrupt, keep_ignored=True)
    try:
        repo = args.publish_repo.absolute()
        why = refusal(args, repo)
        if why:
            print(f"{PROG}: error: {why}", file=sys.stderr)
            return 2
        say(f"release modsys: channel {args.channel} (marketplace "
            f"{publish.MARKETPLACES[args.channel]}), publish repo {repo}")
        return Release(args, repo).run()
    except KeyboardInterrupt:
        print(f"{PROG}: interrupted", file=sys.stderr)
        return 130
    except (build_plugins.BuildError, OSError) as e:  # git is not installed, …
        print(f"{PROG}: error: {e}", file=sys.stderr)
        return 2
    finally:
        for sig, handler in held.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    sys.exit(main())
