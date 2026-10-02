"""`modsys choose` (P8.1 S3): the work order an agent answers to pick modules by meaning, and
the validation of its answer. `choose --task T` (or `--task-file PATH|-`) prints the work order
(a prompt; `--json` the document); `choose --apply FILE|-` validates an answer offline and prints
the picks with each module's read set; `choose --task T --run` asks the user's own agent command
(`MODSYS_AGENT_COMMAND`, see `modsys.agent`) and prints the same. `--apply` and `--run` read an
answer the same way (`agent.unwrap`). Read-only: no lock, no write, no cache."""
import json
import sys
from pathlib import Path

from modsys import agent, workorder
from modsys.catalog_cmd import cards
from modsys.output import EXIT_OK, UsageError, emit
from modsys.pipeline import task_text
from modsys.query import show_target
from modsys.semantic import NO_AGENT, NO_CARDS_NOTE, agent_configured
from modsys.workspace import Workspace

NO_TASK = "give the task: --task TEXT or --task-file FILE (or --apply FILE to validate an answer)"


def register(sub, common) -> None:
    p = sub.add_parser("choose", parents=[common],
                       help="the work order for choosing modules by meaning, and its answer",
                       description="Print the work order for choosing modules by meaning "
                                   "(--task or --task-file), validate an agent's answer to it "
                                   "(--apply FILE|-), or ask your agent command, "
                                   "MODSYS_AGENT_COMMAND (--run).")
    t = p.add_mutually_exclusive_group()
    t.add_argument("--task", help="the task text, any language")
    t.add_argument("--task-file", type=Path, metavar="FILE",
                   help="read the task text from FILE ('-' = stdin)")
    p.add_argument("--top", type=int, help="at most N picks (default 5)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--apply", metavar="FILE", help="validate an answer ('-' = stdin)")
    g.add_argument("--run", action="store_true",
                   help="ask the agent command in MODSYS_AGENT_COMMAND")
    p.set_defaults(func=run)


def _read_answer(source: str):
    """The answer object in FILE or stdin: the answer itself or an agent's JSON envelope, read
    as `--run` reads the agent's stdout (`agent.unwrap`)."""
    try:
        text = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise UsageError(f"{source}: cannot read the answer: {e}") from None
    if not text.strip():
        raise UsageError(f"{source}: the answer is empty (expected a JSON object)")
    try:
        doc = json.loads(text)
    except ValueError as e:
        raise UsageError(f"{source}: the answer is not JSON: {e}") from None
    return agent.unwrap(doc, "answer", "stdin" if source == "-" else source)


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
    task = ""
    if args.apply is None:  # the work order and --run need the task; --apply does not
        if args.task is None and args.task_file is None:
            raise UsageError("--run needs --task TEXT or --task-file FILE" if args.run
                             else NO_TASK)
        task = task_text(args)
        if not args.run:
            emit("choose", workorder.build(ws, task, max_picks), args.json, workorder.render)
            return EXIT_OK
        if not agent_configured(ws.config):
            raise UsageError(agent.NESTED if agent.nested() else NO_AGENT)
    order = workorder.build(ws, task, max_picks)
    check = lambda answer: workorder.validate_answer(answer, order, max_picks)  # noqa: E731
    if not args.run:
        picks, none, notes = check(_read_answer(args.apply))
    elif not cards(ws.registry.modules):  # nothing to choose from: no agent call (M-2)
        picks, none, notes = [], False, [NO_CARDS_NOTE]
    else:
        picks, none, notes = agent.run(ws.config, order, order["answer_schema"], check,
                                       cwd=ws.root)
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
