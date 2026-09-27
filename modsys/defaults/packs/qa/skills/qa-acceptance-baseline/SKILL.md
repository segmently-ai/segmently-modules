---
name: qa-acceptance-baseline
description: Creates or refreshes a module's acceptance baseline, the qa_acceptance role doc that says what must never break, as P0, P1 and P2 criteria with stable AC-NNN ids in Given, When, Then form. Reads every doc and the code of the module through modsys, confirms its understanding, the requirements and the criteria with the user block by block, continues from the highest existing id and never renumbers. Use when the user asks for a module's acceptance baseline, regression criteria, or to refresh them after the module changed.
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

## Steps

1. Load the module.

   ```bash
   modsys show <module> --all-roles --json
   modsys show <module> --role qa_acceptance --json
   modsys code-map files <module> --json
   ```

   Exit 2 "unknown role 'qa_acceptance'": the `qa` pack is not enabled — tell the user
   (`[packs] builtin` in the team config) and stop. A `role:qa_acceptance` row with
   `exists: true` is the doc to refresh; read it and note the highest `AC-NNN` in it.

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

5. Ids, when refreshing: an unchanged criterion keeps its id and text; a changed one keeps its
   id and is edited in place; a new one takes the next id after the highest existing
   `AC-NNN` — continue the numbering, never renumber and never reuse an id; a criterion that
   no longer applies moves to the "Retired" section with its id and the reason.

6. Write the doc.

   - It exists: edit it in place, section by section (P0, P1, P2, Retired).
   - It does not: start from the file of the `roles/qa_acceptance.md` row of
     `modsys templates list --json`, fill it, save it next to the module's other role docs,
     and add it to the module's `context_files`:

     ```bash
     modsys registry set <module> context_files '<the object with roles.qa_acceptance added>' --dry-run
     modsys registry set <module> context_files '<the object with roles.qa_acceptance added>' --json
     ```

     Build the object from `show --all-roles`: `universal` is the universal row, each
     `role:<role>` row is `roles.<role>`; add `roles.qa_acceptance`. Check the dry run's diff
     changes nothing else.

7. Check it.

   ```bash
   modsys lint --json
   modsys show <module> --role qa_acceptance --json
   ```

   No finding for the doc; the `role:qa_acceptance` row exists. Report the criteria added,
   changed and retired per priority, and ask the user to review and commit.

## Gates

Three, never skipped: Gate 1 (understanding), Gate 2 (each block's requirements), Gate 3 (the
criteria, per block or per batch). Nothing is written before Gate 3 of the last block.

## Exit codes

`0` ok · `1` from `lint` = findings: fix the ones the new doc caused · `2` = a usage or config
error, or a refused write: read stderr (an unknown role means the `qa` pack is not enabled).
