import contextlib
import io
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from segmently_modules.cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "bookshop"
# a split parent `orders` (children checkout, refunds, invoices; only checkout has a role doc)
# plus the unsplit `catalog` and `payments`
SPLIT_FIXTURE = Path(__file__).parent / "fixtures" / "bookshop_split"

# Every git call of the suite — the helpers' and the engine's own, which runs in-process —
# ignores the developer's global and system git config (e.g. a core.excludesFile hiding *.py)
# and never finds a repository above the temp dir (a TMPDIR inside a work tree).
# Nor does it start git's automatic maintenance: git 2.54 and 2.55 repack a fresh test
# repository after a commit in a detached process that keeps writing under `.git` after the
# command returned — a temp dir's cleanup then fails ("Directory not empty") and a tree taken
# before a step differs from the one after it.
NO_AUTO_MAINTENANCE = {"GIT_CONFIG_COUNT": "2",
                       "GIT_CONFIG_KEY_0": "maintenance.auto", "GIT_CONFIG_VALUE_0": "false",
                       "GIT_CONFIG_KEY_1": "gc.auto", "GIT_CONFIG_VALUE_1": "0"}
os.environ.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
                  GIT_CEILING_DIRECTORIES=os.path.realpath(tempfile.gettempdir()),
                  **NO_AUTO_MAINTENANCE)


os.environ.pop("SEGMENTLY_MODULES_AGENT_COMMAND", None)  # a developer's own agent never reaches a test


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(list(argv))
        except SystemExit as e:  # argparse usage errors / --version
            code = e.code
    return code, out.getvalue(), err.getvalue()


def run_json(*argv):
    code, out, err = run(*argv, "--json")
    return code, (json.loads(out) if out.strip() else None), err


def copy_fixture(tmp: Path, fixture: Path = FIXTURE) -> Path:
    dst = Path(tmp) / "repo"
    shutil.copytree(fixture, dst)
    return dst


def make_repo(tmp, modules: dict, config: str = "", files=()) -> Path:
    """A small synthetic repository `<tmp>/repo`: `modules` maps a module name (or
    "parent/child", listed after its parent) to its keyword list; each gets a registry entry
    and its MODULE.md. `config` becomes `.segmently-modules/config.toml`; every path in `files` is created
    with one line of code."""
    root = Path(tmp) / "repo"
    registry: dict = {"modules": {}}
    for name, keywords in modules.items():
        parent, _, child = name.partition("/")
        doc = (f"modules/{parent}/submodules/{child}/MODULE.md" if child
               else f"modules/{name}/MODULE.md")
        (root / doc).parent.mkdir(parents=True, exist_ok=True)
        (root / doc).write_text(f"# {name}\n", encoding="utf-8")
        entry = {"description": f"The {name} module.", "keywords": list(keywords),
                 "context_files": {"universal": doc}}
        if child:
            registry["modules"][parent].setdefault("submodules", {})[child] = entry
        else:
            registry["modules"][name] = {"name": name, "status": "active", **entry}
    (root / "modules" / "registry.json").write_text(
        json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    (root / ".segmently-modules").mkdir()
    if config:
        (root / ".segmently-modules" / "config.toml").write_text(config, encoding="utf-8")
    for rel in files:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("x = 1\n", encoding="utf-8")
    return root


def mutate_registry(root: Path, fn) -> None:
    p = root / "modules" / "registry.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    fn(data)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def git(root: Path, *args: str) -> str:
    """Run git in a test repo, isolated from the caller's git environment and identity."""
    import subprocess
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               GIT_CEILING_DIRECTORIES=os.environ["GIT_CEILING_DIRECTORIES"],
               **NO_AUTO_MAINTENANCE)
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True,
                          text=True, env=env).stdout


def init_git(root: Path) -> None:
    """Make a fixture copy a git repo with one commit."""
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")


_VERSION_LINE = re.compile(r'^__version__ = "([^"]+)"$', re.M)
_VERSION_FORM = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:\.dev(\d+))?")


def engine_version(engine: Path | None = None) -> str:
    """`__version__` of the engine source under test (`segmently_modules/__init__.py` read as text, never
    an installed copy) — the one place tests learn the version from."""
    root = engine or Path(__file__).resolve().parents[1]
    text = (root / "segmently_modules/__init__.py").read_text(encoding="utf-8")
    return _VERSION_LINE.search(text).group(1)


def dev_version(version: str | None = None) -> str:
    """`version` (default: the engine's) as a dev version: X.Y.Z.devN stays, X.Y.Z (a release tag's
    checkout) -> X.Y.Z.dev0 — what a stable release run needs to start from."""
    version = version or engine_version()
    return version if _VERSION_FORM.fullmatch(version).group(4) is not None else f"{version}.dev0"


def release_version(version: str | None = None) -> str:
    """The release form of `version` (default: the engine's): X.Y.Z.devN -> X.Y.Z."""
    major, minor, patch, _ = _VERSION_FORM.fullmatch(version or engine_version()).groups()
    return f"{major}.{minor}.{patch}"


def next_release(version: str | None = None) -> str:
    """The release after `version`'s: X.Y.Z[.devN] -> X.Y.(Z+1) — what a second stable run makes."""
    major, minor, patch = release_version(version).split(".")
    return f"{major}.{minor}.{int(patch) + 1}"


def next_dev(version: str | None = None) -> str:
    """What the engine is at after a stable release of `version`: X.Y.(Z+1).dev0."""
    return f"{next_release(version)}.dev0"


def next_minor(version: str | None = None) -> str:
    """The next minor release of `version` (default: the engine's): X.Y.Z[.devN] -> X.(Y+1).0."""
    major, minor, _ = release_version(version).split(".")
    return f"{major}.{int(minor) + 1}.0"


def next_major(version: str | None = None) -> str:
    """The next major release of `version` (default: the engine's): X.Y.Z[.devN] -> (X+1).0.0."""
    major = release_version(version).split(".")[0]
    return f"{int(major) + 1}.0.0"


def changelog_since_first_release(log: str) -> str:
    """CHANGELOG.md from `## [Unreleased]` down to `## [0.1.0]` (exclusive): every entry made
    after the first release, whether it still waits in `[Unreleased]` or a later release took
    it — a doc test of a feature keeps finding its entry after the release that ships it."""
    after = log.split("## [Unreleased]", 1)[1]
    return after.split("\n## [0.1.0]", 1)[0]


def changelog_release(log: str, version: str) -> str:
    """The `## [<version>] - <date>` section of CHANGELOG.md, without its heading line: the
    entries one release shipped."""
    after = log.split(f"## [{version}]", 1)[1].split("\n", 1)[1]
    return after.split("\n## [", 1)[0]

