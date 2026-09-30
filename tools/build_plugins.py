"""Build the modsys agent plugins from this engine tree (P6 D1) — stdlib only, deterministic.

    python3 tools/build_plugins.py [--out dist/plugins] [--version V]

writes three plugin directories into --out (default `dist/plugins` of this engine tree):
  modsys     the `core` pack's skills, `bin/modsys` (tools/launcher.sh, mode 0755) and
             `runtime/modsys/` (the tracked files of `modsys/`, byte for byte)
  modsys-ui  the `ui` pack's skills;  modsys-qa  the `qa` pack's skills
each with `.claude-plugin/plugin.json` (Claude Code), `plugin.json` (Agent Plugins, read by
Codex), `.codex-plugin/plugin.json` (Codex's compatibility manifest) and a README.md, every
manifest rendered from the one PLUGINS table below. The engine is read from git's index and
this work tree — never from an installed copy: `git ls-files modsys/` decides what ships (an
untracked file never does), a file's mode comes from the index (100755 → 0755, else 0644;
`bin/modsys` 0755), directories are 0755, and nothing carries a timestamp: two builds of one
tree are byte-identical. The three plugins are built in a temp directory and moved into --out
at the end (only those three directories are replaced), so an interrupted or refused build
leaves --out as it was.
Exit 0 built · 2 a refusal (stdout empty, stderr `build_plugins.py: error: …`) · 130 Ctrl-C."""
import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
PROG = "build_plugins.py"
SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"  # Agent Plugins manifest
AUTHOR = {"name": "modsys maintainers"}
KEYWORDS = ["modsys", "module-registry", "documentation", "agent-skills"]
# The one table every manifest and README is rendered from: plugin -> the pack it ships.
PLUGINS = {
    "modsys": {"pack": "core", "keywords": ["modules", "cli"],
               "description": "Module-registry skills for coding agents — find, read, update, "
                              "create, split and lint module docs, start them from existing "
                              "code or adopt a registry — with the modsys CLI they run"},
    "modsys-ui": {"pack": "ui", "keywords": ["ui", "design-review"],
                  "description": "The modsys designer-review skill: checks a UI change against "
                                 "the designer docs of the modules it touches"},
    "modsys-qa": {"pack": "qa", "keywords": ["qa", "acceptance-criteria"],
                  "description": "The modsys acceptance-criteria skills: a task's criteria "
                                 "before the code, and a module's acceptance baseline"},
}
CORE = "modsys"  # the plugin with the CLI; the others depend on it (Claude Code)
MANIFESTS = (".claude-plugin/plugin.json", "plugin.json", ".codex-plugin/plugin.json")
NOT_SHIPPED = {".DS_Store", ".modsys-managed", ".modsys-ejected"}
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
                    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
                    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
                    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$")  # semver.org, SemVer 2.0
INTERRUPT_AFTER = "MODSYS_BUILD_INTERRUPT_AFTER"  # test seam: Ctrl-C after building that plugin


class BuildError(Exception):
    """A refusal: exit 2, nothing written."""


def semver_ok(version: str) -> bool:
    return bool(SEMVER.fullmatch(version))


def git(engine: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(engine), *args], capture_output=True, text=True)
    if proc.returncode:
        raise BuildError(f"git {' '.join(args[:2])} failed in {engine}: "
                         f"{proc.stderr.strip() or proc.returncode}")
    return proc.stdout


def engine_version(engine: Path) -> str:
    """`__version__` of the engine tree's `modsys/__init__.py` (read as text, never imported)."""
    try:
        text = (engine / "modsys/__init__.py").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise BuildError(f"cannot read modsys/__init__.py: {e}") from None
    m = re.search(r'^__version__ = "([^"]+)"$', text, re.M)
    if not m:
        raise BuildError("modsys/__init__.py holds no __version__ = \"…\" line")
    return m.group(1)


def tracked(engine: Path) -> dict[str, int]:
    """{path: mode} of the files git tracks under `modsys/` — each one a regular file on disk.
    A symlink or submodule in the index, a tracked file missing on disk or a symlink there is
    a refusal naming it; `__pycache__`, `*.pyc` and the engine's markers never ship."""
    try:
        top = git(engine, "rev-parse", "--show-toplevel").strip()
    except BuildError:
        raise BuildError(f"{engine} is not a git work tree — the build ships the files git "
                         f"tracks under modsys/ (build from a clone, not an export)") from None
    if os.path.realpath(top) != os.path.realpath(engine):
        raise BuildError(f"{engine} is not the top of a git work tree — the build ships the "
                         f"files git tracks under modsys/ (build from a clone, not an export)")
    out = {}
    for entry in git(engine, "ls-files", "-s", "-z", "--", "modsys").split("\0"):
        if not entry:
            continue
        meta, path = entry.split("\t", 1)
        mode = int(meta.split()[0], 8)
        parts = path.split("/")
        if "__pycache__" in parts or path.endswith(".pyc") or parts[-1] in NOT_SHIPPED:
            continue
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise BuildError(f"{path} is tracked as a symlink or a submodule — ship a regular "
                             f"file")
        disk = engine / path
        if disk.is_symlink():
            raise BuildError(f"{path} is a symlink on disk — ship a regular file")
        if not disk.is_file():
            raise BuildError(f"{path} is tracked but missing on disk — restore it (git checkout "
                             f"-- {path}) or commit its removal")
        out[path] = 0o755 if mode & 0o111 else 0o644
    if not out:
        raise BuildError("git tracks no file under modsys/")
    return out


def pack_skills(engine: Path, pack: str) -> dict[str, str]:
    """{skill id: its directory, engine-relative} of a built-in pack, from its pack.toml."""
    rel = f"modsys/defaults/packs/{pack}/pack.toml"
    try:
        data = tomllib.loads((engine / rel).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        raise BuildError(f"cannot read {rel}: {e}") from None
    skills = data.get("skills")
    if not isinstance(skills, dict) or not all(isinstance(s, dict) and
                                               isinstance(s.get("path"), str)
                                               for s in skills.values()):
        raise BuildError(f"{rel}: [skills.<id>] tables with a path are expected")
    return {sid: os.path.normpath(f"modsys/defaults/packs/{pack}/{spec['path']}")
            for sid, spec in sorted(skills.items())}


def license_of(engine: Path) -> str | None:
    """`[project] license` of pyproject.toml when it is a plain string (absent today)."""
    try:
        data = tomllib.loads((engine / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None
    value = data.get("project", {}).get("license")
    return value if isinstance(value, str) else None


def manifests(name: str, version: str, license: str | None = None) -> dict[str, dict]:
    """The three manifests of plugin `name` — {path in the plugin: JSON value}, key order fixed —
    all rendered from PLUGINS: `dependencies` (a bare name, no range) only for Claude Code."""
    spec = PLUGINS[name]
    shared = {"name": name, "version": version, "description": spec["description"],
              "author": dict(AUTHOR), "keywords": KEYWORDS + spec["keywords"]}
    if license:
        shared["license"] = license
    claude = dict(shared)
    if name != CORE:
        claude["dependencies"] = [CORE]
    return {".claude-plugin/plugin.json": claude,
            "plugin.json": {"$schema": SCHEMA, **shared},
            ".codex-plugin/plugin.json": {**shared, "skills": "./skills/"}}


def readme(name: str, skills: list[str]) -> str:
    """The plugin's README: what it holds and one install line per agent; `<owner>/<publish
    repo>` and `<owner>/<repo>` are placeholders (no repository slug before the public release)."""
    spec = PLUGINS[name]
    listed = ", ".join(f"`{s}`" for s in skills)
    what = (f"The `{spec['pack']}` pack of modsys as a plugin: {listed}.")
    if name == CORE:
        what += (" It also carries the modsys command line those skills run: `bin/modsys` runs "
                 "the engine in `runtime/` with Python 3.11 or newer (or `uv`); set "
                 "`MODSYS_PYTHON` to choose the interpreter.")
        needs = ("- Codex: `codex plugin marketplace add <owner>/<publish repo> --ref stable`, "
                 f"then `codex plugin add {name}@modsys`. Codex puts no plugin command on "
                 "PATH, so install the CLI first: `uv tool install "
                 "git+ssh://git@github.com/<owner>/<repo>.git` (or `pipx install "
                 "git+ssh://git@github.com/<owner>/<repo>.git`).\n")
    else:
        what += (" It needs the `modsys` plugin (the modsys command line and the core skills).")
        needs = ("- Codex: `codex plugin marketplace add <owner>/<publish repo> --ref stable`, "
                 f"then `codex plugin add modsys@modsys` and `codex plugin add {name}@modsys` — "
                 "Codex has no plugin dependencies, so add both — and install the CLI first: "
                 "`uv tool install git+ssh://git@github.com/<owner>/<repo>.git` (or `pipx "
                 "install git+ssh://git@github.com/<owner>/<repo>.git`).\n")
    return (f"# {name}\n\n{spec['description']}.\n\n{what}\n\n## Install\n\n"
            f"- Claude Code: `claude plugin marketplace add <owner>/<publish repo>#stable`, then "
            f"`claude plugin install {name}@modsys`"
            + (" (it installs `modsys` too)" if name != CORE else "") + ".\n"
            + needs
            + "- Cursor, Gemini CLI, GitHub Copilot: there is no plugin for them — install the "
              "CLI, enable the pack (`[packs] builtin` in `.modsys/config.toml`) and run "
              "`modsys packs sync --agent cursor` (`--agent gemini`, `--agent copilot`): it "
              "copies the skills into `.agents/skills/`.\n\n"
              "The `dev` channel: `#dev` / `--ref dev` and the marketplace `modsys-dev` (e.g. "
              f"`{name}@modsys-dev`).\n\n"
              "In a repository whose agents get the built-in skills from these plugins, set "
              "`builtin_delivery = \"plugin\"` under `[packs]` in `.modsys/config.toml`: `modsys "
              "packs sync` then copies none of them (an agent that also had the copies would "
              "see each skill twice). Cursor, Gemini CLI and Copilot need `\"repo\"` (the "
              "default).\n")


def write(path: Path, data: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_bytes(data)
        os.chmod(path, mode)
    except OSError as e:
        raise BuildError(f"cannot write {path}: {e.strerror or e}") from None


def read(engine: Path, rel: str) -> bytes:
    try:
        return (engine / rel).read_bytes()
    except OSError as e:
        raise BuildError(f"cannot read {rel}: {e.strerror or e}") from None


def build_one(engine: Path, files: dict[str, int], name: str, version: str,
              license: str | None, dest: Path) -> int:
    """Write plugin `name` into `dest`; the number of files written."""
    skills = pack_skills(engine, PLUGINS[name]["pack"])
    count = 0
    for sid, src in skills.items():
        prefix = src + "/"
        own = sorted(p for p in files if p.startswith(prefix))
        if not own or f"{prefix}SKILL.md" not in files:
            raise BuildError(f"skill {sid}: {src}/SKILL.md is not a tracked file")
        for dirpath, dirnames, filenames in os.walk(engine / src):  # as packs sync: a skill
            for entry in sorted(dirnames + filenames):  # with a symlink is not loadable
                if (Path(dirpath) / entry).is_symlink():
                    link = (Path(dirpath) / entry).relative_to(engine).as_posix()
                    raise BuildError(f"skill {sid}: {link} is a symlink — a skill ships regular "
                                     f"files only")
        for rel in own:
            write(dest / "skills" / sid / rel[len(prefix):], read(engine, rel), files[rel])
            count += 1
    if name == CORE:
        write(dest / "bin/modsys", read(engine, "tools/launcher.sh"), 0o755)
        for rel in sorted(files):
            write(dest / "runtime" / rel, read(engine, rel), files[rel])
        count += 1 + len(files)
    for rel, value in manifests(name, version, license).items():
        write(dest / rel, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode(),
              0o644)
    write(dest / "README.md", readme(name, list(skills)).encode(), 0o644)
    for d in [dest, *(p for p in dest.rglob("*") if p.is_dir())]:
        os.chmod(d, 0o755)
    return count + len(MANIFESTS) + 1


def build(engine: Path, out: Path, version: str | None = None) -> dict:
    """Build the three plugins into `out` (replacing only them). {version, out, plugins:
    {name: files}}; BuildError on a refusal — nothing written then."""
    if version is not None and not semver_ok(version):
        raise BuildError(f"--version {version!r}: a SemVer 2.0 version is required "
                         f"(e.g. 0.2.0, 0.2.0-dev.habcdef12)")
    version = version or engine_version(engine)
    files = tracked(engine)
    license = license_of(engine)
    if not (engine / "tools/launcher.sh").is_file():
        raise BuildError("tools/launcher.sh is missing")
    temp = Path(tempfile.mkdtemp(prefix="modsys-plugins-"))
    try:
        counts = {}
        for name in PLUGINS:
            counts[name] = build_one(engine, files, name, version, license, temp / name)
            if os.environ.get(INTERRUPT_AFTER) == name:
                raise KeyboardInterrupt
        for name in PLUGINS:  # --out is touched only now, once all three are built
            final = out / name
            try:
                out.mkdir(parents=True, exist_ok=True)
                if final.is_symlink() or final.is_file():
                    final.unlink()
                elif final.exists():
                    shutil.rmtree(final)
                shutil.move(str(temp / name), str(final))
            except OSError as e:
                raise BuildError(f"cannot write {e.filename or final}: {e.strerror or e}") \
                    from None
    finally:
        shutil.rmtree(temp, ignore_errors=True)
    return {"version": version, "out": str(out), "plugins": counts}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=PROG, description="Build the modsys plugins "
                                     "(modsys, modsys-ui, modsys-qa) from this engine tree.")
    parser.add_argument("--out", type=Path, default=ENGINE / "dist/plugins",
                        help="the directory to build into (default: dist/plugins of the engine)")
    parser.add_argument("--version", help="the version to stamp (SemVer 2.0; default: the "
                                          "engine's __version__)")
    args = parser.parse_args(argv)
    try:
        result = build(ENGINE, args.out.absolute(), args.version)
    except BuildError as e:
        print(f"{PROG}: error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(f"{PROG}: interrupted", file=sys.stderr)
        return 130
    for name, count in result["plugins"].items():
        print(f"built {name} {result['version']}: {count} files in {result['out']}/{name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
