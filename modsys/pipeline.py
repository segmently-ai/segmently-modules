"""Pipeline verbs. `context` answers "what should this role read before planning this task";
`discover` answers "which modules will this change touch, and which docs follow along".
Both are deterministic (keywords, code pointers, code_map, paths) — agents add judgment."""
import functools
import os
import re
import sys
from pathlib import Path

from modsys.changes import changed_files, map_files, missing_files
from modsys.config import enabled_roles
from modsys.match import match_modules, near_lines, near_misses
from modsys.output import EXIT_OK, UsageError, emit
from modsys.query import show_target
from modsys.workspace import Workspace

_PATHLIKE = re.compile(r"(?<![\w/.-])((?:\.{0,2}/)?[\w.-]+(?:/[\w.-]+)+)")
UPDATE_ROLES = ("developer", "qa")  # a modified module's developer + qa docs follow the code


def task_text(args) -> str:
    if args.task_file:
        try:
            text = sys.stdin.read() if str(args.task_file) == "-" else \
                args.task_file.read_text(encoding="utf-8")
        except OSError as e:
            raise UsageError(f"{args.task_file}: cannot read: {e}") from None
    else:
        text = args.task or ""
    if not text.strip():
        raise UsageError("give the task: --task TEXT or --task-file FILE ('-' = stdin)")
    return text


def _rows(ws, text: str, top: int | None) -> list[dict]:
    cfg = ws.config["match"]
    return match_modules(ws.registry.modules, text, cfg, cfg["top"] if top is None else top,
                         cfg["min_score"])


def build_context(ws, text: str, role: str | None, all_roles: bool, top: int | None) -> dict:
    modules, read, seen = [], [], set()
    for row in _rows(ws, text, top):
        _, shown = show_target(ws, row["module"], role, all_roles)
        modules.append({**row, "read": shown["read"], "code": shown["code"],
                        "code_globs": shown["code_globs"]})
        for r in shown["read"]:
            if r["path"] not in seen:
                seen.add(r["path"])
                read.append({"module": row["module"], **r})
    cfg = ws.config["match"]
    near = near_misses(ws.registry.modules, text, cfg, cfg["top"] if top is None else top,
                       cfg["min_score"])
    return {"task": text, "role": role, "all_roles": all_roles, "modules": modules, "read": read,
            "near_misses": near}


def _mentioned_paths(ws, text: str) -> list[str]:
    """Path-like tokens in free text, made safe before they ever reach a filesystem check:
    a relative mention that escapes the repo (`..`) is dropped; an absolute mention is
    rewritten to a repo-relative posix path when it resolves inside `ws.root`, and dropped
    otherwise — no absolute path survives to be joined onto `ws.root` downstream."""
    paths = set()
    for m in _PATHLIKE.finditer(text):
        raw = Path(m.group(1))
        if raw.is_absolute():
            try:
                rel = raw.resolve().relative_to(ws.root)
            except ValueError:
                continue  # outside the repo — dropped, like a ".." escape
            paths.add(rel.as_posix())
        else:
            posix = Path(os.path.normpath(raw)).as_posix()
            if not posix.startswith(".."):
                paths.add(posix)
    return sorted(paths)


def build_discover(ws, text: str | None, files: list[str], top: int | None,
                   missing: list[str] = ()) -> dict:
    """`text` None = no task: the change alone decides (no keyword scoring, `score` null).
    `missing` = the listed changed files that are not on disk."""
    by_module: dict[str, dict] = {}

    def slot(module: str) -> dict:
        return by_module.setdefault(module, {"module": module,
                                             "score": 0 if text is not None else None,
                                             "keywords": [], "sources": [],
                                             "touched_files": []})

    for row in _rows(ws, text, top) if text is not None else []:
        s = slot(row["module"])
        s.update(score=row["score"], keywords=row["keywords"])
        s["sources"].append("keyword")
    mentioned = _mentioned_paths(ws, text) if text is not None else []
    touched = map_files(ws, files)
    in_text = map_files(ws, mentioned)
    for source, mapping in (("diff", touched), ("path", in_text)):
        for module, hit in mapping["modules"].items():
            s = slot(module)
            if source not in s["sources"]:
                s["sources"].append(source)
            s["touched_files"] += [f for f in hit["files"] if f not in s["touched_files"]]
    targets_of: dict[str, list] = {f: [] for f in files}
    for module, hit in touched["modules"].items():
        for f in hit["files"]:
            targets_of[f].append(module)
    roles = [r for r in UPDATE_ROLES if r in enabled_roles(ws.config)]
    out = []
    for module in sorted(by_module, key=lambda m: (-(by_module[m]["score"] or 0), m)):
        s = by_module[module]
        s["usage"] = "modify" if s["touched_files"] else "reference"
        docs = []
        for role in (roles if s["usage"] == "modify" else [None]):
            _, shown = show_target(ws, module, role, False)
            docs += [r["path"] for r in shown["read"] if r["path"] not in docs]
        s["docs_to_read"] = docs
        s["docs_to_update"] = docs if s["usage"] == "modify" else []
        out.append(s)
    outside = sorted(set(touched["unmapped"]) | {f for f in in_text["unmapped"]
                                                  if (ws.root / f).exists()})
    usage = [m["usage"] for m in out]
    return {"task": text, "modules": out,
            "files": [{"path": f, "modules": sorted(targets_of[f])} for f in sorted(targets_of)],
            "files_outside_modules": outside, "missing_files": list(missing),
            "summary": {"total_modules": len(out), "by_usage": {
                "modify": usage.count("modify"), "reference": usage.count("reference")}}}


def register(sub, common) -> None:
    c = sub.add_parser("context", parents=[common],
                       help="files a role should read before planning a task")
    _task_args(c)
    c.add_argument("--role")
    c.add_argument("--all-roles", action="store_true")
    c.add_argument("--top", type=int)
    c.set_defaults(func=run_context)
    d = sub.add_parser("discover", parents=[common],
                       help="modules a change touches (modify/reference) and their docs",
                       description="Modules a change touches (modify/reference) and the docs "
                                   "to read and update. Give --task and/or --from-diff / "
                                   "--files; without a task there is no keyword scoring.")
    _task_args(d, required=False)
    src = d.add_mutually_exclusive_group()
    src.add_argument("--from-diff", metavar="A..B")
    src.add_argument("--files", nargs="+", metavar="PATH")
    d.add_argument("--top", type=int)
    d.set_defaults(func=run_discover)


def _task_args(p, required: bool = True) -> None:
    g = p.add_mutually_exclusive_group(required=required)
    g.add_argument("--task")
    g.add_argument("--task-file", type=Path)


def run_context(args) -> int:
    if args.top is not None and args.top < 0:
        raise UsageError("--top must be >= 0")
    ws = Workspace.from_args(args)
    roles = enabled_roles(ws.config)
    if args.role and args.role not in roles:
        raise UsageError(f"unknown role '{args.role}' (roles: {', '.join(roles)})")
    data = build_context(ws, task_text(args), args.role, args.all_roles, args.top)
    emit("context", data, args.json, _render_context)
    return EXIT_OK


def run_discover(args) -> int:
    if args.top is not None and args.top < 0:
        raise UsageError("--top must be >= 0")
    has_task = args.task is not None or args.task_file is not None
    if not has_task and not (args.from_diff or args.files):
        raise UsageError("give the task (--task TEXT or --task-file FILE), the change "
                         "(--from-diff A..B or --files PATH …), or both")
    ws = Workspace.from_args(args)
    files = changed_files(ws.root, diff_range=args.from_diff, files=args.files) \
        if (args.from_diff or args.files) else []
    data = build_discover(ws, task_text(args) if has_task else None, files, args.top,
                          missing_files(ws.root, files) if args.files else [])
    # --from-diff REF (no range) compares the working tree with REF: the text says so
    ref = args.from_diff if args.from_diff and ".." not in args.from_diff else None
    emit("discover", data, args.json, functools.partial(_render_discover, ref=ref))
    return EXIT_OK


def _render_context(d) -> None:
    if not d["modules"]:
        print("no module matched (try domain terms, or: modsys list)")
        for line in near_lines(d["near_misses"]):
            print(line)
    for m in d["modules"]:  # why each module matched: its keywords found in the task
        print(f"{m['module']:<28} {'matched':<30} {', '.join(m['keywords'])} "
              f"(score {m['score']})")
    for r in d["read"]:
        mark = "" if r["exists"] else "  (MISSING ON DISK)"
        print(f"{r['module']:<28} {r['label']:<30} {r['path']}{mark}")
    for m in d["modules"]:
        for c in m["code"] + m["code_globs"]:
            print(f"{m['module']:<28} {'code':<30} {c}")


def _render_discover(d, ref: str | None = None) -> None:
    """`ref`: the single ref of `--from-diff REF` — its `diff` source is labelled `diff
    (working tree vs REF)`."""
    for m in d["modules"]:
        score = f"score {m['score']:<3} " if m["score"] is not None else ""
        sources = [f"diff (working tree vs {ref})" if s == "diff" and ref else s
                   for s in m["sources"]]
        print(f"{m['usage']:<9} {m['module']:<30} {score}via {', '.join(sources)}")
        for doc in m["docs_to_update"]:
            print(f"          update {doc}")
    for f in d["files"]:
        print(f"file      {f['path']} -> {', '.join(f['modules']) or '(no module)'}")
    for f in d["files_outside_modules"]:
        print(f"outside   {f}")
    for f in d["missing_files"]:
        print(f"not on disk: {f} (typo? a deleted file still maps)")
