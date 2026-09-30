"""Release the modsys plugins from this engine tree into a publish repository (P6 D7).

    MODSYS_GUARD=<the private leak guard> python3 tools/release.py \\
        --publish-repo DIR --channel dev|stable --publish-slug OWNER/REPO [--push]

Steps, in this order (each printed with its result):
  1 leak guard   the private guard `MODSYS_GUARD` names (run as `<python> <guard> --target
                 DIR`) exits 0 with a `… CLEAN` line on this engine (files and history), and
                 the organisation of --publish-slug appears nowhere in
                 it (files, history — the guard allows the engine's own slug phrase, this scan
                 allows nothing); the guard is never copied or vendored
  2 clean trees  this engine and the publish repository have no change git would see; for
                 `stable`, `v<version>` is in neither and no `<plugin>--v<version>` in the
                 publish repository
  3 tests        the unit suite and the adoption eval (E-A) of this engine
  4 build        `stable`: first the release commit here (`__version__` and pyproject.toml
                 X.Y.Z.devN → X.Y.Z); then tools/build_plugins.py with the channel's version
                 (tools/publish.py) into a temp directory
  5 validate     the guard and the organisation scan over the build; our checks of the laid-out
                 publish tree; `claude plugin validate --strict` of each plugin and of the
                 marketplace (skipped when `claude` is not on PATH)
  6 publish repo the channel's branch (created when missing) gets exactly `plugins/modsys`,
                 `plugins/modsys-ui`, `plugins/modsys-qa` replaced, both marketplace files merged
                 by plugin name (entries it does not own are kept), and its own sections of
                 README.md (the install lines with --publish-slug) and CHANGELOG.md; when git
                 sees no change in them it is "nothing to release" (exit 0, nothing committed)
  7 commit       `release modsys <version> (<channel>)` in the publish repository; `stable` tags
                 `v<version>` and `<plugin>--v<version>` there and `v<version>` here
  8 smoke install a throw-away CLAUDE_CONFIG_DIR: marketplace add, install modsys-ui (its
                 dependency modsys comes with it) and modsys-qa, list, details, the installed
                 `bin/modsys --version` and `lint` on a copy of the bookshop fixture — no model
                 call (skipped when `claude` is not on PATH; then --push is refused)
  then, for `stable`, the commit that starts the next version here (X.Y.(Z+1).dev0), and only
  with --push: `git push --atomic origin` of the channel branch and its tags, then of this
  engine's branch and `v<version>`.
All or nothing: a failed step or Ctrl-C puts both repositories back as they were (branches,
tags, HEAD, index, work tree) and removes every temp directory. Exit 0 done (or nothing to
release) · 1 a step failed · 2 a refusal (stderr names it) · 130 interrupted. Test seam:
MODSYS_RELEASE_INTERRUPT=6 raises Ctrl-C in the middle of step 6, =7 in step 7 between the
commit and the tags."""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

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
GUARD = "MODSYS_GUARD"  # the environment variable naming the private leak guard
CLEAN = re.compile(r"^\S+: CLEAN$", re.M)  # its verdict line (its name is never spelled here)
INTERRUPT = "MODSYS_RELEASE_INTERRUPT"
SECRETS = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")
CLAUDE_TIMEOUT = 300  # seconds per `claude` call: a hanging CLI fails the step, never the run


class Refused(Exception):
    """Exit 2: a precondition does not hold (both repositories are put back)."""


class Failed(Exception):
    """Exit 1: a step failed (both repositories are put back)."""


class NothingToRelease(Exception):
    """Exit 0: the channel already holds this build (both repositories are put back)."""


def say(text: str) -> None:
    print(text, flush=True)


class Repo:
    """A git repository the release may write to, with a snapshot to put it back."""

    def __init__(self, path: Path, label: str):
        self.path, self.label = path, label

    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        proc = subprocess.run(["git", "-C", str(self.path), *args], capture_output=True,
                              text=True)
        if check and proc.returncode:
            raise Failed(f"{self.label}: git {' '.join(args)} failed: "
                         f"{(proc.stderr or proc.stdout).strip()}")
        return proc

    def out(self, *args: str) -> str:
        return self.git(*args).stdout

    def refs(self, kind: str) -> dict[str, str]:
        text = self.out("for-each-ref", "--format=%(refname:short) %(objectname)",
                        f"refs/{kind}")
        return dict(line.split(" ", 1) for line in text.splitlines() if line)

    def head(self) -> str | None:
        proc = self.git("rev-parse", "--verify", "-q", "HEAD", check=False)
        return proc.stdout.strip() or None

    def branch(self) -> str | None:
        proc = self.git("symbolic-ref", "-q", "HEAD", check=False)
        return proc.stdout.strip() or None

    def dirty(self) -> list[str]:
        return self.out("status", "--porcelain", "--untracked-files=all").splitlines()

    def snapshot(self) -> dict:
        return {"branch": self.branch(), "head": self.head(), "branches": self.refs("heads"),
                "tags": self.refs("tags")}

    def restore(self, snap: dict) -> None:
        """Branches, tags, HEAD, index and work tree as in `snap` (the tree was clean then)."""
        now = self.refs("heads")
        for name in now:
            if name not in snap["branches"]:
                self.git("update-ref", "-d", f"refs/heads/{name}", check=False)
        for name, sha in snap["branches"].items():
            if now.get(name) != sha:
                self.git("update-ref", f"refs/heads/{name}", sha, check=False)
        for name in self.refs("tags"):
            if name not in snap["tags"]:
                self.git("tag", "-d", name, check=False)
        if snap["branch"]:
            self.git("symbolic-ref", "HEAD", snap["branch"], check=False)
        elif snap["head"]:
            self.git("update-ref", "--no-deref", "HEAD", snap["head"], check=False)
        if snap["head"]:
            self.git("reset", "-q", "--hard", check=False)
        else:
            self.git("read-tree", "--empty", check=False)
        self.git("clean", "-fdq", check=False)


def run_guard(guard: Path, target: Path, where: str) -> None:
    """The private leak guard over `target`: CLEAN, or a refusal naming the hit count (the
    guard's own lines go to the operator's terminal only)."""
    proc = subprocess.run([sys.executable, str(guard), "--target", str(target)],
                          capture_output=True, text=True,
                          env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    if proc.returncode == 0 and CLEAN.search(proc.stdout):
        return
    if proc.returncode == 1:
        for line in proc.stdout.splitlines():
            print(line, file=sys.stderr)
        count = re.search(r"(\d+) hit\(s\)", proc.stdout)
        raise Refused(f"the leak guard found {count.group(1) if count else 'some'} hit(s) in "
                      f"{where} — fix them in the engine")
    raise Refused(f"the leak guard failed on {where} (exit {proc.returncode}): "
                  f"{(proc.stderr or proc.stdout).strip()}")


def org_hits(engine: Repo, org: str) -> list[str]:
    """Where the organisation appears in the engine (any case): `file <path>` for a tracked
    file, `history` for a commit message or any content in its history."""
    needle = org.lower().encode()
    hits = []
    for rel in engine.out("ls-files", "-z").split("\0"):
        path = engine.path / rel
        if rel and path.is_file() and not path.is_symlink():
            try:
                if needle in path.read_bytes().lower():
                    hits.append(f"file {rel}")
            except OSError as e:
                raise Refused(f"cannot read {rel}: {e.strerror or e}") from None
    log = subprocess.run(["git", "-C", str(engine.path), "log", "--all", "-p", "--text",
                          "--format=%H%n%B"], capture_output=True).stdout
    if needle in log.lower():
        hits.append("history")
    return hits


def dir_hits(root: Path, org: str) -> list[str]:
    needle = org.lower().encode()
    return [f"build {p.relative_to(root).as_posix()}" for p in sorted(root.rglob("*"))
            if p.is_file() and needle in p.read_bytes().lower()]


def replace_section(text: str, begin: str, end: str, body: str) -> str:
    """`text` with the part between the markers replaced by `body` (appended with the markers
    when absent); the text outside them unchanged."""
    block = f"{begin}\n{body}{end}\n"
    if begin in text and end in text and text.index(begin) < text.index(end):
        head, rest = text.split(begin, 1)
        tail = rest.split(end, 1)[1]
        return head + block[:-1] + tail
    return text + ("\n" if text and not text.endswith("\n") else "") + \
        ("\n" if text else "") + block


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


def changelog(text: str, entry: str) -> str:
    """CHANGELOG.md with `entry` added at the top of the modsys section."""
    if LOG_BEGIN in text and LOG_END in text and text.index(LOG_BEGIN) < text.index(LOG_END):
        head, rest = text.split(LOG_BEGIN, 1)
        body, tail = rest.split(LOG_END, 1)
        lines = body.strip("\n").splitlines()
        at = next((i for i, line in enumerate(lines) if line.startswith("- ")), len(lines))
        if at == len(lines) and lines and lines[-1].strip():
            lines.append("")  # a section without an entry yet: a blank line after its heading
            at += 1
        lines.insert(at, entry)  # the newest first
        return head + LOG_BEGIN + "\n" + "\n".join(lines) + "\n" + LOG_END + tail
    return replace_section(text, LOG_BEGIN, LOG_END, f"## modsys\n\n{entry}\n")


def read_text(root: Path, rel: str, where: str = "publish repo") -> str:
    """A text file the release rewrites ("" when missing); a symlink, a directory or a file that
    is not UTF-8 is a failed step naming it — never written through, never guessed."""
    path = root / rel
    if path.is_symlink() or (os.path.lexists(path) and not path.is_file()):
        raise Failed(f"{rel} in the {where} is not a regular file — the release writes "
                     f"regular files only")
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
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
        (root / rel).write_text(text, encoding="utf-8")
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
        self.touched: set[str] = set()  # the repositories written to: only these are put back

    def temp(self, prefix: str) -> Path:
        path = Path(tempfile.mkdtemp(prefix=prefix))
        self.temps.append(path)
        return path

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
                          f"{', '.join(hits)} — no repository slug before the public release")
        return "CLEAN (files and history); the organisation appears nowhere"

    def step2(self) -> str:
        for repo in (self.engine, self.pub):
            dirty = repo.dirty()
            if dirty:
                raise Refused(f"the {repo.label} is dirty: " + "; ".join(
                    line[3:] for line in dirty[:10]) + " — commit or remove the changes")
        try:
            version = publish.base_version(build_plugins.engine_version(ENGINE))
        except build_plugins.BuildError as e:
            raise Refused(str(e)) from None
        if self.channel == "stable":
            if not self.engine.branch():
                raise Refused("the engine is not on a branch — a stable release commits there")
            tags = [f"v{version}"] + [f"{name}--v{version}" for name in build_plugins.PLUGINS]
            for repo, names in ((self.engine, tags[:1]), (self.pub, tags)):
                taken = sorted(set(names) & set(repo.refs("tags")))
                if taken:
                    raise Refused(f"{taken[0]} already exists in the {repo.label} — "
                                  f"{version} is released; bump the engine version")
        return "the engine and the publish repo are clean"

    def step3(self) -> str:
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        suite = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"],
                               cwd=ENGINE, capture_output=True, text=True, env=env)
        ran = next((l for l in suite.stderr.splitlines() if l.startswith("Ran ")), "no tests")
        if suite.returncode:
            raise Failed(f"the unit suite failed ({ran}): {suite.stderr.strip()[-600:]}")
        eval_ = subprocess.run([sys.executable, "evals/adoption/run_eval.py"], cwd=ENGINE,
                               capture_output=True, text=True, env=env)
        if eval_.returncode:
            raise Failed(f"the adoption eval failed: {eval_.stderr.strip()[-600:]}")
        return f"{ran}, OK; the adoption eval passed"

    def step4(self) -> str:
        if self.channel == "stable":
            self.touched.add("engine")
            self.bump(publish.base_version(build_plugins.engine_version(ENGINE)),
                      "release modsys {}")
        self.build = self.temp("modsys-release-build-")
        self.version = publish.build_channel(ENGINE, self.build, self.channel)
        return f"modsys {self.version} ({', '.join(build_plugins.PLUGINS)})"

    def bump(self, version: str, message: str) -> None:
        """Set `__version__` and pyproject.toml's version, and commit them here."""
        for rel, pattern, line in (
                ("modsys/__init__.py", r'^__version__ = "[^"]*"$', f'__version__ = "{version}"'),
                ("pyproject.toml", r'^version = "[^"]*"$', f'version = "{version}"')):
            text, n = re.subn(pattern, line, read_text(ENGINE, rel, "engine"), count=1,
                              flags=re.M)
            if n != 1:
                raise Failed(f"{rel}: no version line to set")
            write_text(ENGINE, rel, text)
        self.engine.git("add", "--", "modsys/__init__.py", "pyproject.toml")
        self.engine.git("commit", "-q", "-m", message.format(version))

    def step5(self) -> str:
        run_guard(self.guard, self.build, f"the build directory {self.build}")
        hits = dir_hits(self.build, self.org)
        if hits:
            raise Refused(f"the organisation of --publish-slug appears in the build directory: "
                          f"{', '.join(hits)}")
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

    def step6(self) -> str:
        pub = self.pub
        self.touched.add("publish")
        if self.channel in pub.refs("heads"):
            if pub.branch() != f"refs/heads/{self.channel}":
                pub.git("checkout", "-q", self.channel)
        elif pub.head():
            pub.git("checkout", "-q", "-b", self.channel)
        else:  # a new repository without a commit: the channel's branch is its first
            pub.git("symbolic-ref", "HEAD", f"refs/heads/{self.channel}")
        root = pub.path
        old = {rel: read_json(root, rel) for rel in MARKETPLACE_FILES}
        claude, codex = publish.marketplaces(self.channel, old[MARKETPLACE_FILES[0]],
                                             old[MARKETPLACE_FILES[1]])
        new_json = {MARKETPLACE_FILES[0]: publish.dump(claude),
                    MARKETPLACE_FILES[1]: publish.dump(codex)}
        readme_new = replace_section(read_text(root, "README.md"), README_BEGIN, README_END,
                                     readme_section(self.args.publish_slug, self.channel,
                                                    self.version))
        log_old = read_text(root, "CHANGELOG.md")
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
        pub.git("add", "-A", "--", *OWNED, *MARKETPLACE_FILES, "README.md")
        if pub.git("diff", "--cached", "--quiet", check=False).returncode == 0:
            raise NothingToRelease(f"the {self.channel} branch already holds modsys "
                                   f"{self.version} — nothing to release")  # git sees no change
        engine_head = self.engine.out("rev-parse", "--short", "HEAD").strip()
        write_text(root, "CHANGELOG.md", changelog(log_old, f"- {self.version} "
                                                            f"({self.channel}): engine "
                                                            f"{engine_head}"))
        pub.git("add", "--", "CHANGELOG.md")
        return (f"branch {self.channel}: {', '.join(OWNED)} replaced, both marketplace files "
                f"({self.market}), the README and CHANGELOG sections")

    def step7(self) -> str:
        pub = self.pub
        pub.git("commit", "-q", "-m", f"release modsys {self.version} ({self.channel})")
        if os.environ.get(INTERRUPT) == "7":  # the seam: Ctrl-C after the commit, before a tag
            raise KeyboardInterrupt
        sha = pub.out("rev-parse", "--short", "HEAD").strip()
        if self.channel != "stable":
            return f"{sha} release modsys {self.version} ({self.channel}); no tag"
        tags = {f"v{self.version}": "modsys"}
        tags.update({f"{name}--v{self.version}": name for name in build_plugins.PLUGINS})
        for tag, what in tags.items():  # annotated, as `claude plugin tag` makes them
            pub.git("tag", "-a", tag, "-m", f"{what} {self.version}")
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
        absent = [s for s in core if s not in details]
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

    def push(self) -> str:
        """Only with --push: the channel branch (and its tags), then the engine (stable)."""
        if not self.args.push:
            return "not requested (an owner command: run again with --push to publish)"
        refs = [self.channel]
        if self.channel == "stable":
            refs += [f"v{self.version}"] + [f"{n}--v{self.version}"
                                             for n in build_plugins.PLUGINS]
        self.pub.git("push", "--atomic", "origin", *refs)
        if self.channel == "stable":
            branch = self.engine.branch().removeprefix("refs/heads/")
            self.engine.git("push", "--atomic", "origin", branch, f"v{self.version}")
        return f"publish repo {', '.join(refs)}" + (
            f"; engine {self.engine.branch().removeprefix('refs/heads/')}, v{self.version}"
            if self.channel == "stable" else "")

    def run(self) -> int:
        snaps = {"engine": self.engine.snapshot(), "publish": self.pub.snapshot()}
        names = {1: "leak guard", 2: "clean trees", 3: "tests", 4: "build", 5: "validate",
                 6: "publish repo", 7: "commit", 8: "smoke install", 9: "next version",
                 10: "push"}
        step = 0
        try:
            for step in range(1, 9):
                say(f"step {step} {names[step]}: {getattr(self, f'step{step}')()}")
            step = 9
            say(f"{names[step]}: {self.next_version()}")
            step = 10
            say(f"{names[step]}: {self.push()}")
            say(f"done: modsys {self.version} ({self.channel})")
            return 0
        except NothingToRelease as e:
            self.put_back(snaps)
            say(f"step {step} {names[step]}: {e}")
            return 0
        except Refused as e:
            self.put_back(snaps)
            print(f"{PROG}: error: {e}", file=sys.stderr)
            return 2
        except (Failed, build_plugins.BuildError, OSError, subprocess.TimeoutExpired) as e:
            if step == 10:  # a push failed: the release stands locally, nothing is put back
                print(f"{PROG}: push failed: {e} — the release is committed and tagged "
                      f"locally; push by hand", file=sys.stderr)
                return 1
            self.put_back(snaps)
            print(f"{PROG}: step {step} {names[step]} failed: {e} — both repositories "
                  f"are as they were", file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            self.put_back(snaps)
            print(f"{PROG}: interrupted — both repositories are as they were", file=sys.stderr)
            return 130
        except Exception as e:  # never a half release, never a traceback
            self.put_back(snaps)
            print(f"{PROG}: step {step} {names.get(step, '')} failed: internal error: "
                  f"{type(e).__name__}: {e} — both repositories are as they were",
                  file=sys.stderr)
            return 1
        finally:
            for path in self.temps:
                shutil.rmtree(path, ignore_errors=True)

    def put_back(self, snaps: dict) -> None:
        """Only a repository this run wrote to (both were clean when step 2 checked them)."""
        if "engine" in self.touched:
            self.engine.restore(snaps["engine"])
        if "publish" in self.touched:
            self.pub.restore(snaps["publish"])


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
    if not SLUG.fullmatch(args.publish_slug):
        print(f"{PROG}: error: --publish-slug {args.publish_slug!r}: expected OWNER/REPO",
              file=sys.stderr)
        return 2
    repo = args.publish_repo.absolute()
    top = subprocess.run(["git", "-C", str(repo), "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True)
    if top.returncode or os.path.realpath(top.stdout.strip()) != os.path.realpath(repo):
        print(f"{PROG}: error: --publish-repo {repo}: not the top of a git work tree",
              file=sys.stderr)
        return 2
    if os.path.realpath(repo) == os.path.realpath(ENGINE):
        print(f"{PROG}: error: --publish-repo is this engine — give the publish repository",
              file=sys.stderr)
        return 2
    if args.push and not shutil.which("claude"):
        print(f"{PROG}: error: --push needs claude on PATH: the smoke install (step 8) must "
              f"run before a push", file=sys.stderr)
        return 2
    say(f"release modsys: channel {args.channel} (marketplace "
        f"{publish.MARKETPLACES[args.channel]}), publish repo {repo}")
    return Release(args, repo).run()


if __name__ == "__main__":
    sys.exit(main())
