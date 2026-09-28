"""`modsys eject SKILL`: take a pack skill over. Its files are copied to
`<config_dir>/overrides/skills/SKILL/` with a `.modsys-ejected` record — the pack, its version
and the file hashes at eject time. From then on `packs sync` materializes the skill from that
copy into every agent directory and the pack never overwrites it; plain `lint` reports MS063
when the pack moves on. `--diff` compares the pack's current files with the copy (read-only).
Back to the pack: delete the directory and run `packs sync` again with the agents (`--agent …`,
or `[packs] agents`); there is no un-eject."""
import difflib
import functools
import json
import os
import shutil
from pathlib import Path

from modsys.output import EXIT_OK, UsageError, emit
from modsys.skill_sync import copy_file, sync_command
from modsys.skills import (EJECTED, EJECTED_SCHEMA, behind_reason, ejected_dir, pack_skills,
                           read_ejected, source_hashes, source_problem)
from modsys.workspace import Workspace

SET_AGENTS = " (or set [packs] agents once)"


def register(sub, common) -> None:
    p = sub.add_parser("eject", parents=[common],
                       help="copy a pack skill into the repo to own it (--diff: compare it with "
                            "the pack)",
                       description="Copy a pack skill to <config_dir>/overrides/skills/SKILL/; "
                                   "packs sync then materializes the skill from that copy and "
                                   "the pack never overwrites it. --diff compares the pack's "
                                   "current files with the copy. Back to the pack: delete the "
                                   f"directory, then {sync_command(None, None)}{SET_AGENTS}.")
    p.add_argument("skill", metavar="SKILL")
    p.add_argument("--diff", action="store_true",
                   help="compare the ejected copy with the pack's current files (read-only)")
    p.add_argument("--dry-run", action="store_true", help="list the files, write nothing")
    p.set_defaults(func=run)


def in_the_way(ws, target: Path) -> None:
    """Exit 2 when the ejected path is a symlink: never an ejected copy (its target is never
    read, written or deleted)."""
    if target.is_symlink():
        raise UsageError(f"{ws.rel(target)} is in the way: a symlink, not an ejected copy — "
                         f"remove it (its target is left alone), then run the command again")


def eject(ws, skill_id: str, dry_run: bool) -> dict:
    """Copy the skill's files and write the record last; every refusal writes nothing and an
    interrupted copy removes the directory."""
    target = ejected_dir(ws.config_dir, skill_id)
    in_the_way(ws, target)
    if os.path.lexists(target):
        raise UsageError(f"skill '{skill_id}' is already ejected: {ws.rel(target)}")
    skills = pack_skills(ws.config_dir)
    if skill_id not in skills:
        raise UsageError(f"unknown skill '{skill_id}' (pack skills: "
                         f"{', '.join(skills) or 'none'})")
    skill = skills[skill_id]
    problem = source_problem(skill.source, skill_id, skill.pack_dir)
    if problem:
        raise UsageError(f"skill '{skill_id}' of pack '{skill.pack}' is not loadable: {problem} "
                         f"(lint MS062); nothing written")
    files = source_hashes(skill.source, ws.rel)
    if not dry_run:
        try:
            target.mkdir(parents=True)
        except OSError as e:
            raise UsageError(f"cannot create {ws.rel(target)}/: {e.strerror}; nothing "
                             f"written") from None
        try:
            for rel in files:
                copy_file(skill.source / rel, target / rel)
            record = {"schema": EJECTED_SCHEMA, "skill": skill_id, "pack": skill.pack,
                      "version": skill.version, "files": files}
            (target / EJECTED).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n",
                                          encoding="utf-8")
        except BaseException as e:  # Ctrl-C or a failed write: no half-made copy stays
            shutil.rmtree(target, ignore_errors=True)
            if isinstance(e, OSError):
                raise UsageError(f"cannot write {ws.rel(target)}/: {e.strerror}; nothing "
                                 f"written") from None
            raise
    return {"skill": skill_id, "pack": skill.pack, "version": skill.version,
            "dir": ws.rel(target), "files": sorted(files), "dry_run": dry_run}


def _lines(path: Path | None) -> list[str] | None:
    """A file's lines for a text diff ([] for a missing side); None for a binary file."""
    if path is None:
        return []
    data = path.read_bytes()
    try:
        return None if b"\0" in data else data.decode("utf-8").splitlines(keepends=True)
    except UnicodeDecodeError:
        return None


def _unified(upstream: Path | None, ejected: Path | None, rel: str) -> str:
    old, new = _lines(upstream), _lines(ejected)
    if old is None or new is None:
        return f"Binary files upstream/{rel} and ejected/{rel} differ\n"
    return "".join(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
                   for line in difflib.unified_diff(old, new, f"upstream/{rel}",
                                                    f"ejected/{rel}"))


def diff(ws, skill_id: str) -> dict:
    """The pack's current files vs the ejected copy; `reason` = `behind_reason` (lint MS063's
    rule, `behind` = a reason): the pack (or a repository pack's version) or its files differ
    from the snapshot recorded at eject time. An unreadable file on either side is exit 2
    `cannot read …`."""
    target = ejected_dir(ws.config_dir, skill_id)
    in_the_way(ws, target)
    if not target.is_dir():
        raise UsageError(f"skill '{skill_id}' is not ejected (eject it first: modsys eject "
                         f"{skill_id})")
    record = read_ejected(target)
    if record is None:
        raise UsageError(f"{ws.rel(target)} has no valid {EJECTED} record — eject it again or "
                         f"restore the file")
    skill = pack_skills(ws.config_dir).get(skill_id)
    if skill is None:
        raise UsageError(f"pack '{record['pack']}' no longer declares skill '{skill_id}' — the "
                         f"ejected copy {ws.rel(target)} is its only source (nothing to "
                         f"compare)")
    upstream = source_hashes(skill.source, ws.rel) if skill.source.is_dir() else {}
    mine = source_hashes(target, ws.rel)
    rows, chunks = [], []
    for rel in sorted(set(upstream) | set(mine)):
        status = ("only-upstream" if rel not in mine else "only-ejected" if rel not in upstream
                  else "same" if upstream[rel] == mine[rel] else "changed")
        rows.append({"path": rel, "status": status})
        if status != "same":
            chunks.append(_unified(skill.source / rel if rel in upstream else None,
                                   target / rel if rel in mine else None, rel))
    reason = behind_reason(skill, record, upstream=upstream)
    return {"skill": skill_id, "pack": skill.pack, "ejected_from": record.get("version"),
            "upstream_version": skill.version, "behind": reason is not None, "reason": reason,
            "files": rows, "diff": "".join(chunks)}


def run(args) -> int:
    ws = Workspace.from_args(args)
    if args.diff:
        if args.dry_run:
            raise UsageError("--dry-run applies to eject without --diff (--diff never writes)")
        emit("eject", diff(ws, args.skill), args.json, _render_diff)
        return EXIT_OK
    agents = (ws.config.get("packs") or {}).get("agents")
    emit("eject", eject(ws, args.skill, args.dry_run), args.json,
         functools.partial(_render_eject, agents=agents))
    return EXIT_OK


def _render_eject(d, agents: list[str] | None) -> None:
    """`agents`: the config's `[packs] agents` — set, a bare `modsys packs sync` works."""
    version = f" {d['version']}" if d["version"] else ""
    print(f"{'would eject' if d['dry_run'] else 'ejected'}  {d['skill']}  "
          f"({d['pack']}{version}) -> {d['dir']}")
    for f in d["files"]:
        print(f"  {f}")
    if d["dry_run"]:
        print(f"next: modsys eject {d['skill']} (to do it)")
        return
    print("edit the copy: packs sync materializes the skill from it, and the pack never "
          "overwrites it")
    print(f"next: {sync_command(None, agents)}{'' if agents else SET_AGENTS}")


def _render_diff(d) -> None:
    if d["reason"]:
        state = f"behind ({d['reason']})"
    elif d["ejected_from"] != d["upstream_version"]:  # a built-in pack: the engine moved on
        state = "up to date (the engine version moved; the skill's files did not)"
    else:
        state = "up to date"
    print(f"{d['skill']}: pack {d['pack']} {d['upstream_version']}, ejected at "
          f"{d['ejected_from']} — {state}")
    for f in d["files"]:
        if f["status"] != "same":
            print(f"{f['status']:<14} {f['path']}")
    if d["diff"]:
        print(d["diff"], end="")
