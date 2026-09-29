"""Helpers of the `init` phase 4–7 tests: a git copy of `bookshop_monorepo` taken through `init
map` and gate 3, calls that assert their exit code, the fake executor's command line, and a
`gh` stand-in plus a local bare remote for `init finish --open-pr` (no network, no real PR)."""
import hashlib
import json
import shlex
import sys
from pathlib import Path

from tests.fixtures.build_monorepo import build
from tests.helpers import run, run_json

FAKE = Path(__file__).resolve().parent / "init_fake_executor.py"
WORK = ".modsys/init"
SIX = ["cart", "catalog", "payments", "recommendations", "storefront", "ui-kit"]
ROLES = ["developer", "qa", "po", "architect"]


def executor(*flags: str) -> str:
    """`--executor` for the fake executor (this interpreter; paths quoted for `shlex`)."""
    return " ".join(shlex.quote(a) for a in (sys.executable, str(FAKE), *flags))


def ok(root: Path, *argv: str, code: int = 0):
    """`modsys <argv> --json --root <root>`: the data (None when stdout is empty)."""
    got, env, err = run_json(*argv, "--root", str(root))
    assert got == code, (argv, got, err, env)
    return env["data"] if env else None


def text(root: Path, *argv: str) -> tuple[int, str, str]:
    return run(*argv, "--root", str(root))


def shop(base: Path, name: str = "shop", exclude=("tools",), config: str = "") -> Path:
    """`bookshop_monorepo` with its history, `init map`, the candidates in `exclude` switched
    off, `init confirm` — gate 3 passed (six modules by default: `tools` excluded)."""
    root = build(Path(base) / name)
    ok(root, "init", "map")
    if config:
        path = root / ".modsys/config.toml"
        path.write_text(path.read_text(encoding="utf-8") + "\n" + config, encoding="utf-8")
    proposal = root / WORK / "proposal.json"
    doc = json.loads(proposal.read_text(encoding="utf-8"))
    for c in doc["candidates"]:
        c["include"] = c["name"] not in exclude
    proposal.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    ok(root, "init", "confirm")
    return root


def state(root: Path) -> dict:
    return json.loads((root / WORK / "state.json").read_text(encoding="utf-8"))


def statuses(root: Path) -> dict:
    return {m: e["status"] for m, e in state(root)["modules"].items()}


def tree_sha(path: Path) -> str:
    """sha256 over every file below `path` (relative path + bytes), sorted."""
    h = hashlib.sha256()
    for p in sorted(Path(path).rglob("*")):
        if p.is_file():
            h.update(p.relative_to(path).as_posix().encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


def protected_sha(root: Path) -> str:
    """sha256 over `modules/`, the registry, CLAUDE.md / AGENTS.md and the team config — what
    only `init finish` may change (P5B-AC-011); the writers' `*.lock` files do not count."""
    h = hashlib.sha256()
    for rel in ("modules", "CLAUDE.md", "AGENTS.md", ".modsys/config.toml"):
        path = root / rel
        files = sorted(p for p in path.rglob("*") if p.is_file() and p.suffix != ".lock") \
            if path.is_dir() else [path] if path.is_file() else []
        for p in files:
            h.update(p.relative_to(root).as_posix().encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}


def gh_shim(bin_dir: Path, log: Path, code: int = 0, remember: bool = False) -> Path:
    """An executable `gh` in `bin_dir` (put it first on PATH): it appends {argv, body} to `log`
    as a JSON line, prints a pull request URL and exits `code`. `remember`: like `gh`, a second
    `pr create` for the same head branch is refused — `… already exists:` and the first one's
    URL on stderr, exit 1 (the log line says `created: false`)."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    shim = bin_dir / "gh"
    url = "https://example.invalid/bookshop/pull/1"
    seen = f"{str(log)!r} + '.heads'"
    shim.write_text(
        f"#!{sys.executable}\nimport json, os, sys\nargs = sys.argv[1:]\nbody = None\n"
        f"if '--body-file' in args:\n    body = open(args[args.index('--body-file') + 1]).read()\n"
        f"head = args[args.index('--head') + 1] if '--head' in args else None\n"
        f"heads = open({seen}).read().split() if os.path.exists({seen}) else []\n"
        f"again = {remember!r} and head in heads\n"
        f"with open({str(log)!r}, 'a') as fh:\n"
        f"    fh.write(json.dumps({{'argv': args, 'body': body, 'created': not again}}) + '\\n')\n"
        f"if again:\n"
        f"    print(f'a pull request for branch \"{{head}}\" into branch \"main\" already exists:',"
        f" file=sys.stderr)\n"
        f"    print({url!r}, file=sys.stderr)\n    sys.exit(1)\n"
        f"if {remember!r}:\n    open({seen}, 'a').write(f'{{head}}\\n')\n"
        f"print({url!r})\nsys.exit({code})\n")
    shim.chmod(0o755)
    return shim


def bare_remote(root: Path, remote: Path) -> Path:
    """A local bare repository as the `origin` of `root`."""
    from tests.helpers import git
    git(remote.parent, "init", "-q", "--bare", remote.name)
    git(root, "remote", "add", "origin", str(remote))
    return remote
