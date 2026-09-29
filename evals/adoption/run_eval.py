#!/usr/bin/env python3
"""E-A — deterministic adoption eval. Builds seven repositories in temp dirs and drives the
modsys CLI of THIS checkout (`python -m modsys`, the checkout on PYTHONPATH):

  greenfield  git init -> init -> 3 modules -> code-map add -> a relation -> lint -> coverage
              -> context -> the agent loop (code change -> lint --changed gate fails -> propose
              -> sync --apply-proposals -> gate passes) -> ci --base <first commit> passes ->
              a code-only change fails ci (drift) -> a docs follow-up passes ci -> a child
              module with its own rule (code-map add --exclusive)
  brownfield  a synthetic layered app (routes / repositories / models / sql / tests + a db
              layer) -> init -> a module per feature + db -> layered code_map rules: MS053
              until the per-feature rules are exclusive -> coverage >= 0.8 -> code-map files
              lists a feature's repository file -> a feature change drifts only the feature ->
              the per-module layout keeps list / match
  packs       a git copy of the bookshop fixture -> packs new (a role + a skill) -> lint clean ->
              create --role (the pack's template) -> show --role -> packs sync to claude and
              codex -> --check -> a local edit is a conflict -> eject -> sync from the ejected
              copy -> the pack moves on: MS063 + eject --diff -> agents-md keeps the team's
              CLAUDE.md text -> templates list names the pack template
  skills      a git copy of the bookshop fixture -> [packs] builtin = core, ui, qa -> packs list
              (3 built-in rows) -> lint without MS06x -> packs sync to claude and codex (12 x 2
              created) -> --check -> agents-md lists the 12 skills -> create --tag ui --tag qa
              (the designer and qa_acceptance templates) -> a code change: sync-instructions
              names the module, MS050 and the keywords hint -> eject module-sync -> packs sync
              from the edited copy -> packs new core is refused (a reserved id)
  adopt       a git copy of the bookshop fixture without its declarations (and a reference copy
              with them) -> adopt --dry-run writes nothing and names the role, the field and the
              code-map rule -> adopt writes .modsys/config.toml -> list / show equal the
              reference's -> a second adopt writes adopt.proposed.toml, config.toml kept -> the
              tree outside .modsys/ is byte-identical to the start
  init-map    the bookshop_monorepo fixture with its built history -> init -> init map (seven
              candidates) -> exclude one, rename one in proposal.json -> init confirm -> init
              status: gate 3 passed -> init resume runs the fan-out -> a fresh copy: init map
              stopped by the test seam -> init resume -> the same outputs
  init        the bookshop_monorepo fixture with its history -> init map (tools switched off)
              -> init confirm -> init fanout: six work items -> init run with the fake writer,
              max_parallel = 1, killed after two modules -> init resume --executor
              --non-interactive: every module done once -> init reconcile: the planted
              duplicate and one collision -> init eval-tasks (the canned tasks) -> init verify
              passes -> init finish --open-pr against a local bare remote and a gh stand-in:
              one commit on modsys/init (its subject = the pull request's title, "docs:
              module docs for 6 module(s) (modsys init)"), the pull request body holds the
              verify summary and the routing table

Every step asserts an exit code and a data check. Prints the scorecard JSON
{scenario: {steps: [{name, ok, detail}], commands, ok}} (commands = modsys invocations) and
exits 1 when any step fails. Stdlib only; no network.

Usage: python3 evals/adoption/run_eval.py
Test seams: MODSYS_EVAL_FAIL_STEP="<scenario>:<step name>" forces that step to fail;
MODSYS_EVAL_SCENARIOS="<scenario>,…" runs only those scenarios (an unknown name: exit 2).
"""
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[2]
FAIL_STEP = "MODSYS_EVAL_FAIL_STEP"  # test seam: "<scenario>:<step name>" forces that step to fail
ONLY = "MODSYS_EVAL_SCENARIOS"  # test seam: "<scenario>,…" runs only those (the time bound)
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

    def modsys(self, *args: str, expect: int = 0, env: dict | None = None):
        """Run one verb with --json; returns (data, stderr). Wrong exit code -> StepFailed.
        `env`: extra environment for this one command."""
        self.commands += 1
        proc = subprocess.run([sys.executable, "-m", "modsys", *args, "--json"], cwd=self.root,
                              env={**self.env, **(env or {})}, capture_output=True, text=True)
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
TRACKED = (".gitignore", ".modsys", "modules", "src")


def ci_statuses(data: dict) -> list[str]:
    return [s["status"] for s in data["steps"]]


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
        data, _ = sc.modsys("code-map", "add", "src", "--pattern", "src/{module}/**")
        check(data["block"] == '[[code_map]]\nid = "src"\npattern = "src/{module}/**"\n',
              f"block {data['block']!r}")
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

    def ci_passes():
        data, _ = sc.modsys("ci", "--base", base["sha"], "--fail-under", "100")
        check(ci_statuses(data) == ["passed", "passed", "passed"], f"ci {ci_statuses(data)}")

    def ci_fails_on_drift():
        sc.append("src/lists/service.py", "MAX_ITEMS = 100\n")
        sc.commit("lists: cap", "src")
        data, _ = sc.modsys("ci", "--base", base["sha"], expect=1)
        check(ci_statuses(data) == ["passed", "failed", "report-only"], f"ci {ci_statuses(data)}")
        drift = [(f["code"], f["module"]) for f in data["steps"][1]["findings"]]
        check(drift == [("MS050", "lists")], f"drift {drift}")

    def ci_passes_after_docs():
        sc.append("modules/lists/roles/developer.md", "\n## Limits\n\nA list holds 100 tasks.\n")
        sc.commit("docs: lists cap", "modules")
        data, _ = sc.modsys("ci", "--base", base["sha"])
        check(ci_statuses(data) == ["passed", "passed", "report-only"], f"ci {ci_statuses(data)}")

    def child_module():
        sc.create("search", "Full-text search over task titles and notes.", ["search"],
                  parent="tasks")
        sc.modsys("code-map", "add", "task-search", "--glob", "src/tasks/search/**",
                  "--module", "tasks/search", "--exclusive")
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
                     ("wire code with code-map add", wire_code),
                     ("relation via registry append", relation),
                     ("writer refuses an edge lint would reject", writer_refuses_bad_edge),
                     ("lint clean", lint_clean), ("coverage 100 %", coverage_full),
                     ("context returns code_globs", context_code_globs),
                     ("commit", commit_modules),
                     ("code-only change fails lint --changed (MS050)", drift_gate_fails),
                     ("propose the doc update", propose_doc),
                     ("sync --from-diff --apply-proposals", sync_applies),
                     ("commit the docs: gate passes", gate_passes),
                     ("ci --base <first commit> passes", ci_passes),
                     ("a code-only change fails ci (drift step)", ci_fails_on_drift),
                     ("a docs follow-up passes ci", ci_passes_after_docs),
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

    def rules_overlap():
        sc.append(".modsys/config.toml", LAYERED_RULES.replace("exclusive = true\n", ""))
        data, _ = sc.modsys("lint")
        overlaps = [f["message"] for f in data["findings"] if f["code"] == "MS053"]
        check(len(overlaps) == 2 and "'db' (-> db) and 'repositories'" in overlaps[0]
              and "'db' (-> db) and 'sql'" in overlaps[1], f"MS053 {overlaps}")
        return overlaps[0]

    def rules_exclusive():  # the hand edit a user makes: rules are edited by hand
        config = sc.root / ".modsys" / "config.toml"
        text = config.read_text(encoding="utf-8")
        for line in ('pattern = "app/repositories/{module}.py"\n',
                     'pattern = "app/sql/{module}.sql"\n'):
            text = text.replace(line, line + "exclusive = true\n")
        config.write_text(text, encoding="utf-8")
        data, _ = sc.modsys("lint")
        check(data["summary"]["error"] == 0 and not findings(data, "MS052")
              and not findings(data, "MS053"), f"lint {findings(data)}")

    def feature_files():
        data, _ = sc.modsys("code-map", "files", "orders")
        via = {f["path"]: f["via"] for f in data["files"]}
        check(via.get("app/repositories/orders.py") == ["code_map:repositories"],
              f"orders files {sorted(via)}")
        return f"{data['total']} files map to orders"

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
                     ("layered rules without exclusive: MS053", rules_overlap),
                     ("per-feature rules exclusive: lint clean", rules_exclusive),
                     ("coverage >= 80 %", coverage_target),
                     ("code-map files lists the feature's repository file", feature_files),
                     ("a feature repository maps only to its feature", exclusive_repository),
                     ("commit", commit),
                     ("a feature change drifts only the feature", feature_drift),
                     ("per-module layout keeps list and match", per_module_layout)]:
        sc.step(name, fn)


# --- packs -------------------------------------------------------------------------------

BOOKSHOP = ENGINE / "tests" / "fixtures" / "bookshop"
REVIEWS = ("Customer reviews of books: ratings, comments and moderation.",
           ["review", "rating", "stars", "comment", "moderation"])


def packs(sc: Scenario) -> None:
    claude_md = "# Bookshop\n\nTeam notes: run the tests before every push.\n"
    skill = sc.root / ".claude/skills/api-review/SKILL.md"
    ejected = sc.root / ".modsys/overrides/skills/api-review/SKILL.md"
    upstream = sc.root / ".modsys/packs/team/skills/api-review/SKILL.md"
    kept = {}

    def statuses(data: dict) -> list[tuple]:
        return [(r["agent"], r["status"]) for r in data["skills"]]

    def sync(expect: int = 0, *flags: str) -> dict:
        data, _ = sc.modsys("packs", "sync", "--agent", "claude", "--agent", "codex", *flags,
                            expect=expect)
        return data

    def fixture():
        shutil.copytree(BOOKSHOP, sc.root, dirs_exist_ok=True)
        sc.git("init", "-q", "-b", "main")
        sc.commit("bookshop", ".")

    def new_pack():
        data, _ = sc.modsys("packs", "new", "team", "--role", "reviewer", "--skill",
                            "api-review", "--description", "Team review conventions")
        check(len(data["files"]) == 3, f"files {data['files']}")
        return ", ".join(data["files"])

    def lint_clean():
        data, _ = sc.modsys("lint")
        check(not [f for f in data["findings"] if f["code"].startswith("MS06")],
              f"lint {findings(data)}")

    def create_with_role():
        description, keywords = REVIEWS
        data, _ = sc.modsys("create", "reviews", "--non-interactive", "--description",
                            description, *[a for k in keywords for a in ("--keyword", k)],
                            "--role", "reviewer")
        check("modules/reviews/roles/reviewer.md" in data["files"], f"files {data['files']}")
        doc = (sc.root / "modules/reviews/roles/reviewer.md").read_text(encoding="utf-8")
        check(doc.startswith("# Reviews — reviewer\n"), f"doc {doc[:60]!r}")

    def show_role():
        data, _ = sc.modsys("show", "reviews", "--role", "reviewer")
        rows = [(r["label"], r["exists"]) for r in data["read"]]
        check(("role:reviewer", True) in rows, f"read {rows}")

    def sync_created():
        data = sync()
        check(statuses(data) == [("claude", "created"), ("codex", "created")],
              f"sync {statuses(data)}")
        kept["skill"] = skill.read_bytes()

    def check_passes():
        sync(0, "--check")

    def local_edit_conflicts():
        skill.write_bytes(kept["skill"] + b"\nA local edit.\n")
        data = sync(1)
        check(statuses(data) == [("claude", "conflict"), ("codex", "unchanged")],
              f"sync {statuses(data)}")
        check(skill.read_bytes().endswith(b"A local edit.\n"), "the local edit was overwritten")

    def revert():
        skill.write_bytes(kept["skill"])
        sync(0, "--check")

    def eject():
        data, _ = sc.modsys("eject", "api-review")
        check(data["dir"] == ".modsys/overrides/skills/api-review", f"eject {data}")

    def sync_from_the_ejected_copy():
        ejected.write_text(ejected.read_text(encoding="utf-8") + "\n5. Check the error codes.\n",
                           encoding="utf-8")
        data = sync()
        rows = [(r["agent"], r["status"], r["source"]) for r in data["skills"]]
        check(rows == [("claude", "updated", "ejected"), ("codex", "updated", "ejected")],
              f"sync {rows}")
        check(skill.read_text(encoding="utf-8").endswith("5. Check the error codes.\n"),
              "the agents' copy is not the ejected copy")

    def pack_moves_on():
        toml = sc.root / ".modsys/packs/team/pack.toml"
        toml.write_text(toml.read_text(encoding="utf-8").replace('version = "0.1.0"',
                                                                 'version = "0.2.0"'),
                        encoding="utf-8")
        upstream.write_text(upstream.read_text(encoding="utf-8")
                            + "\n5. Check the API version header.\n", encoding="utf-8")
        data, _ = sc.modsys("lint")
        messages = [f["message"] for f in data["findings"] if f["code"] == "MS063"]
        check(messages == ["ejected skill 'api-review' is behind pack 'team' (ejected from "
                           "0.1.0, pack is now 0.2.0) — review: modsys eject api-review --diff"],
              f"MS063 {messages}")

    def diff_shows_it():
        data, _ = sc.modsys("eject", "api-review", "--diff")
        check(data["behind"] and "-5. Check the API version header." in data["diff"],
              f"diff {data['diff'][:200]!r}")

    def agents_md():
        sc.write("CLAUDE.md", claude_md)
        data, _ = sc.modsys("agents-md", "--target", "CLAUDE.md", "--target", "AGENTS.md")
        rows = [(r["path"], r["status"]) for r in data["targets"]]
        check(rows == [("CLAUDE.md", "added"), ("AGENTS.md", "created")], f"agents-md {rows}")

    def agents_md_again():
        data, _ = sc.modsys("agents-md", "--target", "CLAUDE.md", "--target", "AGENTS.md")
        check([r["status"] for r in data["targets"]] == ["unchanged", "unchanged"],
              f"agents-md {data['targets']}")
        check((sc.root / "CLAUDE.md").read_text(encoding="utf-8").startswith(claude_md + "\n"),
              "the team's text changed")

    def template_provenance():
        data, _ = sc.modsys("templates", "list")
        rows = {r["template"]: r["source"] for r in data}
        check(rows.get("roles/reviewer.md") == "role-template:team", f"templates {rows}")

    for name, fn in [("a git copy of the bookshop fixture", fixture),
                     ("packs new team --role reviewer --skill api-review", new_pack),
                     ("plain lint: no pack findings", lint_clean),
                     ("create --role reviewer renders the pack template", create_with_role),
                     ("show --role reviewer lists the doc", show_role),
                     ("packs sync: created for claude and codex", sync_created),
                     ("packs sync --check passes", check_passes),
                     ("a local edit is a conflict and stays", local_edit_conflicts),
                     ("revert the edit: in sync again", revert),
                     ("eject api-review", eject),
                     ("packs sync from the edited ejected copy", sync_from_the_ejected_copy),
                     ("the pack moves on: lint MS063", pack_moves_on),
                     ("eject --diff shows the upstream change", diff_shows_it),
                     ("agents-md: added to CLAUDE.md, AGENTS.md created", agents_md),
                     ("agents-md again: unchanged, the team text kept", agents_md_again),
                     ("templates list: the reviewer template comes from the pack",
                      template_provenance)]:
        sc.step(name, fn)


# --- skills ------------------------------------------------------------------------------

BUILTIN_SKILLS = ["designer-review", "module-adopt", "module-create", "module-discover",
                  "module-init", "module-lint", "module-research", "module-scout", "module-split",
                  "module-sync", "qa-acceptance", "qa-acceptance-baseline"]


def skills(sc: Scenario) -> None:
    base = {}

    def fixture():
        shutil.copytree(BOOKSHOP, sc.root, dirs_exist_ok=True)
        sc.git("init", "-q", "-b", "main")
        sc.commit("bookshop", ".")

    def enable():
        sc.write(".modsys/config.toml", '[packs]\nbuiltin = ["core", "ui", "qa"]\n')
        data, _ = sc.modsys("packs", "list")
        rows = [(r["id"], r["builtin"]) for r in data]
        check(rows == [("bookshop", False), ("core", True), ("qa", True), ("ui", True)],
              f"packs {rows}")
        sc.commit("enable the built-in packs", ".modsys")
        base["sha"] = sc.git("rev-parse", "HEAD")

    def lint_clean():
        data, _ = sc.modsys("lint")
        check(not [f for f in data["findings"] if f["code"].startswith("MS06")],
              f"lint {findings(data)}")

    def sync_created():
        data, _ = sc.modsys("packs", "sync", "--agent", "claude", "--agent", "codex")
        rows = sorted({r["skill"] for r in data["skills"] if r["status"] == "created"})
        check(len(data["skills"]) == 24 and rows == BUILTIN_SKILLS, f"sync {data['summary']}")

    def check_passes():
        sc.modsys("packs", "sync", "--check", "--agent", "claude", "--agent", "codex")

    def agents_md():
        sc.modsys("agents-md", "--target", "AGENTS.md")
        text = (sc.root / "AGENTS.md").read_text(encoding="utf-8")
        missing = [s for s in BUILTIN_SKILLS if f"- `{s}` — " not in text]
        check(not missing, f"AGENTS.md lacks {missing}")

    def create_tagged():
        description, keywords = REVIEWS
        data, _ = sc.modsys("create", "reviews", "--non-interactive", "--description",
                            description, *[a for k in keywords for a in ("--keyword", k)],
                            "--tag", "ui", "--tag", "qa")
        docs = {"modules/reviews/roles/designer.md", "modules/reviews/roles/qa_acceptance.md"}
        check(docs <= set(data["files"]), f"files {data['files']}")
        text = (sc.root / "modules/reviews/roles/designer.md").read_text(encoding="utf-8")
        check("\n## UX invariants\n" in text, f"designer doc {text[:80]!r}")
        data, _ = sc.modsys("templates", "list")
        rows = {r["template"]: r["source"] for r in data}
        check((rows.get("roles/designer.md"), rows.get("roles/qa_acceptance.md"))
              == ("role-template:ui", "role-template:qa"), f"templates {rows}")

    def sync_instructions():
        sc.append("src/catalog/service.py", "\nPAGE_SIZE = 20\n")
        sc.commit("catalog: page size", "src")
        data, _ = sc.modsys("sync-instructions", "--from-diff", f"{base['sha']}..HEAD")
        rows = {m["module"]: m for m in data["modules"]}
        check(list(rows) == ["catalog"], f"modules {list(rows)}")
        check([f["code"] for f in rows["catalog"]["drift"]] == ["MS050"],
              f"drift {rows['catalog']['drift']}")
        hints = {f["name"]: f["sync_hint"] for f in rows["catalog"]["fields"]}
        check(bool(hints.get("keywords")), f"fields {sorted(hints)}")

    def eject():
        data, _ = sc.modsys("eject", "module-sync")
        check((data["pack"], data["dir"]) == ("core", ".modsys/overrides/skills/module-sync"),
              f"eject {data}")

    def sync_from_the_ejected_copy():
        sc.append(".modsys/overrides/skills/module-sync/SKILL.md", "\nTeam rule: link the PR.\n")
        data, _ = sc.modsys("packs", "sync", "--agent", "claude", "--agent", "codex")
        rows = [(r["agent"], r["status"], r["source"]) for r in data["skills"]
                if r["status"] != "unchanged"]
        check(rows == [("claude", "updated", "ejected"), ("codex", "updated", "ejected")],
              f"sync {rows}")

    def reserved_id():
        _, err = sc.modsys("packs", "new", "core", expect=2)
        check("pack id 'core' is reserved for the engine's built-in pack" in err,
              f"stderr: {err.strip()}")

    for name, fn in [("a git copy of the bookshop fixture", fixture),
                     ("[packs] builtin: packs list shows core, qa, ui", enable),
                     ("plain lint: no pack findings", lint_clean),
                     ("packs sync: 12 skills x 2 agents created", sync_created),
                     ("packs sync --check passes", check_passes),
                     ("agents-md lists the twelve skills", agents_md),
                     ("create --tag ui --tag qa renders the pack templates", create_tagged),
                     ("a code change: sync-instructions names catalog, MS050 and the hints",
                      sync_instructions),
                     ("eject module-sync", eject),
                     ("packs sync from the edited ejected copy", sync_from_the_ejected_copy),
                     ("packs new core is refused: a reserved id", reserved_id)]:
        sc.step(name, fn)


# --- adopt --------------------------------------------------------------------------------


def tree(root: Path, skip: str = ".modsys") -> dict:
    """{path: bytes} of every file outside `skip` and `.git`."""
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file() and p.relative_to(root).parts[0] not in (skip, ".git")}


def adopt(sc: Scenario) -> None:
    ref = sc.root.parent / "reference"
    start = {}

    def copies():
        for root in (sc.root, ref):
            shutil.copytree(BOOKSHOP, root, dirs_exist_ok=True)
            for rel in ("src/checkout/cart.py", "src/payments/gateway.py"):
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text("VALUE = 1\n", encoding="utf-8")
        (ref / ".modsys/config.toml").write_text('[[code_map]]\nid = "src"\n'
                                                'pattern = "src/{module}/**"\n')
        shutil.rmtree(sc.root / ".modsys")
        sc.git("init", "-q", "-b", "main")
        sc.commit("bookshop, declarations removed", ".")
        start["tree"] = tree(sc.root)

    def dry_run():
        data, _ = sc.modsys("adopt", "--dry-run")
        check(not (sc.root / ".modsys").exists() and tree(sc.root) == start["tree"],
              "adopt --dry-run wrote something")
        i = data["inferred"]
        found = ([r["name"] for r in i["roles"]], [f["name"] for f in i["fields"]],
                 (i["code_map"] or {}).get("pattern"))
        check(found == (["designer"], ["file_paths"], "src/{module}/**"), f"inferred {found}")

    def write():
        data, _ = sc.modsys("adopt")
        check(data["config_path"] == ".modsys/config.toml"
              and (sc.root / ".modsys/config.toml").is_file(), f"adopt {data['config_path']}")

    def same_as_reference():
        for argv in (("list",), ("show", "catalog", "--all-roles")):
            mine, _ = sc.modsys(*argv)
            theirs, _ = sc.modsys(*argv, "--root", str(ref))
            check(mine == theirs, f"{' '.join(argv)} differs from the reference copy")

    def again():
        config = (sc.root / ".modsys/config.toml").read_bytes()
        data, _ = sc.modsys("adopt")
        check(data["config_path"] == ".modsys/adopt.proposed.toml"
              and (sc.root / ".modsys/adopt.proposed.toml").is_file(), f"{data['config_path']}")
        check((sc.root / ".modsys/config.toml").read_bytes() == config, "config.toml changed")

    def untouched():
        check(tree(sc.root) == start["tree"], "a file outside .modsys/ changed")

    for name, fn in [("a copy without declarations and a reference copy", copies),
                     ("adopt --dry-run writes nothing and names the declarations", dry_run),
                     ("adopt writes .modsys/config.toml", write),
                     ("list and show equal the reference copy's", same_as_reference),
                     ("a second adopt writes adopt.proposed.toml", again),
                     ("the tree outside .modsys/ is unchanged", untouched)]:
        sc.step(name, fn)


# --- init-map -----------------------------------------------------------------------------

def monorepo_builder():
    """`tests/fixtures/build_monorepo.py` (loaded by path: the eval imports nothing else)."""
    import importlib.util
    path = ENGINE / "tests" / "fixtures" / "build_monorepo.py"
    spec = importlib.util.spec_from_file_location("build_monorepo", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build


CANDIDATES = ["storefront", "cart", "catalog", "ui-kit", "payments", "recommendations",
              "tools"]


def init_map(sc: Scenario) -> None:
    work = sc.root / ".modsys/init"
    first = {}

    def outputs() -> tuple[bytes, bytes]:
        return (work / "preflight.json").read_bytes(), (work / "proposal.json").read_bytes()

    def fixture():
        sc.root.rmdir()
        monorepo_builder()(sc.root)

    def init():
        data, _ = sc.modsys("init")
        check([f["status"] for f in data["files"]] == ["created"] * 3, f"init {data['files']}")

    def map_it():
        data, _ = sc.modsys("init", "map")
        check(data["candidates"] == CANDIDATES, f"candidates {data['candidates']}")
        check((data["unassigned"], data["hints"]) == (0, 2), f"{data}")
        first["outputs"] = outputs()

    def edit():
        doc = json.loads((work / "proposal.json").read_text(encoding="utf-8"))
        by_name = {c["name"]: c for c in doc["candidates"]}
        by_name["storefront"]["include"] = False
        by_name["ui-kit"]["name"] = "design-kit"
        (work / "proposal.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")

    def confirm():
        data, _ = sc.modsys("init", "confirm")
        check((data["status"], data["excluded"], "design-kit" in data["included"])
              == ("confirmed", ["storefront"], True), f"confirm {data}")

    def status():
        data, _ = sc.modsys("init", "status")
        check("gate 3 passed" in data["next"], f"status {data['next']}")

    def resume():
        data, _ = sc.modsys("init", "resume")
        check(data["ran"] == ["fanout"] and (work / "work/design-kit.json").is_file(),
              f"resume {data}")

    def interrupted():
        fresh = sc.root.parent / "fresh"
        monorepo_builder()(fresh)
        sc.modsys("init", "map", "--root", str(fresh), expect=130,
                  env={"MODSYS_INIT_TEST_STOP": "map"})
        data, _ = sc.modsys("init", "resume", "--root", str(fresh))
        check(data["ran"] == ["map"], f"resume ran {data['ran']}")
        again = tuple((fresh / ".modsys/init" / n).read_bytes()
                      for n in ("preflight.json", "proposal.json"))
        root = str(sc.root).encode()
        check(again == tuple(o.replace(root, str(fresh).encode()) for o in first["outputs"]),
              "the resumed outputs differ from an uninterrupted run")

    for name, fn in [("the bookshop monorepo with its history", fixture), ("init", init),
                     ("init map: seven candidates", map_it),
                     ("exclude one candidate, rename another", edit),
                     ("init confirm", confirm), ("init status: gate 3 passed", status),
                     ("init resume: the fan-out writes the work items", resume),
                     ("an interrupted init map, then init resume: the same outputs",
                      interrupted)]:
        sc.step(name, fn)


# --- init ---------------------------------------------------------------------------------

FAKE_WRITER = ENGINE / "tests" / "init_fake_executor.py"
SIX = ["cart", "catalog", "payments", "recommendations", "storefront", "ui-kit"]
GH_SHIM = """#!{python}
import json, sys
args = sys.argv[1:]
body = open(args[args.index("--body-file") + 1]).read() if "--body-file" in args else None
with open({log!r}, "a") as fh:
    fh.write(json.dumps({{"argv": args, "body": body}}) + "\\n")
print("https://example.invalid/bookshop/pull/1")
"""


def fake_writer(*flags: str) -> str:
    """`--executor` for the test tree's fake writer: this interpreter, the paths quoted."""
    return " ".join(shlex.quote(a) for a in (sys.executable, str(FAKE_WRITER), *flags))


def init_flow(sc: Scenario) -> None:
    work, tmp = sc.root / ".modsys/init", sc.root.parent
    log, prs, remote = tmp / "writer.jsonl", tmp / "gh.jsonl", tmp / "remote.git"
    seen = {}

    def lines(path: Path) -> list[dict]:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def statuses() -> dict:
        doc = json.loads((work / "state.json").read_text(encoding="utf-8"))
        return {m: e["status"] for m, e in doc["modules"].items()}

    def starts() -> list[str]:
        return [e["module"] for e in lines(log) if e["event"] == "start"]

    def fixture():
        sc.root.rmdir()
        monorepo_builder()(sc.root)
        seen["base"] = sc.git("rev-parse", "HEAD")

    def map_it():
        data, _ = sc.modsys("init", "map")
        check(data["candidates"] == CANDIDATES, f"candidates {data['candidates']}")
        doc = json.loads((work / "proposal.json").read_text(encoding="utf-8"))
        for candidate in doc["candidates"]:
            candidate["include"] = candidate["name"] != "tools"
        (work / "proposal.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        sc.append(".modsys/config.toml", "\n[init]\nmax_parallel = 1\n")

    def confirm():
        data, _ = sc.modsys("init", "confirm")
        check((data["status"], sorted(data["included"]), data["excluded"])
              == ("confirmed", SIX, ["tools"]), f"confirm {data}")

    def fanout():
        sc.modsys("init", "fanout")
        items = sorted(p.stem for p in (work / "work").glob("*.json"))
        check(items == SIX and set(statuses().values()) == {"pending"}, f"work items {items}")

    def killed():  # the fake writer SIGKILLs `init run` on its third call
        sc.modsys("init", "run", "--executor",
                  fake_writer("--record", str(log), "--stop-after", "2"), expect=-9)
        got = statuses()
        check(sorted(got.values()) == ["done", "done", "pending", "pending", "pending",
                                       "running"], f"after the kill {got}")
        seen["done"], seen["starts"] = {m for m, s in got.items() if s == "done"}, len(starts())

    def resume():
        data, _ = sc.modsys("init", "resume", "--executor", fake_writer("--record", str(log)),
                            "--non-interactive")
        check(data["ran"] == ["run", "reconcile", "eval-tasks", "verify"], f"resume {data}")
        again = starts()[seen["starts"]:]
        check(set(statuses().values()) == {"done"}
              and sorted(again) == sorted(set(SIX) - seen["done"]),
              f"started again: {again}, done before: {sorted(seen['done'])}")
        seen["registry"] = (work / "staging/registry.json").read_bytes()

    def reconcile():
        data, _ = sc.modsys("init", "reconcile", "--force")
        duplicates = [(d["name"], [x["module"] for x in d["definitions"]])
                      for d in data["duplicates"]]
        collisions = [(c["keyword"], c["owner"], c["moved"]) for c in data["collisions"]]
        check((duplicates, collisions) == ([("formatPrice", ["catalog", "ui-kit"])],
                                           [("price", "cart", ["catalog"])]),
              f"duplicates {duplicates}, collisions {collisions}")
        check((work / "staging/registry.json").read_bytes() == seen["registry"],
              "the rebuilt staging registry differs from the resumed run's")

    def eval_tasks():
        data, _ = sc.modsys("init", "eval-tasks", "--executor", fake_writer(), "--force")
        check((data["status"], data["tasks"], set(data["per_module"].values()))
              == ("written", 30, {5}), f"eval-tasks {data}")

    def verify():
        data, _ = sc.modsys("init", "verify")
        routing = data["routing"]
        check((data["passed"], data["invented"], routing["hits"], routing["tasks"])
              == (True, [], 30, 30), f"verify {data['lint']['summary']} {routing}")

    def finish():
        sc.git("init", "-q", "--bare", str(remote))
        sc.git("remote", "add", "origin", str(remote))
        shim = tmp / "bin" / "gh"
        shim.parent.mkdir()
        shim.write_text(GH_SHIM.format(python=sys.executable, log=str(prs)), encoding="utf-8")
        shim.chmod(0o755)
        data, _ = sc.modsys("init", "finish", "--open-pr",
                            env={"PATH": f"{shim.parent}{os.pathsep}{sc.env.get('PATH', '')}"})
        check(data["pr"] == "https://example.invalid/bookshop/pull/1", f"finish {data}")
        count = sc.git("rev-list", "--count", f"{seen['base']}..modsys/init")
        pushed = sc.git("--git-dir", str(remote), "rev-parse", "modsys/init")
        check((count, pushed) == ("1", sc.git("rev-parse", "modsys/init")),
              f"modsys/init: {count} commit(s) on the base, pushed {pushed}")
        calls = lines(prs)
        body = calls[0]["body"] if calls else ""
        check(len(calls) == 1 and calls[0]["argv"][:2] == ["pr", "create"]
              and "## Verify" in body and "- routing: hit rate 1.0 (30/30" in body
              and "| Module | Hits | Tasks |" in body, f"gh calls {calls}")
        argv, subject = calls[0]["argv"], sc.git("log", "-1", "--format=%s", "modsys/init")
        title = argv[argv.index("--title") + 1] if "--title" in argv else None
        check(subject == title == "docs: module docs for 6 module(s) (modsys init)",
              f"commit subject {subject!r}, pull request title {title!r}")  # Conventional

    for name, fn in [("the bookshop monorepo with its history", fixture),
                     ("init map: seven candidates, tools switched off", map_it),
                     ("init confirm: six modules", confirm),
                     ("init fanout: six work items", fanout),
                     ("init run, killed after two modules", killed),
                     ("init resume: every module done once", resume),
                     ("init reconcile: the duplicate and one collision", reconcile),
                     ("init eval-tasks: the canned tasks", eval_tasks),
                     ("init verify passes", verify),
                     ("init finish --open-pr: one commit, one pull request", finish)]:
        sc.step(name, fn)


SCENARIOS = {"greenfield": greenfield, "brownfield": brownfield, "packs": packs,
             "skills": skills, "adopt": adopt, "init-map": init_map, "init": init_flow}


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
    names = [n.strip() for n in os.environ.get(ONLY, "").split(",") if n.strip()] \
        or list(SCENARIOS)  # "adopt, init" works too
    unknown = sorted(set(names) - set(SCENARIOS))
    if unknown:
        print(f"adoption eval: unknown scenario(s) in {ONLY}: {', '.join(unknown)}",
              file=sys.stderr)
        return 2
    chosen = {n: SCENARIOS[n] for n in SCENARIOS if n in names}
    with ThreadPoolExecutor(max_workers=len(chosen)) as pool:  # independent temp repos
        results = pool.map(lambda item: run_scenario(*item), chosen.items())
        card = dict(zip(chosen, results))
    print(json.dumps(card, indent=2, ensure_ascii=False))
    for name, result in card.items():
        state = "ok" if result["ok"] else "FAILED"
        print(f"adoption eval: {name} {state} ({len(result['steps'])} steps, "
              f"{result['commands']} commands)", file=sys.stderr)
    return 0 if all(r["ok"] for r in card.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
