"""`modsys packs`: create, list and sync packs — a team's roles, role templates and agent
skills.

  new ID [--role NAME]… [--skill NAME]… [--description TEXT] [--priority N]
        scaffold `<config_dir>/packs/ID/`: `pack.toml`, a role template per `--role` and a
        `SKILL.md` per `--skill` (reading every `--role`); every refusal writes nothing
  list  the active packs in precedence order (repository packs, then the enabled built-in
        packs), with their roles and skills
  sync [--agent claude|codex]… [--check]
        copy every pack skill into the agents' skill directories (`skill_sync`); agents = the
        flags, else `[packs] agents`"""
import functools
import os
import re
import shutil
import string
from importlib import resources
from pathlib import Path

from modsys.code_map_cmd import _toml_string
from modsys.config import BUILTIN_PACKS, DEFAULT_PACK_PRIORITY, core_defaults, discover_packs
from modsys.create import NAME, article
from modsys.output import EXIT_FINDINGS, EXIT_OK, UsageError, emit
from modsys.skill_sync import (NO_RECORD, STATUSES, apply_plan, conflict_kind, plan_sync, row,
                               sync_command)
from modsys.skills import (AGENT_DIRS, NAME_RULE, declared_skills, ejected_dir,
                           read_front_matter, skill_id_ok)
from modsys.workspace import Workspace

ACTIONS = ("new", "list", "sync")
NEW_FLAGS = ("--role", "--skill", "--description", "--priority")
SYNC_FLAGS = ("--agent", "--check")
ROLE_NAME = re.compile(r"^[a-z][a-z0-9_]*(-[a-z0-9]+)*$")
FIRST_ROLE_ORDER, ROLE_ORDER_STEP = 100, 10
PACK_DESCRIPTION = "Describe what this pack adds: its roles and skills."


def register(sub, common) -> None:
    p = sub.add_parser("packs", parents=[common],
                       help="create, list or sync packs: a team's roles, templates and "
                            "agent skills",
                       description="new ID: scaffold <config_dir>/packs/ID/ — pack.toml, "
                                   "roles/<role>.md per --role, skills/<skill>/SKILL.md per "
                                   "--skill (each skill reads every --role). list: the "
                                   "installed packs in precedence order with their roles and "
                                   "skills. sync: copy every pack skill into the agents' skill "
                                   "directories (claude: .claude/skills/, codex: "
                                   ".agents/skills/); a locally edited or foreign copy is a "
                                   "conflict and is never overwritten.")
    p.add_argument("action", choices=ACTIONS)
    p.add_argument("name", nargs="?", metavar="ID",
                   help="new: the pack id (lowercase words joined by '-', max 48)")
    p.add_argument("--role", action="append", dest="roles", metavar="NAME",
                   help="new: a role the pack adds, with its template roles/NAME.md "
                        "(repeatable)")
    p.add_argument("--skill", action="append", dest="skills", metavar="NAME",
                   help="new: an agent skill the pack adds, skills/NAME/SKILL.md "
                        "(repeatable)")
    p.add_argument("--description", help="new: one line — what the pack adds")
    p.add_argument("--priority", type=int,
                   help=f"new: precedence among packs (default {DEFAULT_PACK_PRIORITY}; a "
                        f"lower number wins)")
    p.add_argument("--agent", action="append", dest="agents", metavar="claude|codex",
                   help="sync: an agent to write skills for (repeatable; default: [packs] "
                        "agents)")
    p.add_argument("--check", action="store_true",
                   help="sync: write nothing; exit 1 unless every skill is unchanged (CI)")
    p.add_argument("--dry-run", action="store_true",
                   help="new, sync: report what would be written, write nothing")
    p.set_defaults(func=run)


def _scaffold(name: str) -> str:
    return resources.files("modsys").joinpath(f"defaults/scaffold/{name}").read_text(
        encoding="utf-8")


def _and(words: list[str]) -> str:
    return words[0] if len(words) == 1 else f"{', '.join(words[:-1])} and {words[-1]}"


def _check_names(pack_id: str, roles: list[str], skills: list[str]) -> None:
    if not NAME.fullmatch(pack_id) or len(pack_id) > 48:
        raise UsageError(f"pack id {pack_id!r}: use lowercase words joined by '-' (max 48)")
    for flag, values in (("--role", roles), ("--skill", skills)):
        repeated = sorted({v for v in values if values.count(v) > 1})
        if repeated:
            raise UsageError(f"{flag} {repeated[0]!r} is repeated")
    for role in roles:
        if not ROLE_NAME.fullmatch(role) or len(role) > 48:
            raise UsageError(f"role {role!r}: use lowercase letters, digits and '_', words "
                             f"joined by '-', starting with a letter (max 48)")
    for skill in skills:
        if not skill_id_ok(skill):
            raise UsageError(f"skill {skill!r}: {NAME_RULE} (the Agent Skills name rule)")


def _check_free(ws, pack_id: str, pack_dir: Path, roles: list[str], skills: list[str]) -> None:
    if pack_id in BUILTIN_PACKS:
        raise UsageError(f"pack id '{pack_id}' is reserved for the engine's built-in pack — "
                         f"enable it: [packs] builtin = [\"{pack_id}\"]")
    if os.path.lexists(pack_dir):
        raise UsageError(f"{ws.rel(pack_dir)}/ already exists")
    for pack in discover_packs(ws.config_dir):
        if pack["id"] == pack_id:
            raise UsageError(f"pack id '{pack_id}' is already installed "
                             f"({ws.rel(pack['path'])})")
    configured, engine = ws.config.get("roles") or {}, core_defaults().get("roles") or {}
    for role in roles:
        if role in configured:
            owner = configured[role].get("owner")
            where = ("engine defaults" if role in engine else f"pack '{owner}'" if owner
                     else "the team config")
            raise UsageError(f"role '{role}' is already configured ({where}) — to change its "
                             f"doc template: modsys templates override roles/{role}.md")
    declared = {}
    for skill in declared_skills(ws.config_dir):
        declared.setdefault(skill.id, skill)
    for skill in skills:
        if skill in declared:
            raise UsageError(f"skill '{skill}' is already declared by pack "
                             f"'{declared[skill].pack}' ({ws.rel(declared[skill].pack_toml)})")


def scaffold_files(pack_id: str, roles: list[str], skills: list[str], description: str | None,
                   priority: int | None) -> dict[str, str]:
    """{path inside the pack: text} of a new pack, in writing order."""
    tables = ""
    for n, role in enumerate(roles):
        tables += (f"\n[roles.{role}]\norder = {FIRST_ROLE_ORDER + n * ROLE_ORDER_STEP}\n"
                   f"standard = false\n"
                   f"description = "
                   f"{_toml_string(f'What {article(role)} {role} needs to know about a module')}"
                   f"\ntemplate = {_toml_string(f'roles/{role}.md')}\n")
    for skill in skills:
        reads = ", ".join(_toml_string(r) for r in roles)
        tables += (f"\n[skills.{skill}]\npath = {_toml_string(f'skills/{skill}')}\n"
                   f"reads_roles = [{reads}]\n")
    files = {"pack.toml": string.Template(_scaffold("pack.toml")).substitute(
        id=pack_id, id_toml=_toml_string(pack_id),
        priority=DEFAULT_PACK_PRIORITY if priority is None else priority,
        description_toml=_toml_string(description or PACK_DESCRIPTION), tables=tables)}
    for role in roles:  # `${article}` is resolved now; the other placeholders by `create`
        files[f"roles/{role}.md"] = _scaffold("role.md").replace("${article}", article(role))
    task = '"<the task in one sentence>"'
    if roles:
        context = "\n".join(f"   `modsys context --task {task} --role {r} --json`" for r in roles)
        show = "\n".join(f"   `modsys show <module> --role {r}`" for r in roles)
        docs = f"{_and(roles)} docs"
    else:
        context, show, docs = f"   `modsys context --task {task} --json`", \
            "   `modsys show <module>`", "docs"
    for skill in skills:
        what = (f"Works through a task with the {docs} of the modules it touches. Rewrite this "
                f"line to say what the skill does and when an agent should use it.")
        files[f"skills/{skill}/SKILL.md"] = string.Template(_scaffold("SKILL.md")).substitute(
            skill=skill, description=what, context_lines=context, read_what=docs,
            show_lines=show)
    return files


def new_pack(ws, pack_id: str, roles: list[str], skills: list[str], description: str | None,
             priority: int | None, dry_run: bool) -> dict:
    """Scaffold a pack; every refusal writes nothing, an interrupted write removes its files."""
    _check_names(pack_id, roles, skills)
    pack_dir = ws.config_dir / "packs" / pack_id
    _check_free(ws, pack_id, pack_dir, roles, skills)
    files = scaffold_files(pack_id, roles, skills, description, priority)
    if not dry_run:
        try:
            pack_dir.mkdir(parents=True)  # never an existing directory: the pack is ours alone
        except OSError as e:
            raise UsageError(f"cannot create {ws.rel(pack_dir)}/: {e.strerror}; nothing "
                             f"written") from None
        try:
            for rel, text in files.items():
                path = pack_dir / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "x", encoding="utf-8", newline="\n") as fh:
                    fh.write(text)
        except BaseException as e:  # Ctrl-C or a failed write: remove the half-made pack
            shutil.rmtree(pack_dir, ignore_errors=True)
            if isinstance(e, OSError):
                raise UsageError(f"cannot write {ws.rel(pack_dir)}/: {e.strerror}; nothing "
                                 f"written") from None
            raise
    return {"pack": pack_id, "dir": ws.rel(pack_dir),
            "files": [ws.rel(pack_dir / rel) for rel in files], "dry_run": dry_run}


def pack_rows(ws) -> list[dict]:
    """`packs list` data: active packs in precedence order (`builtin`: an engine pack, whose
    `priority` is null — it ranks below every repository pack)."""
    rows = []
    for pack in discover_packs(ws.config_dir):
        data, pack_dir = pack["data"], pack["path"].parent
        skills = []
        for sid, spec in (data.get("skills") or {}).items():
            meta = read_front_matter(pack_dir / spec["path"] / "SKILL.md") or {}
            skills.append({"id": sid, "path": spec["path"],
                           "reads_roles": list(spec.get("reads_roles", [])),
                           "description": meta.get("description") or None,
                           "ejected": ejected_dir(ws.config_dir, sid).is_dir()})
        version, description = data.get("version"), data.get("description")
        rows.append({"id": pack["id"], "version": version if isinstance(version, str) else None,
                     "priority": pack["priority"], "builtin": pack["builtin"],
                     "dir": ws.rel(pack_dir),
                     "description": description if isinstance(description, str) else None,
                     "roles": list(data.get("roles") or {}), "skills": skills})
    return rows


def sync(ws, agents: list[str] | None, check: bool, dry_run: bool) -> dict:
    """`packs sync`: plan every (agent, skill), then apply the plans unless `check` /
    `dry_run`; a conflicting or invalid skill is never written, the others are."""
    if check and dry_run:
        raise UsageError("--check and --dry-run cannot be combined (--check never writes)")
    for agent in agents or []:
        if agent not in AGENT_DIRS:
            raise UsageError(f"unknown agent {agent!r} (agents: {', '.join(AGENT_DIRS)})")
    chosen = list(dict.fromkeys(agents or (ws.config.get("packs") or {}).get("agents") or []))
    if not chosen:
        raise UsageError("choose --agent claude and/or --agent codex, or set [packs] agents")
    try:
        plans = plan_sync(ws, chosen)
    except OSError as e:  # planning only reads: an unreadable agent copy stops the run
        raise UsageError(f"cannot read {ws.rel(e.filename or ws.root)}: "
                         f"{e.strerror or e}") from None
    if not check and not dry_run:
        for plan in plans:
            if plan.same_as is None:
                try:
                    apply_plan(plan)
                except OSError as e:
                    raise UsageError(f"cannot write {ws.rel(plan.dest)}: {e.strerror or e} — "
                                     f"fix it and run packs sync again (a skill written in "
                                     f"part resumes)") from None
    rows = [row(ws, plan) for plan in plans]
    summary = {s: sum(r["status"] == s for r in rows) for s in STATUSES}
    failed = (any(r["status"] != "unchanged" for r in rows) if check
              else bool(summary["conflict"] or summary["invalid"]))
    return {"agents": chosen, "check": check, "dry_run": dry_run, "skills": rows,
            "summary": summary, "failed": failed}


def _refuse_flags(args, action: str, allowed: tuple[str, ...]) -> None:
    given = {"ID": args.name, "--role": args.roles, "--skill": args.skills,
             "--description": args.description, "--priority": args.priority,
             "--agent": args.agents, "--check": args.check or None,
             "--dry-run": args.dry_run or None}
    used = [flag for flag, value in given.items() if value is not None and flag not in allowed]
    if used:
        raise UsageError(f"packs {action} takes no {used[0]}")


def run(args) -> int:
    ws = Workspace.from_args(args)
    if args.action == "list":
        _refuse_flags(args, "list", ())
        emit("packs", pack_rows(ws), args.json, _render_list)
        return EXIT_OK
    if args.action == "sync":
        _refuse_flags(args, "sync", SYNC_FLAGS + ("--dry-run",))
        data = sync(ws, args.agents, args.check, args.dry_run)
        emit("packs", data, args.json, functools.partial(_render_sync, ws=ws))
        return EXIT_FINDINGS if data["failed"] else EXIT_OK
    _refuse_flags(args, "new", ("ID",) + NEW_FLAGS + ("--dry-run",))
    if args.name is None:
        raise UsageError("packs new needs an ID (the new pack's id, e.g. team)")
    data = new_pack(ws, args.name, args.roles or [], args.skills or [], args.description,
                    args.priority, args.dry_run)
    agents = (ws.config.get("packs") or {}).get("agents")
    emit("packs", data, args.json, functools.partial(_render_new, agents=agents))
    return EXIT_OK


def _render_new(d, agents: list[str] | None = None) -> None:
    """`agents`: the config's `[packs] agents` — set, a bare `modsys packs sync` works."""
    verb = "would create" if d["dry_run"] else "created"
    for f in d["files"]:
        print(f"{verb}  {f}")
    role_dir = Path(d["dir"]) / "roles"  # only <pack dir>/roles/<role>.md is a role template
    roles = [Path(f).stem for f in d["files"] if Path(f).parent == role_dir]
    skills = any(Path(f).name == "SKILL.md" for f in d["files"])
    steps = [f"modsys create NAME … --role {roles[0]} (a module with the {roles[0]} doc)"
             if roles else "edit pack.toml (roles, fields, [[code_map]] rules, skills)"]
    if skills:
        steps.append(f"{sync_command(None, agents)} (the skills into the agents' skill "
                     f"directories)")
    print(f"next: {'; then '.join(steps)}")


def _hint(ws, r) -> str:
    """How to resolve a `conflict` or `invalid` row (text output only): by the reason."""
    here, copy = r["dir"], ws.rel(ejected_dir(ws.config_dir, r["skill"]))
    if r["status"] == "invalid":
        if r["source"] != "ejected":
            return "fix the skill in its pack (plain modsys lint reports it as MS062)"
        code = "MS063" if r["reason"].endswith(NO_RECORD) else "MS062"
        return f"fix the ejected copy {copy} (plain modsys lint reports it as {code})"
    if r["status"] != "conflict":
        return ""
    kind, other = conflict_kind(r["reason"])
    if kind == "edit":
        keep = (f"copy it into {copy}" if r["source"] == "ejected"
                else f"modsys eject {r['skill']}, copy the change into {copy}")
        return (f"revert it (git checkout -- {here}) and sync again, or keep the change: {keep}, "
                f"then packs sync")
    return {"hand-written": "a skill written by hand: move or rename it, then sync again",
            "other-pack": f"it belongs to pack '{other}': remove it if that pack is gone, or "
                          f"rename one of the skills",
            "bad-marker": f"restore the marker (git checkout -- {here}) or move the directory "
                          f"away, then sync again",
            "orphan-edit": "revert the edit, or delete the directory if the skill is no longer "
                           "wanted",
            "orphan-bad-marker": f"restore the marker (git checkout -- {here}) or delete the "
                                 f"directory"}.get(kind, "move it away, then sync again")


def _render_sync(d, ws) -> None:
    if not d["skills"]:
        print("no pack skills (add one: modsys packs new ID --skill NAME)")
    for r in d["skills"]:
        where = f"({r['pack']} {r['version']}" if r["version"] else f"({r['pack']}"
        where += ", ejected copy)" if r["source"] == "ejected" else ")"
        if r["pack"] is None and r["source"] is None:  # an orphan whose marker is unreadable
            where = "(no valid marker)"
        elif r["pack"] is None:  # an ejected copy without a record of a skill no pack declares
            where = "(no valid record)"
        same = f"  same directory as {r['same_as']}" if r.get("same_as") else ""
        print(f"{r['status']:<10} {r['agent']:<7} {r['dir']}  {where}{same}")
        if r["reason"]:
            hint = _hint(ws, r)
            print(f"  {r['reason']}" + (f" — {hint}" if hint else ""))
    s = d["summary"]
    counts = ", ".join(f"{s[k]} {k}" for k in STATUSES)
    if d["check"]:
        configured = (ws.config.get("packs") or {}).get("agents")
        state = "; ".join(
            ([f"stale — run {sync_command(d['agents'], configured)}"]
             if s["created"] or s["updated"] or s["removed"] else [])
            + (["blocked — resolve the conflict / invalid rows above"]
               if s["conflict"] or s["invalid"] else [])) or "in sync"
        print(f"packs sync --check: {counts}: {state}")
    else:
        print(f"packs sync: {counts}" + ("  (dry run: nothing written)" if d["dry_run"] else ""))


def _render_list(rows) -> None:
    if not rows:
        print("no packs (create one: modsys packs new ID)")
    for r in rows:
        rank = "built-in" if r["builtin"] else f"priority {r['priority']}"
        print(f"{r['id']} {r['version'] or '(no version)'} {rank}  {r['dir']}")
        for role in r["roles"]:
            print(f"  role   {role}")
        for s in r["skills"]:
            reads = f"  reads {', '.join(s['reads_roles'])}" if s["reads_roles"] else ""
            print(f"  skill  {s['id']}{reads}{'  (ejected)' if s['ejected'] else ''}")
