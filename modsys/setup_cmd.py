"""`modsys setup [--agent A]… [--target FILE]… [--dry-run]`: the one-command start (P6.1 D5).
Three existing steps run in-process, in order — each writes exactly what its own verb writes:

  init        bare `modsys init` (the starter config, the empty registry, the .gitignore
              lines) when `<config_dir>/config.toml` does not exist; else `exists`, not run
  packs sync  `modsys packs sync` for the agents: `--agent`, else `[packs] agents`, else the
              agents whose skill directories hold copies an earlier sync made (a marker in
              `.agents/skills` means codex), else claude and codex
  agents-md   `modsys agents-md` for the targets: `--target`, else CLAUDE.md when claude is
              chosen and AGENTS.md when any other agent is (Gemini CLI reads GEMINI.md:
              `--target GEMINI.md`)

Each step reports one status — `created` (only new files or copies), `updated` (an existing one
changed), `unchanged`, `exists` (init: the config was there), `skipped` (packs sync: no skill to
copy), `conflict` / `invalid` (packs sync left a copy unwritten) — and its own `--json` data as
`detail` (null for a step that did not run). A second run writes nothing. `--dry-run` writes
nothing and plans the later steps against the config init would write: a scratch config dir
outside the repository holding that config.toml beside the real config dir's packs, overrides
and config.user.toml. A step that refuses (exit 2) stops setup at once, naming the step and what
ran before it; a packs sync conflict (exit 1) lets agents-md run, and setup exits 1. Root:
`--root`, else the git top-level of the current directory, else the current directory (as
`init`)."""
import contextlib
import functools
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from modsys.agents_md_cmd import _target, agents_md
from modsys.config import builtin_delivery
from modsys.init_cmd import init_root, plan_init, starter
from modsys.output import EXIT_FINDINGS, EXIT_OK, UsageError, emit
from modsys.packs_cmd import _hint, sync as packs_sync
from modsys.skill_sync import STATUSES, managed_agents
from modsys.skills import AGENT_DIRS, DEFAULT_AGENTS
from modsys.workspace import Workspace

FINDINGS = ("conflict", "invalid")  # packs sync rows it did not write: exit 1, the run goes on
CHANGED = ("updated", "added", "removed")  # an existing file or copy changed
PLANNING_READS = ("packs", "overrides", "config.user.toml")  # besides config.toml
_WORDS = {"created": ("created", "would create"), "updated": ("updated", "would update")}


def register(sub, common) -> None:
    p = sub.add_parser("setup", parents=[common],
                       help="the one-command start: starter config and registry, the skill "
                            "copies, the agents-md block (idempotent)",
                       description="Runs three steps in order: init (the starter config, the "
                                   "empty registry and the .gitignore lines — exists when "
                                   "<config_dir>/config.toml does), packs sync for the agents "
                                   "and agents-md for the instruction files. Agents: --agent, "
                                   "else [packs] agents, else the agents whose skill "
                                   "directories already hold copies packs sync made, else "
                                   "claude and codex. Targets: --target, else CLAUDE.md when "
                                   "claude is chosen and AGENTS.md when any other agent is; "
                                   "Gemini CLI reads GEMINI.md: add --target GEMINI.md. A "
                                   "second run writes nothing. A refused step stops setup "
                                   "(exit 2, naming the step); a skill copy in conflict lets "
                                   "the later steps run and setup exits 1.")
    p.add_argument("--agent", action="append", dest="agents",
                   metavar="claude|codex|cursor|gemini|copilot",
                   help="an agent to copy the pack skills for (repeatable; default: [packs] "
                        "agents, else the agents an earlier packs sync wrote for, else claude "
                        "and codex)")
    p.add_argument("--target", action="append", dest="targets", metavar="FILE",
                   help="a root-relative instruction file for the modsys block (repeatable; "
                        "default: CLAUDE.md for claude, AGENTS.md for the other agents; for "
                        "Gemini CLI: --target GEMINI.md)")
    p.add_argument("--dry-run", action="store_true",
                   help="report what each step would do, write nothing")
    p.set_defaults(func=run)


@dataclass
class _Planned(Workspace):
    """A dry run's workspace before init wrote the config: it reads a scratch config dir, and
    shows the paths inside it as the real config dir's (`rel`)."""
    shown_as: Path | None = None

    def rel(self, path) -> str:
        path = Path(os.path.normpath(Path(path).absolute()))
        with contextlib.suppress(ValueError):
            path = self.shown_as / path.relative_to(self.config_dir)
        return super().rel(path)


def _mirror(src: Path, dst: Path) -> None:
    try:
        dst.symlink_to(src, target_is_directory=src.is_dir())
    except OSError:  # no symlinks here (Windows without the privilege): a copy reads the same
        if src.is_dir():
            shutil.copytree(src, dst, symlinks=True)
        else:
            shutil.copy2(src, dst)


@contextlib.contextmanager
def _workspace(root: Path, config_dir: Path, pending: str | None):
    """The workspace the later steps read: the real one, or — a dry run whose init would
    create the config (`pending`: its text) — one that reads that config without writing it."""
    if pending is None:
        yield Workspace.load(root, config_dir)
        return
    with tempfile.TemporaryDirectory(prefix="modsys-setup-") as tmp:
        scratch = Path(tmp).resolve() / "config"
        scratch.mkdir()
        with open(scratch / "config.toml", "w", encoding="utf-8", newline="\n") as fh:
            fh.write(pending)
        for name in PLANNING_READS:
            if os.path.lexists(config_dir / name):
                _mirror(config_dir / name, scratch / name)
        ws = _Planned.load(root, scratch)
        ws.shown_as = config_dir
        yield ws


def choose_agents(ws, flags: list[str] | None) -> list[str]:
    """`--agent`, else `[packs] agents`, else the agents a bare `packs sync` infers from the
    skill directories, else claude and codex — in order, each once."""
    configured = (ws.config.get("packs") or {}).get("agents")
    return list(dict.fromkeys(flags or configured or managed_agents(ws.root)
                              or DEFAULT_AGENTS))


def default_targets(agents: list[str]) -> list[str]:
    return (["CLAUDE.md"] if "claude" in agents else []) + \
        (["AGENTS.md"] if any(a != "claude" for a in agents) else [])


def _fold(statuses: list[str]) -> str:
    if any(s in CHANGED for s in statuses):
        return "updated"
    return "created" if "created" in statuses else "unchanged"


def sync_status(data: dict) -> str:
    rows = [r["status"] for r in data["skills"]]
    for finding in FINDINGS:
        if finding in rows:
            return finding
    return _fold(rows) if rows else "skipped"


def _stopped(step: str, error: UsageError, steps: list[dict], dry_run: bool) -> UsageError:
    """A step's refusal: its own message, then what the steps before it did."""
    notes = ["dry run: nothing written"] if dry_run else []
    if steps:
        notes.append("before it: " + ", ".join(f"{s['step']} {s['status']}" for s in steps))
    return UsageError(f"setup stopped at {step}: {error}"
                      + (f" ({'; '.join(notes)})" if notes else ""))


def setup(root: Path, config_dir: Path, agents: list[str] | None, targets: list[str] | None,
          dry_run: bool) -> tuple[dict, Workspace]:
    """Run (or plan) the three steps; (data, the workspace the later steps read). Flags are
    checked before any step; a step's refusal stops the run (exit 2, naming the step)."""
    for agent in agents or []:
        if agent not in AGENT_DIRS:
            raise UsageError(f"unknown agent {agent!r} (agents: {', '.join(AGENT_DIRS)})")
    targets = [_target(SimpleNamespace(root=root), t)[0] for t in targets or []]
    steps, pending = [], None
    config = config_dir / "config.toml"
    if config.exists():
        steps.append({"step": "init", "status": "exists", "detail": None})
    else:
        try:
            layout, files = starter(root, config_dir, None, dry_run)
            if dry_run:
                pending = next(t for p, s, t in plan_init(root, config_dir, None)[1]
                               if p == config)
        except UsageError as e:
            raise _stopped("init", e, steps, dry_run) from None
        steps.append({"step": "init", "status": "created",
                      "detail": {"root": str(root), "layout": layout, "files": files,
                                 "dry_run": dry_run}})
    step = "packs sync"
    try:
        with _workspace(root, config_dir, pending) as ws:
            chosen = choose_agents(ws, agents)
            targets = targets or default_targets(chosen)
            synced = packs_sync(ws, chosen, check=False, dry_run=dry_run)
            steps.append({"step": step, "status": sync_status(synced), "detail": synced})
            step = "agents-md"
            written = agents_md(ws, targets, check=False, dry_run=dry_run)
            steps.append({"step": step, "status": _fold([t["status"]
                                                         for t in written["targets"]]),
                          "detail": written})
    except UsageError as e:
        raise _stopped(step, e, steps, dry_run) from None
    return {"dry_run": dry_run, "agents": chosen, "targets": targets, "steps": steps}, ws


def run(args) -> int:
    root = init_root(args.root)
    config_dir = Path(args.config_dir or root / ".modsys").resolve()
    data, ws = setup(root, config_dir, args.agents, args.targets, args.dry_run)
    emit("setup", data, args.json, functools.partial(_render, ws=ws))
    failed = any(s["status"] in FINDINGS for s in data["steps"])
    return EXIT_FINDINGS if failed else EXIT_OK


def _copies(n: int) -> str:
    return f"{n} skill cop{'y' if n == 1 else 'ies'}"


def _items(rows: list[dict], status: str) -> str:
    """Paths, each with its own status when it is not the step's."""
    out = []
    for r in rows:
        own = f"same file as {r['same_as']}" if r.get("same_as") else r["status"]
        out.append(r["path"] + (f" ({own})" if own != status else ""))
    return ", ".join(out)


def _summary(s: dict, ws) -> str:
    d = s["detail"]
    if s["step"] == "init":
        return (_items(d["files"], "created") if d
                else ws.rel(ws.config_dir / "config.toml"))
    if s["step"] == "agents-md":
        return _items(d["targets"], s["status"])
    if not d["skills"]:  # under builtin_delivery = "plugin" a note names the plugins
        return ("nothing to copy" if builtin_delivery(ws.config) == "plugin"
                else "no pack skills (add one: modsys packs new ID --skill NAME)")
    counts = [f"{d['summary'][k]} {k}" for k in STATUSES if d["summary"][k]]
    return _copies(len(d["skills"])) + (f" ({', '.join(counts)})" if len(counts) > 1 else "")


def _render(d, ws) -> None:
    for s in d["steps"]:
        word = _WORDS.get(s["status"], (s["status"],) * 2)[d["dry_run"]]
        print(f"{s['step']:<11} {word:<12} {_summary(s, ws)}")
        if s["step"] != "packs sync":
            continue
        for r in s["detail"]["skills"]:
            if r["status"] in FINDINGS:
                print(f"  {r['status']:<9} {r['agent']:<7} {r['dir']}")
                hint = _hint(ws, r)
                print(f"    {r['reason']}" + (f" — {hint}" if hint else ""))
        for note in s["detail"]["notes"]:
            print(f"  note: {note}")
    print(f"{'agents':<11} {', '.join(d['agents'])}")
    print(f"{'targets':<11} {', '.join(d['targets'])}")
    if d["dry_run"]:
        print("dry run: nothing written")
    for s in d["steps"]:
        if s["status"] in FINDINGS:
            n = sum(s["detail"]["summary"][k] for k in FINDINGS)
            print(f"setup: {s['step']} left {_copies(n)} unwritten — resolve "
                  f"{'it' if n == 1 else 'them'} as shown above, then run modsys setup again")
