"""`modsys init`: set modsys up in a repository — a starter `<config_dir>/config.toml` (every
key commented out, with worked examples), an empty registry (the single file, or the
per-module index) and the `.gitignore` lines for the files the engine creates. Only what is
missing is created (an existing `.gitignore` gets only its missing lines, appended in the
file's own newline style and through a symlink to its target); a second run changes nothing.
Root: `--root`, else the git top-level of the current directory, else the current directory.

Actions (`modsys.init_flow`): `map` (the starter files that are missing, then preflight and map;
stops at gate 3), `confirm` (gate 3), `status`, `resume` — one envelope `modsys.init/1` each."""
import subprocess
from pathlib import Path

from modsys.changes import git_env
from modsys.config import REGISTRY_LAYOUTS, load_config
from modsys.layout import build_index
from modsys.merge import merge
from modsys.output import EXIT_FINDINGS, EXIT_OK, UsageError, emit
from modsys.store import serialize

_HEADER = '''\
## modsys team config — commit it. Every key is optional: uncomment what you need (only
## [packs] builtin is set). Layers (later wins): engine defaults -> built-in packs ([packs]
## builtin) -> packs (.modsys/packs/<id>/pack.toml) -> this file -> .modsys/config.user.toml
## (personal; add it to .gitignore). Tables merge key by key; arrays ADD to the lower layers (an
## override never removes a default). Every key: docs/configuration.md in the modsys repository.

'''
_PATHS = {
    "single": '''\
## Where the registry and the module docs live (defaults shown).
# [paths]
# modules_dir = "modules"
# registry = "modules/registry.json"
# registry_layout = "single"         # "per-module": one module.json per module + a generated index
''',
    "per-module": '''\
## Where the registry and the module docs live. Per-module layout: each module's entry is
## <modules_dir>/<name>/module.json; the registry file is a generated index (modsys index build).
[paths]
registry_layout = "per-module"
# modules_dir = "modules"
# registry = "modules/registry.json"
''',
}
_BODY = '''
## Vocabulary that lint and the registry writers check.
# [registry]
# statuses = ["active", "draft", "planned", "temporary"]
# relations = ["depends-on", "complements", "implemented-in", "shares-contract", "superseded-by"]

## `modsys create` answer limits.
# [create]
# min_keywords = 5                   # a child module needs 1
# description_min = 20
# description_max = 200

## Wire code to modules. sync, discover, lint --changed (MS050), coverage and the code_globs of
## show / context all use these rules. Globs: ** any path, * one segment, ? one character.
## Add a rule with `modsys code-map add` (it appends to this file), or write it by hand.
##
## A pattern's {module} is ONE path segment naming a top-level module: src/catalog/x.py -> catalog.
# [[code_map]]
# id = "src"
# pattern = "src/{module}/**"
##
## globs route files to one module, or to a child named "parent/child".
# [[code_map]]
# id = "catalog-search"
# module = "catalog/search"
# globs = ["src/catalog/search/**", "api/search_*.py"]
##
## exclusive: a file matched and routed by an exclusive rule is mapped ONLY by the exclusive
## rules that route it. Layered repos: a feature's repository file belongs to the feature, not to
## the shared persistence module whose broader rule also matches it.
# [[code_map]]
# id = "catalog-repository"
# module = "catalog"
# globs = ["app/db/repositories/catalog.py"]
# exclusive = true

## Or list code per module in the registry: declare a code_pointer field, then
##   modsys registry set catalog code_paths '["src/catalog/", "lib/isbn.py"]'
# [fields.code_paths]
# type = "string[]"
# kind = "code_pointer"
# scope = ["module", "submodule"]
# description = "Source files or directories of the module"

## Hooks that `modsys sync` runs after it maps a change (argv; ./ = relative to the root).
## A hook reads the event as JSON on stdin and may print {"proposals": [...], "messages": [...]}.
# [[hooks.post_sync]]
# id = "notify"
# run = ["python3", "./tools/notify_owners.py"]
# required = false

## `modsys coverage`: which files count (git-tracked + new, not ignored). The modules dir, this
## directory and dotfiles never count.
# [coverage]
# include = ["**"]
# exclude = ["docs/**"]

## `modsys ci`: one gate — lint, drift since base, coverage. Put the team's defaults here so CI
## runs a bare `modsys ci` (a flag still overrides any key).
# [ci]
# base = "origin/main"
# fail_on = "warning"
# coverage_fail_under = 80

## Packs: a team's roles, doc templates and agent skills (docs/writing-a-pack.md in the modsys
## repository). Create one with `modsys packs new ID --role NAME --skill NAME`; `modsys packs
## sync` copies the skills into these agents' skill directories when no --agent is given.
## builtin: the engine's own packs (docs/skills.md) — "core" = the module skills (scout,
## discover, research, sync, create, split, lint); "ui" = a designer role and a UI review skill;
## "qa" = an acceptance-baseline role and acceptance-criteria skills.
[packs]
builtin = ["core"]                   # or ["core", "ui", "qa"]
# agents = ["claude", "codex"]
'''
_VERBS = {"created": ("created", "would create"), "updated": ("updated", "would update"),
          "exists": ("exists", "exists")}


def starter_config(layout: str) -> str:
    """The starter team config: enables the built-in `core` pack and sets nothing else except a
    non-default registry layout."""
    return _HEADER + _PATHS[layout] + _BODY


ACTIONS = ("map", "confirm", "status", "resume")


def register(sub, common) -> None:
    p = sub.add_parser("init", parents=[common],
                       help="set up modsys here: starter config, empty registry, .gitignore lines "
                            "(map|confirm|status|resume: start from existing code)",
                       description="Without an action: the starter config, an empty registry and "
                                   "the .gitignore lines. map: those, then preflight and map of "
                                   "the existing code into <config_dir>/init/proposal.json "
                                   "(stops at gate 3; refused when the registry has modules). "
                                   "confirm: gate 3 — validate the edited proposal and freeze "
                                   "it. status: the phases and the next step. resume: re-run "
                                   "an interrupted phase.")
    p.add_argument("action", nargs="?", metavar="ACTION",
                   help="map, confirm, status or resume (none: the starter files only)")
    p.add_argument("--layout", choices=REGISTRY_LAYOUTS,
                   help="registry layout for a new setup (default: the configured one, else single)")
    p.add_argument("--dry-run", action="store_true", help="report what would change, write nothing")
    p.add_argument("--restart", action="store_true",
                   help="map: clear <config_dir>/init/ and start over")
    p.set_defaults(func=run)


def init_root(arg) -> Path:
    """`--root`, else the git top-level of the current directory, else the current directory
    (not `find_root`: a fresh repository has no marker yet)."""
    if arg is not None:
        root = Path(arg).resolve()
        if not root.is_dir():
            raise UsageError(f"--root {arg} is not a directory")
        return root
    cwd = Path.cwd().resolve()
    try:
        proc = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
                              capture_output=True, encoding="utf-8", errors="replace",
                              env=git_env())
    except OSError:  # git is not installed
        return cwd
    top = proc.stdout.strip()
    return Path(top).resolve() if proc.returncode == 0 and top else cwd


def plan_init(root: Path, config_dir: Path, requested: str | None) -> tuple[str, list]:
    """(layout, [(path, status, new text or None)]); writes nothing."""
    config_path = config_dir / "config.toml"
    config = load_config(config_dir, root)
    current = config["paths"]["registry_layout"]
    layout = requested or current
    registry = root / config["paths"]["registry"]  # path is the same in either layout
    if layout != current:
        if config_path.exists() or layout == "single" or registry.exists():
            if layout == "per-module":
                how = (f"to convert the existing registry run `modsys index split`, then set "
                       f"[paths] registry_layout = \"per-module\" in {config_path}")
            else:  # the per-module index already holds every entry: it becomes the registry
                how = (f"to go back to one registry file run `modsys index build` (the index "
                       f"then holds every module entry), then set [paths] registry_layout = "
                       f"\"single\" in {config_path}; the <module>/"
                       f"{config['paths']['module_entry']} files are no longer read")
            raise UsageError(f"--layout {layout} conflicts with the configured registry_layout "
                             f"{current!r}; {how}")
        config = merge(config, {"paths": {"registry_layout": layout}})
    files = [(config_path, "exists", None) if config_path.exists()
             else (config_path, "created", starter_config(layout))]
    if registry.exists():
        files.append((registry, "exists", None))
    else:
        text = (build_index(root, config)[0] if layout == "per-module"
                else serialize({"modules": {}}))
        files.append((registry, "created", text))
    gitignore = root / ".gitignore"
    wanted = [f"{config['paths']['registry']}.lock",
              config["paths"]["proposals_dir"].rstrip("/") + "/"]
    try:  # the init work directory (`init map`), when the config dir lies inside the root
        wanted.append((config_dir / "init").relative_to(root).as_posix() + "/")
    except ValueError:
        pass
    if not gitignore.exists():
        files.append((gitignore, "created", "\n".join(wanted) + "\n"))
    else:
        text = gitignore.read_bytes().decode("utf-8")
        have = {line.strip() for line in text.splitlines()}
        missing = [line for line in wanted if line not in have]
        if missing:  # "updated" carries only the text to APPEND, in the file's newline style
            nl = "\r\n" if "\r\n" in text else "\n"
            sep = "" if not text or text.endswith("\n") else nl
            files.append((gitignore, "updated", sep + nl.join(missing) + nl))
        else:
            files.append((gitignore, "exists", None))
    return layout, files


def _create(path: Path, text: str) -> None:
    """Create a NEW file (never replace one another process created in the meantime)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "x", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    except FileExistsError:
        raise UsageError(f"{path} appeared while init was running; run init again") from None


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def starter(root: Path, config_dir: Path, layout: str | None,
            dry_run: bool) -> tuple[str, list]:
    """Plain `init`: create what is missing (unless `dry_run`); (layout, [{path, status}])."""
    layout, files = plan_init(root, config_dir, layout)
    if not dry_run:
        for path, status, text in files:
            if status == "created":
                _create(path, text)
            elif status == "updated":
                with open(path, "ab") as fh:  # append: keeps the bytes, mode and a symlink
                    fh.write(text.encode("utf-8"))
    return layout, [{"path": _rel(root, p), "status": s} for p, s, _ in files]


def _check_flags(args) -> None:
    action = args.action
    if action is not None and action not in ACTIONS:
        raise UsageError(f"unknown init action {action!r} (actions: {', '.join(ACTIONS)})")
    if args.restart and action != "map":
        raise UsageError("--restart works with map only (modsys init map --restart)")
    if args.layout and action not in (None, "map"):
        raise UsageError(f"--layout works with plain init and init map, not init {action}")
    if args.dry_run and action in ("status", "resume"):
        raise UsageError(f"init {action} takes no --dry-run (it never writes)"
                         if action == "status" else "init resume takes no --dry-run")


def run(args) -> int:
    _check_flags(args)
    root = init_root(args.root)
    config_dir = Path(args.config_dir or root / ".modsys").resolve()
    if args.action is not None:
        return run_action(args, root, config_dir)
    layout, files = starter(root, config_dir, args.layout, args.dry_run)
    data = {"root": str(root), "layout": layout, "files": files, "dry_run": args.dry_run}
    emit("init", data, args.json, _render)
    return EXIT_OK


def run_action(args, root: Path, config_dir: Path) -> int:
    from modsys.init_flow import NO_P4, InitFlow  # the flow imports the phases
    flow = InitFlow(root, config_dir, load_config(config_dir, root))
    work = flow.rel(flow.work)
    if args.action == "map":
        flow.check_map(args.restart)
        _, files = starter(root, config_dir, args.layout, args.dry_run)
        if not args.dry_run:  # the starter config may have changed what the phases read
            flow = InitFlow(root, config_dir, load_config(config_dir, root))
        result = flow.map(args.restart, args.dry_run)
        proposal, state = result["proposal"], result["state"]
        data = {"action": "map", "root": str(root), "files": files,
                "preflight": f"{work}/preflight.json", "proposal": f"{work}/proposal.json",
                "candidates": [c["name"] for c in proposal["candidates"]],
                "unassigned": len(proposal["unassigned"]), "hints": len(proposal["hints"]),
                "phase": state["phase"] if state else None,
                "next": flow.next_step(state, work) if state else
                f"run modsys init map without --dry-run to write {work}/",
                "dry_run": args.dry_run}
        emit("init", data, args.json, _render_map)
        return EXIT_OK
    if args.action == "confirm":
        result = flow.confirm(args.dry_run)
        data = {"action": "confirm", "confirmed": f"{work}/confirmed.json", **result,
                "dry_run": args.dry_run}
        emit("init", data, args.json, _render_confirm)
        return EXIT_OK
    if args.action == "status":
        state = flow.load_state()
        data = {"action": "status", "phase": state["phase"] if state else None,
                "phases": {p: s["status"] for p, s in state["phases"].items()} if state else {},
                "next": flow.next_step(state, work)}
        emit("init", data, args.json, _render_status)
        return EXIT_OK
    state = flow.load_state()
    if state is not None and state["phases"]["gate-map"]["status"] == "done":
        data = {"action": "resume", "ran": [], "phase": state["phase"],
                "next": flow.next_step(state, work), "message": NO_P4}
        emit("init", data, args.json, _render_resume)
        return EXIT_FINDINGS
    state, ran = flow.resume()
    data = {"action": "resume", "ran": ran, "phase": state["phase"],
            "next": flow.next_step(state, work), "message": None}
    emit("init", data, args.json, _render_resume)
    return EXIT_OK


def _render_map(d) -> None:
    for f in d["files"]:
        print(f"{_VERBS[f['status']][d['dry_run']]:<13} {f['path']}")
    verb = "would write" if d["dry_run"] else "wrote"
    print(f"{verb:<13} {d['preflight']}")
    print(f"{verb:<13} {d['proposal']}")
    print(f"candidates    {', '.join(d['candidates']) or '(none)'}")
    print(f"unassigned    {d['unassigned']} code file(s); hints {d['hints']}")
    print(f"next: {d['next']}")


def _render_confirm(d) -> None:
    verb = {"confirmed": "confirmed", "updated": "updated", "unchanged": "unchanged"}[d["status"]]
    if d["dry_run"] and d["status"] != "unchanged":
        verb = "would confirm"
    print(f"{verb:<13} {d['confirmed']} ({len(d['included'])} included, {len(d['excluded'])} "
          f"excluded)")
    print(f"modules       {', '.join(d['included'])}")


def _render_status(d) -> None:
    if not d["phases"]:
        print("no init state")
    for phase, status in d["phases"].items():
        print(f"{phase:<10} {status}")
    print(f"next: {d['next']}")


def _render_resume(d) -> None:
    print(f"ran           {', '.join(d['ran'])}" if d["ran"] else "nothing to run")
    if d["message"]:
        print(d["message"])
    print(f"next: {d['next']}")


def _render(d) -> None:
    print(f"root: {d['root']}")
    for f in d["files"]:
        print(f"{_VERBS[f['status']][d['dry_run']]:<13} {f['path']}")
    print(f"layout: {d['layout']}")
    print(f"next: modsys create NAME --description \"…\" --keywords \"a, b, c, d, e\" (5 or "
          f"more); then wire code with modsys code-map add ID --pattern 'src/{{module}}/**' "
          f"(rules land in {d['files'][0]['path']}) and check it with: modsys coverage")
