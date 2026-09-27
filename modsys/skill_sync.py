"""`modsys packs sync`: copy pack skills into the agents' skill directories — claude
`<root>/.claude/skills/<skill>/`, codex `<root>/.agents/skills/<skill>/` — and keep them there.

Every (agent, skill) gets its status BEFORE anything is written:
  created    the destination directory does not exist
  unchanged  every managed file on disk equals the source (bytes and mode), marker current
  updated    the source or the marker differs and nothing was edited locally: changed and new
             files are written, files the source dropped are deleted, the marker is rewritten
  removed    a managed skill (it has a marker) that no installed pack declares any more: its
             managed files and marker are deleted, directories left empty removed; unmanaged
             files stay and are named in `reason`
  conflict   the destination is not ours (no marker, a marker of another pack or skill, not a
             directory), a managed file was edited or deleted locally, or a new source file
             would replace an unmanaged one — the skill is left untouched
  invalid    the source is not loadable by agents (lint MS062) — nothing written for it
The marker `<dest>/.modsys-managed` = {schema, pack, skill, version, source, files: {path:
sha256}} is written LAST: after an interrupted update, a file that already equals the source is
not a local edit, so the next run resumes; a first write (`created`) that fails or is interrupted
removes the directory it made, so the next run creates the skill again. Directories without a
marker are never read beyond the existence check; a symlink inside a destination is never
written through."""
import contextlib
import json
import os
import re
import shutil
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from modsys.skills import (AGENT_DIRS, EJECTED, MANAGED, ejected_copies, pack_skills,
                           read_ejected, sha256_file, source_hashes, source_problem)

MANAGED_SCHEMA = "modsys.managed/1"
STATUSES = ("created", "updated", "unchanged", "removed", "conflict", "invalid")
# fixed reasons that `conflict_kind` and the `packs sync` hints read back
NOT_MANAGED = f"not managed by modsys (no {MANAGED})"
BAD_MARKER = f"{MANAGED} is not a valid marker"
NO_RECORD = f"has no valid {EJECTED} record"  # an `invalid` ejected copy: lint MS063, not MS062
ORPHAN_BAD_MARKER = f"{BAD_MARKER} (not removed)"
_OTHER_PACK = re.compile(r"managed for pack '(.*)', skill '.*'")
_EDIT = re.compile(r" \(locally (?:edited|deleted)\)(?:; |$)")


def sync_command(agents: list[str] | None, configured: list[str] | None) -> str:
    """The `packs sync` command every hint names: bare when `[packs] agents` (`configured`)
    already names `agents` (None: whatever the config names), else with the `--agent` flags
    — claude and codex when no agent was chosen."""
    if configured and (agents is None or list(agents) == list(configured)):
        return "modsys packs sync"
    return "modsys packs sync " + " ".join(f"--agent {a}" for a in agents or AGENT_DIRS)


@dataclass
class Source:
    """Where a skill is materialized from."""
    skill: str
    pack: str | None
    version: str | None
    kind: str  # "pack" | "ejected"
    dir: Path
    problem: str | None
    files: dict[str, str] = field(default_factory=dict)  # path -> sha256


@dataclass
class Plan:
    """The decided status of one (agent, skill) and what applying it writes or deletes."""
    agent: str
    skill: str
    dest: Path
    status: str
    source: Source | None = None
    marker: dict | None = None  # the marker on disk (removed rows: what they came from)
    write: list[str] = field(default_factory=list)
    delete: list[str] = field(default_factory=list)
    reason: str | None = None
    same_as: str | None = None


def skill_sources(ws) -> dict[str, Source]:
    """The source of every skill to materialize, by id: its ejected copy when one exists
    (`<config_dir>/overrides/skills/<id>/`, synced even when no pack declares the skill any
    more; pack and version from its record), else the declaring pack's directory."""
    out = {}
    skills, ejected = pack_skills(ws.config_dir), ejected_copies(ws.config_dir)
    for sid in sorted(set(skills) | set(ejected)):
        if sid in ejected:
            record = read_ejected(ejected[sid])
            if record is None:
                out[sid] = Source(sid, skills[sid].pack if sid in skills else None, None,
                                  "ejected", ejected[sid],
                                  f"the ejected copy {ws.rel(ejected[sid])} {NO_RECORD}")
                continue
            version = record.get("version")
            src = Source(sid, record["pack"], version if isinstance(version, str) else None,
                         "ejected", ejected[sid], source_problem(ejected[sid], sid))
        else:
            skill = skills[sid]
            src = Source(sid, skill.pack, skill.version, "pack", skill.source,
                         source_problem(skill.source, sid, skill.pack_dir))
        src.files = {} if src.problem else source_hashes(src.dir, ws.rel)
        out[sid] = src
    return out


def marker_text(src: Source) -> str:
    return json.dumps({"schema": MANAGED_SCHEMA, "pack": src.pack, "skill": src.skill,
                       "version": src.version, "source": src.kind, "files": src.files},
                      indent=2, sort_keys=True) + "\n"


def _safe(rel) -> bool:
    """A marker path the engine may touch: relative, normalized, never leaving the skill."""
    return (isinstance(rel, str) and bool(rel) and not rel.startswith("/") and "\\" not in rel
            and all(part not in ("", ".", "..") for part in rel.split("/")))


def read_marker(dest: Path) -> dict | None:
    """The marker of `dest`, or None when it is missing or not a well-formed marker."""
    try:
        data = json.loads((dest / MANAGED).read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if (not isinstance(data, dict) or data.get("schema") != MANAGED_SCHEMA
            or not isinstance(data.get("pack"), str) or not isinstance(data.get("skill"), str)
            or not isinstance(data.get("files"), dict)
            or not all(_safe(k) and isinstance(v, str) for k, v in data["files"].items())):
        return None
    return data


def _in_the_way(dest: Path, rel: str, dropped: frozenset = frozenset()) -> bool:
    """A symlink or a non-directory on the way to `dest/rel`, or `dest/rel` itself a symlink or
    a directory: writing or deleting there could leave the skill directory. `dropped`: managed
    files the sync deletes BEFORE it writes — a file among them on the way, or a directory that
    holds only them, is gone by then (the source turned a file into a directory or back)."""
    path = dest
    for part in rel.split("/")[:-1]:
        path = path / part
        if path.is_symlink():
            return True
        if os.path.lexists(path) and not path.is_dir():
            return path.relative_to(dest).as_posix() not in dropped
    target = dest / rel
    if target.is_symlink():
        return True
    return target.is_dir() and not _only_dropped(dest, target, dropped)


def _only_dropped(dest: Path, directory: Path, dropped: frozenset) -> bool:
    """Every entry below `directory` is a plain directory or a file in `dropped`."""
    for dirpath, dirnames, filenames in os.walk(directory):
        for name in dirnames + filenames:
            path = Path(dirpath) / name
            if path.is_symlink() or (name in filenames
                                     and path.relative_to(dest).as_posix() not in dropped):
                return False
    return True


def _same_file(path: Path, src: Path) -> bool:
    return (sha256_file(path) == sha256_file(src)
            and stat.S_IMODE(path.stat().st_mode) == stat.S_IMODE(src.stat().st_mode))


def plan_skill(agent: str, dest: Path, src: Source) -> Plan:
    plan = Plan(agent, src.skill, dest, "invalid", src)
    if src.problem:
        plan.reason = src.problem
        return plan
    if not os.path.lexists(dest):
        plan.status, plan.write = "created", sorted(src.files)
        return plan
    plan.status = "conflict"
    if dest.is_symlink() or not dest.is_dir():
        plan.reason = ("the destination is a symlink" if dest.is_symlink()
                       else "the destination is not a directory")
        return plan
    if not os.path.lexists(dest / MANAGED):
        plan.reason = NOT_MANAGED
        return plan
    marker = plan.marker = read_marker(dest)
    if marker is None:
        plan.reason = BAD_MARKER
        return plan
    if (marker["pack"], marker["skill"]) != (src.pack, src.skill):
        plan.reason = f"managed for pack '{marker['pack']}', skill '{marker['skill']}'"
        return plan
    problems = []
    for rel, recorded in sorted(marker["files"].items()):
        path = dest / rel
        if _in_the_way(dest, rel):
            problems.append(f"{rel} (a symlink or directory in the way)")
        elif not os.path.lexists(path):
            if rel in src.files:
                problems.append(f"{rel} (locally deleted)")
        elif sha256_file(path) not in (recorded, src.files.get(rel)):
            problems.append(f"{rel} (locally edited)")
    dropped = frozenset(set(marker["files"]) - set(src.files))
    for rel in sorted(set(src.files) - set(marker["files"])):
        path = dest / rel
        if _in_the_way(dest, rel, dropped):
            problems.append(f"{rel} (a symlink or directory in the way)")
        elif (os.path.lexists(path) and not path.is_dir()
              and sha256_file(path) != src.files[rel]):
            problems.append(f"{rel} (exists and is not managed by modsys)")
    if problems:
        plan.reason = "; ".join(problems)
        return plan
    plan.write = [rel for rel in sorted(src.files)
                  if not (dest / rel).is_file() or not _same_file(dest / rel, src.dir / rel)]
    plan.delete = [rel for rel in sorted(marker["files"])
                   if rel not in src.files and os.path.lexists(dest / rel)]
    current = (dest / MANAGED).read_bytes() == marker_text(src).encode("utf-8")
    plan.status = "unchanged" if not plan.write and not plan.delete and current else "updated"
    return plan


def plan_orphans(agent: str, agent_dir: Path, wanted: set[str]) -> list[Plan]:
    """`removed` (or `conflict`) plans for managed skill directories nobody declares."""
    plans = []
    if not agent_dir.is_dir():
        return plans
    for dest in sorted(agent_dir.iterdir()):
        if (dest.name in wanted or dest.is_symlink() or not dest.is_dir()
                or not os.path.lexists(dest / MANAGED)):
            continue
        marker = read_marker(dest)
        if marker is not None and marker["skill"] != dest.name:
            continue  # a marker copied from elsewhere: not this directory's own
        plan = Plan(agent, dest.name, dest, "conflict", marker=marker)
        if marker is None:
            plan.reason = ORPHAN_BAD_MARKER
        else:
            edited = [rel for rel, recorded in sorted(marker["files"].items())
                      if os.path.lexists(dest / rel) and (_in_the_way(dest, rel)
                                                          or sha256_file(dest / rel) != recorded)]
            if edited:
                plan.reason = f"{', '.join(edited)} (locally edited; not removed)"
            else:
                plan.status = "removed"
                plan.delete = [rel for rel in sorted(marker["files"])
                               if os.path.lexists(dest / rel)]
                left = sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*")
                              if not p.is_dir() and p.name != MANAGED
                              and p.relative_to(dest).as_posix() not in marker["files"])
                plan.reason = f"left unmanaged files: {', '.join(left)}" if left else None
        plans.append(plan)
    return plans


def conflict_kind(reason: str) -> tuple[str, str | None]:
    """What a `conflict` reason is about, for the hint `packs sync` prints, and the other pack
    for `other-pack`: `orphan-bad-marker` / `orphan-edit` (a skill no pack declares any more,
    not removed), `hand-written` (no marker), `bad-marker`, `other-pack`, `edit` (a managed
    file edited or deleted locally — it wins when a reason joins several problems), else
    `in-the-way` (something the sync must not write over)."""
    if reason == ORPHAN_BAD_MARKER:
        return "orphan-bad-marker", None
    if reason.endswith("(locally edited; not removed)"):
        return "orphan-edit", None
    if reason == NOT_MANAGED:
        return "hand-written", None
    if reason == BAD_MARKER:
        return "bad-marker", None
    other = _OTHER_PACK.fullmatch(reason)
    if other:
        return "other-pack", other.group(1)
    return ("edit" if _EDIT.search(reason) else "in-the-way"), None


def copy_file(src: Path, path: Path) -> None:
    """Write `src`'s bytes and permission bits to `path` atomically (temp file + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(src.read_bytes())
        os.chmod(tmp, stat.S_IMODE(src.stat().st_mode))
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def _prune(dest: Path, rels: list[str], including_dest: bool) -> None:
    """Remove the directories the deleted files leave empty (deepest first)."""
    dirs = {p for rel in rels for p in (dest / rel).parents if dest in p.parents}
    if including_dest:
        dirs.add(dest)
    for d in sorted(dirs, key=lambda p: -len(p.parts)):
        with contextlib.suppress(OSError):
            d.rmdir()


def _write(plan: Plan) -> None:
    for rel in plan.delete:  # first: a dropped file may stand where a new directory goes
        (plan.dest / rel).unlink()
    _prune(plan.dest, plan.delete, False)
    for rel in plan.write:
        copy_file(plan.source.dir / rel, plan.dest / rel)
    text = marker_text(plan.source)
    path = plan.dest / MANAGED
    fd, tmp = tempfile.mkstemp(dir=plan.dest, prefix=f".{MANAGED}.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)  # last: the marker only ever describes files already written


def apply_plan(plan: Plan) -> None:
    """Write, update or remove one skill. A `created` skill's directory is made here (never an
    existing one) and removed again when the write fails or is interrupted, so a rerun creates
    it instead of finding a directory without a marker; an `updated` one resumes by hash."""
    if plan.status == "created":
        plan.dest.parent.mkdir(parents=True, exist_ok=True)
        os.mkdir(plan.dest)  # exclusive: the directory is this run's alone to remove
        try:
            _write(plan)
        except BaseException:  # a failed write or Ctrl-C: no marker-less directory stays
            shutil.rmtree(plan.dest, ignore_errors=True)
            raise
    elif plan.status == "updated":
        _write(plan)
    elif plan.status == "removed":
        for rel in plan.delete:
            (plan.dest / rel).unlink()
        (plan.dest / MANAGED).unlink()
        _prune(plan.dest, plan.delete, True)


def plan_sync(ws, agents: list[str]) -> list[Plan]:
    """Every (agent, skill) plan, agents in the given order, skills by id; an agent whose
    directory is the same real directory as an earlier agent's repeats that agent's plans
    with `same_as` (applied once)."""
    sources = skill_sources(ws)
    plans, seen = [], {}
    for agent in agents:
        agent_dir = ws.root / AGENT_DIRS[agent]
        real = os.path.realpath(agent_dir)
        if real in seen:
            first = seen[real]
            plans += [Plan(agent, p.skill, agent_dir / p.skill, p.status, p.source, p.marker,
                           p.write, p.delete, p.reason, same_as=first)
                      for p in plans if p.agent == first]
            continue
        seen[real] = agent
        mine = [plan_skill(agent, agent_dir / sid, src) for sid, src in sources.items()]
        mine += plan_orphans(agent, agent_dir, set(sources))
        plans += sorted(mine, key=lambda p: p.skill)
    return plans


def row(ws, plan: Plan) -> dict:
    src, marker = plan.source, plan.marker or {}
    files = plan.write + plan.delete if plan.status in ("created", "updated", "removed") else []
    out = {"agent": plan.agent, "skill": plan.skill,
           "pack": src.pack if src else marker.get("pack"),
           "version": src.version if src else marker.get("version"),
           "source": src.kind if src else marker.get("source"),
           "dir": ws.rel(plan.dest), "status": plan.status, "files": sorted(files),
           "reason": plan.reason}
    if plan.same_as:
        out["same_as"] = plan.same_as
    return out
