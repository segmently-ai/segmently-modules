"""`modsys next [--base REF]`: what the repository needs now — one ranked list, each item with
the modsys command that fixes it. Read-only: it composes in-process what plain `lint`, `packs
sync --check`, `agents-md --check`, `roles list`, `proposals list`, `coverage` and the drift of
`ci` report; it writes nothing, takes no lock and keeps no state. What an engine upgrade brought
shows up the same way (D2): a standard role without docs, stale skill copies, a stale block, an
ejected skill behind its pack — derived from the repository, never from a "last seen version".

The kinds, in rank order (D4):
  lint-error    one per plain-lint error: `modsys lint`; a registered role doc missing on disk
                (MS004) `modsys roles add ROLE TARGET --recreate` (SI-P61-7)
  skills        one for the copies `packs sync --check` finds stale, missing, to remove or in
                conflict — agents resolved as a bare `packs sync` resolves them (SI-P61-5)
  agents-md     one per instruction file at the root (CLAUDE.md, AGENTS.md, GEMINI.md,
                .github/copilot-instructions.md) that holds a modsys block differing from its
                render (SI-P61-4)
  role          one per enabled standard role that some module or child has no doc for
  ejected       one per ejected skill lint MS063 warns about (`eject --diff SKILL` when it is
                behind its pack)
  proposals     the pending proposal files
  lint-warning  the other lint warnings, counted, with their codes (MS063 never twice, SI-P61-6)
  unmapped      the files no module maps — only with a `[[code_map]]` rule, inside git
  drift         with --base: MS050 / MS051 since REF (`sync-instructions --from-diff REF..HEAD`)
A kind that cannot run is named in `skipped` (JSON only) with the reason. No config and no
registry: one item, `modsys setup` (SI-P61-8). Exit 0 with or without items."""
import contextlib
import os
import re
import shutil
import tempfile
from pathlib import Path
from shlex import quote

from modsys import __version__
from modsys.agents_md_cmd import _BEGIN, END, _bare, _lines, agents_md
from modsys.changes import commit_ref, git, repo_files, work_tree_error
from modsys.config import enabled_roles
from modsys.coverage_cmd import coverage_report
from modsys.lint import drift_report, lint_registry
from modsys.output import EXIT_OK, UsageError, emit
from modsys.packs_cmd import sync as packs_sync
from modsys.proposals import pending
from modsys.registry import as_list
from modsys.roles_cmd import role_rows
from modsys.skill_sync import managed_agents
from modsys.workspace import Workspace, find_root

INSTRUCTION_FILES = ("CLAUDE.md", "AGENTS.md", "GEMINI.md", ".github/copilot-instructions.md")
COPY_STATES = (("updated", "stale"), ("created", "missing"), ("removed", "to remove"),
               ("conflict", "in conflict"))  # `packs sync` statuses -> how the item names them
NOT_SET_UP = "modsys is not set up here: no config, no registry"
NO_AGENT = ("no agent to check: [packs] agents is not set and no agent's skill directory holds "
            "a copy packs sync made")
_ROLE_DOC = re.compile(r"(?:^|\.)context_files\.roles\.([^.\[\]\s]+)(?:\[\])? path missing on "
                       r"disk$")  # lint MS004 on a registered role doc
_SKILL = re.compile(r"skill '([^']+)'")
_BEHIND, _REVIEW = " is behind pack ", " — review: "  # lint MS063: behind, and its hint


class Skip(Exception):
    """A kind that cannot run here; the message is the reason `skipped` gives."""


def register(sub, common) -> None:
    p = sub.add_parser("next", parents=[common],
                       help="what the repository needs now: one ranked list, each item with "
                            "the command that fixes it (read-only)",
                       description="One ranked list: lint errors, stale or missing skill "
                                   "copies and stale agents-md blocks, standard roles without "
                                   "docs, ejected skills behind their pack, pending proposals, "
                                   "lint warnings, unmapped files (with a [[code_map]] rule), "
                                   "drift since --base — each with the modsys command that "
                                   "fixes it. Also what an engine upgrade brought. Writes "
                                   "nothing; exit 0 with or without items.")
    p.add_argument("--base", metavar="REF",
                   help="also report the drift since REF (code changed without a doc update), "
                        "e.g. the target branch")
    p.set_defaults(func=run)


def _root(args) -> Path:
    """`--root`, else the root `find_root` finds, else the current directory: a directory with
    no root marker and no git above it is a place where modsys is not set up yet."""
    if args.root:
        return args.root
    try:
        return find_root(Path.cwd())
    except UsageError:
        return Path.cwd()


def _set_up(ws) -> bool:
    return ((ws.config_dir / "config.toml").exists()
            or (ws.root / ws.config["paths"]["registry"]).exists())


def lint_errors(ws, findings: list) -> list[tuple]:
    """One item per plain-lint error; MS004 on a role doc of an enabled role points at `roles
    add ROLE TARGET --recreate`, which writes it (SI-P61-7)."""
    enabled, out = set(enabled_roles(ws.config)), []
    for f in findings:
        if f.severity != "error":
            continue
        role = _ROLE_DOC.search(f.message) if f.code == "MS004" and f.path else None
        command = (f"modsys roles add {quote(role.group(1))} {quote(f.module)} --recreate"
                   if role and role.group(1) in enabled else "modsys lint")
        where = f" ({f.path})" if f.path else ""
        out.append(("lint-error", f"{f.code} {f.module}: {f.message}{where}", command))
    return out


def skill_copies(ws) -> list[tuple]:
    """The copies a bare `packs sync --check` finds not in sync (its agents, its delivery
    rules), named by state."""
    if not ((ws.config.get("packs") or {}).get("agents") or managed_agents(ws.root)):
        raise Skip(NO_AGENT)
    data = packs_sync(ws, None, check=True, dry_run=False)
    parts = []
    for status, label in COPY_STATES:
        names = sorted({r["skill"] for r in data["skills"] if r["status"] == status})
        if names:
            parts.append(f"{label} {', '.join(names)}")
    if not parts:
        return []
    return [("skills", f"skill copies not in sync ({', '.join(data['agents'])}): "
                       f"{'; '.join(parts)}", "modsys packs sync")]


def _holds_block(path: Path) -> bool:
    text = path.read_bytes().decode("utf-8", errors="replace")
    return any(_BEGIN.fullmatch(_bare(line)) or _bare(line) == END for line in _lines(text))


def stale_blocks(ws, skipped: list[str]) -> list[tuple]:
    """One item per instruction file at the root that holds a modsys block differing from its
    render (`agents-md --check`); a file without a block is none of `next`'s business, one that
    cannot be checked (malformed markers, not UTF-8) is named in `skipped`. A file that is
    another one's symlink counts once."""
    out, seen = [], set()
    for rel in INSTRUCTION_FILES:
        path = ws.root / rel
        try:
            if not path.is_file() or os.path.realpath(path) in seen or not _holds_block(path):
                continue
        except OSError as e:
            skipped.append(f"agents-md: cannot read {rel}: {e.strerror or e}")
            continue
        seen.add(os.path.realpath(path))
        try:
            status = agents_md(ws, [rel], check=True, dry_run=False)["targets"][0]["status"]
        except UsageError as e:
            skipped.append(f"agents-md: {e}")
            continue
        if status != "unchanged":
            out.append(("agents-md", f"{rel}: the modsys block is stale",
                        f"modsys agents-md --target {quote(rel)}"))
    return out


def missing_roles(ws) -> list[tuple]:
    """One item per enabled standard role with targets (modules, children) that have no doc."""
    return [("role", f"{r['name']}: no doc in {len(r['missing'])} module(s)",
             f"modsys roles add {quote(r['name'])} --all")
            for r in role_rows(ws, enabled_only=True) if r["standard"] and r["missing"]]


def ejected(findings: list) -> list[tuple]:
    """One item per ejected skill a lint MS063 warning names, by skill id: behind its pack →
    `eject --diff`; any other MS063 warning (a symlink, no valid record, an unreadable pack
    file) → lint's message and `modsys lint`."""
    out = {}
    for f in findings:
        if f.code != "MS063" or f.severity != "warning":
            continue
        name = _SKILL.search(f.message)
        sid = name.group(1) if name else f.path or ""
        if sid in out:
            continue
        if _BEHIND in f.message:
            out[sid] = ("ejected", f.message.split(_REVIEW)[0], f"modsys eject --diff {quote(sid)}")
        else:
            out[sid] = ("ejected", f.message, "modsys lint")
    return [out[sid] for sid in sorted(out)]


def proposals(ws) -> list[tuple]:
    files = pending(ws)
    if not files:
        return []
    items = sum(len(doc["items"]) for _, doc in files if isinstance(doc.get("items"), list))
    return [("proposals", f"{len(files)} pending proposal file(s), {items} item(s)",
             "modsys proposals list")]


def lint_warnings(findings: list) -> list[tuple]:
    warnings = [f for f in findings if f.severity == "warning" and f.code != "MS063"]
    if not warnings:
        return []
    codes = ", ".join(sorted({f.code for f in warnings}))
    return [("lint-warning", f"{len(warnings)} lint warning(s): {codes}", "modsys lint")]


UNMAPPED_SHOWN = 3


def unmapped(ws, no_git: str | None) -> list[tuple]:
    if not as_list(ws.config.get("code_map")):
        raise Skip("no [[code_map]] rule")
    if no_git:
        raise Skip(no_git)
    files = coverage_report(ws, repo_files(ws.root))["unmapped"]
    if not files:
        return []
    shown = ", ".join(files[:UNMAPPED_SHOWN]) + (", …" if len(files) > UNMAPPED_SHOWN else "")
    return [("unmapped", f"{len(files)} file(s) map to no module: {shown}", "modsys coverage")]


@contextlib.contextmanager
def index_copy(root: Path):
    """`{"GIT_INDEX_FILE": <a copy of the repository's index>}` for the git calls of `drift`:
    `git diff` against the working tree rewrites the index (through `index.lock`) whenever a
    tracked file is stat-dirty, so it refreshes a copy in a temp dir outside the root instead —
    the same answer, the real index untouched. No index file: none is copied (git reads an
    empty one, as it would). The temp dir goes on every exit, Ctrl-C included."""
    real = Path(git(root, "rev-parse", "--git-path", "index").rstrip("\n"))
    real = real if real.is_absolute() else Path(root) / real  # relative to `-C root`
    tmp = Path(tempfile.mkdtemp(prefix="modsys-next-"))
    try:
        copy = tmp / "index"
        if real.is_file():
            shutil.copy2(real, copy)  # its mtime too: git's racy-entry check reads it
        yield {"GIT_INDEX_FILE": str(copy)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def drift(ws, base: str | None, no_git: str | None) -> list[tuple]:
    """`ci`'s drift since `base` (the working tree and new files against it): the targets
    whose code changed without a doc update (MS050) and frozen snapshots changed (MS051) —
    computed against a copy of the git index (`index_copy`)."""
    if base is None:
        raise Skip("no --base")
    if no_git:
        raise Skip(no_git)
    with index_copy(ws.root) as env:
        findings, _ = drift_report(ws, base, [], env=env)
    parts = []
    for code, what in (("MS050", "code changed without a doc update"),
                       ("MS051", "a frozen snapshot changed")):
        targets = sorted({f.module for f in findings if f.code == code})
        if targets:
            parts.append(f"{what}: {', '.join(targets)}")
    if not parts:
        return []
    return [("drift", f"drift since {base}: {'; '.join(parts)}",
             f"modsys sync-instructions --from-diff {quote(f'{base}..HEAD')}")]


def plan(ws, base: str | None) -> dict:
    """{version, items: [{rank, kind, summary, command}], skipped: ["<kind>: <reason>"]}."""
    found: list[tuple] = []
    skipped: list[str] = []
    if not _set_up(ws):
        found.append(("setup", NOT_SET_UP, "modsys setup"))
    else:
        no_git = work_tree_error(ws.root)
        if base is not None and not no_git:
            base = commit_ref(ws.root, base, origin="flag")  # an unknown ref: exit 2
        findings = lint_registry(ws)

        def kind(name: str, compute, cannot=(Skip, UsageError)) -> None:
            try:
                found.extend(compute())
            except cannot as e:  # this kind cannot run here; the others still do
                skipped.append(f"{name}: {e}")

        found.extend(lint_errors(ws, findings))
        kind("skills", lambda: skill_copies(ws))
        found.extend(stale_blocks(ws, skipped))
        found.extend(missing_roles(ws))
        found.extend(ejected(findings))
        kind("proposals", lambda: proposals(ws))
        found.extend(lint_warnings(findings))
        kind("unmapped", lambda: unmapped(ws, no_git))
        kind("drift", lambda: drift(ws, base, no_git), cannot=Skip)  # git errors: exit 2
    items = [{"rank": rank, "kind": k, "summary": summary, "command": command}
             for rank, (k, summary, command) in enumerate(found, 1)]
    return {"version": __version__, "items": items, "skipped": skipped}


def run(args) -> int:
    ws = Workspace.load(_root(args), args.config_dir)
    emit("next", plan(ws, args.base), args.json, _render)
    return EXIT_OK


def _render(d) -> None:
    print(f"modsys {d['version']}")
    if not d["items"]:
        print("nothing to do")
    for item in d["items"]:
        head = f"{item['rank']}. "
        print(f"{head}{item['summary']}")
        print(f"{' ' * len(head)}{item['command']}")
