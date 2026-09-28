"""A fake `init` executor for the tests and the adoption eval: it writes, from a work item alone,
deterministic docs a writer agent could have written — no model, stdlib only. Run as
`python3 tests/init_fake_executor.py [switches]` by `modsys init run --executor …` (stdin = the
prompt; env MODSYS_INIT_MODULE, MODSYS_INIT_STAGING, MODSYS_INIT_WORK), or import `write_docs`.
Run by `modsys init eval-tasks --executor …` (env MODSYS_INIT_TASKS), it writes that file: five
tasks per module of the staging registry, each naming two of its keywords (`--tasks-mode`
spoils them on purpose).

The bookshop_monorepo modules get the texts of `CANNED` (one keyword, `price`, is shared by
`catalog` and `cart`: the collision `init reconcile` finds); any other module gets texts built
from its name. `storefront` writes one edge of its own (to `catalog`, `complements`).

Switches (anything else on the command line is ignored, so a test can pass odd arguments):
  --record LOG        append a JSON line per start and end: {event, module, argv, stdin_sha256,
                      env (the MODSYS_* variables), cwd, time, pid}
  --stop-after N      calls are counted in LOG.calls/ (one file per call, created exclusively);
                      the call after the Nth writes a partial MODULE.md and partial.tmp, then
                      kills its parent (the `init run`) with SIGKILL
  --stop-group N      the same, but it kills its whole process group: the `init run` and every
                      executor it runs (start the run in a session of its own)
  --fail MODULE       for MODULE: print 50 stderr lines (`--lines N`), exit 3
  --keywords4 MODULE  for MODULE: an entry.json with 4 keywords
  --nothing MODULE    for MODULE: write nothing, exit 0
  --outside PATH      also write PATH (root-relative) — a write outside the staging dir
  --peers K --live D  create D/<module>, then wait (up to 10 s) until D holds K files
  --sleep S           sleep S seconds before writing
  --pids D            write D/<pid> at the start
  --tasks-mode MODE   eval-tasks: `unknown` (one task names `nosuch`), `partial` (the last module
                      gets none), `invalid` (not JSON), `nothing` (no file), `fail` (exit 3),
                      `half` (six tasks per module, three name the next one: hit rate 0.5)"""
import hashlib
import json
import os
import signal
import sys
import time
from pathlib import Path

CANNED = {  # module -> (description, keywords, purpose paragraph)
    "catalog": ("Book titles, authors and ISBN lookups: the books the shop sells.",
                ["catalog", "book", "books", "isbn", "author", "title", "price"],
                "Finds a book by its ISBN and formats its price for display."),
    "cart": ("The reader's cart: lines, quantities and totals before checkout.",
             ["cart", "basket", "line", "total", "quantity", "price"],
             "Adds up the lines a reader has chosen, one price at a time."),
    "ui-kit": ("Buttons, text fields and labels shared by the shop's pages.",
               ["button", "field", "form", "label", "widget"],
               "The reusable pieces every page is built from."),
    "storefront": ("The shop window: the book page a reader sees and buys from.",
                   ["storefront", "page", "shop", "window", "render"],
                   "Renders the page of one book with its buy button."),
    "payments": ("Charges a customer for an order and refunds it when asked.",
                 ["payment", "charge", "refund", "customer", "gateway"],
                 "Talks to the payment gateway for every order."),
    "recommendations": ("Suggests the next book a reader may like from the reading history.",
                        ["recommendation", "suggest", "reader", "history", "score"],
                        "Scores the books a reader might want next."),
    "tools": ("Helper scripts: a weekly sales report and a seed of sample books.",
              ["script", "report", "seed", "sales", "weekly"],
              "Scripts a developer runs by hand, never in production."),
}
EDGES = {"storefront": [{"module": "catalog", "relation": "complements",
                         "description": "shows the books the catalog holds"}]}


def texts(item: dict) -> tuple[str, list[str], str]:
    name = item["module"]
    if name in CANNED:
        return CANNED[name]
    words = [w for w in name.replace("-", " ").split() if w]
    keywords = list(dict.fromkeys(words + [f"{name}-{s}" for s in
                                           ("code", "docs", "change", "fix", "test")]))
    return (f"The {name} module of this repository: its code and what it does.", keywords,
            f"The {name} code, in one place.")


def write_docs(root: Path, item: dict, staging: Path | None = None) -> None:
    """The staging output of one work item: MODULE.md, one doc per role, entry.json."""
    staging = staging or Path(root) / item["staging_dir"]
    description, keywords, purpose = texts(item)
    title = item["module"].replace("-", " ").title()
    rows = [f"| {Path(f).stem.replace('_', ' ')} | `{f}` | a file of the module |"
            for f in item["files"][:5]]
    module_md = "\n".join([f"# {title}", "", f"> {description}", "", "## Purpose", "", purpose,
                           "", "## EXISTING Components - DO NOT CREATE NEW", "",
                           "| Name | Path | Purpose |", "|------|------|---------|", *rows, "",
                           "## Usage", "", "Read the files above before a change.", ""])
    (staging / "roles").mkdir(parents=True, exist_ok=True)
    (staging / "MODULE.md").write_text(module_md, encoding="utf-8")
    for role in item["roles"]:
        (staging / "roles" / f"{role}.md").write_text(
            f"# {title} — {role}\n\nWhat a {role} needs to know: the code lives under "
            f"{', '.join(item['paths'])}.\n", encoding="utf-8")
    entry = {"description": description, "keywords": keywords}
    edges = [e for e in EDGES.get(item["module"], [])
             if e["module"] in {n["to"] for n in item["neighbours"]}]
    if edges:
        entry["related_modules"] = edges
    (staging / "entry.json").write_text(json.dumps(entry, indent=2) + "\n", encoding="utf-8")


def switches(argv: list[str]) -> dict:
    """The known `--name value` switches of argv; everything else is ignored."""
    out, known = {}, {"--record", "--stop-after", "--stop-group", "--fail", "--lines",
                      "--keywords4", "--nothing", "--outside", "--peers", "--live", "--sleep",
                      "--pids", "--tasks-mode"}
    for i, arg in enumerate(argv):
        if arg in known and i + 1 < len(argv):
            out[arg[2:]] = argv[i + 1]
    return out


def record(opts: dict, event: str, stdin: bytes) -> None:
    if "record" not in opts:
        return
    line = {"event": event, "module": os.environ.get("MODSYS_INIT_MODULE"), "argv": sys.argv,
            "stdin_sha256": hashlib.sha256(stdin).hexdigest(),
            "env": {k: v for k, v in os.environ.items() if k.startswith("MODSYS_")},
            "cwd": os.getcwd(), "time": time.time(), "pid": os.getpid()}
    with open(opts["record"], "a", encoding="utf-8") as fh:
        fh.write(json.dumps(line) + "\n")


def call_number(opts: dict) -> int:
    """This call's number (1, 2, …), counted with exclusively created files."""
    calls = Path(opts["record"] + ".calls")
    calls.mkdir(exist_ok=True)
    n = 1
    while True:
        try:
            os.close(os.open(calls / str(n), os.O_CREAT | os.O_EXCL))
            return n
        except FileExistsError:
            n += 1


def write_tasks(path: Path, mode: str | None) -> int:
    """The routing tasks of every module of the staging registry next to `path`."""
    if mode == "fail":
        print("the task writer gave up", file=sys.stderr)
        return 3
    if mode == "nothing":
        return 0
    if mode == "invalid":
        path.write_text("{not json", encoding="utf-8")
        return 0
    registry = json.loads((path.parent / "staging/registry.json").read_text(encoding="utf-8"))
    targets = {}
    for name, entry in registry["modules"].items():
        targets[name] = entry["keywords"]
        for child, sub in (entry.get("submodules") or {}).items():
            targets[f"{name}/{child}"] = sub["keywords"]
    names = sorted(targets)
    if mode == "partial":
        names = names[:-1]
    per = 6 if mode == "half" else 5
    tasks = [{"task": f"change how the {kws[i % len(kws)]} and the {kws[(i + 1) % len(kws)]} "
                      f"work", "module": name}
             for name in names for kws in [targets[name]] for i in range(per)]
    if mode == "half":  # three of each module's six name the next module: hit rate 0.5
        for i, task in enumerate(tasks):
            if i % 6 < 3:
                task["module"] = names[(names.index(task["module"]) + 1) % len(names)]
    if mode == "unknown":
        tasks.append({"task": "change how the nothing works", "module": "nosuch"})
    path.write_text(json.dumps(tasks, indent=2) + "\n", encoding="utf-8")
    return 0


def main() -> int:
    opts = switches(sys.argv[1:])
    stdin = sys.stdin.buffer.read()  # the prompt: this fake writes from the work item alone
    if "MODSYS_INIT_TASKS" in os.environ:
        record(opts, "tasks", stdin)
        return write_tasks(Path(os.environ["MODSYS_INIT_TASKS"]), opts.get("tasks-mode"))
    module = os.environ["MODSYS_INIT_MODULE"]
    staging = Path(os.environ["MODSYS_INIT_STAGING"])
    if "pids" in opts:
        Path(opts["pids"]).mkdir(exist_ok=True)
        (Path(opts["pids"]) / str(os.getpid())).write_text(module)
    record(opts, "start", stdin)
    stop = opts.get("stop-after") or opts.get("stop-group")
    if stop and call_number(opts) == int(stop) + 1:
        staging.mkdir(parents=True, exist_ok=True)
        (staging / "MODULE.md").write_text("# Half a doc\n", encoding="utf-8")
        (staging / "partial.tmp").write_text("half", encoding="utf-8")
        if "stop-group" in opts:
            os.killpg(os.getpgrp(), signal.SIGKILL)
        os.kill(os.getppid(), signal.SIGKILL)
        record(opts, "end", stdin)
        return 0
    if "peers" in opts:
        live = Path(opts["live"])
        live.mkdir(exist_ok=True)
        (live / module).write_text("")
        deadline = time.time() + 10
        while len(list(live.iterdir())) < int(opts["peers"]) and time.time() < deadline:
            time.sleep(0.01)
    if "sleep" in opts:
        time.sleep(float(opts["sleep"]))
    try:
        if opts.get("fail") == module:
            for i in range(int(opts.get("lines", 50))):
                print(f"{module}: line {i + 1} of the failure", file=sys.stderr)
            return 3
        if opts.get("nothing") == module:
            return 0
        item = json.loads(Path(os.environ["MODSYS_INIT_WORK"]).read_text(encoding="utf-8"))
        write_docs(Path.cwd(), item, staging)
        if opts.get("keywords4") == module:
            entry = json.loads((staging / "entry.json").read_text(encoding="utf-8"))
            entry["keywords"] = entry["keywords"][:4]
            (staging / "entry.json").write_text(json.dumps(entry), encoding="utf-8")
        if "outside" in opts:
            target = Path.cwd() / opts["outside"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("# written by the executor\n", encoding="utf-8")
        return 0
    finally:
        record(opts, "end", stdin)


if __name__ == "__main__":
    sys.exit(main())
