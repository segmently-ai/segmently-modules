"""`segmently-modules task-context save|add|show|check|refresh|export|list`: the task context file (`task_context`) —
module-discover saves its result there, later phases add to it and read the slice they need (2026-10-20)."""
from __future__ import annotations

import json
import os
from pathlib import Path

from segmently_modules import task_context as tc
from segmently_modules.config import enabled_roles
from segmently_modules.output import EXIT_FINDINGS, EXIT_OK, UsageError, defer_note, emit
from segmently_modules.store import file_lock
from segmently_modules.workspace import Workspace

VERB = "task-context"


def register(sub, common) -> None:
    p = sub.add_parser(VERB, help="the task context file: discovery's result, extended and read by later phases",
                       description="save: create the file from module-discover's judgements (the engine fills "
                                   "the docs, the rules verbatim, the docs to update, the files outside every "
                                   "module). add: add a phase's findings. show: a slice by role and module. "
                                   "check: is it still fresh (exit 1 when stale). refresh: re-fill stale "
                                   "modules. export: the old discovery-results.json (1.1). list: the saved files, "
                                   "newest first.")
    verbs = p.add_subparsers(dest="action", required=True, metavar="save|add|show|check|refresh|export|list")
    s = verbs.add_parser("save", parents=[common], help="create the file from a judgements file")
    s.add_argument("--from", dest="source", required=True, metavar="FILE", help="the input JSON (- for stdin)")
    s.add_argument("--out", metavar="PATH", help="the file (default: [discover] save_dir, by default the user's cache, /<date>-<slug>.json)")
    s.add_argument("--actor", default="module-discover", help="who saves it (default module-discover)")
    s.add_argument("--phase", default="discover", help="the phase it records (default discover)")
    s.set_defaults(func=run_save)
    a = verbs.add_parser("add", parents=[common], help="add a phase's findings; never removes")
    a.add_argument("file")
    a.add_argument("--phase", required=True)
    a.add_argument("--from", dest="source", required=True, metavar="FILE", help="the input JSON (- for stdin)")
    a.add_argument("--actor", default="cli")
    a.add_argument("--base-revision", type=int, metavar="N", help="refuse unless the file is at revision N")
    a.set_defaults(func=run_add)
    sh = verbs.add_parser("show", parents=[common], help="a slice: the main doc's part always, then the roles named")
    sh.add_argument("file")
    sh.add_argument("--role", action="append", metavar="R", help="a role (repeatable or comma-separated)")
    sh.add_argument("--module", action="append", metavar="M", help="a module of the file (repeatable)")
    sh.add_argument("--for", dest="skill", metavar="SKILL", help="the roles of the skill's reads_roles")
    sh.add_argument("--all-rules", action="store_true", help="every rule of the modules, not only those that apply")
    sh.set_defaults(func=run_show)
    c = verbs.add_parser("check", parents=[common], help="freshness; exit 1 when stale")
    c.add_argument("file")
    c.set_defaults(func=run_check)
    r = verbs.add_parser("refresh", parents=[common], help="re-fill the mechanical part of stale modules")
    r.add_argument("file")
    r.add_argument("--module", action="append", required=True, metavar="M", help="a module (repeatable)")
    r.add_argument("--phase", default="refresh")
    r.add_argument("--actor", default="cli")
    r.set_defaults(func=run_refresh)
    e = verbs.add_parser("export", parents=[common], help="the file in an older shape")
    e.add_argument("file")
    e.add_argument("--format", required=True, choices=tc.EXPORT_FORMATS)
    e.set_defaults(func=run_export)
    ls = verbs.add_parser("list", parents=[common], help="the task context files of the save folder, newest first")
    ls.set_defaults(func=run_list)


def _file(ws, value: str) -> Path:
    """A file argument: relative to the current directory, as a shell user gives it."""
    path = Path(value)
    return path if path.is_absolute() else Path(os.getcwd()) / path


def run_save(args) -> int:
    ws = Workspace.from_args(args)
    inp = tc.read_input(args.source, need_task=True)
    data = tc.build(ws, inp, args.actor, args.phase)
    path = _file(ws, args.out) if args.out else tc.default_path(ws, inp["task"])
    with file_lock(path):
        tc.write(path, data)
    emit(VERB, {"path": ws.rel(path), "revision": data["revision"]}, args.json, lambda d: print(d["path"]))
    return EXIT_OK


def run_add(args) -> int:
    ws = Workspace.from_args(args)
    inp = tc.read_input(args.source, need_task=False)
    path = _file(ws, args.file)
    data = tc.locked_update(path, lambda d: tc.merge(ws, d, inp, args.phase, args.actor), args.base_revision)
    emit(VERB, {"path": ws.rel(path), "revision": data["revision"]}, args.json,
         lambda d: print(f"{d['path']}  revision {d['revision']}"))
    return EXIT_OK


def run_show(args) -> int:
    ws = Workspace.from_args(args)
    data = tc.load(_file(ws, args.file))
    roles = tc._split(args.role)
    if args.skill:
        roles += [r for r in tc.skill_roles(ws, args.skill) if r not in roles]
    named = bool(args.role or args.skill)
    held = {d.get("role") for d in data["docs"]} | {r.get("role") for r in data["rules"]}
    for r in roles:
        if r not in held and r not in enabled_roles(ws.config) and r != "extras":
            defer_note(f"role {r}: not a role of this repository and no doc of the file has it")
    view = tc.select(data, roles if named else None, tc._split(args.module), args.all_rules)
    emit(VERB, view, args.json, _render_show)
    return EXIT_OK


def run_check(args) -> int:
    ws = Workspace.from_args(args)
    result = tc.check(ws, tc.load(_file(ws, args.file)))
    emit(VERB, result, args.json, _render_check)
    return EXIT_OK if result["fresh"] else EXIT_FINDINGS


def run_refresh(args) -> int:
    ws = Workspace.from_args(args)
    path = _file(ws, args.file)
    names = tc._split(args.module)
    changed: list = []

    def change(data):
        held = {m["module"]: m for m in data["modules"]}
        unknown = [n for n in names if n not in held]
        if unknown:
            raise UsageError(f"--module: {', '.join(unknown)} not in the file "
                             f"(modules: {', '.join(held) or 'none'})")
        for n in names:
            tc._target(ws, n)  # gone from the registry: exit 2 with show's message
            changed.extend(p for p in tc.fill_module(ws, data, held[n], refresh=True) if p not in changed)
        tc._outside(ws, data)
        data["revision"] += 1
        tc._phase(data, args.phase, args.actor)
        return data

    data = tc.locked_update(path, change)
    emit(VERB, {"path": ws.rel(path), "revision": data["revision"], "modules": names, "changed_docs": changed},
         args.json, _render_refresh)
    return EXIT_OK


def run_export(args) -> int:
    ws = Workspace.from_args(args)
    data = tc.export_1_1(tc.load(_file(ws, args.file)))
    emit(VERB, data, args.json, lambda d: print(json.dumps(d, indent=2, ensure_ascii=False)))
    return EXIT_OK


# ---- text --------------------------------------------------------------------------------------------------------

def _rule_line(r: dict) -> str:
    text = r.get("text") or r.get("quote") or r.get("title") or ""
    first, *rest = text.split("\n")
    out = [f"- `{r['id']}` ({r.get('role') or 'doc'}) — {first}"]
    out += [f"    {ln.strip()}" for ln in rest if ln.strip()]
    if r.get("source") == "doc" and r.get("quote") and r.get("quote") != text:
        out.append(f"    doc line: {r['quote']}")
    if r.get("applies"):
        out.append(f"    applies: {r['applies']}")
    if r.get("stale"):
        out.append("    stale: the doc changed, read it again")
    return "\n".join(out)


def _doc_lines(d: dict) -> list[str]:
    head = f"- `{d['path']}` ({d.get('role')})"
    if d.get("extracts"):
        return [f"{head}: {x['text']}" + (f" (`{x['ref']}`)" if x.get("ref") else "")
                + (" [stale: read it again]" if x.get("stale") else "") for x in d["extracts"]]
    if d.get("nothing"):
        return [f"{head}: read, nothing for this task"]
    if d.get("read") in ("index", "skipped"):
        return [f"{head}: not read ({d['read']})"]
    return [f"{head}: no extract"]


def _render_show(v: dict) -> None:
    print(f"## Task context: {v.get('task')}  (revision {v.get('revision')})")
    search = v.get("search") or {}
    if search:
        print(f"Search: {search.get('mode')} — lexical {search.get('lexical')}"
              + (f": {search['reason']}" if search.get("reason") else ""))
    rules_of = {}
    docs_of = {}
    for m in v["modules"]:
        rules_of[m["module"]] = [r for r in v["rules"] if r in tc.module_view(v, m["module"])[1]]
        docs_of[m["module"]] = [d for d in v["docs"] if d in tc.module_view(v, m["module"])[0]]
    for m in v["modules"]:
        score = f" (score {m['score']})" if m.get("score") is not None else ""
        print(f"\n### {m['module']} — usage: {m.get('usage')}{score}")
        print(f"Why: {m.get('why') or 'none'}" + ("; named by the user" if m.get("named_by_user") else ""))
        print("Rules:")
        for r in rules_of[m["module"]] or []:
            print(_rule_line(r))
        if not rules_of[m["module"]]:
            print("- none")
        print("Docs:")
        for d in docs_of[m["module"]]:
            print("\n".join(_doc_lines(d)))
        if not docs_of[m["module"]]:
            print("- none")
        print("Code:")
        for f in m.get("files") or []:
            where = f"{f['path']}:{f['line']}" if f.get("line") else f["path"]
            parts = [f"`{f.get('tag') or 'read'}`", f"`{where}`"] + \
                    [x for x in (f"`{f['symbol']}`" if f.get("symbol") else None, f.get("why")) if x]
            print("- " + " — ".join(parts))
        if not m.get("files"):
            print("- none")
        if m.get("tests"):
            print(f"Tests: {m['tests']}")
        if m.get("one_way"):
            print(f"One way: {m['one_way']['kind']} — {m['one_way']['reason']}")
        print("Risks / unknowns: " + ("; ".join(m.get("risks") or []) or "none"))
        for c in m.get("consequences") or []:
            print(f"Likely consequence: {c['text']}" + (f" — {c['file']}" if c.get("file") else ""))
        print("Docs to update: " + (", ".join(f"`{p}`" for p in m.get("docs_to_update") or []) or "none"))
    print("\n### Rejected")
    for r in v.get("rejected") or []:
        print(f"- {r.get('module')} — {r.get('why')} (score {r.get('score')})")
    if not v.get("rejected"):
        print("- none")
    for title, key in (("Files outside every module", "files_outside_modules"), ("Missing files", "missing_files")):
        print(f"\n### {title}")
        print("\n".join(f"- `{p}`" for p in v.get(key) or []) or "- none")
    if v.get("notes"):
        print("\n### Notes")
        for n in v["notes"]:
            refs = f" ({', '.join(n.get('refs') or [])})" if n.get("refs") else ""
            print(f"- [{n.get('phase')}] {n.get('text')}{refs}")
    if v.get("summary"):
        print(f"\nSummary: {v['summary']}")


def _render_check(c: dict) -> None:
    for d in c["docs"]:
        print(f"doc     {d['state']:<8} {d['path']}  ({d.get('module')})")
    for p in c["code"]:
        print(f"code    changed  {p}")
    for m in c["modules"]:
        print(f"module  {m['state']:<8} {m['module']}")
    for n in c["notes"]:
        print(f"note    {n}")
    if c["fresh"]:
        print("fresh")
    else:
        print(f"stale: {len(c['docs'])} doc(s), {len(c['code'])} code file(s), {len(c['modules'])} module(s) — "
              f"refresh the modules (`segmently-modules task-context refresh <file> --module <m>`)")


def _render_refresh(d: dict) -> None:
    print(f"{d['path']}  revision {d['revision']}  refreshed: {', '.join(d['modules'])}")
    for p in d["changed_docs"]:
        print(f"  changed  {p}  (its extracts are marked stale)")


def run_list(args) -> int:
    ws = Workspace.from_args(args)
    rows = tc.list_saved(ws)

    def render(d):
        if not d["files"]:
            print(f"no task context file in {d['folder']}")
        for f in d["files"]:
            print(f"{f['path']}  r{f['revision']}  {f['created']}  {' → '.join(f['phases'])}  {f['task'][:80]!s}")
    emit(VERB, {"folder": str(tc.save_folder(ws)), "files": rows}, args.json, render)
    return EXIT_OK
