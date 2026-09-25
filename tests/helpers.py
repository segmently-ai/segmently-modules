import contextlib
import io
import json
import shutil
from pathlib import Path

from modsys.cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "bookshop"


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


def copy_fixture(tmp: Path) -> Path:
    dst = Path(tmp) / "repo"
    shutil.copytree(FIXTURE, dst)
    return dst


def mutate_registry(root: Path, fn) -> None:
    p = root / "modules" / "registry.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    fn(data)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def git(root: Path, *args: str) -> str:
    """Run git in a test repo, isolated from the caller's git environment and identity."""
    import os
    import subprocess
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True,
                          text=True, env=env).stdout


def init_git(root: Path) -> None:
    """Make a fixture copy a git repo with one commit."""
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
