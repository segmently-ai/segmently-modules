"""`init` phase 1, preflight: what the repository holds, deterministic and sorted.

The file set: `git ls-files --cached --others --exclude-standard` in a git work tree (ONE
listing), else a walk that skips dot-directories and the dependency / build directories
(`DEPENDENCY_DIRS`); minus `[init] exclude` globs (the `[[code_map]]` glob grammar); a listed
path missing on disk is dropped. `build` turns it into `preflight.json`:
`{schema, root, git: {head, commits} | null, files, manifests: [{path, kind, name,
workspaces}]}` — a manifest (package.json, pyproject.toml, setup.cfg, go.mod, Cargo.toml,
composer.json, *.csproj) that does not parse has `name: null` and `workspaces: []`."""
import configparser
import json
import os
import re
import subprocess
import tomllib
from pathlib import Path, PurePosixPath

from modsys.changes import DEPENDENCY_DIRS, git_env, glob_to_regex, work_tree_error

SCHEMA = "modsys.init-preflight/1"
MANIFESTS = ("package.json", "pyproject.toml", "setup.cfg", "go.mod", "Cargo.toml",
             "composer.json")  # plus any *.csproj
# extension -> language: the code files of the file set (lines count; map's units and
# `unassigned` hold code files only)
LANGUAGES = {
    ".c": "C", ".h": "C", ".cc": "C++", ".cpp": "C++", ".hpp": "C++", ".cs": "C#",
    ".go": "Go", ".java": "Java", ".js": "JavaScript", ".jsx": "JavaScript",
    ".mjs": "JavaScript", ".cjs": "JavaScript", ".kt": "Kotlin", ".php": "PHP",
    ".py": "Python", ".rb": "Ruby", ".rs": "Rust", ".scala": "Scala", ".sh": "Shell",
    ".swift": "Swift", ".ts": "TypeScript", ".tsx": "TypeScript", ".mts": "TypeScript",
    ".cts": "TypeScript", ".vue": "Vue", ".svelte": "Svelte", ".dart": "Dart",
    ".ex": "Elixir", ".exs": "Elixir", ".lua": "Lua", ".m": "Objective-C", ".r": "R",
    ".sql": "SQL",
}


def language(path: str) -> str | None:
    """The language of a code file by its extension (`LANGUAGES`), else None."""
    return LANGUAGES.get(PurePosixPath(path).suffix.lower())


def manifest_kind(path: str) -> str | None:
    name = PurePosixPath(path).name
    if name in MANIFESTS:
        return name
    return "csproj" if name.endswith(".csproj") else None


def _walk(root: Path) -> list[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        base = Path(dirpath)
        links = [d for d in dirnames if (base / d).is_symlink()]  # a symlink is a file entry
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".")
                             and d not in DEPENDENCY_DIRS and d not in links)
        out += [(base / n).relative_to(root).as_posix() for n in filenames + links]
    return out


def list_files(root: Path, config: dict) -> list[str]:
    """The init file set (root-relative posix paths, sorted) — see the module docstring."""
    if work_tree_error(root) is None:
        proc = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached", "--others",
                               "--exclude-standard"], capture_output=True, env=git_env())
        paths = [p.decode("utf-8", "surrogateescape") for p in proc.stdout.split(b"\0") if p]
    else:
        paths = _walk(root)
    exclude = [glob_to_regex(g) for g in config["init"]["exclude"]]
    return sorted({p for p in paths if os.path.lexists(root / p)
                   and not any(rx.match(p) for rx in exclude)})


def read_manifest(path: Path, kind: str) -> dict:
    """{name, workspaces, keywords, description} of one manifest; a file that does not parse
    (or has no name) gives `name: None` and empty lists — never an error."""
    out = {"name": None, "workspaces": [], "keywords": [], "description": ""}
    if kind == "csproj":
        out["name"] = path.stem
        return out
    try:
        text = path.read_bytes().decode("utf-8")
        if kind in ("package.json", "composer.json"):
            data = json.loads(text)
            spaces = data.get("workspaces") if kind == "package.json" else None
            if isinstance(spaces, dict):
                spaces = spaces.get("packages")
            out["workspaces"] = [w for w in spaces or [] if isinstance(w, str)] \
                if isinstance(spaces, list) else []
        elif kind in ("pyproject.toml", "Cargo.toml"):
            data = tomllib.loads(text)
            data = (data.get("project") or data.get("tool", {}).get("poetry") or {}) \
                if kind == "pyproject.toml" else data.get("package") or {}
        elif kind == "setup.cfg":
            parser = configparser.ConfigParser(interpolation=None)
            parser.read_string(text)
            data = dict(parser["metadata"]) if parser.has_section("metadata") else {}
            data["keywords"] = [k.strip() for k in data.get("keywords", "").split(",")]
        else:  # go.mod
            m = re.search(r"^module\s+(\S+)", text, re.M)
            data = {"name": m.group(1).strip('"')} if m else {}
    except (OSError, UnicodeDecodeError, ValueError, configparser.Error, AttributeError):
        return out
    if isinstance(data, dict):
        name = data.get("name")
        out["name"] = name if isinstance(name, str) and name.strip() else None
        keywords = data.get("keywords")
        out["keywords"] = [k for k in keywords if isinstance(k, str) and k.strip()] \
            if isinstance(keywords, list) else []
        description = data.get("description")
        out["description"] = description if isinstance(description, str) else ""
    return out


def manifests(root: Path, files: list[str]) -> list[dict]:
    """Every manifest of the file set, by path: {path, kind, name, workspaces, keywords,
    description} (preflight.json keeps the first four)."""
    return [{"path": f, "kind": kind, **read_manifest(root / f, kind)}
            for f in files if (kind := manifest_kind(f))]


def git_info(root: Path) -> dict | None:
    """{head, commits} in a git work tree (`head` null, `commits` 0 before the first commit);
    None outside git."""
    if work_tree_error(root) is not None:
        return None
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "--quiet", "HEAD"],
                          capture_output=True, text=True, env=git_env())
    if head.returncode != 0:
        return {"head": None, "commits": 0}
    count = subprocess.run(["git", "-C", str(root), "rev-list", "--count", "HEAD"],
                           capture_output=True, text=True, env=git_env())
    return {"head": head.stdout.strip(), "commits": int(count.stdout.strip() or 0)}


def build(root: Path, files: list[str], found: list[dict]) -> dict:
    """preflight.json's document for the file set `files` and its manifests `found`."""
    return {"schema": SCHEMA, "root": str(root), "git": git_info(root), "files": len(files),
            "manifests": [{k: m[k] for k in ("path", "kind", "name", "workspaces")}
                          for m in found]}
