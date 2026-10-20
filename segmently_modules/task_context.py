"""The task context file (`segmently-modules.task-context/1`): module-discover's result as a source of truth
for one task that later phases extend and read in slices (owner, 2026-10-20: "a temporary source of truth for a
feature", split by role, the main module doc's part always shown, a full format always available).

The skill writes only its judgements (the usage marks, why lines, the rules it chose by `doc:line`, extracts,
risks, rejected); the engine fills the rest mechanically: each doc's role and hash from `show --discover`, every
rule of those docs whole from `rules_of`, the docs to update, the files outside every module, `head`. Storage is
normalised — each doc and each rule once — and the split by role is `show`'s view. A rule's text always comes
from the doc: 9 of the 14 rules the stand's sessions missed were read and then lost or softened in the retelling
(plan 2026-10-16 §11.11), so the agent names a rule and never retypes it. Every write goes through the CLI: a lock
next to the file, an atomic replace, and a revision a writer may pin (`--base-revision`)."""
from __future__ import annotations

import copy
import json
import re
import subprocess
from datetime import date
from pathlib import Path

from segmently_modules.changes import git_env, map_files, missing_files, routes
from segmently_modules.config import builtin_packs_root, discover_packs, discover_settings, read_toml
from segmently_modules.output import UsageError
from segmently_modules.query import doc_kind, rules_of, show_target
from segmently_modules.registry import as_dict
from segmently_modules.store import atomic_write, file_lock, file_sha256, utc_now

SCHEMA = "segmently-modules.task-context/1"
USAGES = ("new", "modify", "extend", "consume", "reference")
TAGS = ("edit", "read")
CHANGES = ("new", "modify", "extend")  # the usages whose docs are to be updated
UPDATE_ROLES = ("module", "developer", "qa")  # the docs to update of a module the task changes
SCALARS = ("usage", "why", "score", "tests", "one_way")  # replaced by `add`, the old value kept in `history`
INPUT_KEYS = {"task", "search", "modules", "docs", "rules", "rejected", "notes", "summary"}
MODULE_KEYS = {"module", "usage", "score", "why", "named_by_user", "files", "tests", "risks", "consequences",
               "one_way"}  # one_way: {kind, reason}, a change that cannot be undone (a pipeline's size verdict reads it)
EXPORT_FORMATS = ("discovery-1.1",)


# ---- input -------------------------------------------------------------------------------------------------------

def _fail(where: str, what: str) -> None:
    raise UsageError(f"{where}: {what}")


def _check_list(value, where: str) -> list:
    if value is None:
        return []
    if not isinstance(value, list):
        _fail(where, f"expected a list, got {type(value).__name__}")
    return value


def _opt_str(value, where: str) -> None:
    if value is not None and not isinstance(value, str):
        _fail(where, f"expected a string or null, got {value!r}")


def read_input(path: str, need_task: bool) -> dict:
    """The §8.1 input of `save` / `add` (a JSON file, `-` for stdin), checked: unknown keys, a usage or a tag
    outside the contract and wrong types are exit 2 before anything is written."""
    import sys
    try:
        text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    except OSError as e:
        raise UsageError(f"cannot read {path}: {e.strerror}") from None
    try:
        data = json.loads(text)
    except ValueError as e:
        raise UsageError(f"{path}: not JSON: {e}") from None
    if not isinstance(data, dict):
        raise UsageError(f"{path}: expected a JSON object")
    unknown = sorted(set(data) - INPUT_KEYS)
    if unknown:
        _fail(path, f"unknown key(s) {', '.join(unknown)} (keys: {', '.join(sorted(INPUT_KEYS))})")
    if need_task and not (isinstance(data.get("task"), str) and data["task"].strip()):
        _fail(path, "`task` (the task, verbatim) is required")
    if need_task and not isinstance(data.get("modules"), list):
        _fail(path, "`modules` (a list) is required")
    _opt_str(data.get("task"), f"{path}: task")
    _opt_str(data.get("summary"), f"{path}: summary")
    if data.get("search") is not None and not isinstance(data["search"], dict):
        _fail(f"{path}: search", "expected an object")
    for i, m in enumerate(_check_list(data.get("modules"), f"{path}: modules")):
        where = f"{path}: modules[{i}]"
        if not isinstance(m, dict) or not isinstance(m.get("module"), str) or not m["module"]:
            _fail(where, "expected an object with `module`")
        unknown = sorted(set(m) - MODULE_KEYS)
        if unknown:
            _fail(where, f"unknown key(s) {', '.join(unknown)}")
        if "usage" in m and m["usage"] not in USAGES:
            _fail(where, f"usage {m['usage']!r} is not one of {', '.join(USAGES)}")
        if m.get("score") is not None and (isinstance(m["score"], bool) or not isinstance(m["score"], (int, float))):
            _fail(where, f"score {m['score']!r} is not a number")
        for key in ("why", "tests"):
            _opt_str(m.get(key), f"{where}.{key}")
        ow = m.get("one_way")
        if ow is not None and not (isinstance(ow, dict) and set(ow) == {"kind", "reason"}
                                   and all(isinstance(ow[k], str) and ow[k] for k in ow)):
            _fail(f"{where}.one_way", "expected an object with `kind` and `reason`")
        for j, f in enumerate(_check_list(m.get("files"), f"{where}.files")):
            if not isinstance(f, dict) or not isinstance(f.get("path"), str) or not f["path"]:
                _fail(f"{where}.files[{j}]", "expected an object with `path`")
            if f.get("tag") is not None and f["tag"] not in TAGS:
                _fail(f"{where}.files[{j}]", f"tag {f['tag']!r} is not edit or read")
            if f.get("line") is not None and (isinstance(f["line"], bool) or not isinstance(f["line"], int)):
                _fail(f"{where}.files[{j}]", f"line {f['line']!r} is not an integer")
        for j, r in enumerate(_check_list(m.get("risks"), f"{where}.risks")):
            _opt_str(r, f"{where}.risks[{j}]")
        for j, c in enumerate(_check_list(m.get("consequences"), f"{where}.consequences")):
            if not isinstance(c, dict) or not isinstance(c.get("text"), str):
                _fail(f"{where}.consequences[{j}]", "expected an object with `text`")
            _opt_str(c.get("file"), f"{where}.consequences[{j}].file")
    for i, d in enumerate(_check_list(data.get("docs"), f"{path}: docs")):
        if not isinstance(d, dict) or not isinstance(d.get("path"), str) or not d["path"]:
            _fail(f"{path}: docs[{i}]", "expected an object with `path`")
        for j, x in enumerate(_check_list(d.get("extracts"), f"{path}: docs[{i}].extracts")):
            if not isinstance(x, dict) or not isinstance(x.get("text"), str):
                _fail(f"{path}: docs[{i}].extracts[{j}]", "expected an object with `text`")
            _opt_str(x.get("ref"), f"{path}: docs[{i}].extracts[{j}].ref")
    for i, r in enumerate(_check_list(data.get("rules"), f"{path}: rules")):
        if not isinstance(r, dict) or not isinstance(r.get("ref"), str):
            _fail(f"{path}: rules[{i}]", "expected an object with `ref` (`<doc>:<line>`)")
        _opt_str(r.get("applies"), f"{path}: rules[{i}].applies")
        _opt_str(r.get("text"), f"{path}: rules[{i}].text")
    for key in ("rejected", "notes"):
        for i, x in enumerate(_check_list(data.get(key), f"{path}: {key}")):
            if not isinstance(x, dict):
                _fail(f"{path}: {key}[{i}]", "expected an object")
    return data


# ---- the file ----------------------------------------------------------------------------------------------------

def load(path: Path) -> dict:
    """A task context file, its schema checked."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise UsageError(f"cannot read {path}: {e.strerror}") from None
    except ValueError as e:
        raise UsageError(f"{path}: not JSON: {e}") from None
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        got = data.get("schema") if isinstance(data, dict) else None
        raise UsageError(f"{path}: not a task context file (schema {got!r}, expected {SCHEMA!r})")
    if not (isinstance(data.get("revision"), int) and isinstance(data.get("modules"), list)
            and isinstance(data.get("docs"), list) and isinstance(data.get("rules"), list)):
        raise UsageError(f"{path}: a broken task context file (revision, modules, docs or rules)")
    return data


def write(path: Path, data: dict) -> None:
    atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def head_of(root: Path) -> str | None:
    """`git rev-parse HEAD`; None outside git or before the first commit."""
    try:
        proc = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "--quiet", "HEAD"],
                              capture_output=True, encoding="utf-8", errors="replace", env=git_env())
    except OSError:
        return None
    return proc.stdout.strip() or None if proc.returncode == 0 else None


def default_path(ws, task: str) -> Path:
    """`[discover] save_dir`/<YYYY-MM-DD>-<slug of the task's first words>.json; another run's file is never
    replaced (`-2`, `-3`, … after the slug). The directory gets a `.gitignore` holding `*` on first use: a
    task's context is a working file, never committed."""
    folder = Path(discover_settings(ws.config)["save_dir"])
    folder = folder if folder.is_absolute() else ws.root / folder
    words = re.findall(r"[a-z0-9]+", task.lower())[:6]
    slug = "-".join(words)[:48].rstrip("-") or "task"
    stem = f"{date.today().isoformat()}-{slug}"
    path, n = folder / f"{stem}.json", 2
    while path.exists():
        path, n = folder / f"{stem}-{n}.json", n + 1
    folder.mkdir(parents=True, exist_ok=True)
    ignore = folder / ".gitignore"
    if not ignore.exists():
        ignore.write_text("*\n", encoding="utf-8")
    return path


# ---- the mechanical part -----------------------------------------------------------------------------------------

def _target(ws, name: str) -> str:
    """A registry `module[/child]`; an unknown one is exit 2 with `show`'s message."""
    from segmently_modules.rules_cmd import _target as target  # rules_cmd imports query, as this module does
    return target(ws, name)


def _shown_docs(ws, target: str, usage: str) -> list[dict]:
    """The docs of a target as `show <m> --all-roles --discover` lists them, read and not read: [{path, module,
    role, exists, sha256, read}]. A child's parent docs (its universal doc and the parent baseline role docs)
    belong to the parent. A `reference` module: its main doc only."""
    _, shown = show_target(ws, target, None, True, discover=True)
    parent, _, child = target.partition("/")
    rows = [(r, "whole") for r in shown["read"]] + \
           [(r, "index" if r["why"] == "index" else "skipped") for r in shown.get("not_read") or []]
    out = []
    for r, read in rows:
        kind = doc_kind(r["label"])
        if usage == "reference" and kind != "module":
            continue
        owner = parent if child and (r["label"].startswith(("universal", "parent baseline"))) else target
        out.append({"path": r["path"], "module": owner, "role": kind, "exists": (ws.root / r["path"]).is_file(),
                    "sha256": _sha(ws, r["path"]), "read": read, "nothing": False, "extracts": []})
    return out


def _sha(ws, path: str) -> str | None:
    p = ws.root / path
    return file_sha256(p) if p.is_file() else None


def _section_rules(ws, target: str, usage: str) -> list[dict]:
    """Every rule of the target's docs' critical-rules sections, whole (`rules_of`, no budget): a child's parent
    first. A `reference` module: its module docs' rules only."""
    parent, _, child = target.partition("/")
    out = []
    for owner in ([parent, target] if child else [target]):
        for d in rules_of(ws, owner):
            if usage == "reference" and d["role"] != "all":
                continue
            for r in d["rules"]:
                out.append({"id": f"{r['doc']}:{r['line']}", "module": owner, "doc": r["doc"], "line": r["line"],
                            "role": "module" if r["role"] == "all" else r["role"], "title": r["title"],
                            "text": r["text"], "source": "section", "applies": None, "phase": None})
    return out


def _children(ws, target: str) -> list[str]:
    if "/" in target:
        return []
    subs = as_dict(as_dict(ws.registry.modules.get(target)).get("submodules"))
    return [f"{target}/{c}" for c in subs]


def fill_module(ws, data: dict, module: dict, refresh: bool = False) -> list[str]:
    """The mechanical part of one module of the file: its docs and rules merged in (each stored once), its
    children and docs to update. Nothing is removed. `refresh`: each known doc's hash, presence and read mark are
    taken again — an extract of a doc whose hash changed gets `stale: true`, a section rule no longer in its doc
    too — and the module's `head` is now. Returns the paths of the docs whose hash changed."""
    target = module["module"]
    usage = module.get("usage") or "reference"
    docs = {d["path"]: d for d in data["docs"]}
    changed = []
    for d in _shown_docs(ws, target, usage):
        old = docs.get(d["path"])
        if old is None:
            data["docs"].append(d)
            docs[d["path"]] = d
        elif refresh:
            if old.get("sha256") != d["sha256"]:
                changed.append(d["path"])
                for x in old.get("extracts") or []:
                    x["stale"] = True
            old.update(exists=d["exists"], sha256=d["sha256"], read=d["read"])
    rules = {r["id"]: r for r in data["rules"]}
    fresh = _section_rules(ws, target, usage)
    for r in fresh:
        old = rules.get(r["id"])
        if old is None:
            data["rules"].append(r)
            rules[r["id"]] = r
        elif refresh and old.get("source") == "section":
            old.update(title=r["title"], text=r["text"])
            old.pop("stale", None)
    if refresh:
        ids = {r["id"] for r in fresh}
        mine = {target, target.partition("/")[0]}
        for r in data["rules"]:
            if r.get("module") in mine and r.get("doc") in changed:
                if r.get("source") == "section" and r["id"] not in ids:
                    r["stale"] = True  # the doc no longer has a rule at this line
                elif r.get("source") == "doc" and _line(ws, r["doc"], r["line"]) != r.get("quote"):
                    r["stale"] = True
        module["head"] = head_of(ws.root)
    module["children"] = _children(ws, target)
    module["docs_to_update"] = ([d["path"] for role in UPDATE_ROLES for d in data["docs"]
                                 if d["module"] == target and d["role"] == role and d.get("exists")]
                                if usage in CHANGES else [])
    return changed


def _line(ws, doc: str, line: int) -> str | None:
    try:
        lines = (ws.root / doc).read_text(encoding="utf-8", errors="replace").split("\n")
    except OSError:
        return None
    return lines[line - 1].rstrip() if 1 <= line <= len(lines) else None


def _owner_of(ws, path: str) -> str | None:
    """The module whose docs a path is under (`routes`' docs mapping), else None."""
    for _, target, via in routes(ws, [path]):
        if via == "docs":
            return target
    return None


def _foreign_doc(ws, path: str) -> dict:
    """A doc the input names that the modules' read lists do not hold (a doc a later phase read): its module from
    where it lives, its role from that module's `show` label ("extras" when it lists none)."""
    if not (ws.root / path).is_file():
        raise UsageError(f"docs: {path} is not a file in the repository")
    owner, role = _owner_of(ws, path), "extras"
    if owner:
        _, shown = show_target(ws, owner, None, True)
        role = next((doc_kind(r["label"]) for r in shown["read"] if r["path"] == path), "extras")
    return {"path": path, "module": owner, "role": role, "exists": True, "sha256": _sha(ws, path),
            "read": "whole", "nothing": False, "extracts": []}


def _mark_rules(ws, data: dict, rules_in: list[dict], phase: str) -> None:
    """Input rules named by `<doc>:<line>`. One that is a section rule gets `applies` and `phase`; any other is
    added with `source: "doc"`, `quote` = the doc's own line there and `text` = the input's (else the quote).
    A ref past the doc's end or to a missing doc is exit 2."""
    rules = {r["id"]: r for r in data["rules"]}
    docs = {d["path"]: d for d in data["docs"]}
    for r in rules_in:
        doc, sep, line = r["ref"].rpartition(":")
        if not sep or not doc or not line.isdigit() or int(line) < 1:
            raise UsageError(f"rules: {r['ref']!r} is not `<doc>:<line>`")
        rid, n = f"{doc}:{int(line)}", int(line)
        applies = r.get("applies") if r.get("applies") is not None else ""
        known = rules.get(rid)
        if known is not None:
            known["applies"], known["phase"] = applies, phase
            if known.get("source") == "doc" and r.get("text"):
                known["text"] = r["text"]
            continue
        if not (ws.root / doc).is_file():
            raise UsageError(f"rules: {rid}: {doc} is not a file in the repository")
        quote = _line(ws, doc, n)
        if quote is None:
            raise UsageError(f"rules: {rid}: {doc} has no line {n}")
        holder = docs.get(doc)
        entry = {"id": rid, "module": holder["module"] if holder else _owner_of(ws, doc), "doc": doc, "line": n,
                 "role": holder["role"] if holder else None, "title": None, "text": r.get("text") or quote,
                 "quote": quote, "source": "doc", "applies": applies, "phase": phase}
        data["rules"].append(entry)
        rules[rid] = entry


def _add_docs(ws, data: dict, docs_in: list[dict], phase: str) -> None:
    docs = {d["path"]: d for d in data["docs"]}
    for d in docs_in:
        held = docs.get(d["path"])
        if held is None:
            held = _foreign_doc(ws, d["path"])
            data["docs"].append(held)
            docs[d["path"]] = held
        if d.get("nothing") is not None:
            held["nothing"] = bool(d["nothing"])
        seen = {(x["text"], x.get("ref")) for x in held["extracts"]}
        for x in d.get("extracts") or []:
            if (x["text"], x.get("ref")) not in seen:
                held["extracts"].append({"text": x["text"], "ref": x.get("ref"), "phase": phase})
                seen.add((x["text"], x.get("ref")))


def _paths(data: dict) -> list[str]:
    out = []
    for m in data["modules"]:
        for p in [f["path"] for f in m.get("files") or []] + \
                 [c["file"] for c in m.get("consequences") or [] if c.get("file")]:
            if p not in out:
                out.append(p)
    return out


def _outside(ws, data: dict) -> None:
    paths = _paths(data)
    data["files_outside_modules"] = map_files(ws, paths)["unmapped"] if paths else []
    data["missing_files"] = missing_files(ws.root, paths)


def _module_entry(m: dict, target: str) -> dict:
    return {"module": target, "usage": m.get("usage") or "reference", "score": m.get("score"),
            "why": m.get("why"), "named_by_user": bool(m.get("named_by_user")), "children": [],
            "files": [_file(f) for f in m.get("files") or []], "docs_to_update": [], "tests": m.get("tests"),
            "risks": list(m.get("risks") or []),
            "consequences": [{"text": c["text"], "file": c.get("file")} for c in m.get("consequences") or []],
            **({"one_way": m["one_way"]} if m.get("one_way") else {})}


def _file(f: dict) -> dict:
    return {"path": f["path"], "line": f.get("line"), "tag": f.get("tag"), "symbol": f.get("symbol"),
            "why": f.get("why")}


def _phase(data: dict, phase: str, actor: str) -> None:
    data["phases"].append({"phase": phase, "actor": actor, "at": utc_now(), "revision": data["revision"]})


def build(ws, inp: dict, actor: str, phase: str = "discover") -> dict:
    """`save`: the file from the §8.1 input, revision 1."""
    data = {"schema": SCHEMA, "revision": 1, "task": inp["task"], "created": utc_now(), "head": head_of(ws.root),
            "search": inp.get("search"), "phases": [], "modules": [], "docs": [], "rules": [],
            "rejected": [dict(r) for r in inp.get("rejected") or []], "files_outside_modules": [],
            "missing_files": [], "notes": [], "summary": inp.get("summary")}
    for m in inp["modules"]:
        target = _target(ws, m["module"])
        if any(x["module"] == target for x in data["modules"]):
            raise UsageError(f"modules: {target} is listed twice")
        entry = _module_entry(m, target)
        data["modules"].append(entry)
        fill_module(ws, data, entry)
    _add_docs(ws, data, inp.get("docs") or [], phase)
    _mark_rules(ws, data, inp.get("rules") or [], phase)
    data["notes"] = [{"text": n.get("text"), "refs": list(n.get("refs") or []), "phase": phase}
                     for n in inp.get("notes") or []]
    _outside(ws, data)
    _phase(data, phase, actor)
    return data


def merge(ws, data: dict, inp: dict, phase: str, actor: str) -> dict:
    """`add`: the input merged into the file, never removing anything. A new module is filled as on save; for a
    known one `files`, `risks` and `consequences` are appended without duplicates and a changed scalar is replaced,
    the old value kept in `history`."""
    data = copy.deepcopy(data)
    if inp.get("task") and inp["task"] != data.get("task"):
        raise UsageError(f"task: the file is the context of another task ({data.get('task')!r})")
    known = {m["module"]: m for m in data["modules"]}
    for m in inp.get("modules") or []:
        target = _target(ws, m["module"])
        held = known.get(target)
        if held is None:
            held = _module_entry(m, target)
            data["modules"].append(held)
            known[target] = held
            fill_module(ws, data, held)
            continue
        refill = False
        for key in SCALARS:
            if key in m and m[key] is not None and m[key] != held.get(key):
                held.setdefault("history", []).append({"phase": phase, "field": key, "old": held.get(key)})
                held[key] = m[key]
                refill = refill or key == "usage"
        if m.get("named_by_user"):
            held["named_by_user"] = True
        for key, items in (("files", [_file(f) for f in m.get("files") or []]), ("risks", m.get("risks") or []),
                           ("consequences", [{"text": c["text"], "file": c.get("file")}
                                             for c in m.get("consequences") or []])):
            for item in items:
                if item not in held.setdefault(key, []):
                    held[key].append(item)
        if refill:
            fill_module(ws, data, held)
    _add_docs(ws, data, inp.get("docs") or [], phase)
    _mark_rules(ws, data, inp.get("rules") or [], phase)
    for r in inp.get("rejected") or []:
        if r not in data["rejected"]:
            data["rejected"].append(dict(r))
    for n in inp.get("notes") or []:
        data["notes"].append({"text": n.get("text"), "refs": list(n.get("refs") or []), "phase": phase})
    if inp.get("search") is not None:
        data["search"] = inp["search"]
    if inp.get("summary") is not None:
        data["summary"] = inp["summary"]
    _outside(ws, data)
    data["revision"] += 1
    _phase(data, phase, actor)
    return data


def locked_update(path: Path, change, base_revision: int | None = None) -> dict:
    """Load, check `base_revision`, change, write — under the file's lock, with an atomic replace."""
    with file_lock(path):
        data = load(path)
        if base_revision is not None and base_revision != data["revision"]:
            raise UsageError(f"{path}: revision is {data['revision']}, not {base_revision}: read it again")
        new = change(data)
        write(path, new)
        return new


# ---- views -------------------------------------------------------------------------------------------------------

def skill_roles(ws, skill: str) -> list[str]:
    """The roles a skill reads (`reads_roles` of its pack's `[skills.<id>]`): the active packs first, then every
    built-in pack (a skill whose pack this repository has not enabled still names its roles)."""
    for pack in discover_packs(ws.config_dir, ws.root):
        spec = as_dict(as_dict(pack["data"].get("skills")).get(skill))
        if spec:
            return list(spec.get("reads_roles") or [])
    for pack_toml in sorted(builtin_packs_root().glob("*/pack.toml")):
        spec = as_dict(as_dict(read_toml(pack_toml).get("skills")).get(skill))
        if spec:
            return list(spec.get("reads_roles") or [])
    raise UsageError(f"--for {skill}: no pack declares this skill")


def _split(values) -> list[str]:
    return [v.strip() for value in values or [] for v in value.split(",") if v.strip()]


def module_view(data: dict, module: str) -> tuple[list[dict], list[dict]]:
    """The docs and rules shown under one module: its own, and for a child its parent's when the parent is not a
    module of the file itself."""
    names = {m["module"] for m in data["modules"]}
    parent = module.partition("/")[0]
    mine = {module} | ({parent} if parent != module and parent not in names else set())
    return ([d for d in data["docs"] if d.get("module") in mine],
            [r for r in data["rules"] if r.get("module") in mine])


def select(data: dict, roles: list[str] | None, modules: list[str], all_rules: bool) -> dict:
    """`show`'s selection in the file's shape: the named modules (all when none); the docs and rules whose role is
    `module` or one named (every one when no role is named); the applicable rules only, unless `all_rules`."""
    names = [m["module"] for m in data["modules"]]
    unknown = [m for m in modules if m not in names]
    if unknown:
        raise UsageError(f"--module: {', '.join(unknown)} not in the file (modules: {', '.join(names) or 'none'})")
    out = {k: v for k, v in data.items() if k not in ("modules", "docs", "rules")}
    out["modules"] = [m for m in data["modules"] if not modules or m["module"] in modules]
    keep = lambda role: roles is None or role == "module" or role in roles  # noqa: E731
    docs, rules = [], []
    for m in out["modules"]:
        d, r = module_view(data, m["module"])
        docs += [x for x in d if keep(x.get("role")) and x not in docs]
        rules += [x for x in r if keep(x.get("role")) and (all_rules or x.get("applies") is not None)
                  and x not in rules]
    out["docs"], out["rules"] = docs, rules
    return out


# ---- freshness ---------------------------------------------------------------------------------------------------

def _is_commit(root: Path, sha: str) -> bool:
    proc = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}"],
                          capture_output=True, encoding="utf-8", errors="replace", env=git_env())
    return proc.returncode == 0


def _changed_since(root: Path, head: str, files: list[str]) -> list[str]:
    """The files that differ from `head` in the working tree: committed since, staged or not (`git diff <head>`
    compares the working tree with it), deleted ones too."""
    proc = subprocess.run(["git", "-C", str(root), "diff", "--name-only", "--relative", "--no-renames", "-z",
                           "--end-of-options", head, "--", *files],
                          capture_output=True, encoding="utf-8", errors="replace", env=git_env())
    if proc.returncode != 0:
        raise UsageError(f"git diff {head[:12]} failed: {proc.stderr.strip()[:300]}")
    return [p for p in proc.stdout.split("\0") if p]


def check(ws, data: dict) -> dict:
    """Freshness: docs whose hash changed (or that are gone, or new on disk), code files of `files` changed since
    the `head` they were read at (a module's own `head` after `refresh`, else the file's), modules the registry
    no longer has or split since."""
    docs = []
    for d in data["docs"]:
        now = _sha(ws, d["path"])
        if now != d.get("sha256"):
            state = "gone" if now is None else "new" if d.get("sha256") is None else "changed"
            docs.append({"path": d["path"], "module": d.get("module"), "state": state})
    modules = []
    for m in data["modules"]:
        parent, _, child = m["module"].partition("/")
        entry = ws.registry.modules.get(parent)
        if not isinstance(entry, dict) or (child and child not in as_dict(entry.get("submodules"))):
            modules.append({"module": m["module"], "state": "gone"})
        elif not child and set(_children(ws, parent)) - set(m.get("children") or []):
            modules.append({"module": m["module"], "state": "split"})
    code, problems = [], []
    by_head: dict = {}
    for m in data["modules"]:
        files = [f["path"] for f in m.get("files") or []]
        if files:
            by_head.setdefault(m.get("head") or data.get("head"), []).extend(files)
    for head, files in by_head.items():
        if head is None:
            problems.append("no head: the code was not checked (the file was saved outside git)")
            continue
        if not _is_commit(ws.root, head):
            problems.append(f"head {head[:12]} is not a commit here: the code was not checked")
            continue
        for p in _changed_since(ws.root, head, sorted(set(files))):
            if p not in code:
                code.append(p)
    stale = bool(docs or code or modules or any(p.startswith("head ") for p in problems))
    return {"fresh": not stale, "head": data.get("head"), "docs": docs, "code": code, "modules": modules,
            "notes": problems}


# ---- export ------------------------------------------------------------------------------------------------------

USAGE_1_1 = {"modify": "MODIFY", "new": "EXTEND", "extend": "EXTEND", "consume": "READ-ONLY",
             "reference": "READ-ONLY"}


def export_1_1(data: dict) -> dict:
    """The `discovery-results.json` of module-discover before the task context (`version` `1.1`), for a pipeline
    still on it: `usage_type`, `confidence`, `documentation` per role, `files[]` with `offset` / `limit` /
    `reason` starting with the tag."""
    modules = []
    for m in data["modules"]:
        score = m.get("score")
        confidence = ("user_specified" if m.get("named_by_user") else
                      "high" if isinstance(score, (int, float)) and score >= 7 else "medium")
        documentation = {}
        docs, _ = module_view(data, m["module"])
        for d in sorted(docs, key=lambda d: d.get("module") != m["module"]):  # its own docs before its parent's
            if d.get("read") == "whole" or d.get("extracts"):
                documentation.setdefault(f"{d['role']}_md", d["path"])
        files = []
        for f in m.get("files") or []:
            reason = " — ".join(x for x in (f.get("tag"), f.get("symbol"), f.get("why")) if x)
            files.append({"path": f["path"], "offset": f.get("line") or 1, "limit": 30, "reason": reason})
        modules.append({"name": m["module"], "score": score, "confidence": confidence,
                        "usage_type": USAGE_1_1.get(m.get("usage"), "READ-ONLY"), "documentation": documentation,
                        "files": files})
    return {"version": "1.1", "task": data.get("task"), "modules": modules,
            "files_outside_modules": [{"path": p, "offset": 1, "limit": 30, "reason": "outside every module"}
                                      for p in data.get("files_outside_modules") or []],
            "summary": data.get("summary")}
