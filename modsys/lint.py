"""Registry lint. Codes: MS001-MS004, MS006-MS015 registry/field checks · MS020-MS022
keyword budgets and hygiene · MS030-MS032 doc budgets · MS040 component paths ·
MS052 a [[code_map]] rule whose `module` is not in the registry ·
with --changed: MS050 code changed but no doc of its module · MS051 frozen legacy snapshot
modified or deleted (report narrowed to the changed modules)."""
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from modsys.changes import changed_files, diff_names, map_files, target_names
from modsys.fields import value_matches
from modsys.output import EXIT_FINDINGS, EXIT_OK, UsageError, emit
from modsys.query import role_paths
from modsys.registry import as_dict, as_list, stub_head
from modsys.rules import edge_problems, status_problem
from modsys.workspace import Workspace

SEVERITY_RANK = {"info": 0, "warning": 1, "error": 2}
FAIL_ON = {"error": 2, "warning": 1, "never": 99}
_BACKTICK = re.compile(r"`([^`]+)`")


@dataclass
class Finding:
    code: str
    severity: str
    module: str
    message: str
    path: str | None = None


def _context_paths(cf) -> list[tuple[str, object]]:
    out = []
    for key, val in as_dict(cf).items():
        if isinstance(val, str):
            out.append((key, val))
        elif isinstance(val, dict):
            for sub, path in val.items():
                if isinstance(path, str):
                    out.append((f"{key}.{sub}", path))
                elif isinstance(path, list):
                    out += [(f"{key}.{sub}[]", p) for p in path]
        elif isinstance(val, list):
            out += [(f"{key}[]", p) for p in val]
    return out


def _role_docs(cf: dict) -> list:
    return [p for r in as_dict(cf.get("roles")) for p in role_paths(cf, r)]


def _docs(entry: dict, name: str):
    """(module label, universal doc, [role docs]) for a module and its children."""
    cf = as_dict(entry.get("context_files"))
    yield name, cf.get("universal"), _role_docs(cf)
    for child, sub in as_dict(entry.get("submodules")).items():
        if isinstance(sub, dict):
            ccf = as_dict(sub.get("context_files"))
            yield f"{name}/{child}", ccf.get("universal"), _role_docs(ccf)


def _objects(modules: dict):
    """Module entries that are objects; the others get MS013 in the entry pass."""
    return ((n, e) for n, e in modules.items() if isinstance(e, dict))


def _line_count(path: Path) -> int:
    with path.open(encoding="utf-8", errors="replace") as fh:
        return sum(1 for _ in fh)


def lint_registry(ws) -> list[Finding]:
    out: list[Finding] = []
    cfg, root, modules = ws.config, ws.root, ws.registry.modules
    statuses, relations = cfg["registry"]["statuses"], cfg["registry"]["relations"]
    budgets = cfg["budgets"]

    def add(code, severity, module, message, path=None):
        out.append(Finding(code, severity, module, message, path))

    def check_fields(label, entry, scope):
        for key, value in entry.items():
            fdef = ws.fields.get(key)
            if fdef is None:
                add("MS012", "warning", label, f"undeclared field '{key}' (declare [fields.{key}])")
            elif fdef.deprecated:
                add("MS011", "error", label, f"deprecated field '{key}': {fdef.deprecated}")
            elif not value_matches(fdef, value):
                add("MS013", "error", label,
                    f"field '{key}' does not match type {' | '.join(fdef.type)}")
        for fname, fdef in ws.fields.items():
            if scope in fdef.required and fname not in entry:
                add("MS001", "error", label, f"missing required field '{fname}'")

    def check_paths(label, cf, prefix):
        for key, p in _context_paths(cf):
            if not isinstance(p, str):
                add("MS004", "error", label, f"{prefix}.{key} is not a string: {p!r}")
            elif not (root / p).exists():
                add("MS004", "error", label, f"{prefix}.{key} path missing on disk", p)

    declared_roles = set(cfg.get("roles") or {})

    def check_roles(label, cf):
        roles = cf.get("roles") if isinstance(cf, dict) else None
        if roles is not None and not isinstance(roles, dict):
            add("MS013", "error", label, "field 'context_files.roles' does not match type object")
        for r in as_dict(roles):
            if r not in declared_roles:
                add("MS015", "warning", label,
                    f"role '{r}' is not configured (declare [roles.{r}] in config or a pack)")

    for name, entry in modules.items():
        if not isinstance(entry, dict):
            add("MS013", "error", name, "module entry is not an object")
            continue
        check_fields(name, entry, "module")
        if entry.get("name") and entry["name"] != name:
            add("MS002", "error", name, f"'name' field mismatch: {entry['name']!r}")
        problem = status_problem(entry.get("status"), statuses)
        if problem:
            add(problem[0], "error", name, problem[1])
        check_paths(name, entry.get("context_files"), "context_files")
        check_roles(name, entry.get("context_files"))
        for child, sub in as_dict(entry.get("submodules")).items():
            if not isinstance(sub, dict):
                add("MS013", "error", f"{name}/{child}", "submodule entry is not an object")
                continue
            check_fields(f"{name}/{child}", sub, "submodule")
            check_paths(f"{name}/{child}", sub.get("context_files"),
                        f"submodules.{child}.context_files")
            check_roles(f"{name}/{child}", sub.get("context_files"))
        for i, edge in enumerate(as_list(entry.get("related_modules"))):
            if not isinstance(edge, dict):  # the field type check reports MS013
                continue
            for code, message in edge_problems(edge, modules, relations):
                add(code, "error", name, f"related_modules[{i}]: {message}")

    mdir = root / cfg["paths"]["modules_dir"]
    whitelist = set(cfg["registry"]["dir_whitelist"])
    if mdir.is_dir():
        for d in sorted(mdir.iterdir()):
            if (d.is_dir() and d.name not in whitelist and d.name not in modules
                    and not stub_head(root, cfg, d.name)):
                add("MS014", "error", d.name, f"{cfg['paths']['modules_dir']}/{d.name}/ is "
                                              f"not registered and is not a pointer stub")

    shared: Counter = Counter()
    for name, entry in _objects(modules):
        kws = entry.get("keywords") if isinstance(entry.get("keywords"), list) else []
        if len(kws) > budgets["keywords_soft"] and "submodules" not in entry:
            add("MS020", "info", name, f"{len(kws)} keywords > soft budget {budgets['keywords_soft']}")
        for kw in {k.lower() for k in kws if isinstance(k, str)}:
            shared[kw] += 1
        subs = [(f"{name}/{c}", s) for c, s in as_dict(entry.get("submodules")).items()
                if isinstance(s, dict)]
        for label, holder in [(name, entry), *subs]:
            for kw in as_list(holder.get("keywords")):
                if isinstance(kw, str) and not kw.strip():
                    add("MS022", "warning", label, "empty keyword matches every task")
    for kw, count in sorted(shared.items()):
        if count >= budgets["keyword_shared_warn"]:
            add("MS021", "info", "*", f"keyword {kw!r} shared by {count} modules")

    heading = cfg["lint"]["component_table_heading"]
    for name, entry in _objects(modules):
        for label, universal, roles in _docs(entry, name):
            if isinstance(universal, str) and (root / universal).is_file():
                n = _line_count(root / universal)
                if n > budgets["module_doc_hard_stop"]:
                    add("MS031", "error", label, f"{n} lines > hard stop "
                        f"{budgets['module_doc_hard_stop']}: split into submodules", universal)
                elif n > budgets["module_doc_split_signal"]:
                    add("MS030", "warning", label, f"{n} lines > split signal "
                        f"{budgets['module_doc_split_signal']}", universal)
                in_section = False
                for line in (root / universal).read_text(encoding="utf-8",
                                                          errors="replace").splitlines():
                    if line.startswith("#"):
                        in_section = heading in line
                        continue
                    if not in_section or not line.startswith("|"):
                        continue
                    for token in _BACKTICK.findall(line):
                        if token.strip().startswith("@") or any(c in token for c in "<{["):
                            continue  # import alias or placeholder, not a repo path
                        candidate = re.split(r"[:#]", token.strip())[0]
                        if ("/" in candidate and " " not in candidate and "*" not in candidate
                                and "://" not in token and not (root / candidate).exists()):
                            add("MS040", "warning", label,
                                f"component path missing on disk: {candidate}", universal)
            for p in roles:
                if isinstance(p, str) and (root / p).is_file():
                    n = _line_count(root / p)
                    if n > budgets["role_doc_max"]:
                        add("MS032", "warning", label,
                            f"{n} lines > role budget {budgets['role_doc_max']}", p)

    targets = target_names(modules)
    for rule in as_list(cfg.get("code_map")):
        if isinstance(rule, dict) and "module" in rule and rule["module"] not in targets:
            add("MS052", "warning", "*", f"[[code_map]] '{rule.get('id')}': module "
                f"'{rule['module']}' is not a registry module or child; the rule maps nothing")
    return out


def drift_findings(ws, files: list[str], frozen_touched: list[str]) -> tuple[list, set]:
    """MS050/MS051 for a change set; returns (findings, changed top-level modules)."""
    mapping = map_files(ws, files)["modules"]
    mdir = ws.config["paths"]["modules_dir"].rstrip("/") + "/"

    def is_doc(f):  # a frozen snapshot never counts as a doc update
        return f.startswith(mdir) and not f.endswith(".legacy.md")

    docs_changed = {t for t, m in mapping.items() if any(is_doc(f) for f in m["files"])}
    out = []
    for target, m in mapping.items():
        code = [f for f in m["files"] if not f.startswith(mdir)]
        if code and target not in docs_changed and target.partition("/")[0] not in docs_changed:
            out.append(Finding("MS050", ws.config["lint"]["drift_severity"], target,
                               f"code changed ({len(code)} file(s)) but none of its docs"))
    for f in frozen_touched:
        module = f[len(mdir):].split("/")[0] if f.startswith(mdir) else "*"
        out.append(Finding("MS051", "error", module,
                           "frozen legacy snapshot modified or deleted", f))
    return out, {t.partition("/")[0] for t in mapping}


def register(sub, common) -> None:
    p = sub.add_parser("lint", parents=[common],
                       help="check registry, fields, doc budgets and component paths")
    p.add_argument("--fail-on", choices=sorted(FAIL_ON))
    p.add_argument("--changed", action="store_true",
                   help="drift check for a change set; report only the changed modules")
    p.add_argument("--base", default="HEAD",
                   help="--changed: compare the working tree (+ untracked) with this ref")
    p.set_defaults(func=run)


def run(args) -> int:
    ws = Workspace.from_args(args)
    fail_on = args.fail_on or ws.config["lint"]["fail_on"]
    if fail_on not in FAIL_ON:
        raise UsageError(f"[lint].fail_on must be one of {sorted(FAIL_ON)}, got {fail_on!r}")
    findings = lint_registry(ws)
    changed = None
    if args.changed:
        files = changed_files(ws.root, base=args.base)
        frozen = [f for f in diff_names(ws.root, args.base, "--diff-filter=MD")
                  if f.endswith(".legacy.md")]  # a renamed snapshot shows as D (--no-renames)
        drift, touched = drift_findings(ws, files, frozen)
        findings = [f for f in findings if f.module.partition("/")[0] in touched] + drift
        changed = {"base": args.base, "files": files, "modules": sorted(touched)}
    failed = any(SEVERITY_RANK[f.severity] >= FAIL_ON[fail_on] for f in findings)
    counts = Counter(f.severity for f in findings)
    data = {"findings": [asdict(f) for f in findings],
            "summary": {s: counts.get(s, 0) for s in ("error", "warning", "info")},
            "failed": failed}
    if changed is not None:
        data["changed"] = changed
    emit("lint", data, args.json, _render)
    return EXIT_FINDINGS if failed else EXIT_OK


def _render(d) -> None:
    for f in d["findings"]:
        where = f"  ({f['path']})" if f["path"] else ""
        print(f"{f['severity'].upper():<7} {f['code']} {f['module']}: {f['message']}{where}")
    s = d["summary"]
    print(f"\n{s['error']} error(s), {s['warning']} warning(s), {s['info']} info")
