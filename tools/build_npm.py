"""Build the npm package `@segmently/modules` from this engine tree — stdlib only, deterministic.

    python3 tools/build_npm.py [--out dist/npm] [--version V]

writes one package directory, --out itself (default `dist/npm` of this engine tree):
  package.json                 `@segmently/modules`, the version (the engine's X.Y.Z, or X.Y.Z-dev.N
                               for X.Y.Z.devN), the command `segmently-modules`, macOS and Linux
  bin/segmently-modules        tools/launcher.sh, mode 0755 — the plugin's launcher: the first
                               Python 3.9 or newer it finds runs the engine below; Node runs nothing
  runtime/segmently_modules/   the files git tracks under segmently_modules/, byte for byte — what the
                               core plugin's runtime/ holds
  README.md, LICENSE
The engine is read as tools/build_plugins.py reads it: git's index decides what ships, a
file's mode comes from it, nothing carries a timestamp — two builds of one tree are
byte-identical. The package is built in a temp directory next to --out and renamed into place
at the end; --out is replaced only when it is an earlier build of the package (its
package.json names it), never when it is this engine tree or holds it.
Publishing is a maintainer's step (docs/releasing.md): `npm publish <out> --tag next` for a dev
version, `--tag latest` for a release.
Exit 0 built · 2 a refusal (stdout empty, stderr `build_npm.py: error: …`) · 130 Ctrl-C."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_plugins  # noqa: E402  (a sibling script)
from build_plugins import (HOMEPAGE, KEYWORDS, BuildError, engine_version,  # noqa: E402
                           modified, read, semver_ok, tracked, write)

ENGINE = Path(__file__).resolve().parents[1]
PROG = "build_npm.py"
NAME = "@segmently/modules"
COMMAND = "segmently-modules"
DEV = re.compile(r"^(\d+\.\d+\.\d+)\.dev(\d+)$")
STABLE = re.compile(r"^\d+\.\d+\.\d+$")


def npm_version(version: str) -> str:
    """The npm form of an engine version: X.Y.Z as it is, X.Y.Z.devN → X.Y.Z-dev.N."""
    if STABLE.match(version):
        return version
    m = DEV.match(version)
    if m:
        return f"{m.group(1)}-dev.{m.group(2)}"
    raise BuildError(f"the engine's version {version!r} is neither X.Y.Z nor X.Y.Z.devN — give "
                     f"--version")


def dist_tag(version: str) -> str:
    """The npm dist-tag a version is published under: `latest` for X.Y.Z, else `next`."""
    return "latest" if STABLE.match(version) else "next"


def description(engine: Path) -> str:
    """`[project] description` of pyproject.toml."""
    try:
        text = read(engine, "pyproject.toml").decode("utf-8")
        value = build_plugins.tomllib.loads(text)["project"]["description"]
    except (UnicodeDecodeError, build_plugins.tomllib.TOMLDecodeError, KeyError) as e:
        raise BuildError(f"pyproject.toml holds no [project] description: {e}") from None
    return value


def package_json(version: str, about: str) -> bytes:
    doc = {
        "name": NAME,
        "version": version,
        "description": about,
        "license": build_plugins.LICENSE,
        "homepage": HOMEPAGE,
        "repository": {"type": "git", "url": f"git+{HOMEPAGE}.git"},
        "bugs": {"url": f"{HOMEPAGE}/issues"},
        "keywords": KEYWORDS,
        "bin": {COMMAND: f"bin/{COMMAND}"},
        "files": ["bin/", "runtime/"],
        "os": ["darwin", "linux"],
        "publishConfig": {"access": "public"},
    }
    return (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def readme(version: str, about: str) -> bytes:
    docs = f"{HOMEPAGE}/tree/v{version}" if STABLE.match(version) else HOMEPAGE
    text = f"""# Segmently Modules

{about}: a module registry, per-module interface docs and per-role context files, maintained
by a command line and agent skills.

```bash
npm install -g {NAME}
{COMMAND} --help
npx {NAME} --help      # or without installing
```

The package carries the engine (pure Python) and a POSIX `sh` launcher; Node runs nothing.
It needs **Python 3.9 or newer** — on macOS the `python3` of the Command Line Tools (the package
that brings git) is enough — and **git**. The launcher takes `SEGMENTLY_MODULES_PYTHON` when set,
else the first `python3.14` … `python3.9`, `python3` it finds, else `uv run`. macOS and Linux.

The docs, the Claude Code and Codex plugins (they carry the skills) and the changelog:
{docs}. License: MIT.
"""
    return text.encode("utf-8")


def is_build(path: Path) -> bool:
    """`path` is a directory holding an earlier build of the package (its package.json names it)."""
    if path.is_symlink() or not path.is_dir():
        return False
    try:
        doc = json.loads((path / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(doc, dict) and doc.get("name") == NAME


def check_out(engine: Path, out: Path) -> None:
    here = Path(os.path.realpath(engine))
    real = Path(os.path.realpath(out))
    if real == here or real in here.parents:
        raise BuildError(f"--out {out} is this engine tree or holds it — the build would "
                         f"replace it; give another directory")
    if os.path.lexists(out) and not is_build(out):
        raise BuildError(f"{out} exists and is not a build of {NAME} (no package.json naming "
                         f"it) — the build replaces only its own output; remove it or give "
                         f"another --out")


def build(engine: Path, out: Path, version: str | None = None) -> dict:
    """Build the package into `out`. {version, tag, out, files, modified}; BuildError on a
    refusal — nothing written then."""
    if version is not None and not semver_ok(version):
        raise BuildError(f"--version {version!r}: a SemVer 2.0 version is required "
                         f"(e.g. 0.2.1, 0.2.1-dev.3)")
    version = version or npm_version(engine_version(engine))
    files = tracked(engine)
    about = description(engine)
    launcher = read(engine, "tools/launcher.sh")
    license_text = read(engine, "LICENSE")
    check_out(engine, out)
    changed = modified(engine)
    parent = out.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".segmently-modules-npm-", dir=parent))
    aside = None
    try:
        new = staging / "package"
        write(new / "package.json", package_json(version, about), 0o644)
        write(new / "README.md", readme(version, about), 0o644)
        write(new / "LICENSE", license_text, 0o644)
        write(new / "bin" / COMMAND, launcher, 0o755)
        for rel, mode in files.items():
            write(new / "runtime" / rel, read(engine, rel), mode)
        for d in [new, *(p for p in new.rglob("*") if p.is_dir())]:
            os.chmod(d, 0o755)
        if os.path.lexists(out):
            aside = staging / "earlier"
            os.rename(out, aside)
        try:
            os.rename(new, out)
        except OSError:
            if aside is not None:
                os.rename(aside, out)
            raise
    except OSError as e:
        raise BuildError(f"cannot write {e.filename or out}: {e.strerror or e}") from None
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return {"version": version, "tag": dist_tag(version), "out": str(out),
            "files": len(files) + 4, "modified": changed}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=PROG, description=f"Build the npm package {NAME} "
                                     "from this engine tree.")
    parser.add_argument("--out", type=Path, default=ENGINE / "dist/npm",
                        help="the package directory to write (default: dist/npm of the engine)")
    parser.add_argument("--version", help="the version to stamp (SemVer 2.0; default: the "
                                          "engine's __version__ in npm form)")
    args = parser.parse_args(argv)
    try:
        result = build(ENGINE, args.out.absolute(), args.version)
    except BuildError as e:
        print(f"{PROG}: error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(f"{PROG}: interrupted", file=sys.stderr)
        return 130
    print(f"built {NAME} {result['version']}: {result['files']} files in {result['out']}")
    print(f"publish: npm publish {result['out']} --tag {result['tag']}")
    changed = result["modified"]
    if changed:
        more = f", … and {len(changed) - 5} more" if len(changed) > 5 else ""
        print(f"{PROG}: warning: built from a work tree with uncommitted changes: "
              f"{', '.join(changed[:5])}{more}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
