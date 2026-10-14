"""Build the segmently-modules agent plugins from this engine tree (P6 D1) — stdlib only, deterministic.

    python3 tools/build_plugins.py [--out dist/plugins] [--version V]

writes three plugin directories into --out (default `dist/plugins` of this engine tree):
  segmently-modules     the `core` pack's skills, `bin/segmently-modules` (tools/launcher.sh, mode 0755) and
             `runtime/segmently_modules/` (the tracked files of `segmently_modules/`, byte for byte) and `agents/`, mode
             0644: every tracked file directly in `segmently_modules/defaults/agents/` (the `module-chooser`
             subagent; a subdirectory never ships) and one agent per row of the engine's agent
             table (`SKILL_AGENTS` in `segmently_modules/skills.py`, read without importing the engine): its
             front matter (`skills:` preloads its skill, `segmently-modules:<skill>`), a blank line, then a
             short body that runs the skill and returns its output (`AGENT_BODY` +
             `CLAUDE_FALLBACK`; no skill text is copied, P8.6 D1); a skill the core pack does not
             declare, or a tracked agent file of the same name, is a refusal
  segmently-modules-ui  the `ui` pack's skills;  segmently-modules-qa  the `qa` pack's skills
each with `.claude-plugin/plugin.json` (Claude Code), `plugin.json` (Agent Plugins, read by
Codex), `.codex-plugin/plugin.json` (Codex's compatibility manifest) and a README.md, every
manifest rendered from the one PLUGINS table below. The engine is read from git's index and
this work tree — never from an installed copy: `git ls-files segmently_modules/` decides what ships (an
untracked file never does), a file's mode comes from the index (100755 → 0755, else 0644;
`bin/segmently-modules` 0755), directories are 0755, and nothing carries a timestamp: two builds of one
tree are byte-identical. A tracked file that differs from its commit still ships as it is on
disk; one stderr `warning:` line names such files.
The three plugins are built in a temp directory inside --out and renamed into place at the end,
all or nothing (only those three directories are replaced; the earlier ones are renamed aside
first and renamed back on any failure), so an interrupted or refused build leaves --out as it
was — and does not create it. --out is refused when `<out>/<plugin>` is this engine tree or
holds it, or exists and is not a build of that plugin: the builder replaces only its own output.
Exit 0 built · 2 a refusal (stdout empty, stderr `build_plugins.py: error: …`) · 130 Ctrl-C."""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

sys.dont_write_bytecode = True  # running a tool never leaves tools/__pycache__ in the engine

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.9, 3.10: the reader the engine vendors, never the engine
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "segmently_modules/_vendor"))
    import tomli as tomllib  # noqa: E402

ENGINE = Path(__file__).resolve().parents[1]
PROG = "build_plugins.py"
SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"  # Agent Plugins manifest
AUTHOR = {"name": "Segmently Modules maintainers"}
HOMEPAGE = "https://github.com/segmently-ai/segmently-modules"  # the engine: its docs and issues
MARKETPLACE = "segmently-ai/segmently-modules-plugins"  # the publish repository (both channels)
LICENSE = "MIT"
KEYWORDS = ["segmently-modules", "module-registry", "documentation", "agent-skills"]
# The one table every manifest and README is rendered from: plugin -> the pack it ships.
PLUGINS = {
    "segmently-modules": {"pack": "core", "keywords": ["modules", "cli"],
               "description": "Module-registry skills for coding agents — find, read, update, "
                              "create, split and lint module docs, start them from existing "
                              "code or adopt a registry — with the segmently-modules CLI they run"},
    "segmently-modules-ui": {"pack": "ui", "keywords": ["ui", "design-review"],
                  "description": "The Segmently Modules designer skill: prototypes, audits and "
                                 "reviews UI work against the designer docs of the modules it "
                                 "touches"},
    "segmently-modules-qa": {"pack": "qa", "keywords": ["qa", "acceptance-criteria"],
                  "description": "The Segmently Modules acceptance-criteria skills: a task's "
                                 "criteria before the code, and a module's acceptance baseline"},
}
CORE = "segmently-modules"  # the plugin with the CLI; the others depend on it (Claude Code)
AGENTS_DIR = "segmently_modules/defaults/agents/"  # its direct children ship in the core plugin's agents/
AGENT_TABLE = "segmently_modules/skills.py"  # SKILL_AGENTS and PROCEDURE: the engine's one agent table
AGENT_TOOLS = "Read, Grep, Glob, Bash, Agent, Skill"  # the generated agents' tools (Claude Code)
AGENT_MODEL = "sonnet"
MANIFESTS = (".claude-plugin/plugin.json", "plugin.json", ".codex-plugin/plugin.json")
NOT_SHIPPED = {".DS_Store", ".segmently-modules-managed", ".segmently-modules-ejected"}
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
                    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
                    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
                    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$")  # semver.org, SemVer 2.0
# Test seam: `<plugin>` = Ctrl-C after building that plugin; `swap:<plugin>` = Ctrl-C after that
# plugin was renamed into --out.
INTERRUPT_AFTER = "SEGMENTLY_MODULES_BUILD_INTERRUPT_AFTER"
# git's location variables (a parent git hook exports them): they would point git at another
# repository or index — the same list as the engine's `changes.git_env`.
GIT_LOCATION_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                     "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_PREFIX")


class BuildError(Exception):
    """A refusal: exit 2, nothing written."""


class GitMissing(BuildError):
    """git cannot be started at all."""


class Stranded(BuildError):
    """The swap could not be undone: the earlier directories are in the staging directory."""


def semver_ok(version: str) -> bool:
    return bool(SEMVER.fullmatch(version))


def git_env() -> dict:
    """The environment of every git call of the tools: without git's location variables."""
    return {k: v for k, v in os.environ.items() if k not in GIT_LOCATION_VARS}


def run_git(where: Path, *args: str) -> subprocess.CompletedProcess:
    """`git -C where …` for the three tools: the location variables dropped, the output decoded
    as UTF-8 (a path that is not UTF-8 survives as surrogates); GitMissing when git cannot be
    started."""
    try:
        return subprocess.run(["git", "-C", str(where), *args], capture_output=True,
                              encoding="utf-8", errors="surrogateescape", env=git_env())
    except OSError as e:
        raise GitMissing(f"git is not installed or cannot run: {e.strerror or e}") from None


def git(engine: Path, *args: str) -> str:
    proc = run_git(engine, *args)
    if proc.returncode:
        raise BuildError(f"git {' '.join(args[:2])} failed in {engine}: "
                         f"{proc.stderr.strip() or proc.returncode}")
    return proc.stdout


def engine_version(engine: Path) -> str:
    """`__version__` of the engine tree's `segmently_modules/__init__.py` (read as text, never imported)."""
    try:
        text = (engine / "segmently_modules/__init__.py").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise BuildError(f"cannot read segmently_modules/__init__.py: {e}") from None
    m = re.search(r'^__version__ = "([^"]+)"$', text, re.M)
    if not m:
        raise BuildError("segmently_modules/__init__.py holds no __version__ = \"…\" line")
    return m.group(1)


def tracked(engine: Path) -> dict[str, int]:
    """{path: mode} of the files git tracks under `segmently_modules/` — each one a regular file on disk.
    A symlink or submodule in the index, a tracked file missing on disk or a symlink there is
    a refusal naming it; `__pycache__`, `*.pyc` and the engine's markers never ship."""
    try:
        top = git(engine, "rev-parse", "--show-toplevel").strip()
    except GitMissing:
        raise
    except BuildError:
        raise BuildError(f"{engine} is not a git work tree — the build ships the files git "
                         f"tracks under segmently_modules/ (build from a clone, not an export)") from None
    if os.path.realpath(top) != os.path.realpath(engine):
        raise BuildError(f"{engine} is not the top of a git work tree — the build ships the "
                         f"files git tracks under segmently_modules/ (build from a clone, not an export)")
    out = {}
    for entry in git(engine, "ls-files", "-s", "-z", "--", "segmently_modules").split("\0"):
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
        raise BuildError("git tracks no file under segmently_modules/")
    return out


def pack_skills(engine: Path, pack: str) -> dict[str, str]:
    """{skill id: its directory, engine-relative} of a built-in pack, from its pack.toml."""
    rel = f"segmently_modules/defaults/packs/{pack}/pack.toml"
    try:
        data = tomllib.loads((engine / rel).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        raise BuildError(f"cannot read {rel}: {e}") from None
    skills = data.get("skills")
    if not isinstance(skills, dict) or not all(isinstance(s, dict) and
                                               isinstance(s.get("path"), str)
                                               for s in skills.values()):
        raise BuildError(f"{rel}: [skills.<id>] tables with a path are expected")
    return {sid: os.path.normpath(f"segmently_modules/defaults/packs/{pack}/{spec['path']}")
            for sid, spec in sorted(skills.items())}


def agent_table(engine: Path) -> tuple[dict, str]:
    """(SKILL_AGENTS, the agents' body template: AGENT_BODY + CLAUDE_FALLBACK) of the engine
    tree's `segmently_modules/skills.py` — its literal assignments, read with `ast` (the engine is never
    imported)."""
    try:
        tree = ast.parse(read(engine, AGENT_TABLE), AGENT_TABLE)
    except SyntaxError as e:
        raise BuildError(f"cannot read {AGENT_TABLE}: {e}") from None
    found = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in ("SKILL_AGENTS", "AGENT_BODY", "CLAUDE_FALLBACK")):
            try:
                found[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                raise BuildError(f"{AGENT_TABLE}: {node.targets[0].id} is not a literal") from None
    table, body, fallback = (found.get("SKILL_AGENTS"), found.get("AGENT_BODY"),
                             found.get("CLAUDE_FALLBACK"))
    if not (isinstance(table, dict) and isinstance(body, str) and isinstance(fallback, str) and all(
            isinstance(spec, dict) and isinstance(spec.get("skill"), str)
            and isinstance(spec.get("description"), str) for spec in table.values())):
        raise BuildError(f"{AGENT_TABLE}: SKILL_AGENTS (agent -> skill, description), "
                         f"AGENT_BODY and CLAUDE_FALLBACK are expected")
    return table, body + fallback


def agent_header(name: str, description: str, skill: str) -> bytes:
    """A generated agent's front matter (its skill preloaded) and the blank line before its
    body."""
    return (f"---\nname: {name}\ndescription: {description}\ntools: {AGENT_TOOLS}\n"
            f"model: {AGENT_MODEL}\nskills:\n  - {CORE}:{skill}\n---\n\n"
            ).encode("utf-8")


def agent_files(engine: Path, files: dict[str, int]) -> dict[str, bytes]:
    """{file name in the core plugin's `agents/`: bytes}: every tracked file directly in
    `segmently_modules/defaults/agents/` (one in a subdirectory never ships), then one generated agent per
    row of the agent table — a refusal when its skill is not in the core pack or a tracked
    agent file has its name."""
    out, source = {}, {}
    for rel in sorted(files):
        name = rel[len(AGENTS_DIR):]
        if rel.startswith(AGENTS_DIR) and "/" not in name:
            out[name], source[name] = read(engine, rel), rel
    table, body = agent_table(engine)
    skills = pack_skills(engine, PLUGINS[CORE]["pack"])
    for agent, spec in sorted(table.items()):
        if spec["skill"] not in skills:
            raise BuildError(f"agent {agent}: the {PLUGINS[CORE]['pack']} pack declares no skill "
                             f"{spec['skill']} (the agent table in {AGENT_TABLE} names it)")
        name = f"{agent}.md"
        if name in out:
            raise BuildError(f"{source[name]} collides with the agent {agent} generated for "
                             f"the skill {spec['skill']} — rename or remove {source[name]}")
        out[name] = (agent_header(agent, spec["description"], spec["skill"])
                     + (body.format(skill=spec["skill"]) + "\n").encode("utf-8"))
    return out


def license_of(engine: Path) -> str | None:
    """`[project] license` of pyproject.toml when it is a plain string (absent today)."""
    try:
        data = tomllib.loads((engine / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None
    value = data.get("project", {}).get("license")
    return value if isinstance(value, str) else None


def manifests(name: str, version: str, spdx: str | None = None) -> dict[str, dict]:
    """The three manifests of plugin `name` — {path in the plugin: JSON value}, key order fixed —
    all rendered from PLUGINS: `dependencies` (a bare name, no range), `homepage`, `repository`
    and `license` only for Claude Code (the keys its manifest schema defines)."""
    spec = PLUGINS[name]
    shared = {"name": name, "version": version, "description": spec["description"],
              "author": dict(AUTHOR), "keywords": KEYWORDS + spec["keywords"]}
    if spdx:
        shared["license"] = spdx
    claude = {**shared, "homepage": HOMEPAGE, "repository": HOMEPAGE,
              "license": shared.get("license", LICENSE)}
    if name != CORE:
        claude["dependencies"] = [CORE]
    return {".claude-plugin/plugin.json": claude,
            "plugin.json": {"$schema": SCHEMA, **shared},
            ".codex-plugin/plugin.json": {**shared, "skills": "./skills/"}}


def readme(name: str, skills: list[str], agents: list[str] = (), version: str = "") -> str:
    """The plugin's README: what it holds and one install line per agent, with the public
    repositories; the command line pinned to `version` when it is a stable X.Y.Z (a dev build
    follows the engine's main)."""
    spec = PLUGINS[name]
    generated: list[str] = []
    listed = ", ".join(f"`{s}`" for s in skills)
    cli = f"git+{HOMEPAGE}.git" + (f"@v{version}" if re.fullmatch(r"\d+\.\d+\.\d+", version)
                                   else "")  # a dev build comes from main: so does its CLI
    what = (f"The `{spec['pack']}` pack of Segmently Modules as a plugin: {listed}.")
    if name == CORE:
        what += (" It also carries the segmently-modules command line those skills run: `bin/segmently-modules` runs "
                 "the engine in `runtime/` with Python 3.9 or newer (or `uv`); set "
                 "`SEGMENTLY_MODULES_PYTHON` to choose the interpreter. It ships the read-only "
                 "`module-chooser` agent (`segmently-modules:module-chooser`, Claude Code) that the skills "
                 "hand a `segmently-modules choose` work order; every plugin update replaces it, so change "
                 "how modules are chosen with `segmently-modules templates override choose/rules.md`.")
        generated = sorted(a[:-3] for a in agents if a != "module-chooser.md")
        if generated:
            what += (" It also ships the agents "
                     + ", ".join(f"`{a}`" for a in generated[:-1]) + f" and `{generated[-1]}`"
                     + " (`segmently-modules:<name>`): each one runs its skill in the agent's own context "
                       "and returns the skill's output.")
        needs = (f"- Codex: `codex plugin marketplace add {MARKETPLACE} --ref stable`, "
                 f"then `codex plugin add {name}@segmently-modules`. Codex puts no plugin command on "
                 f"PATH, so install the CLI first, at the plugin's version: `uv tool "
                 f"install {cli}` (or `pipx install {cli}`)."
                 + (" Codex reads no plugin agents: `segmently-modules setup` and `segmently-modules packs sync "
                    "--agent codex` write the three skills' agents to `.codex/agents/` in the "
                    "repository." if generated else "") + "\n")
    else:
        what += (" It needs the `segmently-modules` plugin (the segmently-modules command line and the core skills).")
        needs = (f"- Codex: `codex plugin marketplace add {MARKETPLACE} --ref stable`, "
                 f"then `codex plugin add segmently-modules@segmently-modules` and `codex plugin add {name}@segmently-modules` — "
                 "Codex has no plugin dependencies, so add both — and install the CLI first, "
                 f"at the plugins' version: `uv tool install {cli}` (or `pipx install "
                 f"{cli}`).\n")
    return (f"# {name}\n\n{spec['description']}.\n\n{what}\n\n## Install\n\n"
            f"- Claude Code: `claude plugin marketplace add {MARKETPLACE}#stable`, then "
            f"`claude plugin install {name}@segmently-modules`"
            + (" (it installs `segmently-modules` too)" if name != CORE else "") + ".\n"
            + needs
            + "- Cursor, Gemini CLI, GitHub Copilot: there is no plugin for them — install the "
              "CLI, set Segmently Modules up in the repository (`segmently-modules init` enables the `core` pack; or "
              "set `[packs] builtin` in `.segmently-modules/config.toml`), then run `segmently-modules packs sync "
              "--agent cursor` (`--agent gemini`, `--agent copilot`): it copies the skills into "
              "`.agents/skills/`; these agents need the default `\"repo\"` delivery.\n\n"
              "The `dev` channel: `#dev` / `--ref dev` and the marketplace `segmently-modules-dev` (e.g. "
              f"`{name}@segmently-modules-dev`).\n\n"
              "In a repository whose agents get the built-in skills from these plugins, set "
              "`builtin_delivery = \"plugin\"` under `[packs]` in `.segmently-modules/config.toml`: `segmently-modules "
              "packs sync` then copies none of them and removes the copies it made (with the "
              "default `\"repo\"` delivery and the plugin, an agent sees each built-in skill "
              "twice)"
            + ("; it still writes Codex's three agent files in `.codex/agents/`" if generated
               else "")
            + ". Cursor, Gemini CLI and Copilot need `\"repo\"` (the default).\n")


def write(path: Path, data: bytes, mode: int) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
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
              spdx: str | None, dest: Path, agents: dict[str, bytes]) -> int:
    """Write plugin `name` into `dest` (`agents`: the core plugin's `agents/`, `agent_files`);
    the number of files written."""
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
        write(dest / "bin/segmently-modules", read(engine, "tools/launcher.sh"), 0o755)
        for rel in sorted(files):
            write(dest / "runtime" / rel, read(engine, rel), files[rel])
        count += 1 + len(files)
        for file_name, data in sorted(agents.items()):  # Claude Code finds agents/ itself
            write(dest / "agents" / file_name, data, 0o644)
            count += 1
    for rel, value in manifests(name, version, spdx).items():
        write(dest / rel, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode(),
              0o644)
    write(dest / "README.md", readme(name, list(skills), list(agents) if name == CORE else [],
                                     version).encode(), 0o644)
    write(dest / "LICENSE", read(engine, "LICENSE"), 0o644)  # MIT: the notice travels with copies
    for d in [dest, *(p for p in dest.rglob("*") if p.is_dir())]:
        os.chmod(d, 0o755)
    return count + len(MANIFESTS) + 2


def modified(engine: Path) -> list[str]:
    """The tracked files that ship (`segmently_modules/`, tools/launcher.sh) and differ from their commit —
    staged or not: the build ships them as they are on disk."""
    out = git(engine, "--no-optional-locks", "status", "--porcelain", "-z",
              "--untracked-files=no", "--", "segmently_modules", "tools/launcher.sh").split("\0")
    names, skip = [], False
    for entry in out:
        if skip or len(entry) < 4:  # the second path of a rename / copy, or the end
            skip = False
            continue
        names.append(entry[3:])
        skip = entry[0] in "RC" or entry[1] in "RC"
    return sorted(names)


def is_build(path: Path, name: str) -> bool:
    """`path` is a directory holding an earlier build of plugin `name` (its Claude Code manifest
    names it) — the only thing the builder replaces."""
    if path.is_symlink() or not path.is_dir():
        return False
    try:
        doc = json.loads((path / MANIFESTS[0]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(doc, dict) and doc.get("name") == name


def check_out(engine: Path, out: Path) -> None:
    """Refuse an --out whose `<out>/<plugin>` is not the builder's to replace: the engine tree
    itself or a directory holding it (real paths — replacing it would delete the engine, `.git`
    included), or anything that exists and is not an earlier build of that plugin."""
    here = Path(os.path.realpath(engine))
    if Path(os.path.realpath(out)) == here:
        raise BuildError(f"--out {out} is this engine tree — the plugins would land among its "
                         f"files; build into a directory of their own")
    for name in PLUGINS:
        final = out / name
        real = Path(os.path.realpath(final))
        if real == here or real in here.parents:
            raise BuildError(f"--out {out}: {final} is this engine tree or holds it — the "
                             f"build would replace it; give another directory")
        if os.path.lexists(final) and not is_build(final, name):
            raise BuildError(f"{final} exists and is not a build of the {name} plugin (no "
                             f"{MANIFESTS[0]} naming it) — the build replaces only its own "
                             f"output; remove it or give another --out")


def make_dirs(path: Path) -> list[Path]:
    """Create `path` and its missing parents; the directories created, the deepest first (a
    failed build removes them again)."""
    missing, at = [], path
    while not os.path.lexists(at) and at != at.parent:
        missing.append(at)
        at = at.parent
    try:
        for d in reversed(missing):
            d.mkdir()
    except OSError as e:
        remove_dirs(missing)
        raise BuildError(f"cannot write {e.filename or path}: {e.strerror or e}") from None
    return missing


def remove_tree(path: Path) -> bool:
    """Remove `path` — the staging directory, which may hold an earlier build a user made
    unreadable in part (a directory of mode 000): every directory met is made searchable and
    writable first. True when it is gone."""
    stack = [path]
    while stack:
        at = stack.pop()
        try:
            if at.is_symlink() or not at.is_dir():
                continue
            os.chmod(at, 0o700)
            stack.extend(Path(entry.path) for entry in os.scandir(at))
        except OSError:
            continue
    shutil.rmtree(path, ignore_errors=True)
    return not os.path.lexists(path)


def remove_dirs(dirs: list[Path]) -> None:
    for d in dirs:  # the deepest first; one that is not empty (or not there) stays
        try:
            d.rmdir()
        except OSError:
            pass


def swap(out: Path, staging: Path) -> None:
    """Rename the three plugins built in `staging/new` into `out`, all or nothing: each earlier
    `<out>/<name>` is renamed aside (into `staging/old`) first, and any failure or Ctrl-C
    renames everything back — read from the directories themselves, so an interrupt between two
    renames undoes exactly what happened. Stranded when the way back fails: `staging` is kept."""
    new, old = staging / "new", staging / "old"
    try:
        old.mkdir()
        for name in PLUGINS:
            final = out / name
            if os.path.lexists(final):
                os.rename(final, old / name)
            os.rename(new / name, final)
            if os.environ.get(INTERRUPT_AFTER) == f"swap:{name}":
                raise KeyboardInterrupt
    except BaseException as e:
        main_thread = threading.current_thread() is threading.main_thread()
        before = signal.signal(signal.SIGINT, signal.SIG_IGN) if main_thread else None
        try:  # a second Ctrl-C never interrupts the way back
            stuck = []
            for name in reversed(list(PLUGINS)):
                final = out / name
                try:
                    if not os.path.lexists(new / name) and os.path.lexists(final):
                        os.rename(final, new / name)  # the new one was in place: take it out
                    if os.path.lexists(old / name):
                        os.rename(old / name, final)
                except OSError as back:
                    stuck.append(f"{final} ({back.strerror or back})")
        finally:
            if main_thread:
                signal.signal(signal.SIGINT, before)
        if stuck:
            raise Stranded(f"cannot put back {', '.join(stuck)} — the earlier directories are "
                           f"in {old}, the new ones in {new}") from None
        if isinstance(e, OSError):
            raise BuildError(f"cannot write {e.filename or out}: {e.strerror or e}") from None
        raise


def build(engine: Path, out: Path, version: str | None = None) -> dict:
    """Build the three plugins into `out` (replacing only them). {version, out, plugins:
    {name: files}, modified: the shipped tracked files with uncommitted changes}; BuildError on
    a refusal — nothing written then, `out` not even created."""
    if version is not None and not semver_ok(version):
        raise BuildError(f"--version {version!r}: a SemVer 2.0 version is required "
                         f"(e.g. 0.2.0, 0.2.0-dev.habcdef12)")
    version = version or engine_version(engine)
    files = tracked(engine)
    agents = agent_files(engine, files)
    spdx = license_of(engine)
    if not (engine / "tools/launcher.sh").is_file():
        raise BuildError("tools/launcher.sh is missing")
    check_out(engine, out)  # before --out is touched
    changed = modified(engine)
    created = make_dirs(out)
    staging, keep, built, left = None, False, False, None
    try:
        try:
            staging = Path(tempfile.mkdtemp(prefix=".segmently-modules-build-", dir=out))
        except OSError as e:
            raise BuildError(f"cannot write {out}: {e.strerror or e}") from None
        counts = {}
        for name in PLUGINS:
            counts[name] = build_one(engine, files, name, version, spdx,
                                     staging / "new" / name, agents)
            if os.environ.get(INTERRUPT_AFTER) == name:
                raise KeyboardInterrupt
        swap(out, staging)  # --out's plugin directories are touched only now
        built = True
    except Stranded:
        keep = True
        raise
    except OSError as e:
        raise BuildError(f"cannot write {e.filename or out}: {e.strerror or e}") from None
    finally:
        if staging and not keep and not remove_tree(staging):
            left = str(staging)  # nothing is lost: it held the earlier build
        if not built:
            remove_dirs(created)
    return {"version": version, "out": str(out), "plugins": counts, "modified": changed,
            "left": left}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=PROG, description="Build the segmently-modules plugins "
                                     "(segmently-modules, segmently-modules-ui, segmently-modules-qa) from this engine tree.")
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
    if result["left"]:
        print(f"{PROG}: warning: cannot remove {result['left']} (the earlier build) — delete "
              f"it by hand", file=sys.stderr)
    changed = result["modified"]
    if changed:  # the work tree's bytes ship: say so, once
        more = f", … and {len(changed) - 5} more" if len(changed) > 5 else ""
        print(f"{PROG}: warning: built from a work tree with uncommitted changes: "
              f"{', '.join(changed[:5])}{more}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
