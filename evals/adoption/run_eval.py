#!/usr/bin/env python3
"""E-A — deterministic adoption eval. Builds two repositories from nothing in temp dirs and
drives the modsys CLI of THIS checkout (`python -m modsys`, the checkout on PYTHONPATH):

  greenfield  git init -> init -> 3 modules -> code_map -> a relation -> lint -> coverage ->
              context -> the agent loop (code change -> lint --changed gate fails -> propose ->
              sync --apply-proposals -> gate passes) -> a child module with its own rule
  brownfield  a synthetic layered app (routes / repositories / models / sql / tests + a db
              layer) -> init -> a module per feature + db -> layered code_map rules with
              exclusive -> coverage >= 0.8 -> a feature change drifts only the feature ->
              the per-module layout keeps list / match

Every step asserts an exit code and a data check. Prints the scorecard JSON
{scenario: {steps: [{name, ok, detail}], commands, ok}} (commands = modsys invocations) and
exits 1 when any step fails. Stdlib only; no network.

Usage: python3 evals/adoption/run_eval.py
"""
import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[2]
FAIL_STEP = "MODSYS_EVAL_FAIL_STEP"  # test seam: "<scenario>:<step name>" forces that step to fail
GIT_IDENTITY = {"GIT_AUTHOR_NAME": "eval", "GIT_AUTHOR_EMAIL": "eval@example.invalid",
                "GIT_COMMITTER_NAME": "eval", "GIT_COMMITTER_EMAIL": "eval@example.invalid",
                "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}


class StepFailed(Exception):
    """A check inside a step failed; the scenario stops there."""


class Scenario:
    def __init__(self, name: str, root: Path):
        self.name, self.root = name, root
        self.steps: list[dict] = []
        self.commands = 0
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("GIT_", "MODSYS_"))}
        self.env.update(GIT_IDENTITY, PYTHONPATH=str(ENGINE))

    def modsys(self, *args: str, expect: int = 0):
        """Run one verb with --json; returns (data, stderr). Wrong exit code -> StepFailed."""
        self.commands += 1
        proc = subprocess.run([sys.executable, "-m", "modsys", *args, "--json"], cwd=self.root,
                              env=self.env, capture_output=True, text=True)
        if proc.returncode != expect:
            raise StepFailed(f"modsys {' '.join(args)}: exit {proc.returncode}, expected "
                             f"{expect}: {proc.stderr.strip()[:300]}")
        data = json.loads(proc.stdout)["data"] if proc.stdout.strip() else None
        return data, proc.stderr

    def git(self, *args: str) -> str:
        proc = subprocess.run(["git", *args], cwd=self.root, env=self.env, capture_output=True,
                              text=True)
        if proc.returncode != 0:
            raise StepFailed(f"git {' '.join(args)}: {proc.stderr.strip()[:300]}")
        return proc.stdout.strip()

    def commit(self, message: str, *paths: str) -> None:
        self.git("add", "--", *paths)
        self.git("commit", "-q", "-m", message)

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def append(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")

    def create(self, name: str, description: str, keywords: list[str], parent: str | None = None):
        argv = ["create", name, "--non-interactive", "--description", description]
        argv += [a for k in keywords for a in ("--keyword", k)]
        data, _ = self.modsys(*argv, *(["--parent", parent] if parent else []))
        check(data["module"] == (f"{parent}/{name}" if parent else name), f"created {data}")

    def step(self, name: str, fn) -> None:
        try:
            if os.environ.get(FAIL_STEP) == f"{self.name}:{name}":
                raise StepFailed(f"forced by {FAIL_STEP} (test seam)")
            detail, ok = fn() or "", True
        except StepFailed as e:
            detail, ok = str(e), False
        self.steps.append({"name": name, "ok": ok, "detail": detail})
        if not ok:
            raise StepFailed(name)


def check(condition: bool, detail: str) -> None:
    if not condition:
        raise StepFailed(detail)


def findings(data: dict, code: str | None = None) -> list[tuple[str, str]]:
    return [(f["code"], f["module"]) for f in data["findings"] if code in (None, f["code"])]


def modules_of(sync_data: dict) -> dict:
    return {m["module"]: m["via"] for m in sync_data["modules"]}


# --- greenfield --------------------------------------------------------------------------

GREEN_MODULES = {
    "tasks": ("Task items: create, complete, reorder; the home of a single task.",
              ["task", "todo", "complete", "due", "priority"]),
    "lists": ("Task lists: group, share and order tasks in named lists.",
              ["list", "group", "share", "board", "folder"]),
    "reminders": ("Reminders: schedule and send notifications before a task is due.",
                  ["reminder", "notify", "schedule", "alarm", "snooze"]),
}
SRC_RULE = '\n[[code_map]]\nid = "src"\npattern = "src/{module}/**"\n'
SEARCH_RULE = ('\n[[code_map]]\nid = "task-search"\nmodule = "tasks/search"\n'
               'globs = ["src/tasks/search/**"]\nexclusive = true\n')
TRACKED = (".gitignore", ".modsys", "modules", "src")


def greenfield(sc: Scenario) -> None:
    base = {}

    def git_init():
        sc.git("init", "-q", "-b", "main")

    def no_registry_names_init():
        _, err = sc.modsys("list", expect=2)
        check("run `modsys init`" in err, f"stderr: {err.strip()}")

    def init():
        data, _ = sc.modsys("init")
        statuses = [f["status"] for f in data["files"]]
        check(statuses == ["created"] * 3, f"statuses {statuses}")
        return ", ".join(f["path"] for f in data["files"])

    def init_again():
        data, _ = sc.modsys("init")
        check({f["status"] for f in data["files"]} == {"exists"}, f"second run {data['files']}")

    def add_modules():
        for name, (description, keywords) in GREEN_MODULES.items():
            sc.create(name, description, keywords)
        data, _ = sc.modsys("list")
        check(sorted(r["module"] for r in data) == sorted(GREEN_MODULES), f"list {data}")

    def wire_code():
        for rel in ("src/tasks/service.py", "src/lists/service.py", "src/reminders/service.py",
                    "src/reminders/scheduler.py"):
            sc.write(rel, "VALUE = 1\n")
        sc.append(".modsys/config.toml", SRC_RULE)
        data, _ = sc.modsys("sync", "--files", "src/reminders/scheduler.py", "--dry-run")
        check(modules_of(data) == {"reminders": ["code_map:src"]}, f"mapped {modules_of(data)}")

    def relation():
        edge = {"module": "tasks", "relation": "depends-on",
                "description": "Reminders fire for task due dates"}
        data, _ = sc.modsys("registry", "append", "reminders", "related_modules", json.dumps(edge))
        check(data["changed"] is True, f"changed {data['changed']}")

    def writer_refuses_bad_edge():
        _, err = sc.modsys("registry", "append", "reminders", "related_modules",
                           json.dumps({"module": "tasks", "relation": "depends-on"}), expect=2)
        check("(lint MS007)" in err, f"stderr: {err.strip()}")

    def lint_clean():
        data, _ = sc.modsys("lint")
        check(data["summary"] == {"error": 0, "warning": 0, "info": 0}, f"lint {findings(data)}")

    def coverage_full():
        data, _ = sc.modsys("coverage", "--fail-under", "100")
        check((data["total"], data["share"]) == (4, 1.0), f"coverage {data}")
        return f"share {data['share']} of {data['total']} files"

    def context_code_globs():
        data, _ = sc.modsys("context", "--task", "snooze a reminder", "--role", "developer")
        rows = {m["module"]: m["code_globs"] for m in data["modules"]}
        check(rows == {"reminders": ["src/reminders/**"]}, f"context {rows}")

    def commit_modules():
        sc.commit("modules", *TRACKED)
        base["sha"] = sc.git("rev-parse", "HEAD")

    def drift_gate_fails():
        sc.append("src/tasks/service.py", "DUE_SOON_HOURS = 24\n")
        sc.commit("due soon", "src")
        data, _ = sc.modsys("lint", "--changed", "--base", base["sha"], "--fail-on", "warning",
                            expect=1)
        check(findings(data) == [("MS050", "tasks")], f"findings {findings(data)}")

    def propose_doc():
        data, _ = sc.modsys("propose", "--run-id", "run1", "--agent", "builder",
                            "--module", "tasks", "--op", "doc_append",
                            "--doc", "modules/tasks/roles/developer.md",
                            "--value", "## Due soon\n\nA task is due soon 24 hours before its due date.",
                            "--reason", "document DUE_SOON_HOURS")
        check(data["item"]["op"] == "doc_append", f"item {data['item']}")

    def sync_applies():
        data, _ = sc.modsys("sync", "--from-diff", f"{base['sha']}..HEAD", "--apply-proposals")
        check(list(modules_of(data)) == ["tasks"], f"modules {modules_of(data)}")
        check(data["proposals"]["summary"]["applied"] == 1, f"proposals {data['proposals']}")
        doc = (sc.root / "modules/tasks/roles/developer.md").read_text(encoding="utf-8")
        check("\n\n## Due soon\n\nA task is due soon" in doc, "doc_append not separated")

    def gate_passes():
        sc.commit("docs: due soon", *TRACKED)
        data, _ = sc.modsys("lint", "--changed", "--base", base["sha"], "--fail-on", "warning")
        check(findings(data) == [], f"findings {findings(data)}")

    def child_module():
        sc.create("search", "Full-text search over task titles and notes.", ["search"],
                  parent="tasks")
        sc.append(".modsys/config.toml", SEARCH_RULE)
        sc.write("src/tasks/search/index.py", "INDEX = {}\n")
        data, _ = sc.modsys("sync", "--files", "src/tasks/search/index.py", "--dry-run")
        check(modules_of(data) == {"tasks/search": ["code_map:task-search"]},
              f"mapped {modules_of(data)}")
        data, _ = sc.modsys("lint")
        check(findings(data) == [], f"lint {findings(data)}")
        data, _ = sc.modsys("coverage", "--fail-under", "100")
        check(data["modules"].get("tasks/search") == 1, f"coverage {data['modules']}")

    for name, fn in [("git init", git_init),
                     ("no registry: the error names modsys init", no_registry_names_init),
                     ("init", init), ("init again changes nothing", init_again),
                     ("create tasks, lists, reminders", add_modules),
                     ("wire code with [[code_map]]", wire_code),
                     ("relation via registry append", relation),
                     ("writer refuses an edge lint would reject", writer_refuses_bad_edge),
                     ("lint clean", lint_clean), ("coverage 100 %", coverage_full),
                     ("context returns code_globs", context_code_globs),
                     ("commit", commit_modules),
                     ("code-only change fails lint --changed (MS050)", drift_gate_fails),
                     ("propose the doc update", propose_doc),
                     ("sync --from-diff --apply-proposals", sync_applies),
                     ("commit the docs: gate passes", gate_passes),
                     ("child module mapped by its own exclusive rule", child_module)]:
        sc.step(name, fn)


# --- brownfield --------------------------------------------------------------------------

FEATURES = {
    "orders": ("Order intake: place, change and cancel customer orders.",
               ["order", "purchase", "basket", "cancel order", "order status"]),
    "invoices": ("Invoices: issue, send and settle invoices for delivered orders.",
                 ["invoice", "receipt", "tax", "due amount", "settle"]),
    "shipments": ("Shipments: pack, ship and track parcels for paid orders.",
                  ["shipment", "parcel", "tracking", "carrier", "delivery"]),
    "reviews": ("Customer reviews: collect, moderate and show ratings for items.",
                ["review", "rating", "stars", "moderation", "feedback"]),
}
DB = ("db", "Database layer: sessions, the base repository and the shared schema.",
      ["database", "session", "schema", "base repository", "sql"])
LAYERED_RULES = '''
[[code_map]]
id = "routes"
pattern = "app/routes/{module}/**"

[[code_map]]
id = "repositories"
pattern = "app/repositories/{module}.py"
exclusive = true

[[code_map]]
id = "models"
pattern = "app/models/{module}.py"

[[code_map]]
id = "sql"
pattern = "app/sql/{module}.sql"
exclusive = true

[[code_map]]
id = "tests"
pattern = "tests/test_{module}.py"

[[code_map]]
id = "db"
module = "db"
globs = ["app/db/**", "app/repositories/**", "app/sql/**"]
'''


def layered_app() -> dict[str, str]:
    """A synthetic layered web app: each feature spread over five layers, plus a db layer."""
    files = {"README.md": "# shop\n", "pyproject.toml": "[project]\nname = \"shop\"\n",
             ".gitignore": "__pycache__/\n", "app/main.py": "APP = 'shop'\n",
             "app/db/__init__.py": "", "app/db/session.py": "SESSION = None\n",
             "app/db/base.py": "class Base: pass\n",
             "app/repositories/base.py": "class BaseRepository: pass\n",
             "app/sql/schema.sql": "-- shared schema\n", "tests/conftest.py": "FIXTURES = {}\n"}
    for f in FEATURES:
        files[f"app/routes/{f}/__init__.py"] = ""
        files[f"app/routes/{f}/api.py"] = f"ROUTE = '/{f}'\n"
        files[f"app/repositories/{f}.py"] = f"class {f.title()}Repository: pass\n"
        files[f"app/models/{f}.py"] = f"class {f.title()[:-1]}: pass\n"
        files[f"app/sql/{f}.sql"] = f"-- {f} queries\n"
        files[f"tests/test_{f}.py"] = f"def test_{f}(): pass\n"
    return files


def brownfield(sc: Scenario) -> None:
    app = layered_app()
    before = {}

    def generate():
        sc.git("init", "-q", "-b", "main")
        for rel, text in app.items():
            sc.write(rel, text)
        sc.commit("existing app", *app)
        return f"{len(app)} files"

    def init():
        data, _ = sc.modsys("init")
        check({f["path"]: f["status"] for f in data["files"]}[".gitignore"] == "updated",
              f"files {data['files']}")
        check("__pycache__/" in (sc.root / ".gitignore").read_text(encoding="utf-8"),
              ".gitignore lost its line")

    def baseline():
        data, _ = sc.modsys("coverage")
        check((data["total"], data["mapped"]) == (len(app) - 1, 0), f"baseline {data}")
        return f"{data['total']} files, none mapped"

    def add_modules():
        for name, (description, keywords) in FEATURES.items():
            sc.create(name, description, keywords)
        sc.create(*DB)

    def rules():
        sc.append(".modsys/config.toml", LAYERED_RULES)
        data, _ = sc.modsys("lint")
        check(data["summary"]["error"] == 0 and not findings(data, "MS052"),
              f"lint {findings(data)}")

    def coverage_target():
        data, _ = sc.modsys("coverage", "--fail-under", "80")
        check(data["share"] >= 0.8, f"share {data['share']}")
        check(sorted(data["unmapped"]) == ["README.md", "app/main.py", "pyproject.toml",
                                           "tests/conftest.py"], f"unmapped {data['unmapped']}")
        return f"share {data['share']} ({data['mapped']}/{data['total']})"

    def exclusive_repository():
        data, _ = sc.modsys("sync", "--files", "app/repositories/orders.py",
                            "app/repositories/base.py", "--dry-run")
        check(modules_of(data) == {"db": ["code_map:db"], "orders": ["code_map:repositories"]},
              f"mapped {modules_of(data)}")
        check(data["modules"][1]["files"] == ["app/repositories/orders.py"],
              f"orders files {data['modules'][1]['files']}")

    def commit():
        sc.commit("modules", ".gitignore", ".modsys", "modules")

    def feature_drift():
        for rel in ("app/repositories/orders.py", "app/routes/orders/api.py", "app/sql/orders.sql"):
            sc.append(rel, "# changed\n")
        data, _ = sc.modsys("lint", "--changed", "--fail-on", "warning", expect=1)
        check(findings(data, "MS050") == [("MS050", "orders")], f"drift {findings(data)}")
        data, _ = sc.modsys("discover", "--files", "app/repositories/orders.py",
                            "app/routes/orders/api.py", "app/sql/orders.sql")
        usage = {m["module"]: m["usage"] for m in data["modules"]}
        check(usage == {"orders": "modify"}, f"discover {usage}")

    def per_module_layout():
        before["list"], _ = sc.modsys("list")
        before["match"], _ = sc.modsys("match", "order invoice shipment")
        data, _ = sc.modsys("index", "split")
        check(len(data["files"]) == len(FEATURES) + 1, f"split {data['files']}")
        sc.append(".modsys/config.toml", '\n[paths]\nregistry_layout = "per-module"\n')
        sc.modsys("index", "build", "--check")
        after_list, _ = sc.modsys("list")
        after_match, _ = sc.modsys("match", "order invoice shipment")

        def by_name(rows):
            return sorted(rows, key=lambda r: r["module"])

        check(by_name(after_list) == by_name(before["list"]), "list differs after split")
        check(after_match == before["match"], "match differs after split")

    for name, fn in [("generate and commit a layered app", generate),
                     ("init keeps the existing .gitignore", init),
                     ("baseline coverage", baseline),
                     ("a module per feature + db", add_modules),
                     ("layered [[code_map]] rules, lint clean", rules),
                     ("coverage >= 80 %", coverage_target),
                     ("a feature repository maps only to its feature", exclusive_repository),
                     ("commit", commit),
                     ("a feature change drifts only the feature", feature_drift),
                     ("per-module layout keeps list and match", per_module_layout)]:
        sc.step(name, fn)


SCENARIOS = {"greenfield": greenfield, "brownfield": brownfield}


def run_scenario(name: str, build) -> dict:
    with tempfile.TemporaryDirectory(prefix=f"modsys-eval-{name}-") as tmp:
        sc = Scenario(name, Path(tmp) / name)
        sc.root.mkdir()
        try:
            build(sc)
        except StepFailed:
            pass  # recorded by Scenario.step; the scenario stops at its first failed step
        except Exception as e:  # never a traceback: an unexpected error is a failed step
            sc.steps.append({"name": "unexpected error", "ok": False,
                             "detail": f"{type(e).__name__}: {e}"})
    return {"steps": sc.steps, "commands": sc.commands,
            "ok": bool(sc.steps) and all(s["ok"] for s in sc.steps)}


def main() -> int:
    with ThreadPoolExecutor(max_workers=len(SCENARIOS)) as pool:  # independent temp repos
        results = pool.map(lambda item: run_scenario(*item), SCENARIOS.items())
        card = dict(zip(SCENARIOS, results))
    print(json.dumps(card, indent=2, ensure_ascii=False))
    for name, result in card.items():
        state = "ok" if result["ok"] else "FAILED"
        print(f"adoption eval: {name} {state} ({len(result['steps'])} steps, "
              f"{result['commands']} commands)", file=sys.stderr)
    return 0 if all(r["ok"] for r in card.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
