# Roles and templates

## Change the template a role's docs are written from
`modsys templates list --json` shows, per template, the layer that wins here: `override`,
`role-template:<pack>`, `pack:<pack>`, `engine`, or `engine-fallback` (the generic `_role.md`
for a role with no file of its own). `modsys templates override roles/<role>.md --dry-run`, then
without `--dry-run`, copies the winning one to `.modsys/overrides/templates/roles/<role>.md`;
edit that copy — it wins from then on (an existing override is never replaced). Keep the
placeholders the copied file already uses (the module's title, name, description, status,
keywords and parent, the role and its description): `create` and `roles add` fill them in.

A template only shapes NEW docs (`create`, `roles add`); existing docs are never rewritten. To
bring existing docs to the new shape: list them (`modsys roles list --json`, the role's `docs`),
then add the new sections module by module from each module's code and docs, after the user's
OK — never overwrite what someone wrote. Undo: delete the override file.

For several repositories: put the template in a team pack instead
(`<pack>/templates/roles/<role>.md`, or the role's `template` key in its `pack.toml`).

## Change the MODULE.md template
The same: `modsys templates override MODULE.md --dry-run`, then without `--dry-run`; edit
`.modsys/overrides/templates/MODULE.md`.

## Add a role to every module
The `module-roles` skill: it declares the role when it is new (a `[roles.<name>]` table with
`order`, `standard = true` and a one-line `description` in `.modsys/config.toml`), shows
`modsys roles add <role> --all --dry-run`, writes the docs and fills them.

## A role only some modules need
`[roles.<name>]` with `standard = false` and `applies_when = "<tag>"`; `create … --tag <tag>`
scaffolds its doc; for existing modules `modsys roles add <role> <module> --dry-run`, then
without `--dry-run`.

## See the roles and who lacks a doc
`modsys roles list --json` — every role, its `docs` and `missing` modules; a child without its
own doc is `inherited` (the parent's covers it). Hide a role: `enabled = false` in its table.
