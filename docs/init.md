# Start from existing code: `modsys init`

> Start here: [README](../README.md), "Start from existing code". Every verb's JSON:
> [cli-contract.md](cli-contract.md). The `[init]` keys: [configuration.md](configuration.md#init).

A repository with code and no module registry gets its modules, their docs, the registry, the
code routing rules and the agents' block in seven phases. Two of them are gates where a person
decides; everything else is a script, or a writer (an agent) per module. The engine keeps every
intermediate file in `<config_dir>/init/` (default `.modsys/init/`, git-ignored by `modsys init`)
and never touches the modules dir, the registry or the config before the last gate.

| # | Phase | Command | Writes (in `<config_dir>/init/`) | Who |
|---|---|---|---|---|
| 1 | preflight | `modsys init map` | `preflight.json` | the script |
| 2 | map | `modsys init map` | `proposal.json` | the script |
| — | gate 3 | `modsys init confirm` | `confirmed.json` | a person edits the proposal, then confirms |
| 4 | fan-out | `modsys init fanout`, then the writers | `work/<module>.json`, `staging/<module>/` | one writer per module |
| 5 | reconcile | `modsys init reconcile` | `staging/registry.json`, `reconcile.json` | the script (a person judges what it lists) |
| 6 | verify | `modsys init eval-tasks`, `modsys init verify` | `routing-tasks.json`, `verify.json` | a task writer, then the script |
| — | gate 7 | `modsys init finish` | the modules dir, the registry, the config, the agents' block | a person, or a pull request |

`modsys init status` shows every phase and every module, and names the next step;
`modsys init resume` continues from the recorded phase.

## Gate 3: the candidates

`modsys init map` proposes candidate modules from the package manifests, the source
directories, the imports, CODEOWNERS and the files that change together. Edit
`<config_dir>/init/proposal.json` — each candidate's `include`, `name` and `paths` — to merge,
split, rename or drop candidates, then `modsys init confirm`: it names every problem at once
(a name that breaks the `create` rule, a glob that matches no file, two candidates that claim
one file) and freezes the proposal as `confirmed.json`. An agent that drives init stops after
`init map`: it shows the candidates and asks the person before `init confirm` (the
`module-init` skill does this). Once the fan-out has started the module set is fixed: `init
confirm` refuses, and `modsys init map --restart` starts over — unless modules were created by
hand in the registry meanwhile: then `--restart` refuses too (continue with `modsys init
resume`, or take them out of the registry and the modules dir first). After `init finish`,
`init map` says `init is finished — see modsys init status`.

## Phase 4: one writer per module

`modsys init fanout` writes one work item per confirmed module:

```json
{"module": "cart", "parent": null, "paths": ["packages/cart/**"],
 "files": ["packages/cart/package.json", "packages/cart/src/index.ts"], "files_total": 2,
 "neighbours": [{"to": "catalog", "imports": 1}], "roles": ["developer", "qa", "po", "architect"],
 "staging_dir": ".modsys/init/staging/cart", "prompt": "…"}
```

`files` holds the first 200 files (in path order), `files_total` all of them; `neighbours` the
import edges to other confirmed modules; `roles` the role docs `create` would scaffold. The
`prompt` tells the writer what to write into `staging_dir`: `MODULE.md`, one `roles/<role>.md`
per role (from the doc templates, embedded), and `entry.json` — `description` (the `[create]`
length limits), `keywords` (at least `[create] min_keywords`, the words a task about the module
would use), optional `related_modules` edges — describing only components that exist.

A module the registry already has (someone created it by hand after gate 3) is `done` from the
start (`existing: true`, no prompt) and never rewritten; a `<modules_dir>/<name>/` without a
registry entry stops the fan-out until it is registered or moved away.

Each module's status: `pending` → `running` (claimed) → `done` or `failed`. Three ways to get
them written, all over the same state:

- **An agent session with subagents** — the `module-init` skill (docs/skills.md) claims up to
  `[init] max_parallel` items and hands each to a subagent.
- **One agent, no subagents** — a loop:

  ```bash
  modsys init next --json                 # claims the first pending module: its work item and prompt
  # … write the files into the item's staging_dir …
  modsys init done cart --json            # checks them: done, or exit 1 naming each problem
  ```

- **CI** — an executor command:

  ```bash
  modsys init run --executor "my-writer --model small"
  ```

  It runs the command once per pending module, `[init] max_parallel` at a time: the prompt on
  stdin, the root as the working directory, `MODSYS_INIT_MODULE`, `MODSYS_INIT_STAGING` and
  `MODSYS_INIT_WORK` (absolute paths) in the environment. The command is split like a shell
  line but never run by a shell. Exit 0 and a staging output `init done` accepts → `done`.
  Exit 0 and a refused output → retried once in the same run: a new attempt (its staging dir
  cleared) whose prompt ends with the problems, and a stderr line `modsys: <module>: refused —
  retrying once`; refused again → `failed` with them. A retry that cannot be claimed (the
  writer left its staging dir a symlink or not removable, its work item is gone) → `failed`
  with the problems and `; the retry could not start: <reason>` — the other modules run on.
  Any other exit → `failed` at once with the last 20 lines of stderr — no retry. A write
  outside `<config_dir>/init/` fails the run.
  There is no timeout: stop a hung run with Ctrl-C, then `modsys init resume`.

`modsys init done` checks a staging dir: exactly the expected files, none empty or still holding
a placeholder of the templates (see "Your own prompts"), `entry.json` with only the allowed keys
and the `create` rules, edges to known modules with a known relation and a description.

`init done` also runs the invented-component check of `init verify` (below) over the module's
`MODULE.md` and role docs, read at their final paths, so the writer fixes what it invented
while it still has the context: every backticked repository path exists inside the root — or
is a doc this init will write (`<modules_dir>/<module>/MODULE.md` and the role docs of the
work items: a writer may cite a sibling's doc before it is written) —, and a backticked `Name`
of a components table occurs in its row's file. Each problem names the doc and the line:
`MODULE.md:12: path does not exist: src/lines.ts (write paths from the repository root, as in
the file list)`, `MODULE.md:20: symbol not found in its row's file: lineTotals`, `MODULE.md:20:
no file to check: lineTotal`. A doc that is missing, empty or not UTF-8 is named as such and
not read. `init verify` still runs the full check over the whole staging tree.

The problems of an output `init run` refused stay in the module's entry of `state.json`
(`problems`, shown by `modsys init status`) until its next claim — by `init run`, `init resume
--executor` or `init next`. That claim hands them to the writer: the returned item carries them
as `previous_problems`, and its `prompt` ends with a section `## The previous attempt was
refused` listing them (the work item file itself never changes). The section is added at the
claim, after the template was rendered, so it may quote a `${…}` from a problem line. An `init
done` that refuses writes nothing: the writer is still at work. A claim whose work item file is
missing is refused before anything is written (exit 2, the problems kept), naming the way out:
`modsys init fanout` while no module has been claimed yet, else `modsys init map --restart`.

A killed or failed run is picked up by `modsys init resume` (or `modsys init run` again): every
`running` or `failed` module goes back to `pending` with its staging dir cleared; a `done`
module is never run again.

## Phase 5: reconcile

`modsys init reconcile` (every module done) builds the staging registry from the `entry.json`
files and reports in `reconcile.json`:

- `edges` — the import edges between modules become `depends-on` edges (a writer's own edge to
  the same module wins);
- `collisions` — a keyword two new modules hold belongs to the one with the most files whose
  path or text holds it; the others lose it from their keywords — never a negative keyword,
  which would pull them out of every task that uses the word (unless removing it leaves one
  below the keyword minimum, or it is a tie: then it is a judgement item);
- `duplicates` — a name defined in two modules, at least one of them new (Python top-level
  `def` / `class`, JS/TS `export function|class|const|interface|type`), with file:line — a
  module created by hand counts as the other (a report row: its entry is never changed); a
  name only modules created by hand share is not reported;
- `judgement` — what the script leaves to a person: ties, keyword floors, duplicates.

Edit the new modules' entries in `staging/registry.json` by hand (keywords, descriptions) as
you like: `verify` reads the edits. A module that was already in the registry is changed in the
registry itself, then `modsys init reconcile --force` — `init finish` never rewrites it. Do that
first: `--force` rebuilds the staging registry from the `entry.json` files, so the new modules'
keyword edits come after it. A second `reconcile` refuses to overwrite the edits (exit 2);
`--force` rebuilds from the `entry.json` files; a hand edit that breaks the file is named by
`verify` (fix it, or `--force`).

## Phase 6: routing and verify

The routing eval measures whether a task a developer would type reaches its module. The tasks
come from a writer that never sees the keywords:

```bash
modsys eval routing --prompt              # the task writer's prompt: each module's purpose paragraph and files
modsys init eval-tasks --executor "my-writer"   # or: the executor writes .modsys/init/routing-tasks.json
modsys eval routing --tasks .modsys/init/routing-tasks.json   # the hit rate (during init: the staging registry)
```

A task hits when its module (or one of its children) is among the first 3 modules `context`
ranks for it. The eval passes when hits ≥ `[init] routing_min_hit_rate` × tasks (0.8 by default);
`hit_rate` is rounded down to 3 decimals.

`modsys init verify` reads the staging tree as if it were in place and runs three checks:

1. **lint** — clean means no error and no warning (info is fine);
2. **invented components** — every backticked repository path in a staging doc exists inside
   the root (the staging docs count at their final paths), and in a table with a `Symbol` or
   `Name` column and a `Path` column, a backticked symbol occurs, as a whole identifier, in the
   file of its row's `Path` cell (a table without a `Path` column is not checked; a file that
   cannot be read as text — a directory, unreadable, binary — is `no file to check`);
3. **routing** — the eval above, when `routing-tasks.json` exists (else `routing: not
   measured`).

It writes `verify.json` with a hash of the staging tree (files and symlinks): `init finish`
refuses a tree that changed since. On misses, improve the missed new modules' keywords in
`staging/registry.json` — never the tasks — and verify again. A tasks file `init eval-tasks`
refuses (not JSON, a module left out) is moved to `routing-tasks.rejected.json`: the next step
is `init eval-tasks` again, and until it succeeds `init verify` and `init finish` refuse (exit 2:
`the routing tasks were refused — run modsys init eval-tasks (or write the file and use
--force)`). Written by hand instead: `init verify --force` measures the file, `init finish
--force` records the override. Both also refuse a symlinked `staging/<module>/`.

## Gate 7: finish

```bash
modsys init finish                        # a person read verify.json: move, register, map, tell the agents
modsys init finish --open-pr              # or: a branch, one commit, a pull request (gh)
```

`init finish` moves every new module's staging docs into the modules dir, adds its entry to the
registry through the registry writer, appends one `[[code_map]]` rule `init-<module>` (its
confirmed paths) to the team config, and writes the managed block into `CLAUDE.md` /
`AGENTS.md` (those that exist; `--agents-md FILE` names others) — all or nothing, and never a
commit: it prints the `git add` line. It refuses while verify has not passed or the last `init
eval-tasks` run was refused (`--force` records the override) and never overwrites a module
directory or a registry entry that appeared since. A file an interrupted finish could not put
back is named in its error.

`--open-pr` needs `gh` on `PATH`, a remote `origin` and a clean tree (the starter files `init`
created may be uncommitted: the commit takes them). It creates `modsys/init` (`--branch`) from
the current commit, commits, pushes and opens the pull request against the current branch
(`--base`) with the verify summary, the routing table and the judgement items. The commit's
subject and the pull request's title are `docs: module docs for <n> module(s) (modsys init)`
(Conventional Commits). A commit a hook, the git identity or signing refuses, a failed push or
`gh` leaves the pull request pending: `modsys init resume --open-pr` retries what is left, back
on the branch. A step that was done but not recorded (a kill in between) is not done twice: the
commit already on the branch is kept, and a pull request `gh` says already exists is recorded.

## Without a person

```bash
modsys init map
modsys init resume --non-interactive --executor "my-writer" --open-pr
```

`init resume` continues from the recorded phase and stops at the first step that needs an
agent or a person, naming it. With `--non-interactive` gate 3 passes as the proposal stands,
the executor writes the modules and the routing tasks, a failing verify stops the run (exit 1),
and gate 7 is the pull request — without `--open-pr` it stops before `init finish`.

## Your own prompts

Both prompts are templates, resolved like every template (the team's override, then the packs,
then the engine):

| Template | Renders |
|---|---|
| `init/module_prompt.md` | a work item's `prompt`: `${module}`, `${paths}`, `${files}`, `${files_note}`, `${neighbours}`, `${staging_dir}`, `${docs}`, `${roles}`, `${relations}`, `${description_min}`, `${description_max}`, `${min_keywords}`, `${ask_fields}` |
| `init/routing_prompt.md` | the task writer's prompt: `${count}`, `${per_module}`, `${modules}` |

```bash
modsys templates list                               # init/module_prompt.md  engine  …
modsys templates override init/module_prompt.md     # a copy in .modsys/overrides/templates/ to edit
```

A placeholder a template does not know is rendered as `<name>`: a rendered prompt never holds
`${` (the section a claim appends after a refused attempt may quote one from a problem line).

`modsys init done` refuses a staging doc that still holds `${<name>}` (or `${<name>` without its
brace) for a `<name>` that is a placeholder of a template `init` renders for that module — the
resolved `MODULE.md`, the role templates of its work item and `init/module_prompt.md` (your
override and packs included, so their own placeholders count too). Any other `${…}` is text:
`${API_URL}` in a shell example or a JavaScript template string passes. The one case it still
refuses is code that uses one of those names itself (`${title}` in a JavaScript string): the
writer rewords it. A template it cannot read then (not UTF-8, unreadable) stops `init done` with
exit 2 `cannot read <path>: <reason>`; under `init run` that module fails at once (`the check
could not run: …`, no retry) and the others run on.

## When something goes wrong

| Situation | What to do |
|---|---|
| `init confirm` exit 2 | fix every problem it names in `proposal.json`, confirm again |
| `init confirm` after the fan-out | refused: `modsys init map --restart` starts over — refused too once modules were created by hand in the registry: continue with `modsys init resume`, or take them out of the registry and the modules dir first |
| a module stays `failed` | `modsys init status` shows its error; `modsys init resume` puts it back |
| a run was killed | `modsys init resume`: interrupted modules restart from a clean staging dir |
| `init reconcile` exit 2 (edited) | keep the edits, or `--force` to rebuild from `entry.json` |
| `init eval-tasks` exit 1 | the refused file is in `routing-tasks.rejected.json`: fix the task writer, then `modsys init eval-tasks` again (no `--force` needed) |
| `init verify` / `init finish` exit 2: the routing tasks were refused | `modsys init eval-tasks` again; or write `routing-tasks.json` by hand, then `init verify --force` and `init finish --force` (recorded) |
| `init finish` exit 2 (verify) | `modsys init verify`, then finish; `--force` only on purpose |
| `init finish` exit 2 (conflict) | a module directory appeared since: move it away — only that clears it (a new reconcile rebuilds the same entry); a staging registry edit of a module already in the registry: make it in the registry itself, then `modsys init reconcile --force` |
| `init finish` was interrupted | `modsys init finish` again: an interrupted finish puts back what it wrote (a file it could not put back is named: restore it by hand; after a kill, move away what it left — its refusal names each file) |
| a pull request is pending | fix what refused it (a commit hook, the git identity, the remote, `gh`), then `modsys init resume --open-pr` |
