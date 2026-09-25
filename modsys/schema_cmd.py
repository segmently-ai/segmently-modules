import json

from modsys.fields import to_json_schema
from modsys.output import EXIT_OK, emit
from modsys.workspace import Workspace


def register(sub, common) -> None:
    p = sub.add_parser("schema", parents=[common], help="print the registry JSON Schema")
    p.set_defaults(func=run)


def run(args) -> int:
    ws = Workspace.from_args(args)
    schema = to_json_schema(ws.fields, ws.config["registry"]["statuses"])
    emit("schema", schema, args.json, lambda d: print(json.dumps(d, indent=2)))
    return EXIT_OK
