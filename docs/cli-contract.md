# modsys CLI contract (for pipelines)

> Start here: [README](../README.md) — install, a 5-minute walkthrough, brownfield adoption.
> Every config section and key, packs and the lint codes: [configuration.md](configuration.md).

Every verb accepts `--root DIR` (default: nearest directory with `.modsys/` or
`modules/registry.json`, else the nearest `.git`; `init`: the git top-level of the current
directory, else the current directory), `--config-dir DIR` (default `<root>/.modsys`) and
`--json`.

- **stdout with `--json`:** exactly one JSON document `{"schema": "modsys.<verb>/1", "data": …}`.
- **Exit codes:** `0` ok · `1` findings (lint at/above `--fail-on`, coverage below
  `--fail-under`, a failed `ci` step, rejected proposals, a failed required hook, a stale index with `--check`, a
  pointer stub) · `2` usage, config or registry error (a missing registry says to run
  `modsys init`) — stdout is empty, stderr carries `modsys: error: …`. The one extra code is `130`:
  interrupted by Ctrl-C (SIGINT, e.g. during a lock wait or at a `create` prompt), stderr
  `modsys: interrupted`.
- **Never a traceback:** an unexpected failure is exit `2` with `modsys: internal error: …`;
  set `MODSYS_DEBUG=1` to see the traceback.
- **Writers** (`registry`, `index`, `proposals apply`, `sync --apply-proposals`, `create`,
  `migrate`) take the registry lock (`<registry>.lock`), write atomically, and refuse a file that
  changed since it was read. `code-map add` appends one rule to `<config_dir>/config.toml` (one
  append-mode write, validated first; never a rewrite). `--dry-run` writes nothing. Field writes (`registry`, `propose`,
  proposals from hooks) refuse a value lint would report as an error for that field: a `status`
  outside `[registry] statuses`, a `related_modules` edge without `module` / `relation` /
  `description`, with an unknown relation, or to an unknown module or child. `init` only
  creates files that do not exist yet (and appends missing `.gitignore` lines).
- **`--files PATH …`** (`sync`, `discover`): a path that does not exist is still mapped (a
  deleted file is a real change) and listed in `missing_files` (`[]` for `--from-diff`, which
  lists real changes only); a directory is refused (exit `2`, nothing mapped, no hook runs) —
  list its files instead, e.g. `git ls-files <dir>`.
- **Git refs** (`--from-diff A..B` of `sync` / `discover`, `--base REF` of `lint --changed` and
  `ci`): a
  value starting with `-` is refused (exit `2`) — it would be read as a git option. Changed paths
  are relative to the root and limited to it, also when the root is a subdirectory of the git
  repository; a rename counts as a delete plus an add.

## Files the engine creates

- `<registry>.lock` (default `modules/registry.json.lock`): the advisory lock every writer takes
  — in the per-module layout too, where it guards every `<module>/module.json` and the index
  (`index build` takes the same lock). It stays on disk; ignore it in git.
- `<proposals_dir>/` (default `.modsys/proposals/`): the proposals queue — pending
  `<run_id>-<agent>.json` files, a `<run_id>-<agent>.json.lock` next to each, and `done/` with
  every processed file and its per-item results. Ignore the whole directory unless the team wants
  the queue history in git; then ignore only its `*.lock` files.

```gitignore
modules/registry.json.lock
.modsys/proposals/
```

`modsys init` appends these two lines (for the configured registry and proposals paths) when
they are missing.

| Verb | `data` |
|---|---|
| `init` | `{root, layout, files: [{path, status}], dry_run}` — root: `--root`, else the git top-level of the current directory, else the current directory; `status`: `created` · `updated` (`.gitignore` got its missing lines) · `exists`; creates only missing files, a second run changes nothing |
| `schema` | JSON Schema (draft 2020-12) of the registry, including declared fields |
| `match TEXT` | `[{module, score, keywords, negative}]` best first — always this plain list; the near-miss hint (below, `context`) appears only in the text output |
| `show MODULE` | `{module, status, description, keywords, read: [{label, path, exists}], code: [path], code_globs: [glob], submodules?}`; a pointer stub: `{module, stub}` (exit 1). `keywords` = the target's own routing keywords (a child: the child's list); `code` = values of `code_pointer` fields; `code_globs` = the `[[code_map]]` globs that route files to the module (a pattern's `{module}` filled in) — both are routing rules, not a file list; for the files a given change actually touches use `discover --files` / `sync --dry-run --files` |
| `related MODULE` | `{module, edges: [edge], reverse: [{from, …edge}]}` |
| `list` | `[{module, status, description, children}]` |
| `lint` | `{findings: [{code, severity, module, message, path}], summary: {error, warning, info}, failed, changed?: {base, files, modules}}` |
| `registry OP TARGET FIELD [VALUE]` | `{op, target, field, dry_run, changed, diff?}` |
| `index build\|split` | build: `{index, stale, written, check}` · split: `{files, dry_run, next}` |
| `propose` | `{file, run_id, agent, item}` — `--agent` defaults to `$MODSYS_AGENT`, else `cli` |
| `proposals list\|apply\|reject` | list: `[{file, run_id, agent, created_at, items}]` · apply: `{files: [{file, run_id, agent, results: [{id, op, module, status, reason?}]}], summary: {applied, noop, rejected}, dry_run}` · reject: `{rejected_files}` |
| `hooks list` | `[{event, id, owner, enabled, required, run}]` |
| `sync` | `{run_id, diff_range, changed_files, modules: [{module, files, via}], unmapped, missing_files, hooks: {hooks: [{id, owner, required, status, messages, queued, error?}], failed_required} \| null, proposals: <apply data> \| null, dry_run}` |
| `create NAME` | `{module, files, entry, dry_run}` |
| `migrate` | `{applied: [{id, description, notes}], dry_run, diff?}` |
| `context` | `{task, role, all_roles, modules: [{module, score, keywords, negative, read, code, code_globs}], read: [{module, label, path, exists}], near_misses: [{module, score, keywords, near: [{keyword, task_word}]}]}` — `near_misses` is `[]` whenever a module matched; when none reaches `[match] min_score` it lists the targets with a keyword that loosely matches a task word (`near`) or with exact hits below `min_score` (`keywords`, `score`), at most `top` |
| `discover` | `{task, modules: [{module, score, keywords, sources, touched_files, usage, docs_to_read, docs_to_update}], files: [{path, modules: [target]}], files_outside_modules, missing_files, summary: {total_modules, by_usage: {modify, reference}}}` — `task` and every `score` are `null` when only `--from-diff` / `--files` is given (no keyword scoring ran); with a task, a module found only through the change has `score` `0`. `files` = every changed file with the targets it maps to (`[]` = unmapped), sorted by path |
| `coverage` | `{total, mapped, share, modules: {target: n}, unmapped: [path]}` — files = git-tracked + new not ignored, filtered by `[coverage] include`/`exclude`, never the modules dir, the config dir or dotfiles; `share` = mapped / total, rounded down to 3 decimals (`1.0` when no file counts, so it never overstates); `--fail-under PCT` must be `0`–`100` (else exit 2) and is compared against the reported percent (`share` × 100, rounded to one decimal) — exit 1 when that percent is below `PCT`; exit 2 outside a git repository |

| `code-map list\|add\|files` | list: `[{id, module, pattern, globs, exclusive}]` — the effective `[[code_map]]` rules (every layer merged; `module` / `pattern` / `globs` are `null` when the rule has none); `--module TARGET` keeps the rules that route files to TARGET (a rule naming it, or a `pattern` rule for a top-level TARGET) · add `ID (--pattern P \| --glob G … --module M) [--module M] [--exclusive] [--dry-run]`: `{id, file, block, dry_run}` — `block` = the appended `[[code_map]]` text; refused (exit 2, nothing written) without `config.toml`, for an id defined in any layer, an unknown `--module`, a pattern without `{module}` · files `TARGET`: `{target, files: [{path, via: [source]}], total}` — every repository file (git-tracked + new, not ignored; `[coverage]` filters do not apply) that maps to TARGET, `via` = `docs` · `code_pointer:<field>` · `code_map:<id>`; exit 2 outside a git repository; an unknown TARGET is exit 2 |
| `ci` | `{base, fail_on, steps: [{name, status, summary, findings?}], failed, notes}` — `steps` always `lint`, `drift`, `coverage`, in that order, all run; `status`: `passed` · `failed` · `report-only` (coverage without a threshold) · `no-changes` (drift found no changed file); lint/drift `summary` = `{error, warning, info}` (drift adds `base`, `files`, `modules`) and `findings` as in `lint`; coverage `summary` = `{share, mapped, total, unmapped, fail_under}` (`unmapped` = a count); `notes` explains a drift step with nothing to compare against `HEAD`. Exit 1 when a step failed; exit 2 (stdout empty, no step ran) for an unknown or option-like `--base`, a threshold outside 0–100, a root outside git. Settings: flag, else `[ci]`, else `fail_on` `warning`, base `HEAD`, no threshold |

## Pipeline stages

| Stage | Command |
|---|---|
| before plan | `modsys context --task "…" --role developer --json` |
| after plan | `modsys discover --task-file plan.md --json` |
| CI, no task text | `modsys discover --from-diff $BASE..HEAD --json` |
| during build | `modsys propose --run-id $RUN --agent builder --module M --op … --reason "…"` |
| after build | `modsys sync --from-diff $BASE..HEAD --apply-proposals --run-id $RUN --json` |
| CI gate | `modsys ci --base $BASE --fail-under 80 --json` — lint (plain: config-level findings MS021, MS052, MS053 appear only here), drift against `$BASE` (a real ref: the PR's target branch or a captured pre-change commit) and coverage, always all three |
