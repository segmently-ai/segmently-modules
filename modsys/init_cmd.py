"""`modsys init`: set modsys up in a repository — a starter `<config_dir>/config.toml` (every
key commented out, with worked examples), an empty registry (the single file, or the
per-module index) and the `.gitignore` lines for the files the engine creates. Only what is
missing is created (an existing `.gitignore` gets only its missing lines); a second run
changes nothing. Root: `--root`, else the git top-level of the current directory, else the
current directory."""
import subprocess
from pathlib import Path

from modsys.changes import git_env
from modsys.config import REGISTRY_LAYOUTS, load_config
from modsys.layout import build_index
from modsys.merge import merge
from modsys.output import EXIT_OK, UsageError, emit
from modsys.store import atomic_write, serialize

_HEADER = '''\
## modsys team config — commit it. Every key is optional: uncomment what you need.
## Layers (later wins): engine defaults -> packs (.modsys/packs/<id>/pack.toml) -> this file
## -> .modsys/config.user.toml (personal, git-ignored). Tables merge key by key; arrays ADD to
## the lower layers (an override never removes a default). Every key: docs/configuration.md in
## the modsys repository.

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
## exclusive: a file matched by an exclusive rule is mapped ONLY by the exclusive rules that
## match it. Layered repos: a feature's repository file belongs to the feature, not to the shared
## persistence module whose broader rule also matches it.
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
'''
_VERBS = {"created": ("created", "would create"), "updated": ("updated", "would update"),
          "exists": ("exists", "exists")}


def starter_config(layout: str) -> str:
    """The starter team config: sets nothing except a non-default registry layout."""
    return _HEADER + _PATHS[layout] + _BODY


def register(sub, common) -> None:
    p = sub.add_parser("init", parents=[common],
                       help="set up modsys here: starter config, empty registry, .gitignore lines")
    p.add_argument("--layout", choices=REGISTRY_LAYOUTS,
                   help="registry layout for a new setup (default: the configured one, else single)")
    p.add_argument("--dry-run", action="store_true", help="report what would change, write nothing")
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
    config = load_config(config_dir)
    current = config["paths"]["registry_layout"]
    layout = requested or current
    registry = root / config["paths"]["registry"]  # path is the same in either layout
    if layout != current:
        if config_path.exists() or layout == "single" or registry.exists():
            raise UsageError(f"--layout {layout} conflicts with the configured registry_layout "
                             f"{current!r}; to convert an existing registry run `modsys index "
                             f"split` and set [paths] registry_layout in {config_path}")
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
    if not gitignore.exists():
        files.append((gitignore, "created", "\n".join(wanted) + "\n"))
    else:
        text = gitignore.read_text(encoding="utf-8")
        have = {line.strip() for line in text.splitlines()}
        missing = [line for line in wanted if line not in have]
        if missing:
            sep = "" if not text or text.endswith("\n") else "\n"
            files.append((gitignore, "updated", text + sep + "\n".join(missing) + "\n"))
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


def run(args) -> int:
    root = init_root(args.root)
    config_dir = Path(args.config_dir or root / ".modsys").resolve()
    layout, files = plan_init(root, config_dir, args.layout)
    if not args.dry_run:
        for path, status, text in files:
            if status == "created":
                _create(path, text)
            elif status == "updated":
                atomic_write(path, text)
    data = {"root": str(root), "layout": layout,
            "files": [{"path": _rel(root, p), "status": s} for p, s, _ in files],
            "dry_run": args.dry_run}
    emit("init", data, args.json, _render)
    return EXIT_OK


def _render(d) -> None:
    for f in d["files"]:
        print(f"{_VERBS[f['status']][d['dry_run']]:<13} {f['path']}")
    print(f"layout: {d['layout']}")
    print(f"next: modsys create NAME --description \"…\" --keyword … (5 or more); then wire "
          f"code with [[code_map]] in {d['files'][0]['path']} and check it with: modsys coverage")
