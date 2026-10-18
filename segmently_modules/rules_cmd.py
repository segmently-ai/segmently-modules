"""`rules`: every critical rule, in full, of the modules a change touches — the modules named, the
modules the given files map to (`--files` / `--from-diff`, as `discover` maps them), and the parent
of each child among them. The input of a rule check: a plan or a diff read against the rules of
the modules it changes, and of discover's `Rules:` block. No budget: the caller asked for the rules,
so every text is whole. Each target's rules come from every doc of it — the module doc, then each
role doc — tagged with the doc's role; `index` says whether every doc carries its rules index."""
from __future__ import annotations

from segmently_modules.changes import changed_files, map_files, missing_files
from segmently_modules.output import EXIT_OK, UsageError, emit
from segmently_modules.query import _stub_or_unknown, index_state, rules_of
from segmently_modules.registry import as_dict, resolve_module_arg
from segmently_modules.workspace import Workspace


def _target(ws, arg: str) -> str:
    """A named `module[/child]` (or a path into the modules dir) as a registry target."""
    target = resolve_module_arg(arg, ws.config["paths"]["modules_dir"]).rstrip("/")
    parent, _, child = target.partition("/")
    if parent not in ws.registry.modules:
        _stub_or_unknown(ws, parent)  # raises for an unknown name
        raise UsageError(f"'{parent}' is a pointer stub, not a module — it has no rules")
    subs = as_dict(as_dict(ws.registry.modules[parent]).get("submodules"))
    if child and child not in subs:
        raise UsageError(f"'{child}' is not a submodule of '{parent}' "
                         f"(children: {', '.join(subs) or 'none'})")
    return target


def _doc(ws, target: str):
    parent, _, child = target.partition("/")
    entry = as_dict(ws.registry.modules.get(parent))
    holder = as_dict(as_dict(entry.get("submodules")).get(child)) if child else entry
    doc = as_dict(holder.get("context_files")).get("universal")
    return doc if isinstance(doc, str) and doc else None


def build_rules(ws, names: list[str], files: list[str], role: str | None = None) -> dict:
    via: dict[str, list] = {}
    touched: dict[str, list] = {}

    def add(target: str, why: str) -> None:
        reasons = via.setdefault(target, [])
        if why not in reasons:
            reasons.append(why)

    for arg in names:
        add(_target(ws, arg), "named")
    mapping = map_files(ws, files) if files else {"modules": {}, "unmapped": []}
    for target, hit in mapping["modules"].items():
        add(target, "files")
        touched[target] = hit["files"]
    for target in list(via):
        if "/" in target:
            add(target.partition("/")[0], "parent")
    heading = as_dict(ws.config.get("lint")).get("critical_rules_heading") or ""
    out = []
    for target in sorted(via):  # a parent sorts before its children
        docs = [d for d in rules_of(ws, target) if role is None or d["role"] in ("all", role)]
        out.append({"module": target, "doc": _doc(ws, target), "via": via[target],
                    "files": touched.get(target, []),
                    "docs": [{k: d[k] for k in ("doc", "role", "present", "indexed")}
                             | {"rules": len(d["rules"])} for d in docs if d["exists"]],
                    "index": index_state(docs),
                    "rules": [r for d in docs for r in d["rules"]]})
    return {"heading": heading, "modules": out,
            "files_outside_modules": mapping["unmapped"],
            "missing_files": missing_files(ws.root, files) if files else []}


def register(sub, common) -> None:
    r = sub.add_parser("rules", parents=[common],
                       help="the critical rules, in full, of the modules a change touches",
                       description="Every critical rule, whole, of the modules named, the modules "
                                   "the files map to, and the parent of each child among them — "
                                   "the input of a rule check of a plan or a diff.")
    r.add_argument("module", nargs="*", help="module or module/child")
    src = r.add_mutually_exclusive_group()
    src.add_argument("--from-diff", metavar="A..B")
    src.add_argument("--files", nargs="+", action="extend", metavar="PATH")
    r.add_argument("--role", help="only the module doc's rules and this role's docs' rules")
    r.set_defaults(func=run_rules)


def run_rules(args) -> int:
    if not (args.module or args.files or args.from_diff):
        raise UsageError("give the modules (module or module/child …), the change "
                         "(--files PATH … or --from-diff A..B), or both")
    ws = Workspace.from_args(args)
    files = changed_files(ws.root, diff_range=args.from_diff, files=args.files) \
        if (args.files or args.from_diff) else []
    emit("rules", build_rules(ws, args.module, files, args.role), args.json, _render_rules)
    return EXIT_OK


def _render_rules(d) -> None:
    for m in d["modules"]:
        why = ", ".join("parent of a child here" if v == "parent" else v for v in m["via"])
        print(f"## {m['module']} — {m['doc'] or 'no module doc'}  ({why})")
        for f in m["files"]:
            print(f"   file {f}")
        if not m["rules"]:
            print(f"   no rules: no doc of it has a '{d['heading']}' section" if m["doc"]
                  else "   no rules: context_files has no universal doc")
        idx = m["index"]
        if m["docs"]:
            print("   rules index: " + ("complete" if idx["complete"] else
                                       "not indexed: " + ", ".join(idx["missing"])))
        for r in m["rules"]:
            first, _, rest = r["text"].partition("\n")
            tag = "" if r["role"] == "all" else f"[{r['role']}] "
            print(f"- {r['doc']}:{r['line']}  {tag}{first}")
            for line in rest.split("\n") if rest.strip() else []:
                if line.strip():
                    print(f"    {line}")
        print()
    if d["files_outside_modules"]:
        print(f"files outside modules: {', '.join(d['files_outside_modules'])}")
    if d["missing_files"]:
        print(f"missing on disk: {', '.join(d['missing_files'])}")
    total = sum(len(m["rules"]) for m in d["modules"])
    print(f"{total} rule(s) in {len(d['modules'])} module(s)")
