"""Registry lint. Codes: MS001-MS004, MS006-MS015 registry/field checks · MS020-MS022
keyword budgets and hygiene · MS030-MS032 doc budgets · MS040 component paths ·
MS052 a [[code_map]] rule whose `module` is not in the registry · MS053 two [[code_map]] rules
route one file to two different modules · MS060-MS062, MS064, MS065 pack checks (unknown
pack.toml keys, role templates, skills agents cannot load, skills reading unconfigured roles,
shadowed skill ids) · MS063 ejected skills behind their pack · MS066 a repository pack that
replaces a built-in pack (info) ·
with --changed: MS050 code changed but no doc of its module · MS051 frozen legacy snapshot
modified or deleted (report narrowed to the changed modules)."""
import re
from collections import Counter
from dataclasses import asdict, dataclass
from itertools import combinations
from pathlib import Path

from modsys.changes import (changed_files, code_map_routes, diff_names, map_files, repo_files,
                            target_names, work_tree_error)
from modsys.config import (BUILTIN_PACKS, PACK_META_KEYS, ROLE_SCHEMA, discover_packs,
                           enabled_roles)
from modsys.fields import value_matches
from modsys.output import EXIT_FINDINGS, EXIT_OK, UsageError, emit
from modsys.query import role_paths
from modsys.registry import as_dict, as_list, stub_head
from modsys.rules import edge_problems, status_problem
from modsys.skills import (EJECTED, SKILL_KEYS, behind_reason, declared_skills, ejected_copies,
                           ejected_symlinks, inside, pack_skills, read_ejected, source_problem)
from modsys.workspace import Workspace

SEVERITY_RANK = {"info": 0, "warning": 1, "error": 2}
FAIL_ON = {"error": 2, "warning": 1, "never": 99}
_BACKTICK = re.compile(r"`([^`]+)`")
# the top-level keys of a pack.toml besides its meta keys: every config section the engine reads
PACK_SECTIONS = ("paths", "registry", "budgets", "match", "lint", "create", "coverage", "ci",
                 "packs", "roles", "fields", "code_map", "hooks", "schema_version")


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


def lint_registry(ws, overlap: bool = True) -> list[Finding]:
    """Every registry, doc and config finding. `overlap=False` skips MS053, the one check
    that lists every repository file — `lint --changed` would drop it anyway (module `*`)."""
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
    out += pack_findings(ws)
    if overlap:
        out += overlap_findings(ws)
    return out


def pack_findings(ws) -> list[Finding]:
    """The pack checks (config-level, module `*`, `path` = the offending file): MS060 unknown
    `pack.toml` keys, MS061 role templates that are missing or outside the pack, MS062 skills
    agents cannot load (a pack's, or an ejected copy's), MS063 ejected skills whose pack moved
    on (or dropped them), MS064 `reads_roles` naming a role no layer enables, MS065 a skill id
    shadowed by a higher-precedence pack, MS066 (info) a repository pack whose id is a built-in
    pack's — it replaces that pack, enabled or not."""
    out: list[Finding] = []
    for pack in discover_packs(ws.config_dir):
        data, toml, pack_dir, pid = pack["data"], ws.rel(pack["path"]), pack["path"].parent, \
            pack["id"]
        unknown = [(k, "at the top level") for k in data
                   if k not in PACK_META_KEYS and k not in PACK_SECTIONS]
        for table, schema in (("roles", ROLE_SCHEMA), ("skills", SKILL_KEYS)):
            for name, spec in as_dict(data.get(table)).items():
                unknown += [(k, f"in [{table}.{name}]") for k in as_dict(spec) if k not in schema]
        out += [Finding("MS060", "warning", "*", f"pack '{pid}': unknown key '{key}' {where}",
                        toml) for key, where in unknown]
        if not pack["builtin"] and pid in BUILTIN_PACKS:
            out.append(Finding("MS066", "info", "*", f"repository pack '{pid}' replaces the "
                               f"built-in pack '{pid}'", toml))
        for role, spec in as_dict(data.get("roles")).items():
            template = as_dict(spec).get("template")
            if not isinstance(template, str):
                continue
            path = pack_dir / template
            if not inside(path, pack_dir):
                out.append(Finding("MS061", "error", "*", f"pack '{pid}': role '{role}' template "
                                   f"'{template}' is outside the pack", toml))
            elif not path.is_file():
                out.append(Finding("MS061", "error", "*", f"pack '{pid}': role '{role}' template "
                                   f"'{template}' does not exist", ws.rel(path)))
    configured, enabled = set(ws.config.get("roles") or {}), set(enabled_roles(ws.config))
    for skill in declared_skills(ws.config_dir):
        toml = ws.rel(skill.pack_toml)
        problem = source_problem(skill.source, skill.id, skill.pack_dir)
        if problem:
            where = (toml if problem.startswith("the path") else
                     ws.rel(skill.source / "SKILL.md") if problem.startswith("SKILL.md") else
                     ws.rel(skill.source))
            out.append(Finding("MS062", "error", "*", f"skill '{skill.id}' of pack "
                               f"'{skill.pack}' is not loadable by agents: {problem}", where))
        for role in skill.reads_roles:
            if role not in enabled:
                why = "is disabled" if role in configured else "no layer configures"
                out.append(Finding("MS064", "warning", "*", f"skill '{skill.id}' of pack "
                                   f"'{skill.pack}' reads role '{role}', which {why}", toml))
        if skill.shadowed_by:
            out.append(Finding("MS065", "warning", "*", f"skill '{skill.id}' of pack "
                               f"'{skill.pack}' is shadowed by pack '{skill.shadowed_by}' "
                               f"(higher precedence); rename one", toml))
    skills = pack_skills(ws.config_dir)
    for sid, link in ejected_symlinks(ws.config_dir).items():  # the target is never read
        out.append(Finding("MS063", "warning", "*", f"'{ws.rel(link)}' is a symlink, not an "
                           f"ejected copy of skill '{sid}' — packs sync and eject treat it as "
                           f"in the way; remove it (modsys eject {sid} makes a real copy)",
                           ws.rel(link)))
    for sid, copy in ejected_copies(ws.config_dir).items():
        record, where = read_ejected(copy), ws.rel(copy)
        if record is None:
            out.append(Finding("MS063", "warning", "*", f"ejected skill '{sid}' has no valid "
                               f"{EJECTED} record — eject it again or restore the file", where))
            continue
        problem = source_problem(copy, sid)  # the copy `packs sync` materializes instead
        if problem:
            out.append(Finding("MS062", "error", "*", f"ejected skill '{sid}' ({where}) is not "
                               f"loadable by agents: {problem}",
                               ws.rel(copy / "SKILL.md") if problem.startswith("SKILL.md")
                               else where))
        if sid not in skills:
            out.append(Finding("MS063", "info", "*", f"ejected skill '{sid}': pack "
                               f"'{record['pack']}' no longer declares it; the ejected copy is "
                               f"its only source", where))
            continue
        skill = skills[sid]
        try:
            reason = behind_reason(skill, record)
        except OSError as e:  # an unreadable pack file: say so, never crash (P4B-AC-003)
            unreadable = ws.rel(e.filename or skill.source)
            out.append(Finding("MS063", "warning", "*", f"ejected skill '{sid}': cannot read "
                               f"{unreadable}: {e.strerror or e} — cannot tell whether pack "
                               f"'{skill.pack}' moved on since the eject", unreadable))
            continue
        if reason:
            out.append(Finding("MS063", "warning", "*", f"ejected skill '{sid}' is behind pack "
                               f"'{skill.pack}' ({reason}) — review: modsys eject {sid} --diff",
                               where))
    return out


def _related(a: str, b: str) -> bool:
    """The same target, or one is the other's parent (`catalog` and `catalog/search`)."""
    return a == b or a == b.partition("/")[0] or b == a.partition("/")[0]


def overlap_findings(ws) -> list[Finding]:
    """MS053 (config-level, module `*`): per pair of `[[code_map]]` rules, the repository files
    (git-tracked + new, no coverage filters) they route — after `exclusive` precedence — to two
    targets where neither is the other's parent. Only the rules route files here (docs and
    `code_pointer` sources are never evaluated). Skipped silently with fewer than two rules
    (no pair can overlap) and outside a git work tree."""
    rules = [r for r in as_list(ws.config.get("code_map")) if isinstance(r, dict) and "id" in r]
    if len(rules) < 2 or work_tree_error(ws.root):
        return []
    per_file: dict[str, dict] = {}  # path -> {rule id: target}; repo_files order = sorted
    for path, target, rule_id in code_map_routes(ws, repo_files(ws.root)):
        per_file.setdefault(path, {})[rule_id] = target
    pairs: dict[tuple, list] = {}  # (rule a, rule b) -> [files, first path, target a, target b]
    for path, by_rule in per_file.items():
        for a, b in combinations(sorted(by_rule), 2):
            if not _related(by_rule[a], by_rule[b]):
                pairs.setdefault((a, b), [0, path, by_rule[a], by_rule[b]])[0] += 1
    severity = ws.config["lint"]["overlap_severity"]
    return [Finding("MS053", severity, "*",
                    f"[[code_map]] '{a}' (-> {ta}) and '{b}' (-> {tb}) both map {n} file(s), "
                    f"e.g. {path} — mark the more specific rule exclusive = true or narrow "
                    f"its globs")
            for (a, b), (n, path, ta, tb) in sorted(pairs.items())]


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


def drift_report(ws, base: str, findings: list[Finding]) -> tuple[list[Finding], dict]:
    """`lint --changed`: `findings` narrowed to the top-level modules the change since `base`
    touches, plus MS050/MS051; and the change as {base, files, modules}."""
    files = changed_files(ws.root, base=base)
    frozen = [f for f in diff_names(ws.root, base, "--diff-filter=MD")
              if f.endswith(".legacy.md")]  # a renamed snapshot shows as D (--no-renames)
    drift, touched = drift_findings(ws, files, frozen)
    narrowed = [f for f in findings if f.module.partition("/")[0] in touched] + drift
    return narrowed, {"base": base, "files": files, "modules": sorted(touched)}


def failing(findings: list[Finding], fail_on: str) -> bool:
    return any(SEVERITY_RANK[f.severity] >= FAIL_ON[fail_on] for f in findings)


def severity_counts(findings: list[Finding]) -> dict:
    counts = Counter(f.severity for f in findings)
    return {s: counts.get(s, 0) for s in ("error", "warning", "info")}


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
    findings = lint_registry(ws, overlap=not args.changed)  # --changed never reports MS053
    changed = None
    if args.changed:
        findings, changed = drift_report(ws, args.base, findings)
    failed = failing(findings, fail_on)
    data = {"findings": [asdict(f) for f in findings], "summary": severity_counts(findings),
            "failed": failed}
    if changed is not None:
        data["changed"] = changed
    emit("lint", data, args.json, _render)
    return EXIT_FINDINGS if failed else EXIT_OK


def _render(d) -> None:
    for f in d["findings"]:
        where = f"  ({f['path']})" if f["path"] else ""
        print(f"{f['severity'].upper():<7} {f['code']} {f['module']}: {f['message']}{where}")
    if d["findings"]:
        print()
    s = d["summary"]
    print(f"{s['error']} error(s), {s['warning']} warning(s), {s['info']} info")
