"""Changed files -> modules. A file belongs to a module (or `module/child`) through:
  docs          — it lives under `<modules_dir>/<module>/` (children: `…/submodules/<child>/`)
  code_pointer  — a `kind = "code_pointer"` field names the file or a directory above it
  code_map      — a `[[code_map]]` rule: `globs` for one `module` (a top-level module or a
                  `parent/child`), or a `pattern` whose `{module}` segment names a top-level
                  module (e.g. "src/{module}/**"; `{module}` captures exactly ONE path segment).
                  A file matched by an `exclusive = true` rule is mapped ONLY by the exclusive
                  rules that match it; docs and code_pointer mapping are unaffected.
Glob syntax: `**` any path, `*` one segment, `?` one character."""
import os
import re
import subprocess
from pathlib import Path

from modsys.output import UsageError
from modsys.registry import as_dict, as_list

# git location variables a parent git hook may export; they would point git at another repo
_GIT_LOCATION_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                      "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_PREFIX")
CODE_MAP_SCHEMA = {"id": "str", "module": "str", "pattern": "str", "globs": "list[str]",
                   "exclusive": "bool"}


def git_env() -> dict:
    return {k: v for k, v in os.environ.items() if k not in _GIT_LOCATION_VARS}


def git(root: Path, *args: str, label: str | None = None) -> str:
    """Run git in `root`; `label` replaces the argv in the error message."""
    proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                          encoding="utf-8", errors="replace", env=git_env())
    if proc.returncode != 0:
        raise UsageError(f"git {label or ' '.join(args)} failed: {proc.stderr.strip()[:300]}")
    return proc.stdout


def _rev(value: str) -> str:
    """A user-given ref or `A..B` range; one that starts with '-' would be read as an option
    (e.g. `--output=FILE` makes git write a file), so it is refused."""
    if value.startswith("-"):
        raise UsageError(f"git ref or range {value!r} may not start with '-'")
    return value


def _paths(output: str) -> list[str]:
    return [p for p in output.split("\0") if p]


def diff_names(root: Path, rev: str, *options: str) -> list[str]:
    """Paths `git diff` reports against `rev` (a ref: vs the working tree; or `A..B`):
    relative to `root` and limited to it (--relative: `root` may be a subdirectory of the git
    repository), a rename listed as delete + add (--no-renames), raw names (-z: no C-quoting
    of non-ASCII names), and `rev` after --end-of-options."""
    rev = _rev(rev)
    return _paths(git(root, "diff", "--name-only", "--relative", "--no-renames", "-z", *options,
                      "--end-of-options", rev,
                      label=" ".join(("diff", "--name-only", *options, rev))))


def changed_files(root: Path, diff_range: str | None = None, files=None,
                  base: str | None = None) -> list[str]:
    """Root-relative changed paths from explicit `files`, a `diff_range` ("A..B"), or `base`
    (base vs the working tree, plus untracked files); git listings keep only files under
    `root`. Sorted, de-duplicated."""
    if files:
        out = set()
        for f in files:
            p = Path(f)
            if p.is_absolute():
                try:
                    p = p.resolve().relative_to(Path(root).resolve())
                except ValueError:
                    raise UsageError(f"{f} is outside the repository {root}") from None
            rel = Path(os.path.normpath(p)).as_posix()
            if rel == ".." or rel.startswith("../"):
                raise UsageError(f"{f} is outside the repository {root}")
            out.add(rel)
        return sorted(out)
    if diff_range:
        return sorted(set(diff_names(root, diff_range)))
    if base:
        tracked = diff_names(root, base)
        untracked = _paths(git(root, "ls-files", "-z", "--others", "--exclude-standard"))
        return sorted(set(tracked + untracked))
    raise UsageError("give changed files: --from-diff A..B, --files …, or --base REF")


def glob_to_regex(pattern: str) -> re.Pattern:
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern.startswith("{module}", i):
            out.append("(?P<module>[^/]+)")
            i += len("{module}")
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def validate_code_map(layer: dict, source, check_table) -> None:
    rules = layer.get("code_map")
    if rules is None:
        return
    if not isinstance(rules, list) or not all(isinstance(r, dict) for r in rules):
        raise UsageError(f"{source}: code_map must be an array of tables ([[code_map]])")
    for rule in rules:
        if not isinstance(rule.get("id"), str) or not rule["id"]:
            raise UsageError(f"{source}: every [[code_map]] entry needs an id")
        check_table(rule, CODE_MAP_SCHEMA, f"code_map.{rule['id']}", source)
        if "pattern" not in rule and "globs" not in rule:
            raise UsageError(f"{source}: code_map.{rule['id']}: needs a pattern or globs")
        if "globs" in rule and "module" not in rule:
            raise UsageError(f"{source}: code_map.{rule['id']}: globs need a module")
        if "pattern" in rule and "{module}" not in rule["pattern"]:
            raise UsageError(f"{source}: code_map.{rule['id']}: pattern needs a {{module}} segment")


def _pointer_paths(value) -> list[str]:
    paths = value if isinstance(value, list) else [value]
    return [p.split(":")[0].rstrip("/") for p in paths if isinstance(p, str) and p]


def _targets(modules: dict):
    """(target, entry) for every module and child entry that is an object."""
    for name, entry in modules.items():
        if isinstance(entry, dict):
            yield name, entry
            for child, sub in as_dict(entry.get("submodules")).items():
                if isinstance(sub, dict):
                    yield f"{name}/{child}", sub


def target_names(modules: dict) -> set[str]:
    """Every module and `parent/child` name a `[[code_map]]` rule may route files to."""
    return {target for target, _ in _targets(modules)}


def code_globs(config: dict, target: str) -> list[str]:
    """The `[[code_map]]` globs that route files to `target` — where its code lives, for agents
    (`show` / `context`). A `pattern` rule without a `module` contributes its pattern with
    `{module}` = the target (top-level targets only: `{module}` is one path segment); a rule
    whose `module` is the target contributes its globs or pattern (`{module}` read as `*`).
    These are routing rules, not a file list: an `exclusive` rule elsewhere may take files."""
    out = []
    for rule in as_list(config.get("code_map")):
        if not isinstance(rule, dict) or "id" not in rule:
            continue
        globs = [rule["pattern"]] if "pattern" in rule else as_list(rule.get("globs"))
        if rule.get("module") == target:
            out += [g.replace("{module}", "*") for g in globs if isinstance(g, str)]
        elif "module" not in rule and "/" not in target:
            out += [g.replace("{module}", target) for g in globs if isinstance(g, str)]
    return list(dict.fromkeys(out))


def map_files(ws, files: list[str]) -> dict:
    """{"modules": {target: {"files": […], "via": […]}}, "unmapped": […]}"""
    modules = ws.registry.modules
    targets = target_names(modules)
    mdir = ws.config["paths"]["modules_dir"].rstrip("/") + "/"
    pointers = [(t, f, p) for t, e in _targets(modules)
                for f, d in ws.fields.items() if d.kind == "code_pointer" and f in e
                for p in _pointer_paths(e[f])]
    rules = [(r["id"], r.get("module"), [glob_to_regex(g) for g in
                                         ([r["pattern"]] if "pattern" in r else r["globs"])],
              r.get("exclusive") is True)
             for r in as_list(ws.config.get("code_map")) if isinstance(r, dict) and "id" in r]
    hits: dict[str, dict] = {}

    def hit(target, path, via):
        slot = hits.setdefault(target, {"files": [], "via": []})
        if path not in slot["files"]:
            slot["files"].append(path)
        if via not in slot["via"]:
            slot["via"].append(via)
        mapped.add(path)

    mapped: set = set()
    for path in files:
        if path.startswith(mdir):
            parts = path[len(mdir):].split("/")
            if parts[0] in modules:
                child = parts[2] if len(parts) > 3 and parts[1] == "submodules" else None
                target = f"{parts[0]}/{child}" if child and child in as_dict(
                    as_dict(modules[parts[0]]).get("submodules")) else parts[0]
                hit(target, path, "docs")
        for target, field, pointer in pointers:
            if path == pointer or path.startswith(pointer + "/"):
                hit(target, path, f"code_pointer:{field}")
        routed = []  # (target, rule id, exclusive) of every code_map rule that routes the file
        for rule_id, module, regexes, exclusive in rules:
            for rx in regexes:
                m = rx.match(path)
                if not m:
                    continue
                name = module or m.group("module")
                if name in targets:
                    routed.append((name, rule_id, exclusive))
        if any(exclusive for _, _, exclusive in routed):
            routed = [r for r in routed if r[2]]  # exclusive rules win the file
        for name, rule_id, _ in routed:
            hit(name, path, f"code_map:{rule_id}")
    return {"modules": dict(sorted(hits.items())),
            "unmapped": [f for f in files if f not in mapped]}
