"""`modsys code-map`: the `[[code_map]]` rules and the files they route.

  list [--module TARGET]  the effective rules (every layer merged); with --module only the
                          rules that route files to TARGET (a module or `parent/child`)
  files TARGET            every repository file (git-tracked + new, not ignored; no coverage
                          filters) that maps to TARGET, with its mapping sources per file:
                          `docs`, `code_pointer:<field>`, `code_map:<id>`"""
from modsys.changes import repo_files, require_work_tree, routes, rule_routes_to, target_names
from modsys.output import EXIT_OK, UsageError, emit
from modsys.registry import as_list
from modsys.workspace import Workspace

ACTIONS = ("list", "files")


def register(sub, common) -> None:
    p = sub.add_parser("code-map", parents=[common],
                       help="list [[code_map]] rules, or every file that maps to a module",
                       description="list: the effective [[code_map]] rules (--module TARGET: "
                                   "only those routing files to TARGET). files TARGET: every "
                                   "repository file that maps to TARGET and how (docs, "
                                   "code_pointer:<field>, code_map:<id>); needs git.")
    p.add_argument("action", choices=ACTIONS)
    p.add_argument("name", nargs="?", metavar="TARGET", help="files: a module or parent/child")
    p.add_argument("--module", metavar="TARGET",
                   help="list: only the rules that route files to TARGET")
    p.set_defaults(func=run)


def check_target(ws, target: str) -> str:
    """`target` when it names a registry module or child; else exit 2 with the closest names."""
    targets = target_names(ws.registry.modules)
    if target not in targets:
        near = sorted(t for t in targets if target.lower() in t.lower())
        hint = f" — closest: {', '.join(near[:5])}" if near else ""
        raise UsageError(f"unknown module '{target}'{hint}")
    return target


def rule_rows(config: dict, target: str | None = None) -> list[dict]:
    """The effective rules, optionally only those that route files to `target`."""
    return [{"id": r["id"], "module": r.get("module"), "pattern": r.get("pattern"),
             "globs": r.get("globs"), "exclusive": r.get("exclusive") is True}
            for r in as_list(config.get("code_map"))
            if isinstance(r, dict) and "id" in r and (target is None or rule_routes_to(r, target))]


def files_of(ws, target: str) -> dict:
    """Every repository file that maps to `target`, with its sources, in path order."""
    require_work_tree(ws.root, "code-map files")
    per_file: dict[str, list] = {}
    for path, routed_to, via in routes(ws, repo_files(ws.root)):
        if routed_to == target:
            vias = per_file.setdefault(path, [])
            if via not in vias:
                vias.append(via)
    return {"target": target, "files": [{"path": p, "via": v} for p, v in per_file.items()],
            "total": len(per_file)}


def run(args) -> int:
    ws = Workspace.from_args(args)
    if args.action == "list":
        if args.name is not None:
            raise UsageError("code-map list takes no TARGET (filter with --module TARGET)")
        target = None if args.module is None else check_target(ws, args.module)
        emit("code-map", rule_rows(ws.config, target), args.json, _render_list)
        return EXIT_OK
    if args.name is None:
        raise UsageError("code-map files needs a TARGET (a module or parent/child)")
    if args.module is not None:
        raise UsageError("code-map files takes no --module (the TARGET is the module)")
    emit("code-map", files_of(ws, check_target(ws, args.name)), args.json, _render_files)
    return EXIT_OK


def _render_list(rows) -> None:
    if not rows:
        print("no [[code_map]] rules")
    for r in rows:
        where = r["pattern"] if r["pattern"] is not None else ", ".join(r["globs"] or [])
        flag = "  exclusive" if r["exclusive"] else ""
        print(f"{r['id']:<24} {r['module'] or '{module}':<24} {where}{flag}")


def _render_files(d) -> None:
    for f in d["files"]:
        print(f"{f['path']}  ({', '.join(f['via'])})")
    print(f"{d['total']} file(s) map to {d['target']}")
