import json
from pathlib import Path

from modsys import create as creator
from modsys.output import EXIT_OK, UsageError, emit
from modsys.workspace import Workspace


def register(sub, common) -> None:
    p = sub.add_parser("create", parents=[common],
                       help="scaffold a module (or --parent child): docs + registry entry")
    p.add_argument("name")
    p.add_argument("--parent", help="create a child of this module")
    p.add_argument("--answers", type=Path, help="JSON object: description, keywords, status, "
                                                "tags, roles, and ask_on_create fields")
    p.add_argument("--description")
    p.add_argument("--keyword", action="append", dest="keywords", help="repeatable")
    p.add_argument("--status")
    p.add_argument("--tag", action="append", dest="tags", help="repeatable (applies_when roles)")
    p.add_argument("--role", action="append", dest="roles", help="repeatable (optional roles)")
    p.add_argument("--non-interactive", action="store_true", help="never prompt; fail on gaps")
    p.add_argument("--dry-run", action="store_true", help="show files and entry, write nothing")
    p.set_defaults(func=run)


def _answers(args) -> dict:
    answers = {}
    if args.answers:
        try:
            answers = json.loads(args.answers.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise UsageError(f"{args.answers}: cannot read answers: {e}") from None
        if not isinstance(answers, dict):
            raise UsageError(f"{args.answers}: answers must be a JSON object")
    for key in ("description", "keywords", "status", "tags", "roles"):
        if getattr(args, key) is not None:
            answers[key] = getattr(args, key)
    return answers


def run(args) -> int:
    ws = Workspace.from_args(args)
    answers = _answers(args)
    missing = creator.validate_answers(ws, answers, "submodule" if args.parent else "module")
    if missing and not args.non_interactive and creator.interactive():
        answers = creator.prompt_missing(ws, answers, missing)
    plan = creator.plan_create(ws, args.name, args.parent, answers)
    if not args.dry_run:
        creator.apply_create(ws, plan)
    data = {"module": plan["module"], "files": sorted(plan["files"]), "entry": plan["entry"],
            "dry_run": args.dry_run}
    emit("create", data, args.json, _render)
    return EXIT_OK


def _render(d) -> None:
    verb = "would create" if d["dry_run"] else "created"
    for f in d["files"]:
        print(f"{verb}  {f}")
    print(f"{'would register' if d['dry_run'] else 'registered'}  {d['module']}")
