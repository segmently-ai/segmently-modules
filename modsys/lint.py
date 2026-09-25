import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from modsys.fields import value_matches
from modsys.output import EXIT_FINDINGS, EXIT_OK, UsageError, emit
from modsys.query import role_paths
from modsys.registry import stub_head
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
    for key, val in (cf or {}).items() if isinstance(cf, dict) else []:
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


def _docs(entry: dict, name: str):
    """(module label, universal doc, [role docs]) for a module and its children."""
    cf = entry.get("context_files") or {}
    yield name, cf.get("universal"), [p for r in (cf.get("roles") or {}) for p in role_paths(cf, r)]
    for child, sub in (entry.get("submodules") or {}).items():
        ccf = sub.get("context_files") or {}
        yield (f"{name}/{child}", ccf.get("universal"),
               [p for r in (ccf.get("roles") or {}) for p in role_paths(ccf, r)])


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

    for name, entry in modules.items():
        check_fields(name, entry, "module")
        if entry.get("name") and entry["name"] != name:
            add("MS002", "error", name, f"'name' field mismatch: {entry['name']!r}")
        if entry.get("status") is not None and entry["status"] not in statuses:
            add("MS003", "error", name, f"status {entry['status']!r} not in {statuses}")
        check_paths(name, entry.get("context_files"), "context_files")
        for child, sub in (entry.get("submodules") or {}).items():
            check_fields(f"{name}/{child}", sub, "submodule")
            check_paths(f"{name}/{child}", sub.get("context_files"),
                        f"submodules.{child}.context_files")
        for i, edge in enumerate(entry.get("related_modules") or []):
            where = f"related_modules[{i}]"
            if edge.get("relation") not in relations:
                add("MS006", "error", name, f"{where}: relation {edge.get('relation')!r} "
                                            f"not in {relations}")
            if not edge.get("description"):
                add("MS007", "error", name, f"{where}: missing description")
            target = edge.get("module")
            if not isinstance(target, str) or not target:
                add("MS008", "error", name, f"{where}: missing module target")
                continue
            parent, _, child = target.partition("/")
            if parent not in modules:
                add("MS009", "error", name, f"{where}: target '{parent}' not in registry")
            elif child and child not in (modules[parent].get("submodules") or {}):
                add("MS010", "error", name, f"{where}: '{child}' is not a submodule of '{parent}'")

    mdir = root / cfg["paths"]["modules_dir"]
    whitelist = set(cfg["registry"]["dir_whitelist"])
    if mdir.is_dir():
        for d in sorted(mdir.iterdir()):
            if (d.is_dir() and d.name not in whitelist and d.name not in modules
                    and not stub_head(root, cfg, d.name)):
                add("MS014", "error", d.name, f"{cfg['paths']['modules_dir']}/{d.name}/ is "
                                              f"not registered and is not a pointer stub")

    shared: Counter = Counter()
    for name, entry in modules.items():
        kws = entry.get("keywords") if isinstance(entry.get("keywords"), list) else []
        if len(kws) > budgets["keywords_soft"] and "submodules" not in entry:
            add("MS020", "info", name, f"{len(kws)} keywords > soft budget {budgets['keywords_soft']}")
        for kw in {k.lower() for k in kws if isinstance(k, str)}:
            shared[kw] += 1
    for kw, count in sorted(shared.items()):
        if count >= budgets["keyword_shared_warn"]:
            add("MS021", "info", "*", f"keyword {kw!r} shared by {count} modules")

    heading = cfg["lint"]["component_table_heading"]
    for name, entry in modules.items():
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
    return out


def register(sub, common) -> None:
    p = sub.add_parser("lint", parents=[common],
                       help="check registry, fields, doc budgets and component paths")
    p.add_argument("--fail-on", choices=sorted(FAIL_ON))
    p.set_defaults(func=run)


def run(args) -> int:
    ws = Workspace.from_args(args)
    fail_on = args.fail_on or ws.config["lint"]["fail_on"]
    if fail_on not in FAIL_ON:
        raise UsageError(f"[lint].fail_on must be one of {sorted(FAIL_ON)}, got {fail_on!r}")
    findings = lint_registry(ws)
    failed = any(SEVERITY_RANK[f.severity] >= FAIL_ON[fail_on] for f in findings)
    counts = Counter(f.severity for f in findings)
    data = {"findings": [asdict(f) for f in findings],
            "summary": {s: counts.get(s, 0) for s in ("error", "warning", "info")},
            "failed": failed}
    emit("lint", data, args.json, _render)
    return EXIT_FINDINGS if failed else EXIT_OK


def _render(d) -> None:
    for f in d["findings"]:
        where = f"  ({f['path']})" if f["path"] else ""
        print(f"{f['severity'].upper():<7} {f['code']} {f['module']}: {f['message']}{where}")
    s = d["summary"]
    print(f"\n{s['error']} error(s), {s['warning']} warning(s), {s['info']} info")
