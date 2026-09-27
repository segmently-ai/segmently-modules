"""Pack skills (the Agent Skills format): the `[skills.<id>]` model of a pack, the `SKILL.md`
front-matter reader and the checks that decide whether agents can load a skill.

A pack declares a skill as a `[skills.<id>]` table in its `pack.toml` — a pack meta key, never
merged into the config: `path` (required: the skill directory, relative to the pack) and
`reads_roles` (optional: the roles whose module docs the skill reads). The id follows the
Agent Skills name rule and must equal the `name` in the skill's `SKILL.md` front matter. When
two packs declare one id, the higher-precedence pack's declaration wins everywhere (plain
`lint` reports the other as MS065)."""
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from modsys.config import discover_packs
from modsys.output import UsageError

SKILL_ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SKILL_ID_MAX = 64
SKILL_KEYS = ("path", "reads_roles")
NAME_RULE = "1–64 characters: lowercase letters and digits, words joined by single hyphens"
DESCRIPTION_MAX = 1024
_KEY = re.compile(r"^([A-Za-z_][\w.-]*)[ \t]*:(?:[ \t]+(.*))?$")
_BLOCK = re.compile(r"^([|>])(?:[1-9]?[+-]?|[+-][1-9])$")  # block scalar indicator
_COMMENT = re.compile(r"[ \t]+#.*$")


def skill_id_ok(value: str) -> bool:
    return len(value) <= SKILL_ID_MAX and bool(SKILL_ID.fullmatch(value))


def validate_skills(data: dict, source) -> None:
    """Config errors (exit 2, naming `source`) in the `[skills.<id>]` tables of one pack.
    Missing files and unknown keys are lint findings instead (MS062, MS060)."""
    skills = data.get("skills")
    if skills is None:
        return
    if not isinstance(skills, dict):
        raise UsageError(f"{source}: skills must be a table of [skills.<id>] tables, "
                         f"got {skills!r}")
    for sid, spec in skills.items():
        if not isinstance(spec, dict):
            raise UsageError(f"{source}: skills.{sid} must be a table ([skills.{sid}]), "
                             f"got {spec!r}")
        if not skill_id_ok(sid):
            raise UsageError(f"{source}: skill id {sid!r}: {NAME_RULE} (the Agent Skills "
                             f"name rule)")
        if "path" not in spec:
            raise UsageError(f"{source}: [skills.{sid}] path is missing (the skill directory, "
                             f"relative to the pack)")
        if not isinstance(spec["path"], str):
            raise UsageError(f"{source}: [skills.{sid}] path: expected a string, "
                             f"got {spec['path']!r}")
        roles = spec.get("reads_roles", [])
        if not (isinstance(roles, list) and all(isinstance(r, str) for r in roles)):
            raise UsageError(f"{source}: [skills.{sid}] reads_roles: expected a list of "
                             f"strings, got {roles!r}")


def _unquote(value: str) -> str | None:
    """A quoted scalar's text (None when `value` is not one complete quoted scalar, optionally
    followed by a comment)."""
    quote = value[:1]
    if quote not in ("'", '"'):
        return None
    i = 1
    while i < len(value):
        if quote == '"' and value[i] == "\\":
            i += 2
            continue
        if value[i] == quote:
            if quote == "'" and value[i + 1:i + 2] == "'":
                i += 2
                continue
            rest = value[i + 1:].strip()
            if rest and not rest.startswith("#"):
                return None
            inner = value[1:i]
            if quote == "'":
                return inner.replace("''", "'")
            try:
                return json.loads(f'"{inner}"')
            except json.JSONDecodeError:
                return inner
        i += 1
    return None


def _fold(lines: list[str]) -> str:
    """`>` block: lines joined with spaces; a blank line starts a new line."""
    paragraphs, current = [], []
    for line in lines:
        if line:
            current.append(line)
        elif current:
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    return "\n".join(paragraphs)


def front_matter(text: str) -> dict[str, str] | None:
    """The top-level `key: value` pairs of a `SKILL.md` front matter, or None when there is
    none (the first line is not `---`, or no later line is). A stdlib-only reader for what
    skills use: quoted scalars are unquoted; block scalars (`|`, `>`, with `-` / `+`) are
    joined from their indented lines (`>` folded with spaces) and never end in a newline; a
    plain scalar's indented continuation lines are folded with spaces; the indented lines
    under a key without a value (e.g. `metadata:`) are skipped (the key reads as ""); comment
    lines are skipped. A UTF-8 BOM and `\\r\\n` line ends are accepted."""
    lines = text.lstrip("﻿").splitlines()
    if not lines or lines[0].rstrip() != "---":
        return None
    end = next((i for i in range(1, len(lines)) if lines[i].rstrip() == "---"), None)
    if end is None:
        return None
    out: dict[str, str] = {}
    key, style, value, extra = None, "skip", "", []

    def flush() -> None:
        if key is None:
            return
        if style in ("|", ">"):
            indent = min((len(l) - len(l.lstrip()) for l in extra if l.strip()), default=0)
            body = [l[indent:].rstrip() if l.strip() else "" for l in extra]
            out[key] = ("\n".join(body) if style == "|" else _fold(body)).strip("\n")
        elif style == "plain":
            out[key] = " ".join([value] + [l.strip() for l in extra if l.strip()])
        else:
            out[key] = value

    for line in lines[1:end]:
        if line[:1] in (" ", "\t") or not line.strip():
            if key is not None and style != "skip":
                extra.append(line if line.strip() else "")
            continue
        if line.startswith("#"):
            continue
        flush()
        m = _KEY.match(line.rstrip())
        if not m:
            key = None
            continue
        key, raw, extra = m.group(1), (m.group(2) or "").strip(), []
        if not raw:
            style, value = "skip", ""
        elif _BLOCK.match(_COMMENT.sub("", raw)):
            style, value = raw[0], ""
        elif (quoted := _unquote(raw)) is not None:
            style, value = "quoted", quoted
        else:
            style, value = "plain", _COMMENT.sub("", raw).strip()
    flush()
    return out


def read_front_matter(path: Path) -> dict[str, str] | None:
    """`front_matter` of a file; None when it is unreadable or not UTF-8."""
    try:
        return front_matter(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError):
        return None


def first_symlink(directory: Path) -> str | None:
    """The first symlink below `directory` (posix, relative to it), never following one."""
    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames.sort()
        for name in sorted(dirnames + filenames):
            path = Path(dirpath) / name
            if path.is_symlink():
                return path.relative_to(directory).as_posix()
    return None


def _inside(path: Path, base: Path) -> bool:
    return path == base or base in path.parents


def source_problem(src: Path, skill_id: str, pack_dir: Path | None = None) -> str | None:
    """Why agents could not load the skill in directory `src` — lint MS062, `packs sync`
    status `invalid`, `eject` refusals — or None. `pack_dir`: the pack the source must stay
    inside (a pack skill); None for an ejected copy."""
    if pack_dir is not None:
        lexical = Path(os.path.normpath(src.absolute()))
        if not _inside(lexical, Path(os.path.normpath(pack_dir.absolute()))) or not _inside(
                Path(os.path.realpath(src)), Path(os.path.realpath(pack_dir))):
            return "the path is outside the pack directory"
    if not os.path.lexists(src):
        return "the path does not exist"
    if src.is_symlink():
        return "symlink in source: ."
    if not src.is_dir():
        return "the path is not a directory"
    link = first_symlink(src)
    if link:
        return f"symlink in source: {link}"
    md = src / "SKILL.md"
    if not md.is_file():
        return "no SKILL.md"
    meta = read_front_matter(md)
    if meta is None:
        return "SKILL.md has no front matter (a --- block at the top, closed by a --- line)"
    name = meta.get("name")
    if not name:
        return "SKILL.md front matter has no name"
    if name != skill_id:
        return f"SKILL.md name '{name}' is not the skill id '{skill_id}'"
    description = meta.get("description", "")
    if not description.strip():
        return "SKILL.md front matter has no description"
    if len(description) > DESCRIPTION_MAX:
        return (f"SKILL.md description has {len(description)} characters "
                f"(max {DESCRIPTION_MAX})")
    return None


@dataclass
class PackSkill:
    """One `[skills.<id>]` declaration of an installed pack."""
    id: str
    pack: str
    version: str | None
    pack_dir: Path
    pack_toml: Path
    path: str
    reads_roles: list[str]
    shadowed_by: str | None = None  # the higher-precedence pack that declares the same id

    @property
    def source(self) -> Path:
        return self.pack_dir / self.path


def declared_skills(config_dir: Path) -> list[PackSkill]:
    """Every skill declaration of every installed pack: packs in precedence order (highest
    first), each pack's skills in declaration order."""
    out, first = [], {}
    for pack in discover_packs(config_dir):
        version = pack["data"].get("version")
        for sid, spec in (pack["data"].get("skills") or {}).items():
            out.append(PackSkill(sid, pack["id"], version if isinstance(version, str) else None,
                                 pack["path"].parent, pack["path"], spec["path"],
                                 list(spec.get("reads_roles", [])), first.get(sid)))
            first.setdefault(sid, pack["id"])
    return out


def pack_skills(config_dir: Path) -> dict[str, PackSkill]:
    """The declaration each skill id resolves to (the highest-precedence pack's), by id."""
    return {s.id: s for s in sorted(declared_skills(config_dir), key=lambda s: s.id)
            if s.shadowed_by is None}


def ejected_dir(config_dir: Path, skill_id: str) -> Path:
    """Where `modsys eject` puts a skill's repo-owned copy."""
    return config_dir / "overrides" / "skills" / skill_id
