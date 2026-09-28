"""`init` phase 2, map (script only, deterministic): the candidate modules of an existing
codebase, written to `proposal.json` for gate 3.

A candidate is a unit — a directory:
  1. every package root of the manifests (a manifest at the repository root is never a unit);
     a package root inside another unit is not a candidate of its own (the outer one's
     rationale names it); a manifest that does not parse still makes its directory a unit;
  2. with no package manifest below the root: the source directories one level under `src/`,
     `lib/`, `app/`, `packages/`, `services/`, `apps/` — or, when none holds one, the top-level
     directories that hold code (a code file: an extension of the preflight language table).
Names: the manifest name without a scope (`@org/`) or path, else the directory name, normalized
to the `create` rule (lowercase words joined by '-', max 48); names two units share get their
parent directory as a prefix. Each candidate: `{name, include: true, paths: ["<dir>/**"],
confidence, rationale, signals, edges, keywords}`."""
import re
from pathlib import PurePosixPath

from modsys.changes import DEPENDENCY_DIRS
from modsys.preflight import language

SCHEMA = "modsys.init-proposal/1"
CONTAINERS = ("src", "lib", "app", "packages", "services", "apps")
NAME_MAX = 48
MANIFEST_WEIGHT = 0.4


def module_name(raw: str) -> str:
    """`raw` (a manifest name or a directory) as a module name of the `create` rule."""
    last = raw.rstrip("/").split("/")[-1]
    name = re.sub(r"[^a-z0-9]+", "-", last.lower()).strip("-")
    name = re.sub(r"^[^a-z]+", "", name)[:NAME_MAX].rstrip("-")
    return name or "module"


def _dir(path: str) -> str:
    parent = PurePosixPath(path).parent.as_posix()
    return "" if parent == "." else parent


def _code_dirs(files: list[str], skip: set[str]) -> list[tuple[str, str]]:
    """Rule 2: (unit directory, rationale) of the source directories."""
    code = [f for f in files if language(f) and not any(
        part.startswith(".") or part in DEPENDENCY_DIRS for part in f.split("/")[:-1])]
    units = []
    for container in CONTAINERS:
        subs = sorted({f.split("/")[1] for f in code
                       if f.startswith(container + "/") and f.count("/") >= 2})
        units += [(f"{container}/{s}", f"a source directory under {container}/") for s in subs]
    if not units:
        tops = sorted({f.split("/")[0] for f in code if "/" in f} - skip)
        units = [(t, "a top-level directory that holds code") for t in tops]
    return units


def units(files: list[str], manifests: list[dict], skip: set[str]) -> list[dict]:
    """The candidate units: {dir, manifest (or None), rationale}, by directory."""
    by_dir: dict[str, dict] = {}
    for m in manifests:  # manifests come sorted by path: the first per directory wins
        d = _dir(m["path"])
        if d and not d.split("/")[0].startswith(".") and d.split("/")[0] not in skip:
            by_dir.setdefault(d, m)
    if not by_dir:
        return [{"dir": d, "manifest": None, "rationale": [why]}
                for d, why in _code_dirs(files, skip)]
    out = []
    for d in sorted(by_dir):
        if any(d.startswith(o + "/") for o in by_dir if o != d):
            continue  # a nested package root belongs to the unit around it
        m = by_dir[d]
        rationale = [f"a package root: {m['path']}"
                     + (f" names it '{m['name']}'" if m["name"] else " (its name did not parse)")]
        nested = [n for n in sorted(by_dir) if n.startswith(d + "/")]
        if nested:
            rationale.append(f"it holds the nested package root(s) {', '.join(nested)} — part "
                             f"of this unit, not candidates of their own")
        out.append({"dir": d, "manifest": m, "rationale": rationale})
    return out


def names(found: list[dict]) -> list[str]:
    """One module name per unit; names that collide get the parent directory as a prefix, then
    the whole path."""
    base = [module_name(u["manifest"]["name"]) if u["manifest"] and u["manifest"]["name"]
            else module_name(u["dir"]) for u in found]
    out = list(base)
    for step in (1, 2):
        counts = {n: out.count(n) for n in out}
        if all(c == 1 for c in counts.values()):
            break
        for i, u in enumerate(found):
            if counts[out[i]] > 1:
                parts = u["dir"].split("/")
                prefix = parts[:-1][-1:] if step == 1 else parts[:-1]
                out[i] = module_name("-".join(prefix + [base[i]])) if prefix else out[i]
    return out


def build(root, config: dict, files: list[str], manifests: list[dict]) -> dict:
    """proposal.json's document."""
    skip = {config["paths"]["modules_dir"].split("/")[0], *DEPENDENCY_DIRS}
    found = units(files, manifests, skip)
    candidates = []
    for unit, name in zip(found, names(found)):
        manifest = 1.0 if unit["manifest"] else 0.0
        candidates.append({"name": name, "include": True, "paths": [f"{unit['dir']}/**"],
                           "confidence": round(MANIFEST_WEIGHT * manifest, 2),
                           "rationale": unit["rationale"],
                           "signals": {"manifest": manifest}, "edges": [], "keywords": []})
    return {"schema": SCHEMA, "root": str(root), "candidates": candidates, "unassigned": [],
            "hints": []}
