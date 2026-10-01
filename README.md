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

Pick the route your agent uses — every one gives the same `modsys` command line.

**Python.** modsys needs Python ≥ 3.11. Stock macOS ships 3.9 at `/usr/bin/python3`, which is too
old: `uvx` (or `uv tool install`) fetches a suitable Python by itself, or `brew install python`
and use that one.

**Claude Code** — the plugin carries the skills and the command line:

```bash
claude plugin marketplace add <owner>/<publish repo>#stable
claude plugin install modsys@modsys        # the core skills and `modsys` itself
claude plugin install modsys-ui@modsys     # optional: the designer-review skill
claude plugin install modsys-qa@modsys     # optional: the acceptance-criteria skills
```

**Codex** — the plugin carries the skills; install the command line first (a Codex plugin puts
nothing on `PATH`), at the released version the plugin comes from:

```bash
uv tool install git+ssh://git@github.com/<owner>/<repo>.git@v<version>   # or pipx install, below
codex plugin marketplace add <owner>/<publish repo> --ref stable
codex plugin add modsys@modsys
```

A repository that keeps the default `"repo"` delivery and has run `modsys packs sync` shows a
plugin user every built-in skill twice — the plugin's and the copy; `builtin_delivery =
"plugin"` (below) makes `packs sync` remove the copies it made.

**Cursor, Gemini CLI, GitHub Copilot** — no plugin: install the command line, set modsys up in
the repository (`modsys init` enables the `core` pack; or set `[packs] builtin` in
`.modsys/config.toml` yourself), then copy the skills into `.agents/skills/` — these agents
need the default `"repo"` delivery:

```bash
uv tool install git+ssh://git@github.com/<owner>/<repo>.git
modsys init                                 # once: the config, with [packs] builtin = ["core"]
modsys packs sync --agent cursor            # or --agent gemini, --agent copilot
modsys packs sync --agent cursor --remove   # later: take the copies out again
```

The `dev` channel carries every change before a release: `#dev` instead of `#stable`, `--ref
dev`, and the marketplace `modsys-dev` (`claude plugin install modsys@modsys-dev`). A repository
whose agents get the built-in skills from the plugins sets `builtin_delivery = "plugin"` under
`[packs]`, so `packs sync` does not copy them a second time
([docs/skills.md](docs/skills.md#from-the-repository-or-from-a-plugin)).

**The command line alone** — in a virtual environment, from a checkout or the repository:

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install /path/to/modsys                       # a checkout
pip install git+https://github.com/<owner>/<repo>.git   # or the repository
modsys --help
```

Or from git, without a checkout (Python 3.11 or newer; no other dependency):

```bash
uv tool install git+ssh://git@github.com/<owner>/<repo>.git   # on PATH; uv fetches a Python when none fits
uvx --from git+ssh://git@github.com/<owner>/<repo>.git modsys --version   # or run it without installing
pipx install git+ssh://git@github.com/<owner>/<repo>.git      # needs a Python 3.11+ already installed
```

Add `@v<version>` to the URL to pin a release tag.

## The shortest start

```bash
modsys setup                       # init, packs sync and the agents-md block in one command (--dry-run first)
modsys next                        # the daily loop: what the repository needs now, with the command for each
modsys roles add designer --all    # a new role: its doc for every existing module (--dry-run first)
```

`modsys setup` picks the agents from the skill directories it finds (else `claude` and `codex`)
and writes `CLAUDE.md` for Claude and `AGENTS.md` for every other agent. Gemini CLI reads
`GEMINI.md`, so run `modsys setup --target GEMINI.md` for it. `modsys next` is read-only: one
ranked list of what to fix (lint errors, stale skill copies, a role without docs, …), each item
with the modsys command that fixes it. `modsys roles list` shows, per role, which modules have its
doc and which do not.

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
keyword at a time — use it for a keyword that itself contains a comma. Each `create` is its own
write: when one in a batch like this fails, the modules before it stay created — fix that one and
run it again. `create` warns (on stderr; it still creates the module) about keywords that route
poorly: 3 characters or fewer, a generic word such as `data` or `list`, or a word whose plain
plural or singular is missing (`task` without `tasks`).

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
lock. Without `--run-id` it applies every pending proposal file; `--run-id r1` applies only that
run's (the file `propose --run-id r1` queued) — in a pipeline that runs several agents, pass it:

```bash
modsys sync --from-diff "$BASE..HEAD" --apply-proposals              # every pending run
modsys sync --from-diff "$BASE..HEAD" --apply-proposals --run-id r1  # only run r1
```

The registry writers `registry` and `propose` refuse values lint would report as errors (an
unknown status, an edge without a description or to an unknown module).

### When something goes wrong

A refusal writes nothing and says what to fix; a lint finding names its code. Two of each:

```bash
modsys registry set reminders status '"shipped"'   # exit 2, nothing written
modsys code-map add notes --glob "src/notes/**" --module notes   # exit 2, nothing written
modsys lint --fail-on warning                      # exit 1 after a hand edit (below)
```

```text
modsys: error: field 'status': status 'shipped' not in ['active', 'draft', 'planned', 'temporary'] (lint MS003)
modsys: error: code-map add: 'notes' is not a registry module or child (modsys list shows the modules)
WARNING MS052 *: [[code_map]] 'remind': module 'remiders' is not a registry module or child; the rule maps nothing
WARNING MS053 *: [[code_map]] 'reminder-jobs' (-> reminders) and 'src' (-> tasks) both map 1 file(s), e.g. src/tasks/jobs.py — mark the more specific rule exclusive = true or narrow its globs
```

The fixes: a status from the list (`'"active"'`); `modsys create notes …` first, then the rule;
for MS052 (a hand-edited rule in `.modsys/config.toml`), correct its `module` — the typo
`remiders`; for MS053 (a hand-added rule `reminder-jobs` with the glob `src/*/jobs.py`), make it
`exclusive = true` or narrow its glob, so one file maps to one module — then
`modsys lint --fail-on warning` exits 0 again.

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
modsys init                      # keeps your .gitignore, appends its lines
modsys coverage                  # everything unmapped: the baseline
```

(To have modsys propose the modules from the code first, see
[Start from existing code](#start-from-existing-code); by hand:)

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

   Files of one feature that are not named after it (`app/jobs/nightly_totals.py`,
   `app/api/order_export.py` for `orders`) take ONE rule with a `--glob` per path (`--glob`
   repeats):

   ```bash
   modsys code-map add orders-extra --module orders --glob "app/jobs/nightly_totals.py" --glob "app/api/order_export.py"
   ```

   `exclusive` wins only over NON-exclusive rules. Two exclusive rules that route one file to
   different modules are still an MS053 overlap:

   ```bash
   modsys code-map add repositories --pattern "app/repositories/{module}.py" --exclusive
   modsys code-map add db-repositories --module db --glob "app/repositories/**" --exclusive  # MS053
   ```

   Both claim `app/repositories/orders.py` (for `orders` and for `db`): keep one of them
   exclusive, or narrow the other's globs.

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

## Adopt an existing registry

A repository whose registry and module docs another tool wrote — no `.modsys/` yet — needs a
team config so the engine reads it without surprises (its roles, extra fields, a timestamp key,
where the code lives). `adopt` infers it and never changes the registry or a doc:

```bash
modsys adopt --dry-run     # the config it would write, each key with an `# adopt:` line saying why
modsys adopt               # writes .modsys/config.toml; lint runs in report mode
modsys init                # adds the .gitignore lines (lock file, proposals, init); keeps the config
modsys lint --fail-on warning
git add .modsys/config.toml .gitignore && git commit -m "modsys: read the existing registry"
```

Review the report first: roles (`order`, `standard` when 80 % of the modules carry one),
fields (`type`, `scope`, `kind = "code_pointer"` when their values name repository paths), the
directories under the modules dir that are not modules, the registry's `updated_at` key, one
`[[code_map]]` rule when half the modules have `<prefix>/<module>/` (below half, the best
candidate is written commented out and reported as `code_map_suggestion`), and — commented out,
for the team to decide — doc budgets its docs exceed. `adopt` writes that one file only:
`modsys init` adds the `.gitignore` lines for the lock file, proposals and init, and keeps your
config (`adopt`'s next steps say so while lines are missing). A registry elsewhere: `--registry
docs/modules/registry.json`. With a config already there, `adopt` writes what is still missing
to `.modsys/adopt.proposed.toml` instead — merge it by hand. The rules and thresholds:
[docs/configuration.md](docs/configuration.md#adopting-an-existing-registry).

## Start from existing code

A codebase without modules yet: `init map` proposes them from the code — package manifests,
source directories, imports, CODEOWNERS and the files that change together:

```bash
modsys init map        # the starter files, then .modsys/init/preflight.json and proposal.json
# edit .modsys/init/proposal.json: each candidate's include, name and paths (merge, split, drop)
modsys init confirm    # gate 3: checks the proposal and freezes it as confirmed.json
modsys init fanout     # one work item per module: .modsys/init/work/<module>.json with its prompt
modsys init status     # the phases, the modules and the next step
```

Then one writer per module documents its code into `.modsys/init/staging/<module>/` — three
ways to drive them, over the same state:

- **The `module-init` skill** in an agent session: it runs the whole flow, dispatches one
  subagent per module (`[init] max_parallel` at a time) and stops at both gates for you.
- **One agent, one module at a time**: `modsys init next` claims a module and prints its
  prompt; the agent writes the files; `modsys init done <module>` checks them.
- **CI**: an executor command gets each prompt on stdin —
  `modsys init run --executor "<command>"`.

```bash
modsys init reconcile  # the staging registry: import edges, shared keywords, duplicate names
modsys eval routing --prompt   # the task writer's prompt: purpose paragraphs and files, never keywords
# a writer puts [{"task": …, "module": …}] into .modsys/init/routing-tasks.json
modsys init verify     # lint, invented components, the routing hit rate — nothing moved yet
modsys init finish     # gate 7: the docs, the registry, the code-map rules, the agents' block
```

In CI, without a person — gate 3 as proposed, gate 7 as a pull request:

```bash
modsys init map
modsys init resume --non-interactive --executor "my-writer" --open-pr
```

`init finish` never commits (it prints the `git add` line); `--open-pr` makes one commit on a
new branch and opens the pull request with `gh` (both titled
`docs: module docs for <n> module(s) (modsys init)`, a Conventional Commits subject). An
interrupted or failed run continues with `modsys init resume`. Code outside every package root
gets candidates by the source-directory rule too (a top-level `tools/`, say). When `init map`
notes code files outside every candidate, a manifest in a fixture, docs site or functions folder
sits inside a source directory and keeps that directory's code out: add it to `[init] exclude`
and run `modsys init map --restart`. Modules created by hand after gate 3 are kept as they are.
`init map` refuses a registry that already has modules: use `adopt` (above). Every phase, the
executor contract, the prompt templates and verify's checks: [docs/init.md](docs/init.md); the
`[init]` keys: [docs/configuration.md](docs/configuration.md#init).

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
- `module-lint` — the gate explained and its safe findings fixed;
- `module-init` — a codebase without modules taken through `modsys init`, with two stops for you;
- `module-adopt` — an existing registry read as it is: the config inferred and explained.

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
  lint codes, the `adopt` rules and the `[init]` keys.
- [Adopt an existing registry](#adopt-an-existing-registry) and
  [Start from existing code](#start-from-existing-code) — `modsys adopt`, `modsys init map`;
  [docs/init.md](docs/init.md) — every phase of `modsys init`, the executor, `modsys eval
  routing`.
- [docs/cli-contract.md](docs/cli-contract.md) — every verb's JSON `data`, exit codes, the files
  the engine creates, pipeline stages.
- [docs/writing-a-pack.md](docs/writing-a-pack.md) — packs: roles, templates, agent skills,
  `packs sync`, `eject`, the `agents-md` block.
- [docs/skills.md](docs/skills.md) — the built-in skills (`core`, `ui`, `qa`): what each one
  does, enabling, syncing and owning them.
- `modsys <verb> --help` — flags and limits of one verb.
- [evals/adoption/](evals/adoption/README.md) — the adoption evals (a deterministic script and
  blind-agent prompts).
- [docs/releasing.md](docs/releasing.md) — for maintainers: building the plugins, channels and
  versions, the release and its checks, CI.
