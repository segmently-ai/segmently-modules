from pathlib import Path

from modsys.config import enabled_roles
from modsys.output import EXIT_FINDINGS, EXIT_OK, UsageError, emit
from modsys.registry import as_dict, as_list, resolve_module_arg, stub_head
from modsys.workspace import Workspace


def role_paths(cf: dict, role: str) -> list:
    val = as_dict(as_dict(cf).get("roles")).get(role)
    if isinstance(val, str):
        return [val]
    if isinstance(val, list):
        return list(val)
    return []


def _extras(cf: dict):
    for key, val in as_dict(cf).items():
        if key in ("universal", "roles"):
            continue
        for p in val if isinstance(val, list) else [val]:
            if isinstance(p, str):
                yield key, p


def _stub_or_unknown(ws, name: str) -> tuple[int, dict]:
    stub = stub_head(ws.root, ws.config, name)
    if stub:
        return EXIT_FINDINGS, {"module": name, "stub": stub}
    near = [n for n in ws.registry.modules if name.lower() in n.lower()]
    hint = f" — closest: {', '.join(near[:5])}" if near else ""
    raise UsageError(f"unknown module '{name}'{hint}")


def _object(entry, label: str) -> dict:
    if not isinstance(entry, dict):
        raise UsageError(f"registry entry '{label}' is not an object")
    return entry


def show_module(ws, arg: str, role: str | None, all_roles: bool) -> tuple[int, dict]:
    modules = ws.registry.modules
    modules_dir = ws.config["paths"]["modules_dir"]
    resolved = resolve_module_arg(arg, modules_dir)
    if resolved == arg and "/" in arg and (Path(arg).exists() or (ws.root / arg).exists()):
        raise UsageError(f"'{arg}' is a file path outside {modules_dir}/ — not a module; "
                         f"read it directly")
    parent, _, child = resolved.partition("/")
    if parent not in modules:
        return _stub_or_unknown(ws, parent)
    entry = _object(modules[parent], parent)
    subs = as_dict(entry.get("submodules"))
    if child and child not in subs:
        raise UsageError(f"'{child}' is not a submodule of '{parent}' "
                         f"(children: {', '.join(subs) or 'none'})")
    sub = _object(subs[child], f"{parent}/{child}") if child else {}
    result = {"module": f"{parent}/{child}" if child else parent,
              "status": entry.get("status"), "description": entry.get("description"),
              "read": [], "code": []}

    def add(label, path):
        if isinstance(path, str) and path:  # malformed paths are lint's job (MS004)
            result["read"].append({"label": label, "path": path,
                                   "exists": (ws.root / path).exists()})

    roles = enabled_roles(ws.config) if all_roles else ([role] if role else [])
    cf = as_dict(entry.get("context_files"))
    add("universal (parent INDEX)" if subs else "universal", cf.get("universal"))
    if child:
        ccf = as_dict(sub.get("context_files"))
        add(f"child universal ({child})", ccf.get("universal"))
        for r in roles:
            for p in role_paths(ccf, r):
                add(f"child role:{r}", p)
            for p in role_paths(cf, r):
                add(f"parent baseline role:{r}", p)
        for key, p in _extras(ccf):
            add(f"child {key}", p)
    else:
        for r in roles:
            for p in role_paths(cf, r):
                add(f"role:{r}", p)
        for key, p in _extras(cf):
            add(key, p)
        if subs:
            result["submodules"] = {c: (as_dict(s).get("description") or "")
                                    for c, s in subs.items()}
    for name, fdef in ws.fields.items():
        if fdef.kind == "code_pointer" and entry.get(name):
            val = entry[name]
            result["code"].extend(val if isinstance(val, list) else [val])
    return EXIT_OK, result


def related_edges(ws, arg: str, relation: str | None) -> tuple[int, dict]:
    modules = ws.registry.modules
    name = resolve_module_arg(arg, ws.config["paths"]["modules_dir"]).partition("/")[0]
    if name not in modules:
        return _stub_or_unknown(ws, name)
    entry = _object(modules[name], name)
    if relation and relation not in ws.config["registry"]["relations"]:
        raise UsageError(f"unknown relation '{relation}' "
                         f"(relations: {', '.join(ws.config['registry']['relations'])})")

    def edges(e: dict):  # malformed edges are lint's job (MS013); skip them here
        return [x for x in as_list(e.get("related_modules")) if isinstance(x, dict)
                and (not relation or x.get("relation") == relation)]

    fwd = edges(entry)
    rev = []
    for other, other_entry in modules.items():
        if other == name:
            continue
        for e in edges(as_dict(other_entry)):
            target = e.get("module")
            if isinstance(target, str) and target.partition("/")[0] == name:
                rev.append({"from": other, **e})
    return EXIT_OK, {"module": name, "edges": fwd, "reverse": rev}


def list_modules(ws, status: str | None) -> tuple[int, list]:
    rows = []
    for name, entry in ws.registry.modules.items():
        entry = as_dict(entry)  # a non-object entry is still listed (lint reports it)
        if status and entry.get("status") != status:
            continue
        desc = entry.get("description")
        rows.append({"module": name, "status": entry.get("status"),
                     "description": (desc if isinstance(desc, str) else "").split(". ")[0][:100],
                     "children": ",".join(as_dict(entry.get("submodules")))})
    return EXIT_OK, rows


def register(sub, common) -> None:
    s = sub.add_parser("show", parents=[common], help="resolve module[/child] to files to read")
    s.add_argument("module")
    s.add_argument("--role")
    s.add_argument("--all-roles", action="store_true")
    s.set_defaults(func=run_show)
    r = sub.add_parser("related", parents=[common], help="typed edges of a module (+ reverse)")
    r.add_argument("module")
    r.add_argument("--relation")
    r.set_defaults(func=run_related)
    li = sub.add_parser("list", parents=[common], help="one orientation line per module")
    li.add_argument("--status")
    li.set_defaults(func=run_list)


def run_show(args) -> int:
    ws = Workspace.from_args(args)
    roles = enabled_roles(ws.config)
    if args.role and args.role not in roles:
        raise UsageError(f"unknown role '{args.role}' (roles: {', '.join(roles)})")
    code, data = show_module(ws, args.module, args.role, args.all_roles)
    emit("show", data, args.json, _render_show)
    return code


def run_related(args) -> int:
    ws = Workspace.from_args(args)
    code, data = related_edges(ws, args.module, args.relation)
    emit("related", data, args.json, _render_related)
    return code


def run_list(args) -> int:
    ws = Workspace.from_args(args)
    code, rows = list_modules(ws, args.status)
    emit("list", rows, args.json, _render_list)
    return code


def _render_show(d) -> None:
    if "stub" in d:
        print(f"'{d['module']}' is a POINTER STUB (not in registry). Stub says:\n{d['stub']}")
        return
    print(f"{d['module']}  [{d['status']}]\n  {d['description']}")
    for r in d["read"]:
        mark = "" if r["exists"] else "  (MISSING ON DISK)"
        print(f"  read  {r['label']:<32} {r['path']}{mark}")
    for c in d["code"]:
        print(f"  code  {c}")
    for c, desc in (d.get("submodules") or {}).items():
        print(f"  child {d['module']}/{c:<30} {desc}")


def _render_related(d) -> None:
    if "stub" in d:
        print(f"'{d['module']}' is a POINTER STUB. Stub says:\n{d['stub']}")
        return
    print(f"forward edges — {len(d['edges']) or 'NONE'}:")
    for e in d["edges"]:
        print(f"  {str(e.get('relation')):<18} {str(e.get('module')):<38} {e.get('description')}")
    print(f"reverse edges — {len(d['reverse']) or 'NONE'}:")
    for e in d["reverse"]:
        print(f"  {str(e.get('relation')):<18} {e['from']:<38} {e.get('description')}")


def _render_list(rows) -> None:
    for r in sorted(rows, key=lambda r: r["module"]):
        kids = f"  [children: {r['children']}]" if r["children"] else ""
        print(f"{r['module']:<36} {str(r['status'] or ''):<9} {r['description']}{kids}")
    print(f"\n{len(rows)} modules")
