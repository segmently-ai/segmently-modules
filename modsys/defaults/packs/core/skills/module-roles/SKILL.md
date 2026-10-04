---
name: module-roles
description: Adds a new role's doc to every existing module. Declares the role when it is undeclared, shows the plan with modsys roles add --dry-run, writes the docs, fills each one from that module's code and docs, then checks lint and next. Use when the user says "add a role", "a new role for every module", "the upgrade brought a role", or when modsys next names roles add.
---

# module-roles

## When to use

- The team (or a newer modsys) added a role, and the existing modules lack its doc.
- The user asks to add a role to every module, or `modsys next --json` names `roles add` for a role.

## When not to use

- A code change made the docs stale: use `module-sync`.
- The work needs a new module: use `module-create`.
- Only lint findings need fixing: use `module-lint`.

## Scope

Writes: one `roles/<role>.md` doc per registered module and child (never over an existing doc), and
the role's declaration in the team config when it is undeclared. It never edits a `*.legacy.md`
file, never edits code, never commits; ask the user to review and commit. Temporary files go
outside the repository.

If `modsys` is not found, tell the user how to install it — the `modsys` plugin for Claude Code, `uv tool install git+ssh://git@github.com/<owner>/<repo>.git`, or `pipx install git+ssh://git@github.com/<owner>/<repo>.git` — and stop until it runs.

## Steps

When the team (or a newer modsys) adds a role, the existing modules lack its doc.

When `modsys next --json` names the roles add command with --all for a role (the upgrade brought
the role), the role is declared already — start at step 1.

If `modsys roles list --json` does not list the role, declare it first: a [roles.ROLE] table with
order, standard = true (every module gets the doc) and a one-line description in the team config,
.modsys/config.toml, or in a pack the team owns — ask the user what the role is for when unclear.
Then continue with step 1.

1. `modsys roles add ROLE --all --dry-run` — show the user the docs it would create or register and
   the registered ones missing on disk.
2. `modsys roles add ROLE --all --json` — writes them, never over an existing doc; `--recreate`
   only for a registered doc whose file is gone.
3. Fill each new doc with what that role needs for that module, from its code and docs — one module
   at a time, never inventing components.
4. `modsys lint --json` — fix what the new docs caused.
5. `modsys next --json` — report what is left.

## Gates

Autonomous by default: it declares, writes and fills. It stops and asks only when the role is
undeclared and what it is for is unclear: the user says what the role covers, then it declares
the role. Never fill a doc with a claim the module's code and docs do not support.

## Exit codes

`0` ok · `1` = findings left (`lint`) or a role that cannot be added: read the result and act ·
`2` = a usage or config error or a refused write: read stderr, fix the input, run again once.
