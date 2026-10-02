"""`modsys choose` (P8.1 S3): the work order an agent answers to pick modules by meaning, and
the validation of its answer. `choose --task T` prints the work order (a prompt; `--json` the
document); `choose --apply FILE|-` validates an answer offline and prints the picks with each
module's read set; `choose --task T --run` asks the user's own agent command (`[agent]`, see
`modsys.agent`) and prints the same. Read-only: no lock, no write, no cache."""
import json
import sys
from pathlib import Path

from modsys import agent, workorder
from modsys.output import EXIT_OK, UsageError, emit
from modsys.query import show_target
from modsys.semantic import NO_AGENT, agent_configured
from modsys.workspace import Workspace


def register(sub, common) -> None:
    p = sub.add_parser("choose", parents=[common],
                       help="the work order for choosing modules by meaning, and its answer",
                       description="Print the work order for choosing modules by meaning "
                                   "(--task), validate an agent's answer to it (--apply "
                                   "FILE|-), or ask the agent command of [agent] (--run).")
    p.add_argument("--task", help="the task text, any language")
    p.add_argument("--top", type=int, help="at most N picks (default 5)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--apply", metavar="FILE", help="validate an answer ('-' = stdin)")
    g.add_argument("--run", action="store_true", help="ask the agent command of [agent]")
    p.set_defaults(func=run)


def _read_answer(source: str):
    try:
        text = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise UsageError(f"{source}: cannot read the answer: {e}") from None
    if not text.strip():
        raise UsageError(f"{source}: the answer is empty (expected a JSON object)")
    try:
        return json.loads(text)
    except ValueError as e:
        raise UsageError(f"{source}: the answer is not JSON: {e}") from None


def _with_read_sets(ws, picks: list[dict]) -> list[dict]:
    out = []
    for p in picks:
        _, shown = show_target(ws, p["module"], None, False)
        out.append({**p, "read": shown["read"]})
    return out


def run(args) -> int:
    top = args.top
    if top is not None and top < 1:
        raise UsageError("--top must be >= 1")
    ws = Workspace.from_args(args)
    max_picks = workorder.DEFAULT_MAX_PICKS if top is None else top
    if args.apply is None and not args.run:
        if args.task is None or not args.task.strip():
            raise UsageError("give the task: --task TEXT (or --apply FILE to validate an answer)")
        emit("choose", workorder.build(ws, args.task, max_picks), args.json, workorder.render)
        return EXIT_OK
    if args.run:
        if args.task is None or not args.task.strip():
            raise UsageError("--run needs --task TEXT")
        if not agent_configured(ws.config):
            raise UsageError(NO_AGENT)
    order = workorder.build(ws, args.task or "", max_picks)
    check = lambda answer: workorder.validate_answer(answer, order, max_picks)  # noqa: E731
    picks, none, notes = agent.run(ws.config, order, order["answer_schema"], check) \
        if args.run else check(_read_answer(args.apply))
    data = {"picks": _with_read_sets(ws, picks), "none": none, "notes": notes,
            "max_picks": max_picks}
    emit("choose", data, args.json, _render)
    return EXIT_OK


def _render(d) -> None:
    if not d["picks"]:
        print("no module chosen")
    for p in d["picks"]:
        reason = f"  {p['reason']}" if p.get("reason") else ""
        print(f"{p['confidence']:.2f}  {p['module']}{reason}")
        for r in p["read"]:
            mark = "" if r["exists"] else "  (MISSING ON DISK)"
            print(f"      read  {r['label']:<28} {r['path']}{mark}")
    for n in d["notes"]:
        print(f"note: {n}")
