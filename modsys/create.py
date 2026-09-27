"""`modsys create`: scaffold a module (or `--parent` child) — docs from templates plus its
registry entry. Answers come from `--answers file.json`, flags, or (on a terminal) prompts;
with `--non-interactive` a missing answer is an error that lists every missing key.

Template resolution (first hit wins), for `MODULE.md`, `roles/<role>.md` and `agents-md.md`
(`resolve_template_source` names the layer — `modsys templates list` shows it):
  1. `<config_dir>/overrides/templates/<path>`                         source "override"
  2. a role's own `template` (path inside its owning pack)             "role-template:<pack>"
  3. `<pack>/templates/<path>` for packs in precedence order           "pack:<pack>"
  4. engine defaults: MODULE.md, agents-md.md and one file per         "engine"
     standard role; `roles/_role.md` for any other role                "engine-fallback"
Templates use `${name}` placeholders: name, title, description, status, keywords, parent,
role, role_description."""
import contextlib
import json
import re
import string
import sys
from importlib import resources
from pathlib import Path

from modsys.config import enabled_roles
from modsys.fields import value_matches
from modsys.output import UsageError
from modsys.store import atomic_write, open_store

NAME = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
BASE_ANSWERS = {"description", "keywords", "status", "tags", "roles"}


def ask_fields(ws, scope: str) -> dict:
    return {n: d for n, d in ws.fields.items() if d.ask_on_create and scope in d.scope}


def _create_cfg(ws) -> dict:
    return ws.config["create"]


def validate_answers(ws, answers: dict, scope: str) -> list[str]:
    """Missing required keys (for the error message); raises for invalid values."""
    cfg = _create_cfg(ws)
    extra = ask_fields(ws, scope)
    unknown = set(answers) - BASE_ANSWERS - set(extra)
    if unknown:
        raise UsageError(f"unknown answer key(s): {', '.join(sorted(unknown))} "
                         f"(allowed: {', '.join(sorted(BASE_ANSWERS | set(extra)))})")
    missing = [k for k in ("description", "keywords") if k not in answers]
    missing += [k for k in extra if k not in answers]
    if missing:
        return missing
    desc = answers["description"]
    if not isinstance(desc, str) or not (cfg["description_min"] <= len(desc.strip())
                                         <= cfg["description_max"]):
        raise UsageError(f"description must be {cfg['description_min']}–"
                         f"{cfg['description_max']} characters")
    kws = answers["keywords"]
    need = cfg["min_keywords"] if scope == "module" else 1
    if not (isinstance(kws, list) and all(isinstance(k, str) and k.strip() for k in kws)
            and len(set(kws)) >= need):
        raise UsageError(f"keywords must be at least {need} distinct non-empty strings")
    status = answers.get("status", cfg["default_status"])
    if scope == "module" and status not in ws.config["registry"]["statuses"]:
        raise UsageError(f"status {status!r} not in {ws.config['registry']['statuses']}")
    for key in ("tags", "roles"):
        v = answers.get(key, [])
        if not (isinstance(v, list) and all(isinstance(i, str) for i in v)):
            raise UsageError(f"{key} must be a list of strings")
    for name, fdef in extra.items():
        if not value_matches(fdef, answers[name]):
            raise UsageError(f"answer {name!r} does not match type {' | '.join(fdef.type)}")
    return []


def prompt_missing(ws, answers: dict, missing: list[str]) -> dict:
    out = dict(answers)
    for key in missing:
        fdef = ws.fields.get(key)
        hint = {"description": "one sentence: WHAT it does, WHY, WHEN to use it",
                "keywords": "comma-separated routing terms"}.get(key, fdef.description if fdef else "")
        raw = input(f"{key} ({hint}): ").strip()
        if key == "keywords":
            out[key] = [k.strip() for k in raw.split(",") if k.strip()]
        elif fdef and fdef.type != ("string",):
            try:
                out[key] = json.loads(raw)
            except json.JSONDecodeError:
                raise UsageError(f"{key}: expected JSON for type {' | '.join(fdef.type)}") from None
        else:
            out[key] = raw
    return out


def roles_to_scaffold(ws, answers: dict) -> list[str]:
    roles = ws.config.get("roles") or {}
    wanted = set(answers.get("roles", []))
    unknown = wanted - set(enabled_roles(ws.config))
    if unknown:
        raise UsageError(f"unknown role(s): {', '.join(sorted(unknown))}")
    tags = set(answers.get("tags", []))
    return [r for r in enabled_roles(ws.config)
            if roles[r].get("standard") or roles[r].get("applies_when") in tags or r in wanted]


def engine_templates() -> Path:
    """The engine's default templates directory (package data)."""
    return Path(str(resources.files("modsys").joinpath("defaults/templates")))


def resolve_template_source(ws, relpath: str, role: str | None = None) -> tuple[str, Path]:
    """(source, path) of the template file that wins for `relpath` — see the module docstring
    for the order and the source names."""
    candidates = [("override", ws.config_dir / "overrides" / "templates" / relpath)]
    spec = (ws.config.get("roles") or {}).get(role or "", {})
    pack_dirs = ws.config.get("_pack_dirs", {})
    if role and spec.get("template") and spec.get("owner") in pack_dirs:
        candidates.append((f"role-template:{spec['owner']}",
                           Path(pack_dirs[spec["owner"]]) / spec["template"]))
    candidates += [(f"pack:{p}", Path(pack_dirs[p]) / "templates" / relpath)
                   for p in ws.config.get("_packs", [])]
    for source, path in candidates:
        if path.is_file():
            return source, path
    engine = engine_templates() / relpath
    if engine.is_file():
        return "engine", engine
    return "engine-fallback", engine_templates() / "roles" / "_role.md"


def resolve_template(ws, relpath: str, role: str | None = None) -> str:
    return resolve_template_source(ws, relpath, role)[1].read_text(encoding="utf-8")


def _check_name(value: str) -> None:
    if not NAME.fullmatch(value) or len(value) > 48:
        raise UsageError(f"module name {value!r}: use lowercase words joined by '-' (max 48)")


def plan_create(ws, name: str, parent: str | None, answers: dict) -> dict:
    """Validate everything and compute files + entry; writes nothing."""
    _check_name(name)
    modules = ws.registry.modules
    mdir = ws.config["paths"]["modules_dir"]
    if parent:
        _check_name(parent)
        if not isinstance(modules.get(parent), dict):
            raise UsageError(f"unknown parent module '{parent}'")
        if name in (modules[parent].get("submodules") or {}):
            raise UsageError(f"'{parent}/{name}' already exists")
        rel_dir = f"{mdir}/{parent}/submodules/{name}"
    else:
        if name in modules:
            raise UsageError(f"module '{name}' already exists")
        rel_dir = f"{mdir}/{name}"
    if (ws.root / rel_dir).exists():
        raise UsageError(f"{rel_dir}/ already exists (a stub or unregistered directory?)")
    scope = "submodule" if parent else "module"
    missing = validate_answers(ws, answers, scope)
    if missing:
        raise UsageError(f"missing answers: {', '.join(missing)} "
                         f"(pass --answers file.json or the matching flags)")
    status = answers.get("status", _create_cfg(ws)["default_status"])
    values = {"name": name, "title": name.replace("-", " ").title(),
              "description": answers["description"].strip(), "status": status,
              "keywords": ", ".join(answers["keywords"]), "parent": parent or ""}
    doc = ws.config["paths"]["module_doc"]
    files = {f"{rel_dir}/{doc}": string.Template(resolve_template(ws, "MODULE.md"))
             .safe_substitute(values)}
    role_files = {}
    for role in roles_to_scaffold(ws, answers):
        spec = ws.config["roles"][role]
        rel = f"{rel_dir}/roles/{role}.md"
        files[rel] = string.Template(resolve_template(ws, f"roles/{role}.md", role)) \
            .safe_substitute(values, role=role, role_description=spec.get("description", ""))
        role_files[role] = rel
    files = {p: t if t.endswith("\n") else t + "\n" for p, t in files.items()}
    entry = {} if parent else {"name": name}
    entry["description"] = values["description"]
    if not parent:
        entry["status"] = status
    entry["keywords"] = list(dict.fromkeys(answers["keywords"]))
    entry["context_files"] = {"universal": f"{rel_dir}/{doc}", "roles": role_files}
    for key in ask_fields(ws, scope):
        entry[key] = answers[key]
    return {"module": f"{parent}/{name}" if parent else name, "files": files, "entry": entry,
            "parent": parent, "name": name, "rel_dir": rel_dir}


def _check_still_free(ws, plan: dict, modules: dict) -> None:
    """Re-check existence against the just-locked registry (and the filesystem) before any
    doc is written — the plan-time check (`plan_create`) can be stale by the time the lock is
    held, since another writer may have created the same module in between."""
    parent, name = plan["parent"], plan["name"]
    if parent:
        if not isinstance(modules.get(parent), dict):
            raise UsageError(f"unknown parent module '{parent}'")
        if name in (modules[parent].get("submodules") or {}):
            raise UsageError(f"'{parent}/{name}' already exists")
    elif name in modules:
        raise UsageError(f"module '{name}' already exists")
    if (ws.root / plan["rel_dir"]).exists():
        raise UsageError(f"{plan['rel_dir']}/ already exists (a stub or unregistered directory?)")


def apply_create(ws, plan: dict) -> None:
    """Write docs, then the registry entry; on a registry failure remove what was written."""
    written: list[Path] = []
    store = open_store(ws)
    try:
        with store.edit() as reg:
            modules = reg.raw["modules"]
            _check_still_free(ws, plan, modules)
            for rel, text in plan["files"].items():
                path = ws.root / rel
                atomic_write(path, text)
                written.append(path)
            if plan["parent"]:
                modules[plan["parent"]].setdefault("submodules", {})[plan["name"]] = plan["entry"]
            else:
                modules[plan["name"]] = plan["entry"]
    except BaseException:
        stop = ws.root / ws.config["paths"]["modules_dir"]
        dirs = set()
        for path in written:
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
            dirs.update(d for d in path.parents if stop in d.parents)
        for d in sorted(dirs, key=lambda p: -len(p.parts)):  # deepest first; only empty ones go
            with contextlib.suppress(OSError):
                d.rmdir()
        raise


def interactive() -> bool:
    return sys.stdin is not None and sys.stdin.isatty()
