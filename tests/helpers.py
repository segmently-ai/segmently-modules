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
