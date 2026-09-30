---
name: module-create
description: Creates a new module, or a child of an existing one, with its docs and registry entry through modsys create. Gathers the name, a one-sentence description, at least five keywords, the roles and the parent, shows a dry run and waits for a yes, then creates it, fills the scaffolded docs from what the user knows, routes its code and checks lint. Use when the user says "add a module", "create a module for X", "register this area", or when work lands in code that no module owns.
---

# module-create

Add a module (or a child of a split module) the way the registry expects it: a scaffolded doc
set filled with what is actually known, a registry entry that routes tasks to it, and its code
mapped — confirmed by the user before anything is written.

## When to use

- The user wants a new module, or a new child under an existing module.
- `module-discover` or `module-sync` reported files that no module owns, and the user agrees
  they form a new area.

## When not to use

- The module exists and only its docs are behind: use `module-sync`.
- An existing module is too big and should become several children: use `module-split`.
- You only need to know whether a module for X already exists: use `module-scout`.

## Scope

Writes: the new module's docs (scaffolded by the `create` verb, then filled in), its registry
entry, and a routing rule for its code in the team config (the `code-map add` verb). It never
edits another module, never edits a `*.legacy.md` file, and never commits.

If `modsys` is not found, tell the user how to install it — the `modsys` plugin for Claude Code, `uv tool install git+ssh://git@github.com/<owner>/<repo>.git`, or `pipx install git+ssh://git@github.com/<owner>/<repo>.git` — and stop until it runs.

## Steps

1. Check the name is free and not a duplicate in disguise.

   ```bash
   modsys list --json
   modsys match "<the new module's main words>" --json
   ```

   A strong match means an existing module may already own this area: show it and ask before
   going on.

2. Gather the answers, one question at a time when the user has not given them:

   - **name**: lowercase words joined by `-`;
   - **description**: one sentence — what it does, why it exists, when a task belongs to it;
   - **keywords**: at least five words or short phrases a task about it would use (a child
     needs one), in the user's own vocabulary;
   - **roles**: every module gets the standard role docs; extra roles come from `--role`, or
     from `--tag` for roles the config ties to a tag. The configured roles are the
     `roles/<role>.md` rows of `modsys templates list --json`;
   - **parent**: only for a child of an existing module;
   - **code**: where its code lives, if it exists yet.

3. Show the plan and wait.

   ```bash
   modsys create <name> --non-interactive --description "<one sentence>" --keywords "<k1, k2, k3, k4, k5>" --dry-run
   modsys create <child> --parent <module> --non-interactive --description "<one sentence>" --keywords "<k1>" --dry-run
   ```

   Add `--role <role>` or `--tag <tag>` as gathered. Show the files it would write and the
   registry entry. Exit 2 names what is wrong (a taken name, a description out of bounds, too
   few keywords): fix it with the user and show the dry run again. **Wait for an explicit yes.**

4. Create it — the same command with `--json` in place of `--dry-run`:

   ```bash
   modsys create <name> --non-interactive --description "<one sentence>" --keywords "<k1, k2, k3, k4, k5>" --json
   ```

5. Fill the scaffolded docs (the `files` of the result). Every template section holds a short
   prompt in an HTML comment: replace it with what the user told you and what the existing code
   shows, or delete the section when there is nothing true to say yet. Never invent components
   or rules. For an area that is only planned, say "Planned:" before what does not exist yet.

6. Route its code, when the user said where it lives.

   ```bash
   modsys code-map add <rule id> --glob "<glob>" --module <name> --dry-run
   modsys code-map add <rule id> --glob "<glob>" --module <name> --json
   ```

   Show the dry run first. A rule id that exists already is refused: pick another id.

7. Check it.

   ```bash
   modsys lint --json
   modsys show <name> --json
   ```

   No error findings for the new module; every doc in `read[]` exists.

8. Report the files written, the registry entry, the routing rule, and what the docs still
   leave open. Ask the user to review and commit.

## Gates

- After the dry run (step 3): nothing is written until the user says yes.
- Before routing code (step 6): the user confirms the glob.

## Exit codes

`0` ok · `1` from `lint` = findings (fix the new module's, report the others) · `2` = a
refused input or config error: read stderr, fix with the user, run again.
