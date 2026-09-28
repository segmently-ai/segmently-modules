"""Helpers of the `init` phase 4–7 tests: a git copy of `bookshop_monorepo` taken through `init
map` and gate 3, calls that assert their exit code, and the fake executor's command line."""
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
    only `init finish` may change (P5B-AC-011)."""
    h = hashlib.sha256()
    for rel in ("modules", "CLAUDE.md", "AGENTS.md", ".modsys/config.toml"):
        path = root / rel
        files = sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else \
            [path] if path.is_file() else []
        for p in files:
            h.update(p.relative_to(root).as_posix().encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()
