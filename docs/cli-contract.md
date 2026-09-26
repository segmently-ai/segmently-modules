# modsys CLI contract (for pipelines)

Every verb accepts `--root DIR` (default: nearest directory with `.modsys/` or
`modules/registry.json`, else the nearest `.git`), `--config-dir DIR` (default `<root>/.modsys`)
and `--json`.

- **stdout with `--json`:** exactly one JSON document `{"schema": "modsys.<verb>/1", "data": …}`.
- **Exit codes:** `0` ok · `1` findings (lint at/above `--fail-on`, rejected proposals, a failed
  required hook, a stale index with `--check`, a pointer stub) · `2` usage, config or registry
  error — stdout is empty, stderr carries `modsys: error: …`. The one extra code is `130`:
  interrupted by Ctrl-C (SIGINT, e.g. during a lock wait or at a `create` prompt), stderr
  `modsys: interrupted`.
- **Never a traceback:** an unexpected failure is exit `2` with `modsys: internal error: …`;
  set `MODSYS_DEBUG=1` to see the traceback.
- **Writers** (`registry`, `index`, `proposals apply`, `sync --apply-proposals`, `create`,
  `migrate`) take the registry lock (`<registry>.lock`), write atomically, and refuse a file that
  changed since it was read. `--dry-run` writes nothing.
- **Git refs** (`--from-diff A..B` of `sync` / `discover`, `--base REF` of `lint --changed`): a
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

| Verb | `data` |
|---|---|
| `schema` | JSON Schema (draft 2020-12) of the registry, including declared fields |
| `match TEXT` | `[{module, score, keywords, negative}]` best first |
| `show MODULE` | `{module, status, description, read: [{label, path, exists}], code: [path], code_globs: [glob], submodules?}`; a pointer stub: `{module, stub}` (exit 1). `code` = values of `code_pointer` fields; `code_globs` = the `[[code_map]]` globs that route files to the module (a pattern's `{module}` filled in) |
| `related MODULE` | `{module, edges: [edge], reverse: [{from, …edge}]}` |
| `list` | `[{module, status, description, children}]` |
| `lint` | `{findings: [{code, severity, module, message, path}], summary: {error, warning, info}, failed, changed?: {base, files, modules}}` |
| `registry OP TARGET FIELD [VALUE]` | `{op, target, field, dry_run, changed, diff?}` |
| `index build\|split` | build: `{index, stale, written, check}` · split: `{files, dry_run, next}` |
| `propose` | `{file, run_id, agent, item}` |
| `proposals list\|apply\|reject` | list: `[{file, run_id, agent, created_at, items}]` · apply: `{files: [{file, run_id, agent, results: [{id, op, module, status, reason?}]}], summary: {applied, noop, rejected}, dry_run}` · reject: `{rejected_files}` |
| `hooks list` | `[{event, id, owner, enabled, required, run}]` |
| `sync` | `{run_id, diff_range, changed_files, modules: [{module, files, via}], unmapped, hooks: {hooks: [{id, owner, required, status, messages, queued, error?}], failed_required} \| null, proposals: <apply data> \| null, dry_run}` |
| `create NAME` | `{module, files, entry, dry_run}` |
| `migrate` | `{applied: [{id, description, notes}], dry_run, diff?}` |
| `context` | `{task, role, all_roles, modules: [{module, score, keywords, negative, read, code, code_globs}], read: [{module, label, path, exists}]}` |
| `discover` | `{task, modules: [{module, score, keywords, sources, touched_files, usage, docs_to_read, docs_to_update}], files_outside_modules, summary: {total_modules, by_usage: {modify, reference}}}` |

## Pipeline stages

| Stage | Command |
|---|---|
| before plan | `modsys context --task "…" --role developer --json` |
| after plan | `modsys discover --task-file plan.md --json` |
| during build | `modsys propose --run-id $RUN --agent builder --module M --op … --reason "…"` |
| after build | `modsys sync --from-diff $BASE..HEAD --apply-proposals --run-id $RUN --json` |
| CI gate | `modsys lint --changed --base $BASE --fail-on warning --json` |
