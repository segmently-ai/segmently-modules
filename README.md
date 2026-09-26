# modsys

Code-structure-centric context layer for AI coding agents: a module registry, per-module
interface docs and per-role context files, maintained by a CLI and agent skills.

modsys keeps a registry of your code's functional modules (`modules/registry.json`), one
`MODULE.md` plus role docs (`roles/developer.md`, `roles/qa.md`, …) per module, and rules that
map code files to modules. With that, an agent asks "what do I read before this task?"
(`context`), "which modules does this change touch?" (`discover`), and CI asks "did the code
change without its docs?" (`lint --changed`). Every verb prints a JSON envelope with `--json`
and uses exit codes a pipeline can branch on ([docs/cli-contract.md](docs/cli-contract.md)).

Status: pre-release, private. Python ≥ 3.11, stdlib only; git for `coverage`,
`lint --changed` and `--from-diff`.

## Install

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install /path/to/modsys                       # a checkout
pip install git+https://github.com/<owner>/modsys.git   # or the repository
modsys --help
```

## Greenfield in 5 minutes

A new todo API with three features: tasks, lists, reminders.

```bash
mkdir todo && cd todo && git init
modsys init        # .modsys/config.toml (commented starter), modules/registry.json, .gitignore lines
```

Create the modules. A top-level module needs a one-sentence description (20–200 characters)
and at least 5 distinct keywords — the terms that route a task to it:

```bash
modsys create tasks --non-interactive \
  --description "Task items: create, complete, reorder; the home of a single task." \
  --keyword task --keyword todo --keyword complete --keyword due --keyword priority
modsys create lists --non-interactive \
  --description "Task lists: group, share and order tasks in named lists." \
  --keyword list --keyword group --keyword share --keyword board --keyword folder
modsys create reminders --non-interactive \
  --description "Reminders: schedule and send notifications before a task is due." \
  --keyword reminder --keyword notify --keyword schedule --keyword alarm --keyword snooze
```

Each gets `modules/<name>/MODULE.md`, one doc per standard role and a registry entry. Now wire
the code: modules know nothing about code until a `[[code_map]]` rule (or a `code_pointer`
field) says which files belong to which module.

```bash
mkdir -p src/tasks src/lists src/reminders
touch src/tasks/__init__.py src/lists/__init__.py src/reminders/__init__.py
```

Append to `.modsys/config.toml`:

```toml
[[code_map]]
id = "src"
pattern = "src/{module}/**"     # {module} = one path segment naming a module: src/tasks/x.py -> tasks
```

Record a typed relation, then check everything:

```bash
modsys registry append reminders related_modules \
  '{"module": "tasks", "relation": "depends-on", "description": "Reminders fire for task due dates"}'
modsys lint                          # 0 error(s), 0 warning(s), 0 info
modsys coverage --fail-under 80      # share of the repo's files that map to a module, unmapped files
modsys show reminders                # docs to read, and `code  src/reminders/**`
git add .gitignore .modsys modules src && git commit -m "modules"
```

The agent loop — before planning, after the change, and the CI gate:

```bash
modsys context --task "snooze a reminder" --role developer   # what to read, where the code is
BASE=$(git rev-parse HEAD)
# … the agent changes src/reminders/snooze.py and commits …
modsys lint --changed --base "$BASE" --fail-on warning      # exit 1: MS050, code changed, docs did not
modsys propose --run-id r1 --module reminders --op doc_append \
  --doc modules/reminders/roles/developer.md --reason "document snooze" --value-file - <<'EOF'
## Snooze

`snooze(minutes)` moves the reminder's due time; a snoozed reminder fires once.
EOF
modsys sync --from-diff "$BASE..HEAD" --apply-proposals     # maps the change, runs hooks, applies proposals
git add modules/reminders && git commit -m "docs: snooze"
modsys lint --changed --base "$BASE" --fail-on warning      # exit 0
```

Agents never edit the registry or module docs mid-run: they `propose`, and one
`sync --apply-proposals` (or `proposals apply`) applies every queued item under the registry
lock. `registry`/`propose` refuse values lint would report as errors (an unknown status, an
edge without a description or to an unknown module).

A child module for a sub-area, with its own code rule:

```bash
modsys create search --parent tasks --non-interactive \
  --description "Full-text search over task titles and notes." --keyword search
```

```toml
[[code_map]]
id = "task-search"
module = "tasks/search"          # a globs rule may name a child
globs = ["src/tasks/search/**"]
exclusive = true                 # otherwise rule "src" maps these files to tasks as well
```

## Brownfield: an existing, layered codebase

```bash
cd existing-app
modsys init                      # keeps your .gitignore, appends two lines
modsys coverage                  # everything unmapped: the baseline
```

1. **One module per feature** (`modsys create orders …`, `modsys create invoices …`), plus one
   per shared layer that has its own rules (`modsys create db …`).
2. **Map the layers.** Layered repos keep a feature's code in several places
   (`app/routes/orders/`, `app/repositories/orders.py`, `app/models/orders.py`). One `pattern`
   rule per layer does it; mark the rules whose files would ALSO match a shared layer's broader
   rule `exclusive`, so a feature change does not drift the layer module too:

   ```toml
   [[code_map]]
   id = "routes"
   pattern = "app/routes/{module}/**"

   [[code_map]]
   id = "repositories"
   pattern = "app/repositories/{module}.py"
   exclusive = true              # app/repositories/orders.py -> orders only, not db

   [[code_map]]
   id = "db"
   module = "db"
   globs = ["app/db/**", "app/repositories/**"]   # base classes, sessions, the rest
   ```

3. **Iterate on `modsys coverage`** until the unmapped list is only what belongs to no module
   (exclude it with `[coverage] exclude = [...]`), then gate CI on
   `modsys coverage --fail-under 80` (your target) next to `modsys lint --changed`.
4. **Optional per-module layout** — one `modules/<name>/module.json` per module instead of one
   shared file (fewer merge conflicts in big teams):

   ```bash
   modsys index split               # writes modules/<name>/module.json for every module
   # then set [paths] registry_layout = "per-module" in .modsys/config.toml
   modsys list                      # same modules, now read from the module files
   modsys index build --check       # in CI: exit 1 when the generated index is stale
   ```

## Reference

- [docs/configuration.md](docs/configuration.md) — config layers, every section and key, packs,
  lint codes.
- [docs/cli-contract.md](docs/cli-contract.md) — every verb's JSON `data`, exit codes, the files
  the engine creates, pipeline stages.
- `modsys <verb> --help` — flags and limits of one verb.
- [evals/adoption/](evals/adoption/README.md) — the adoption evals (a deterministic script and
  blind-agent prompts).
