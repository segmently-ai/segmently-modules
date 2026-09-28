"""`modsys adopt`: make the engine read an existing registry — written by other tooling —
without changing it. The registry is read as it is (one file, or the per-module layout) and the
team config it needs is inferred, every key followed by `# adopt:` lines with the evidence:

  [paths]            the registry's path and modules dir when they are not the configured ones;
                     `registry_layout = "per-module"` when every module has its entry file
  [roles.<r>]        every `context_files.roles` key no active layer declares: `order` after the
                     highest configured order (+10 each, by frequency then name), `standard`
                     when >= 80 % of the top-level modules carry it
  [fields.<k>]       every entry key that is neither a core field nor declared: `type` from the
                     observed values (a union ordered by count), `scope` from where it was seen,
                     `kind = "code_pointer"` when >= 80 % of its strings name repository paths;
                     a float, a null or a mixed list cannot be declared (`inferred.skipped`)
  dir_whitelist      directories under the modules dir that are not modules (no dot-dirs, no
                     pointer stubs)
  updated_at_path    a registry-level key <= 2 levels deep named updated / modified holding an
                     ISO-8601 timestamp (the shallowest, then by name)
  [[code_map]]       one `<prefix>/{module}/**` rule when >= 50 % of the top-level modules have
                     `<prefix>/<module>` (a directory, or a code-pointer value under it); prefixes
                     up to 3 segments, never the modules / config / dot / dependency dirs; none
                     when a layer has rules. When no prefix reaches 50 %, the best one is written
                     COMMENTED OUT (`inferred.code_map_suggestion`), never as a rule
  [budgets]          COMMENTED OUT: the observed maximum where the doc budgets would flag docs

Thresholds are integer comparisons (80 %: `count * 5 >= total * 4`; 50 %: `count * 2 >=
total`). The team and user configs are active layers: with a config present, the inferred keys
go to `<config_dir>/adopt.proposed.toml` (always rewritten; an existing config is never edited),
else to a new `<config_dir>/config.toml`; `--dry-run` writes nothing. Lint then runs in report
mode against the config merged with what was inferred (exit 0 either way). The registry, its
docs and every file outside the config dir are never written."""
import contextlib
import os
import re
import tempfile
import tomllib
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from modsys.changes import DEPENDENCY_DIRS
from modsys.code_map_cmd import _toml_string
from modsys.config import load_config
from modsys.fields import CORE_FIELDS, load_field_defs
from modsys.init_cmd import _HEADER, ignore_lines
from modsys.layout import load_per_module
from modsys.lint import _docs, _line_count, lint_registry
from modsys.output import EXIT_OK, UsageError, emit
from modsys.registry import as_dict, load_registry, stub_head
from modsys.store import atomic_write
from modsys.workspace import Workspace, find_root

STARTER_OPENING = ("modsys team config — commit it. Every key is optional: uncomment what you "
                   "need (only [packs] builtin is set).")
ADOPT_OPENING = ("modsys team config, written by modsys adopt — review it, then commit it. adopt "
                 "set the keys below (each `# adopt:` line says why); commented-out keys are "
                 "for the team to decide.")
LINT_SHOWN = 50
PROPOSAL = "adopt.proposed.toml"
_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?"
                  r"(?:Z|[+-]\d{2}:?\d{2})?)?$")
_UPDATED = re.compile(r"updated|modified", re.I)
_EMPTY = "[]"  # an empty list: any `X[]`
_SHOWN_NAMES = 10


def adopt_header() -> str:
    """The starter header with its opening replaced (the adopted keys are active; only what is
    commented out is left to the team), re-wrapped."""
    flat = " ".join(_HEADER.replace("##", " ").split()).replace(STARTER_OPENING, ADOPT_OPENING)
    lines, line = [], "##"
    for word in flat.split(" "):
        if len(line) + 1 + len(word) > 96:
            lines.append(line)
            line = "##"
        line += " " + word
    return "\n".join(lines + [line]) + "\n\n"


def register(sub, common) -> None:
    p = sub.add_parser("adopt", parents=[common],
                       help="infer the config an existing registry needs (never edits it)",
                       description="Read an existing registry (written by other tooling) as it "
                                   "is and infer the team config the engine needs to read it: "
                                   "paths, roles, fields, the dir whitelist, updated_at_path, a "
                                   "code-map rule, doc budgets (commented out) — each key with "
                                   "its evidence. Writes <config_dir>/config.toml, or "
                                   "<config_dir>/adopt.proposed.toml when a config exists (merge "
                                   "it by hand); the registry and docs are never changed. Then "
                                   "lint runs in report mode (exit 0).")
    p.add_argument("--registry", metavar="PATH",
                   help="the registry file, root-relative (default: the configured one, "
                        "modules/registry.json)")
    p.add_argument("--dry-run", action="store_true",
                   help="write nothing; data.config (text: the output) holds the TOML")
    p.set_defaults(func=run)


def _toml_key(name: str) -> str:
    return name if _BARE_KEY.fullmatch(name) else _toml_string(name)


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    return _toml_string(value)


def _names(labels: list[str]) -> str:
    shown = ", ".join(labels[:_SHOWN_NAMES])
    more = len(labels) - _SHOWN_NAMES
    return shown + (f" and {more} more" if more > 0 else "")


def at_least_80(count: int, total: int) -> bool:
    return total > 0 and count * 5 >= total * 4


def at_least_50(count: int, total: int) -> bool:
    return total > 0 and count * 2 >= total


def _entries(modules: dict):
    """(label, entry, scope) of every module and child entry that is an object."""
    for name, entry in modules.items():
        if isinstance(entry, dict):
            yield name, entry, "module"
            for child, sub in as_dict(entry.get("submodules")).items():
                if isinstance(sub, dict):
                    yield f"{name}/{child}", sub, "submodule"


class _Skip(Exception):
    """A value no type expression of the grammar describes."""


def type_expr(value) -> str:
    """The grammar's type expression of one registry value (`_EMPTY` for `[]`); a float, a null
    or a list mixing element types raises `_Skip` with the reason."""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        inner = {type_expr(v) for v in value}
        if not inner:
            return _EMPTY
        typed = inner - {_EMPTY}
        if len(typed) > 1:
            raise _Skip("a list mixing element types")
        return (typed.pop() if typed else "string[]") + "[]"
    if value is None:
        raise _Skip("a null value (no type in the grammar)")
    raise _Skip(f"a {'float' if isinstance(value, float) else type(value).__name__} value "
                f"(no type in the grammar)")


def names_repo_path(root: Path, text: str) -> bool:
    """`text` names an existing path of the repository (`path:line` and `path#L3` allowed; a
    directory counts). Absolute paths, `~`, `..` escapes and globs never count, and nothing
    outside the root is probed (symlinks are not followed)."""
    path = re.split(r"[:#]", text, maxsplit=1)[0].strip()
    if not path or path.startswith(("/", "~")) or any(c in path for c in "*?[\\"):
        return False
    norm = os.path.normpath(path)
    if norm in (".", "..") or norm.startswith("../") or os.path.isabs(norm):
        return False
    return os.path.lexists(root / norm)


def _strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


class Inference:
    """What `adopt` infers for one registry, with the TOML lines of each section."""

    def __init__(self, root: Path, config_dir: Path, config: dict, registry_rel: str, raw: dict,
                 paths: dict):
        self.root, self.config_dir, self.config = root, config_dir, config
        self.registry_rel, self.raw, self.modules = registry_rel, raw, raw["modules"]
        self.paths = paths  # the [paths] adopt infers ({} when the configured ones fit)
        self.modules_dir = paths.get("modules_dir", config["paths"]["modules_dir"])
        self.top = [n for n, e in self.modules.items() if isinstance(e, dict)]
        self.sections: list[list[str]] = []
        self.registry_keys: list[tuple[str, object, list[str]]] = []  # one [registry] table
        self.suggestion_lines: list[str] = []
        self.budget_lines: list[str] = []
        self.data: dict = {}

    def section(self, header: str, keys: list[tuple[str, object, list[str]]]) -> None:
        lines = [header]
        for key, value, evidence in keys:
            lines.append(f"{_toml_key(key)} = {_toml_value(value)}")
            lines += [f"# adopt: {e}" for e in evidence]
        self.sections.append(lines)

    def run(self) -> dict:
        self.infer_paths()
        self.infer_roles()
        self.infer_fields()
        self.infer_dir_whitelist()
        self.infer_updated_at_path()
        if self.registry_keys:
            self.section("[registry]", self.registry_keys)
        self.infer_code_map()
        self.infer_budgets()
        return self.data

    def infer_paths(self) -> None:
        self.data["paths"] = dict(self.paths)
        if self.paths:
            evidence = {"registry": f"the registry is {self.registry_rel}",
                        "modules_dir": f"the registry's directory: {self.modules_dir}",
                        "registry_layout": f"every module of {self.registry_rel} has its "
                                           f"{self.modules_dir}/<name>/"
                                           f"{self.config['paths']['module_entry']}"}
            self.section("[paths]", [(k, v, [evidence[k]]) for k, v in self.paths.items()])

    def infer_roles(self) -> None:
        declared = set(self.config.get("roles") or {})
        carriers: dict[str, list[str]] = {}
        top_carriers: Counter = Counter()
        for label, entry, scope in _entries(self.modules):
            for role in as_dict(as_dict(entry.get("context_files")).get("roles")):
                if role not in declared:
                    carriers.setdefault(role, []).append(label)
                    if scope == "module":
                        top_carriers[role] += 1
        orders = [s["order"] for s in (self.config.get("roles") or {}).values()
                  if isinstance(s, dict) and isinstance(s.get("order"), int)
                  and not isinstance(s.get("order"), bool)]
        base = max(orders, default=0)
        rows = []
        for n, role in enumerate(sorted(carriers, key=lambda r: (-len(carriers[r]), r)), 1):
            order, count = base + 10 * n, top_carriers[role]
            standard = at_least_80(count, len(self.top))
            labels = carriers[role]
            rows.append({"name": role, "order": order, "standard": standard, "modules": labels})
            self.section(f"[roles.{_toml_key(role)}]", [
                ("order", order, [f"after the highest configured order ({base}); carried by "
                                  f"{len(labels)} entr{'y' if len(labels) == 1 else 'ies'}: "
                                  f"{_names(labels)}"]),
                ("standard", standard, [f"{count} of {len(self.top)} top-level modules carry "
                                        f"it ({'at least' if standard else 'below'} 80 %)"])])
        self.data["roles"] = rows

    def infer_fields(self) -> None:
        known = set(CORE_FIELDS) | set(load_field_defs(self.config))
        seen: dict[str, dict] = {}
        for label, entry, scope in _entries(self.modules):
            for key, value in entry.items():
                if key in known:
                    continue
                slot = seen.setdefault(key, {"types": Counter(), "scopes": set(), "labels": [],
                                             "skip": None, "strings": []})
                slot["scopes"].add(scope)
                slot["labels"].append(label)
                slot["strings"] += _strings(value)
                try:
                    slot["types"][type_expr(value)] += 1
                except _Skip as e:
                    slot["skip"] = slot["skip"] or f"{e} on {label}"
        rows, skipped = [], []
        for key, slot in seen.items():
            if slot["skip"]:
                skipped.append({"key": key, "reason": slot["skip"]})
                continue
            types = slot["types"]
            if _EMPTY in types:
                lists = [t for t in types if t.endswith("[]") and t != _EMPTY]
                empty = types.pop(_EMPTY)
                if not lists:
                    types["string[]"] += empty
            ordered = sorted(types, key=lambda t: (-types[t], t))
            scope = [s for s in ("module", "submodule") if s in slot["scopes"]]
            strings = slot["strings"]
            existing = sum(names_repo_path(self.root, s) for s in strings)
            pointer = at_least_80(existing, len(strings))
            observed = ", ".join(f"{t} ({types[t]})" for t in ordered)
            keys = [("type", ordered[0] if len(ordered) == 1 else ordered,
                     [f"observed on {len(slot['labels'])} entr"
                      f"{'y' if len(slot['labels']) == 1 else 'ies'} ({_names(slot['labels'])}): "
                      f"{observed}"]
                     + ([f"{existing} of {len(strings)} string values name existing paths "
                         f"(below 80 %): data"] if strings and not pointer else []))]
            if pointer:
                keys.append(("kind", "code_pointer", [f"{existing} of {len(strings)} string "
                                                      f"values name existing paths (at least "
                                                      f"80 %)"]))
            keys.append(("scope", scope, [f"seen on {' and '.join(scope)} entries"]))
            rows.append({"name": key, "type": ordered, "kind": "code_pointer" if pointer
                         else "data", "scope": scope, "entries": len(slot["labels"])})
            self.section(f"[fields.{_toml_key(key)}]", keys)
        self.data["fields"] = rows
        self.data["skipped"] = skipped

    def infer_dir_whitelist(self) -> None:
        mdir = self.root / self.modules_dir
        have = set(self.config["registry"]["dir_whitelist"])
        dirs = sorted(d.name for d in mdir.iterdir()
                      if d.is_dir() and not d.name.startswith(".") and d.name not in self.modules
                      and d.name not in have and not stub_head(self.root, self.config, d.name)) \
            if mdir.is_dir() else []
        self.data["dir_whitelist"] = dirs
        if dirs:
            self.registry_keys.append(("dir_whitelist", dirs, [
                f"{self.modules_dir}/{d}/ is not a registry module or a pointer stub (lint "
                f"MS014 otherwise)" for d in dirs]))

    def infer_updated_at_path(self) -> None:
        found = []
        if not self.config["registry"].get("updated_at_path"):
            for key, value in self.top_level().items():
                if isinstance(value, dict):
                    found += [(2, f"{key}.{k}", v) for k, v in value.items()
                              if "." not in k and _UPDATED.search(k)]
                elif _UPDATED.search(key):
                    found.append((1, key, value))
        found = sorted((d, p) for d, p, v in found if isinstance(v, str) and _ISO.match(v))
        self.data["updated_at_path"] = found[0][1] if found else None
        if found:
            others = [p for _, p in found[1:]]
            self.registry_keys.append(("updated_at_path", found[0][1], [
                "a registry-level ISO-8601 timestamp named updated/modified; the registry "
                "writers stamp it" + (f" (also found: {', '.join(others)})" if others else "")]))

    def top_level(self) -> dict:
        return {k: v for k, v in self.raw.items() if k != "modules" and "." not in k}

    def pointer_values(self) -> dict[str, list[str]]:
        fields = [f["name"] for f in self.data["fields"] if f["kind"] == "code_pointer"]
        fields += [n for n, d in load_field_defs(self.config).items() if d.kind == "code_pointer"]
        return {m: [s for f in fields for s in _strings(self.modules[m].get(f))]
                for m in self.top}

    def prefixes(self) -> set[str]:
        """Directories up to 3 segments deep that may hold one directory per module: never
        the modules dir, the config dir, a dot-directory or a dependency / build directory."""
        skip = {self.modules_dir.rstrip("/")}
        with contextlib.suppress(ValueError):
            skip.add(self.config_dir.relative_to(self.root).as_posix())
        out = set()
        for dirpath, dirnames, _ in os.walk(self.root):
            rel = Path(dirpath).relative_to(self.root).as_posix()
            depth = 0 if rel == "." else rel.count("/") + 1
            dirnames[:] = sorted(d for d in dirnames if not d.startswith(".")
                                 and d not in DEPENDENCY_DIRS
                                 and (d if rel == "." else f"{rel}/{d}") not in skip)
            if depth:
                out.add(rel)
            if depth >= 3:
                dirnames[:] = []
        return out

    def infer_code_map(self) -> None:
        self.data["code_map"] = self.data["code_map_suggestion"] = None
        if self.config.get("code_map") or not self.top:
            return
        pointers = self.pointer_values()
        candidates = self.prefixes()
        for module, values in pointers.items():
            for value in values:
                parts = value.split("/")
                for i in range(1, min(4, len(parts))):
                    if parts[i] == module and not parts[0].startswith("."):
                        candidates.add("/".join(parts[:i]))
        scores = []
        for prefix in candidates:
            if prefix.split("/")[0] in DEPENDENCY_DIRS or prefix == self.modules_dir.rstrip("/"):
                continue
            covered = [m for m in self.top if (self.root / prefix / m).is_dir()
                       or any(v == f"{prefix}/{m}" or v.startswith(f"{prefix}/{m}/")
                              for v in pointers[m])]
            if covered:
                scores.append((-len(covered), prefix.count("/"), prefix, covered))
        scores.sort()
        if scores and not at_least_50(len(scores[0][3]), len(self.top)):
            self.suggest(scores[0][2], scores[0][3])
        scores = [s for s in scores if at_least_50(len(s[3]), len(self.top))]
        if not scores:
            return
        _, _, prefix, covered = scores[0]
        pattern = f"{prefix}/{{module}}/**"
        alternatives = [{"pattern": f"{p}/{{module}}/**", "covered": len(c)}
                        for _, _, p, c in scores[1:6]]
        rule_id = prefix.replace("/", "-")
        self.data["code_map"] = {"id": rule_id, "pattern": pattern, "covered": len(covered),
                                 "total": len(self.top), "alternatives": alternatives}
        evidence = [f"{len(covered)} of {len(self.top)} top-level modules have {prefix}/<module> "
                    f"({_names(covered)}): at least 50 %"]
        if alternatives:
            evidence.append("alternatives: " + ", ".join(f"{a['pattern']} ({a['covered']})"
                                                         for a in alternatives))
        self.section("[[code_map]]", [("id", rule_id, [f"the prefix {prefix}"]),
                                      ("pattern", pattern, evidence)])

    def suggest(self, prefix: str, covered: list[str]) -> None:
        """The best prefix below the 50 % threshold, written commented out for the team."""
        pattern = f"{prefix}/{{module}}/**"
        self.data["code_map_suggestion"] = {"pattern": pattern, "covered": len(covered),
                                            "total": len(self.top)}
        self.suggestion_lines = [
            "## adopt: no code-map rule reaches 50 % of the top-level modules. A team decision: "
            "uncomment", "## the best candidate to route code by it.", "# [[code_map]]",
            f"# id = {_toml_string(prefix.replace('/', '-'))}",
            f"# pattern = {_toml_string(pattern)}",
            f"# adopt: {len(covered)} of {len(self.top)} top-level modules have {prefix}/<module> "
            f"({_names(covered)}): below the 50 % threshold"]

    def infer_budgets(self) -> None:
        budgets = self.config["budgets"]
        module_docs, role_docs = [], []
        for name, entry in self.modules.items():
            if not isinstance(entry, dict):
                continue
            for _, universal, roles in _docs(entry, name):
                if isinstance(universal, str) and (self.root / universal).is_file():
                    module_docs.append(_line_count(self.root / universal))
                role_docs += [_line_count(self.root / p) for p in roles
                              if isinstance(p, str) and (self.root / p).is_file()]
        rows = []
        split, hard, role = (budgets["module_doc_split_signal"], budgets["module_doc_hard_stop"],
                             budgets["role_doc_max"])
        top_module, top_role = max(module_docs, default=0), max(role_docs, default=0)
        if top_module > hard:
            n = sum(x > hard for x in module_docs)
            rows.append(("module_doc_hard_stop", top_module, n,
                         f"{n} MODULE.md over {hard} lines; this clears {n} MS031"))
        if top_module > split:
            n = sum(x > split for x in module_docs)
            rows.append(("module_doc_split_signal", top_module, n,
                         f"{n} MODULE.md over {split} lines; this clears {n} MS030 / MS031"))
        if top_role > role:
            n = sum(x > role for x in role_docs)
            rows.append(("role_doc_max", top_role, n,
                         f"{n} role doc(s) over {role} lines; this clears {n} MS032"))
        self.data["budgets"] = [{"key": k, "observed_max": v, "clears": n}
                                for k, v, n, _ in rows]
        if rows:
            self.budget_lines = ["## adopt: the doc budgets flag some docs. A team decision: "
                                 "uncomment to raise them.", "# [budgets]"]
            for key, value, _, evidence in rows:
                self.budget_lines += [f"# {key} = {value}", f"# adopt: {evidence}"]

    def text(self) -> str:
        blocks = ["\n".join(lines) for lines in self.sections if lines]
        if self.suggestion_lines:
            blocks.append("\n".join(self.suggestion_lines))
        if self.budget_lines:
            blocks.append("\n".join(self.budget_lines))
        body = "\n\n".join(blocks) if blocks else "# adopt: nothing to add"
        return adopt_header() + body + "\n"


def _registry_path(root: Path, config: dict, arg: str | None) -> tuple[str, bool]:
    """(root-relative registry path, given by --registry)."""
    if arg is None:
        return config["paths"]["registry"], False
    path = Path(arg)
    if path.is_absolute():  # as given, else its directory resolved (a symlinked root)
        norm = Path(os.path.normpath(path))
        for candidate in (norm, norm.parent.resolve() / norm.name):
            with contextlib.suppress(ValueError):
                path = candidate.relative_to(root)
                break
        else:
            raise UsageError(f"--registry {arg} is outside the repository {root}")
    rel = Path(os.path.normpath(path)).as_posix()
    if rel in (".", "..") or rel.startswith("../"):
        raise UsageError(f"--registry {arg} is outside the repository {root}")
    return rel, True


def plan_adopt(root: Path, config_dir: Path, registry_arg: str | None) -> dict:
    """Everything `adopt` would write and report; reads only."""
    if config_dir.exists() and not config_dir.is_dir():
        raise UsageError(f"{config_dir} is not a directory (the config dir); nothing written")
    config = load_config(config_dir, root)
    rel, given = _registry_path(root, config, registry_arg)
    registry = root / rel
    if not registry.is_file():
        if given:
            raise UsageError(f"registry not found: {rel}")
        raise UsageError(f"no registry at {rel} — pass the registry file with --registry PATH "
                         f"(root-relative), or start from the code: modsys init map")
    raw = load_registry(registry).raw
    paths: dict = {}
    if rel != config["paths"]["registry"]:
        paths["registry"] = rel
        mdir = Path(rel).parent.as_posix()
        if mdir != config["paths"]["modules_dir"]:
            paths["modules_dir"] = mdir
    layout = config["paths"]["registry_layout"]
    modules_dir = paths.get("modules_dir", config["paths"]["modules_dir"])
    entry = config["paths"]["module_entry"]
    if layout == "single" and raw["modules"]:
        missing = [m for m in raw["modules"] if not (root / modules_dir / m / entry).is_file()]
        if not missing:
            layout = paths["registry_layout"] = "per-module"
        elif len(missing) < len(raw["modules"]):
            raise UsageError(f"{rel}: a mixed layout — some modules have {modules_dir}/<name>/"
                             f"{entry}, these do not: {', '.join(missing)}; give every module "
                             f"its entry file, or none")
    if layout == "per-module":
        raw = load_per_module(root, {**config, "paths": {**config["paths"], **paths}}).raw
    inference = Inference(root, config_dir, config, rel, raw, paths)
    inferred = inference.run()
    existing = (config_dir / "config.toml").exists()
    target = config_dir / (PROPOSAL if existing else "config.toml")
    return {"registry": rel, "layout": layout, "modules": len(raw["modules"]),
            "inferred": inferred, "target": target, "existing": existing,
            "text": inference.text()}


def merged_config(root: Path, config_dir: Path, text: str) -> dict:
    """The active config with the inferred layer (`text`) merged in."""
    return load_config(config_dir, root, extra=tomllib.loads(text), extra_source="adopt")


def lint_report(root: Path, config_dir: Path, config: dict) -> dict:
    """Lint in report mode against `config` (the merged one)."""
    ws = Workspace(root, config_dir, config, load_field_defs(config))
    findings = lint_registry(ws)
    counts = Counter(f.code for f in findings)
    return {"counts": dict(sorted(counts.items())),
            "findings": [asdict(f) for f in findings[:LINT_SHOWN]]}


def ignores_missing(root: Path, config_dir: Path, config: dict) -> bool:
    """True when `<root>/.gitignore` is missing or lacks a line `modsys init` would add."""
    try:
        text = (root / ".gitignore").read_bytes().decode("utf-8", "replace")
    except FileNotFoundError:
        text = ""
    except OSError:
        return False  # unreadable: `modsys init` reports it itself
    have = {line.strip() for line in text.splitlines()}
    return any(line not in have for line in ignore_lines(root, config_dir, config))


def write_config(path: Path, text: str, rel: str, replace: bool) -> None:
    """The proposal is replaced atomically; a new config.toml is created exclusively (a temp
    file hard-linked into place: never over a file that appeared meanwhile, never half)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if replace:
            atomic_write(path, text)
            return
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    except OSError as e:
        raise UsageError(f"cannot write {rel}: {e.strerror or e}") from None
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.chmod(tmp, 0o644)
        try:
            os.link(tmp, path)
        except FileExistsError:
            raise UsageError(f"{rel} appeared while adopt was running; run adopt again") from None
    except OSError as e:
        raise UsageError(f"cannot write {rel}: {e.strerror or e}") from None
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def run(args) -> int:
    root = Path(args.root or find_root(Path.cwd())).resolve()
    config_dir = Path(args.config_dir or root / ".modsys").resolve()
    plan = plan_adopt(root, config_dir, args.registry)
    rel = _rel(root, plan["target"])
    if not args.dry_run:
        write_config(plan["target"], plan["text"], rel, replace=plan["existing"])
    config_rel = _rel(root, config_dir / "config.toml")
    steps = []
    if plan["existing"]:
        steps.append(f"merge {rel} into {config_rel} by hand (an existing config is never "
                     f"edited), then delete {rel}")
    elif args.dry_run:
        steps.append(f"run modsys adopt without --dry-run to write {rel}")
    else:
        steps.append(f"review {rel} (each `# adopt:` line says why), then commit it")
    config = merged_config(root, config_dir, plan["text"])
    if ignores_missing(root, config_dir, config):  # adopt itself writes one file only
        steps.append("modsys init — adds the .gitignore lines for the lock file, proposals and "
                     "init (it keeps your config)")
    steps.append(f'enable the core agent skills: [packs] builtin = ["core"] in {config_rel}')
    if not plan["modules"]:
        steps.append("the registry has no modules yet: to start from the code, run "
                     "modsys init map")
    report = lint_report(root, config_dir, config)
    if report["counts"]:
        steps.append("the lint findings above remain: modsys lint (and docs/configuration.md "
                     "for each code)")
    data = {"root": str(root), "registry": plan["registry"], "layout": plan["layout"],
            "inferred": plan["inferred"], "config_path": rel, "config": plan["text"],
            "lint": report, "next_steps": steps, "dry_run": args.dry_run}
    emit("adopt", data, args.json, _render)
    return EXIT_OK


def _render(d) -> None:
    if d["dry_run"]:
        print(d["config"], end="")
        print()
    i = d["inferred"]
    print(f"root: {d['root']}")
    print(f"registry: {d['registry']} ({d['layout']})")
    rule = i["code_map"]["pattern"] if i["code_map"] else "none"
    print(f"inferred: {len(i['paths'])} path key(s), {len(i['roles'])} role(s), "
          f"{len(i['fields'])} field(s), {len(i['dir_whitelist'])} whitelisted dir(s), "
          f"updated_at_path {i['updated_at_path'] or 'none'}, code map {rule}, "
          f"{len(i['budgets'])} budget(s) (commented out); {len(i['skipped'])} key(s) skipped")
    for s in i["skipped"]:
        print(f"  skipped {s['key']}: {s['reason']}")
    hint = i["code_map_suggestion"]
    if hint:
        print(f"  code map suggestion (commented out): {hint['pattern']} — {hint['covered']} of "
              f"{hint['total']} top-level modules, below 50 %")
    print(f"{'would write' if d['dry_run'] else 'wrote'} {d['config_path']}")
    counts = d["lint"]["counts"]
    print("lint (report mode): " + (", ".join(f"{c} ×{n}" for c, n in counts.items())
                                    if counts else "no findings"))
    for step in d["next_steps"]:
        print(f"next: {step}")
