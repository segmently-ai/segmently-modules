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
modsys init        # .modsys/config.toml (starter: enables the core skills), modules/registry.json, .gitignore lines
```

Create the modules. A top-level module needs a one-sentence description (20–200 characters)
and at least 5 distinct keywords — the terms that route a task to it:

```bash
modsys create tasks --non-interactive \
  --description "Task items: create, complete, reorder; the home of a single task." \
  --keywords "task, todo, complete, due, priority"
modsys create lists --non-interactive \
  --description "Task lists: group, share and order tasks in named lists." \
  --keywords "list, group, share, board, folder"
modsys create reminders --non-interactive \
  --description "Reminders: schedule and send notifications before a task is due." \
  --keywords "reminder, notify, schedule, alarm, snooze"
```

`--keywords` takes a comma-separated list (repeatable); `--keyword` (repeatable) adds one
keyword at a time — use it for a keyword that itself contains a comma.

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

The agent loop — before planning, after the change, and the gate (`modsys ci`, see
[CI gate](#ci-gate)):

```bash
modsys context --task "snooze a reminder" --role developer   # what to read, where the code is
BASE=$(git rev-parse HEAD)   # the commit the change starts from — capture BEFORE editing/committing
# … the agent changes src/reminders/snooze.py and commits …
modsys ci --base "$BASE"     # exit 1: step drift failed — MS050, code changed, docs did not
modsys propose --run-id r1 --module reminders --op doc_append \
  --doc modules/reminders/roles/developer.md --reason "document snooze" --value-file - <<'EOF'
## Snooze

`snooze(minutes)` moves the reminder's due time; a snoozed reminder fires once.
EOF
modsys sync --from-diff "$BASE..HEAD" --apply-proposals     # maps the change, runs hooks, applies proposals
git add modules/reminders && git commit -m "docs: snooze"
modsys ci --base "$BASE"     # exit 0: lint passed, drift passed, coverage report-only
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
   lists exactly which files it holds and through which rule; plain `modsys lint` reports two
   rules that route one file to two modules as MS053. Then gate CI with `modsys ci` (next
   section) and your coverage target.
4. **Optional per-module layout** — one `modules/<name>/module.json` per module instead of one
   shared file (fewer merge conflicts in big teams):

   ```bash
   modsys index split               # writes modules/<name>/module.json for every module
   # then set [paths] registry_layout = "per-module" in .modsys/config.toml
   modsys list                      # same modules, now read from the module files
   modsys index build --check       # in CI: exit 1 when the generated index is stale
   ```

## CI gate

```bash
modsys ci --base origin/main --fail-under 80
```

One command, three steps that always all run, so one failure never hides another: `lint`
(plain — config-level findings such as a typo'd `[[code_map]]` module, MS052, or two rules
routing one file to two modules, MS053, appear only here), `drift` (`lint --changed` against
`--base`: code changed without its module's docs, MS050) and `coverage` (fails below
`--fail-under`; without a threshold it only reports). Exit 1 when a step failed, 2 for a usage
error. `--base` must be a real ref — in CI the pull request's target branch (fetch it first),
or the `"$BASE"` captured before a change; against the default `HEAD` a clean checkout has
nothing to compare, and `ci` says so in its notes. Outside a merge-ref checkout, pass
`--base "$(git merge-base origin/main HEAD)"` so the target branch's own later commits are not
counted as changes. Put the team's defaults in `[ci]` of `.modsys/config.toml` (`fail_on`,
`base`, `coverage_fail_under`), then CI runs a bare `modsys ci`.

## Core skills

modsys ships agent skills that drive it for you — in Claude Code and Codex. `modsys init`
enables them (`[packs] builtin = ["core"]` in `.modsys/config.toml`; add `"ui"` and `"qa"` for
the designer and QA-acceptance packs). Copy them where the agents read them and commit them:

```bash
modsys packs sync --agent claude --agent codex   # .claude/skills/module-*/ and .agents/skills/module-*/
```

- `module-scout` — quick context on the modules a task names, while it is discussed;
- `module-discover` — the touch-set of a confirmed task or a branch: modules, docs, code files;
- `module-research` — one question answered in depth from docs and code, with the gaps;
- `module-sync` — after the work: docs, keywords and links brought in line, `ci` green;
- `module-create` — a new module or child, confirmed by a dry run;
- `module-split` — an oversized module split into children, confirmed before any write;
- `module-lint` — the gate explained and its safe findings fixed.

Each one, the `ui` / `qa` packs, keeping them current and owning one: [docs/skills.md](docs/skills.md).

## Packs and skills

A pack is a team's own layer on top of modsys: roles with their doc templates and agent skills
that read those docs. It lives in `.modsys/packs/<id>/` and is committed with the repository.

```bash
modsys packs new team --role reviewer --skill api-review   # pack.toml, roles/reviewer.md, skills/api-review/SKILL.md
modsys create reviews --non-interactive --role reviewer \
  --description "Customer reviews of books: ratings, comments and moderation." \
  --keywords "review, rating, stars, comment, moderation"
modsys packs sync --agent claude --agent codex   # .claude/skills/api-review/ and .agents/skills/api-review/
modsys agents-md --target CLAUDE.md --target AGENTS.md   # one managed block telling agents how to use modsys
```

`packs sync --check` and `agents-md --check` are the CI lines; `modsys eject <skill>` takes a
skill over (the pack never overwrites it again) and `modsys templates list` shows where every doc
template comes from. The walkthrough, `pack.toml` reference, conflicts and the lint codes
MS060–MS065: [docs/writing-a-pack.md](docs/writing-a-pack.md).

## Reference

- [docs/configuration.md](docs/configuration.md) — config layers, every section and key, packs,
  lint codes.
- [docs/cli-contract.md](docs/cli-contract.md) — every verb's JSON `data`, exit codes, the files
  the engine creates, pipeline stages.
- [docs/writing-a-pack.md](docs/writing-a-pack.md) — packs: roles, templates, agent skills,
  `packs sync`, `eject`, the `agents-md` block.
- [docs/skills.md](docs/skills.md) — the built-in skills (`core`, `ui`, `qa`): what each one
  does, enabling, syncing and owning them.
- `modsys <verb> --help` — flags and limits of one verb.
- [evals/adoption/](evals/adoption/README.md) — the adoption evals (a deterministic script and
  blind-agent prompts).
