# Modules: create, children, status, split, remove or rename, layout

## Create a module
The `module-create` skill: it gathers a one-sentence description, at least five keywords and the
roles, shows a dry run, waits for a yes, then writes the docs from the templates and the
registry entry. By hand:
`modsys create <name> --description "<one sentence>" --keywords "a, b, c, d, e" --non-interactive --dry-run`,
then the same without `--dry-run`.

## Create a child of a module
`module-create` with the parent named, or
`modsys create <child> --parent <module> --keywords "<word>" --non-interactive --dry-run` (one
keyword is enough for a child). `--no-standard-roles` scaffolds only the `--role` / `--tag`
roles: the parent's docs cover the others.

## Change a module's status, description or keywords
`modsys registry set <module> status '"draft"' --dry-run`, then without `--dry-run`. Allowed
statuses: `[registry] statuses` (default `active`, `draft`, `planned`, `temporary`). Keywords:
`modsys registry append <module> keywords '"<word>"' --dry-run`; `remove` takes one out. Values
are JSON: quote strings.

## Split a module that grew too big
The `module-split` skill (lint MS030 / MS031 flag the size): it proposes two to six children,
stops for a confirmation, freezes the split docs as `*.legacy.md`, moves sections verbatim and
turns the parent into an index.

## Remove or rename a module
modsys has no verb for either. Say so. The manual work: the registry entry, the module's
directory, its `context_files` paths, the edges other modules point at it with
(`modsys related <module> --json` lists them) and its `[[code_map]]` rules; then
`modsys lint --json` shows what is still broken. Ask the user before deleting any doc.

## One registry file or one file per module
`[paths] registry_layout = "per-module"` keeps each entry in `<modules_dir>/<name>/module.json`
plus a generated index: `modsys index split --dry-run`, then without `--dry-run`, converts;
`modsys index build --json` regenerates the index (`--check` in CI). See the modules:
`modsys list --json`, `modsys catalog --json`.
