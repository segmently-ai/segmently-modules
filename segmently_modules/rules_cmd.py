"""`rules`: every critical rule, in full, of the modules a change touches — the modules named, the
modules the given files map to (`--files` / `--from-diff`, as `discover` maps them), and the parent
of each child among them. The input of a rule check: a plan or a diff read against the rules of
the modules it changes, and of discover's `Rules:` block. No budget: the caller asked for the rules,
so every text is whole. Each target's rules come from every doc of it — the module doc, then each
role doc — tagged with the doc's role; `index` says whether every doc carries its rules index."""
from __future__ import annotations

from segmently_modules.changes import changed_files, map_files, missing_files
from segmently_modules.output import EXIT_OK, UsageError, emit
from segmently_modules.query import _stub_or_unknown, index_state, rule_docs, rules_of
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
                    "docs": [{k: d[k] for k in ("doc", "role", "indexable", "present", "indexed", "stale")}
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
    r.add_argument("--missing", action="store_true",
                   help="list the docs without a rules index (every module and child when none "
                        "is named); read-only")
    r.add_argument("--build", action="store_true",
                   help="index the named docs or modules' docs without an index now, one writer "
                        "per doc (needs SEGMENTLY_MODULES_ALLOW_INDEX_WRITER=1 and a writer)")
    r.set_defaults(func=run_rules)


def build_missing(ws, names: list[str]) -> dict:
    """`rules --missing`: per target (the named ones, else every module and child), the docs
    without an `Indexed:` line, the indexed ones with their date, and the docs another skill owns
    (never indexed by hand); only targets with a missing doc are listed, the summary counts all."""
    from segmently_modules.changes import target_names
    from segmently_modules.config import rules_index_setting
    targets = [_target(ws, n) for n in names] if names else sorted(target_names(ws.registry.modules))
    rows, totals = [], {"targets": 0, "docs": 0, "indexed": 0, "missing": 0, "owned": 0}
    for target in targets:
        docs = [d for d in rules_of(ws, target) if d["exists"]]
        missing = index_state(docs)["missing"]
        owned = [d["doc"] for d in docs if not d["indexable"]]
        indexed = [{"doc": d["doc"], "date": d["indexed"]} for d in docs if d["indexable"] and d["indexed"]]
        totals["targets"] += 1
        totals["docs"] += len(docs)
        totals["indexed"] += len(indexed)
        totals["missing"] += len(missing)
        totals["owned"] += len(owned)
        if missing:
            rows.append({"module": target, "missing": missing, "indexed": indexed, "owned": owned})
    return {"setting": rules_index_setting(ws.config), "modules": rows, "summary": totals}


def _render_missing(d) -> None:
    for m in d["modules"]:
        print(f"{m['module']}  missing: {', '.join(m['missing'])}")
    t = d["summary"]
    print(f"{t['missing']} doc(s) without a rules index in {len(d['modules'])} of {t['targets']} "
          f"module(s); {t['indexed']} indexed, {t['owned']} owned by another skill "
          f"([rules] index = {d['setting']})")


def build_targets(ws, names: list[str]) -> list[dict]:
    """`rules --build`'s docs: a doc path (`….md`) as itself, a module as its docs without an index
    (and its parent's, for a child); [{doc, target, role}], each doc once."""
    from segmently_modules.changes import target_names
    from segmently_modules.index_build import pending
    owner = {}
    for target in sorted(target_names(ws.registry.modules)):
        for doc, role in rule_docs(ws, target):
            owner.setdefault(doc, (target, role))
    items, seen = [], set()
    for n in names:
        if n.endswith(".md"):
            if n not in owner:
                raise UsageError(f"{n}: not a module doc or role doc of any module")
            got = [{"doc": n, "target": owner[n][0], "role": owner[n][1]}]
        else:
            got = pending(ws, [_target(ws, n)])
        for i in got:
            if i["doc"] not in seen:
                seen.add(i["doc"]); items.append(i)
    return items


def _render_build(d) -> None:
    for r in d["docs"]:
        print(f"{r['doc']}  {r['status']}" + (f"  ({r.get('added', 0):+d} rules)" if r["status"] == "built" else ""))
    for f in d["other_changes"]:
        print(f"changed outside the docs indexed: {f}")
    t = d["summary"]
    print(f"{t['built']} built, {t['failed']} failed, {t['refused']} refused, {t['timeout']} timed out")


def run_rules(args) -> int:
    if args.build:
        if args.files or args.from_diff or args.role or args.missing:
            raise UsageError("--build takes module names or doc paths only")
        if not args.module:
            raise UsageError("--build: name the modules or docs (rules --missing lists them)")
        ws = Workspace.from_args(args)
        from segmently_modules.index_build import build
        items = build_targets(ws, args.module)
        emit("rules", build(ws, items) if items else {"docs": [], "other_changes": [],
             "summary": {"built": 0, "failed": 0, "refused": 0, "timeout": 0}}, args.json, _render_build)
        return EXIT_OK
    if args.missing:
        if args.files or args.from_diff or args.role:
            raise UsageError("--missing takes module names only (or none: every module)")
        ws = Workspace.from_args(args)
        emit("rules", build_missing(ws, args.module), args.json, _render_missing)
        return EXIT_OK
    if not (args.module or args.files or args.from_diff):
        raise UsageError("give the modules (module or module/child …), the change "
                         "(--files PATH … or --from-diff A..B), or both")
    ws = Workspace.from_args(args)
    from segmently_modules.config import enabled_roles
    if args.role and args.role not in enabled_roles(ws.config):
        raise UsageError(f"unknown role '{args.role}' (roles: {', '.join(enabled_roles(ws.config))})")
    files = changed_files(ws.root, diff_range=args.from_diff, files=args.files) \
        if (args.files or args.from_diff) else []
    data = build_rules(ws, args.module, files, args.role)
    if args.module and not args.from_diff:
        # under `discover`, the modules a reader names here are the ones it chose: their docs without an
        # index are built in the background (c05 pilot 8: the reader read `rules` but skipped step 7)
        from segmently_modules.index_build import discover_hook
        hook = discover_hook(ws, [_target(ws, m) for m in args.module], False)
        if hook:
            data["rules_build"] = hook
    emit("rules", data, args.json, _render_rules)
    return EXIT_OK


def _render_rules(d) -> None:
    for m in d["modules"]:
        why = ", ".join("parent of a child here" if v == "parent" else v for v in m["via"])
        print(f"## {m['module']} — {m['doc'] or 'no module doc'}  ({why})")
        for f in m["files"]:
            print(f"   file {f}")
        if not m["rules"]:
            with_section = [x for x in m["docs"] if x["present"]]
            print("   no rules: context_files has no universal doc" if not m["doc"] else
                  f"   no rules: its '{d['heading']}' section(s) list none" if with_section else
                  f"   no rules: no doc of it has a '{d['heading']}' section")
        idx = m["index"]
        if m["docs"]:
            print("   rules index: " + ("complete" if idx["complete"] else
                                       "not indexed: " + ", ".join(idx["missing"]))
                  + ("; stale: " + ", ".join(idx["stale"]) if idx["stale"] else ""))
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
    b = d.get("rules_build")
    if b and b["status"] in ("started", "running"):
        print(f"rules index: {len(b['docs'])} doc(s) being indexed in the background (rules --build); "
              f"this run has the rules above, the next one the index")
    elif b and b.get("note"):
        print(f"rules index: not built — {b['note']}")
