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

Matching (`match`, `context`, `discover --task`) is exact-token: a keyword matches a whole word
in the task text, case-insensitive, with no stemming or plural handling — the keyword `todo`
does not match a task that says "todos", `complete` does not match "completed". (The word
boundary only applies on an edge of the keyword that is itself a letter/digit/`_`; a keyword
starting or ending with punctuation, e.g. `.epub` or `c++`, can still match inside a longer
token on that side.) Register the forms your team actually types (singular AND plural,
synonyms). If nothing reaches `[match] min_score`, `context`/`match` say so (`no module matched
(try domain terms, or: modsys list)` / `no keyword matches (try rephrasing with domain terms, or
use: list)`) and list the near misses — modules with a keyword that almost matches a task word:

```text
no module matched (try domain terms, or: modsys list)
near  reminders                    reminder ~ reminders
re-run with the module's own keyword in the task text, or read it directly: modsys show reminders
```

(`context --json` carries the same rows as `near_misses`.) Plain `discover --task` with no
match just omits the module — there is no module-name argument to fall back to (`context`
takes only `--task`/`--task-file`, never a module). Re-run with a word that IS one of the
module's registered keywords (`modsys show <module>` prints them on its `keys` line), add the
missing one (`modsys registry append tasks keywords '"todos"'`, JSON value — quote a string),
or skip matching and read the module directly: `modsys show tasks --role developer`.

Each gets `modules/<name>/MODULE.md`, one doc per standard role and a registry entry. Now wire
the code: modules know nothing about code until a `[[code_map]]` rule (or a `code_pointer`
field) says which files belong to which module.

```bash
mkdir -p src/tasks src/lists src/reminders
touch src/tasks/__init__.py src/lists/__init__.py src/reminders/__init__.py
modsys code-map add src --pattern "src/{module}/**"   # {module} = one path segment: src/tasks/x.py -> tasks
```

`code-map add` appends the rule to `.modsys/config.toml` — it never rewrites the file, and
refuses an id that already exists in any layer; edit or remove rules there by hand:

```toml
[[code_map]]
id = "src"
pattern = "src/{module}/**"
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

The agent loop — before planning, after the change, and the drift half of the CI gate (the
other half, plain `modsys lint --fail-on warning` plus `modsys coverage --fail-under …`, is not
shown here — see the CI gate row in [docs/cli-contract.md](docs/cli-contract.md)):

```bash
modsys context --task "snooze a reminder" --role developer   # what to read, where the code is
BASE=$(git rev-parse HEAD)   # the commit the change starts from — capture BEFORE editing/committing
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
modsys code-map add task-search --glob "src/tasks/search/**" --module tasks/search --exclusive
```

A `--glob` rule may name a child (`--module tasks/search`); `--exclusive` keeps rule `src` from
mapping these files to `tasks` as well.

`modsys show tasks` still lists `code  src/tasks/**` — `[[code_map]]` rules are routing globs,
not resolved per-file ownership, so the parent's rule still textually covers
`src/tasks/search/` too. Prove the split against a real file instead:

```bash
modsys discover --files src/tasks/search/index.py
# modify    tasks/search                   via diff
#           update modules/tasks/MODULE.md
#           update modules/tasks/submodules/search/MODULE.md
#           update modules/tasks/submodules/search/roles/developer.md
#           update modules/tasks/roles/developer.md
#           update modules/tasks/submodules/search/roles/qa.md
#           update modules/tasks/roles/qa.md
# file      src/tasks/search/index.py -> tasks/search
```

Only `tasks/search` is listed — the `file` line shows the file maps there and nowhere else.
`discover --files` (space-separated file paths — a directory is refused; a path not on disk is
still mapped and reported as `not on disk`, so a typo shows) is the file-level truth, like
`sync --dry-run --files`; `show`'s / `context`'s `code` and `code_globs` lines are routing
rules, not a file list.

## Brownfield: an existing, layered codebase

```bash
cd existing-app
modsys init                      # keeps your .gitignore, appends two lines
modsys coverage                  # everything unmapped: the baseline
```

1. **One module per feature** (`modsys create orders …`, `modsys create invoices …`), plus one
   per shared layer that has its own rules (`modsys create db …`).
2. **Map the layers — one rule per per-feature layer.** Layered repos keep a feature's code in
   several places (`app/routes/orders/`, `app/repositories/orders.py`, `app/models/orders.py`,
   per-feature SQL under a shared directory like `app/db/queries/sql/orders.sql`, schemas,
   tests…). Give EVERY per-feature layer its own `{module}` `pattern` rule — not just the
   obvious ones — and mark `exclusive` any per-feature rule whose files sit inside a shared
   layer's directory, so a feature change does not silently also count as a change to the
   shared module:

   ```bash
   modsys code-map add routes --pattern "app/routes/{module}/**"
   modsys code-map add repositories --pattern "app/repositories/{module}.py" --exclusive
   modsys code-map add queries-sql --pattern "app/db/queries/sql/{module}.sql" --exclusive
   modsys code-map add db --module db --glob "app/db/**" --glob "app/repositories/**"
   ```

   `repositories` is exclusive so `app/repositories/orders.py` maps to `orders` only, not also
   to `db`; `queries-sql` is exclusive because its per-feature files live INSIDE the shared
   `app/db/` tree — without that rule they silently map to `db`, not `orders`. `db` keeps the
   base classes, sessions and the rest.

   Check the rules against real files, one per layer: `modsys discover --files
   app/db/queries/sql/orders.sql` (its `file` line should read `-> orders`, not `-> db`) — the
   same command used to verify the child-module split above.
3. **Iterate on `modsys coverage`** until the unmapped list is only what belongs to no module
   (exclude it with `[coverage] exclude = [...]`), then look at `modsys coverage --json`'s
   per-module counts: a shared/catch-all module with a suspiciously large file count is the
   smell of a missing per-feature rule (see the SQL example above) — `modsys code-map files db`
   lists exactly which files it holds and through which rule. Then gate CI on all three:
   `modsys lint --fail-on warning` (config-level findings such as a typo'd `[[code_map]]` rule
   appear only here, never under `--changed`; the default `fail_on = "error"` misses MS052, a
   warning), `modsys lint --changed --base origin/main --fail-on warning` (name a real base —
   `--base` defaults to `HEAD`, so a bare `--changed` on a clean CI checkout diffs HEAD against
   itself and can never find drift; in CI use the PR's target ref, e.g. `origin/main`, or the
   `"$BASE"` captured before the change, as in the agent loop above) and `modsys coverage
   --fail-under 80` (your target).
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
