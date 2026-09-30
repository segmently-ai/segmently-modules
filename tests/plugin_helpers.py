"""Helpers of the P6 packaging tests: a throw-away copy of this engine as its own git repository
(the tools build and release the tree they live in), the tools loaded by path, and a
throw-away Claude Code configuration for the real `claude` when it is on PATH."""
import importlib.util
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

from tests.helpers import git

ENGINE = Path(__file__).resolve().parents[1]
CLAUDE = shutil.which("claude")
NO_CLAUDE = "claude not on PATH"  # the visible skip reason (P6-AC-011)


def engine_files(prefixes=("modsys/", "tools/")) -> list[str]:
    """This engine's files under `prefixes` that git tracks or would track (untracked but not
    ignored: a task's new file before its commit), plus pyproject.toml and .gitignore."""
    out = subprocess.run(["git", "-C", str(ENGINE), "ls-files", "-z", "--cached", "--others",
                          "--exclude-standard"], capture_output=True, text=True,
                         check=True).stdout.split("\0")
    return sorted(p for p in out if p and (p.startswith(prefixes) or p in (
        "pyproject.toml", ".gitignore")) and (ENGINE / p).is_file())


def copy_engine(dest: Path, extra: dict[str, str] | None = None,
                prefixes=("modsys/", "tools/")) -> Path:
    """A git repository at `dest` holding this engine's files (modes kept) and `extra`
    {path: text}, committed once — what the tools see in a clone of the engine."""
    for rel in engine_files(prefixes):
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ENGINE / rel, dest / rel)
    for rel, text in (extra or {}).items():
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        (dest / rel).write_text(text, encoding="utf-8")
    git(dest, "init", "-q", "-b", "main")
    git(dest, "add", "-A")
    git(dest, "commit", "-q", "-m", "engine")
    return dest


def load_tool(name: str):
    """`tools/<name>.py` of this engine as a module (the tools are scripts, not a package)."""
    path = ENGINE / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"modsys_tool_{name}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run_tool(engine: Path, name: str, *argv: str, env: dict | None = None, **kw):
    """Run `tools/<name>.py` of the engine copy `engine` with this Python."""
    return subprocess.run([sys.executable, str(engine / "tools" / f"{name}.py"), *argv],
                          capture_output=True, text=True, env={**os.environ, **(env or {})},
                          **kw)


def claude_env(config_dir: Path) -> dict:
    """The environment of a real `claude` call: a throw-away config, no credentials."""
    config_dir.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items()
           if k not in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")}
    return {**env, "CLAUDE_CONFIG_DIR": str(config_dir)}


def tree(root: Path) -> dict[str, tuple[int, bytes]]:
    """{relative path: (mode bits, bytes)} of every file below `root`, and every directory's
    mode under the key `<dir>/`."""
    out = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        mode = stat.S_IMODE(path.lstat().st_mode)
        out[rel + "/" if path.is_dir() else rel] = (mode, b"" if path.is_dir()
                                                    else path.read_bytes())
    return out
