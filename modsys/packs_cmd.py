"""`modsys packs`: create and list packs — a team's roles, role templates and agent skills.

  new ID [--role NAME]… [--skill NAME]… [--description TEXT] [--priority N]
        scaffold `<config_dir>/packs/ID/`: `pack.toml`, a role template per `--role` and a
        `SKILL.md` per `--skill` (reading every `--role`); every refusal writes nothing
  list  the installed packs in precedence order, with their roles and skills"""
import os
import re
import shutil
import string
from importlib import resources
from pathlib import Path

from modsys.code_map_cmd import _toml_string
from modsys.config import DEFAULT_PACK_PRIORITY, core_defaults, discover_packs
from modsys.create import NAME
from modsys.output import EXIT_OK, UsageError, emit
from modsys.skills import (NAME_RULE, declared_skills, ejected_dir, read_front_matter,
                           skill_id_ok)
from modsys.workspace import Workspace

ACTIONS = ("new", "list")
ROLE_NAME = re.compile(r"^[a-z][a-z0-9_]*(-[a-z0-9]+)*$")
FIRST_ROLE_ORDER, ROLE_ORDER_STEP = 100, 10
PACK_DESCRIPTION = "Describe what this pack adds: its roles and skills."


def register(sub, common) -> None:
    p = sub.add_parser("packs", parents=[common],
                       help="create or list packs: a team's roles, templates and agent skills",
                       description="new ID: scaffold <config_dir>/packs/ID/ — pack.toml, "
                                   "roles/<role>.md per --role, skills/<skill>/SKILL.md per "
                                   "--skill (each skill reads every --role). list: the "
                                   "installed packs in precedence order with their roles and "
                                   "skills.")
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
    p.add_argument("--dry-run", action="store_true", help="new: list the files, write nothing")
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
                   f"description = {_toml_string(f'What a {role} needs to know about a module')}"
                   f"\ntemplate = {_toml_string(f'roles/{role}.md')}\n")
    for skill in skills:
        reads = ", ".join(_toml_string(r) for r in roles)
        tables += (f"\n[skills.{skill}]\npath = {_toml_string(f'skills/{skill}')}\n"
                   f"reads_roles = [{reads}]\n")
    files = {"pack.toml": string.Template(_scaffold("pack.toml")).substitute(
        id=pack_id, id_toml=_toml_string(pack_id),
        priority=DEFAULT_PACK_PRIORITY if priority is None else priority,
        description_toml=_toml_string(description or PACK_DESCRIPTION), tables=tables)}
    for role in roles:
        files[f"roles/{role}.md"] = _scaffold("role.md")
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
    """`packs list` data: installed packs in precedence order."""
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
                     "priority": pack["priority"], "dir": ws.rel(pack_dir),
                     "description": description if isinstance(description, str) else None,
                     "roles": list(data.get("roles") or {}), "skills": skills})
    return rows


def run(args) -> int:
    ws = Workspace.from_args(args)
    if args.action == "list":
        used = [flag for flag, value in (("ID", args.name), ("--role", args.roles),
                                         ("--skill", args.skills),
                                         ("--description", args.description),
                                         ("--priority", args.priority),
                                         ("--dry-run", args.dry_run or None))
                if value is not None]
        if used:
            raise UsageError(f"packs list takes no {used[0]}")
        emit("packs", pack_rows(ws), args.json, _render_list)
        return EXIT_OK
    if args.name is None:
        raise UsageError("packs new needs an ID (the new pack's id, e.g. team)")
    data = new_pack(ws, args.name, args.roles or [], args.skills or [], args.description,
                    args.priority, args.dry_run)
    emit("packs", data, args.json, _render_new)
    return EXIT_OK


def _render_new(d) -> None:
    verb = "would create" if d["dry_run"] else "created"
    for f in d["files"]:
        print(f"{verb}  {f}")
    roles = [Path(f).stem for f in d["files"] if Path(f).parent.name == "roles"]
    steps = [f"modsys create NAME … --role {roles[0]} (a module with the {roles[0]} doc)"
             if roles else "edit pack.toml (roles, fields, [[code_map]] rules, skills)"]
    print(f"next: {steps[0]}; modsys packs list shows the pack")


def _render_list(rows) -> None:
    if not rows:
        print("no packs (create one: modsys packs new ID)")
    for r in rows:
        print(f"{r['id']} {r['version'] or '(no version)'} priority {r['priority']}  {r['dir']}")
        for role in r["roles"]:
            print(f"  role   {role}")
        for s in r["skills"]:
            reads = f"  reads {', '.join(s['reads_roles'])}" if s["reads_roles"] else ""
            print(f"  skill  {s['id']}{reads}{'  (ejected)' if s['ejected'] else ''}")
