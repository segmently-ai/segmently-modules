---
name: qa-acceptance-baseline
description: Creates or refreshes a module's acceptance baseline, the qa_acceptance role doc that says what must never break, as P0, P1 and P2 criteria with stable AC-NNN ids in Given, When, Then form. Reads every doc and the code of the module through modsys, confirms its understanding, the requirements and the criteria with the user block by block, continues from the highest existing id and never renumbers. Use when the user asks for a module's acceptance baseline, regression criteria, or to refresh them after the module changed.
argument-hint: "[scenario]"
arguments: scenario
---

# qa-acceptance-baseline

Write down, for one module, the behaviour that must keep working — as criteria with ids that
never change, so task-level criteria (`qa-acceptance`) and tests can point at them.

## When to use

- A module has no acceptance baseline yet, and the user wants one.
- A module changed and its baseline must catch up (new behaviour, changed behaviour, retired
  behaviour).

## When not to use

- The criteria are for one task, not the whole module: use `qa-acceptance`.
- You only need to know how the module is tested today: use `module-scout` with the `qa` role.
- The module's other docs are out of date: use `module-sync` first — the baseline is built
  from them.

## Scope

Writes: the module's `qa_acceptance` doc, and its entry in the module's registry
`context_files` when the doc is new. It never edits code or another doc, never edits a
`*.legacy.md` file, and never commits.

If `modsys` is not found, tell the user how to install it — the `modsys` plugin for Claude Code, `uv tool install git+ssh://git@github.com/<owner>/<repo>.git`, or `pipx install git+ssh://git@github.com/<owner>/<repo>.git` — and stop until it runs.

## Steps

**Route.** Take the scenario named by the invocation (`$scenario`) when one is given, else by
the user's words, and its file below: read it, then follow it — its steps are step 5.

- **create** — the module has no acceptance baseline yet ("write", "create", "start" one)
  → `references/create.md`
- **refresh** — the module changed and its baseline must catch up ("refresh", "update" it —
  new, changed or retired behaviour) → `references/refresh.md`

If a `modsys` command exits 1 or 2, read `references/exit-codes.md`.

1. Load the module.

   ```bash
   modsys show <module> --all-roles --json
   modsys show <module> --role qa_acceptance --json
   modsys code-map files <module> --json
   ```

   A `role:qa_acceptance` row with `exists: true` is the doc to refresh; read it and note the
   highest `AC-NNN` in it.

2. Read every doc of the module fully and skim its code files for the interfaces the docs name
   (entry points, commands, messages, limits).

3. **Gate 1 — understanding.** Present: what the module does and why, its main flows, its
   functional blocks with a risk each, the rules its docs state, the edge cases you found, and
   anything the docs and the code disagree on. Wait for "ok" or corrections.

4. For each functional block:

   - list its requirements, each traced to a doc line or a code file — **Gate 2**: wait for
     the user to confirm the list;
   - write its criteria: **Given** / **When** / **Then** with an observable result; P0 for
     critical and high risk, P1 for medium, P2 for low; use boundary values, decision tables
     and state transitions where the requirement has limits, combinations or states —
     **Gate 3**: wait for the user to confirm the criteria.

   For a large module, batch the criteria of several blocks into one Gate 3; never skip Gate 2.

5. Write the doc. Follow the scenario's file (the Route above).

6. Check it.

   ```bash
   modsys lint --json
   modsys show <module> --role qa_acceptance --json
   ```

   No finding for the doc; the `role:qa_acceptance` row exists. Report the criteria added,
   changed and retired per priority, and ask the user to review and commit.

## Gates

Three, never skipped: Gate 1 (understanding), Gate 2 (each block's requirements), Gate 3 (the
criteria, per block or per batch). Nothing is written before Gate 3 of the last block.
