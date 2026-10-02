---
name: qa-acceptance
description: Writes the acceptance criteria of one task before any code is written. Finds the touched modules with modsys discover, reads their qa and qa_acceptance docs, flags problems in the task itself, splits it into sub-tasks, applies equivalence partitioning, boundary values, decision tables or state transitions, and writes prerequisites PRE-NNN and criteria AC-NNN in Given, When, Then form, reusing existing baseline criteria by id. Saves a Markdown file the user names. Use when the user asks for acceptance criteria, a test plan or a definition of done for a task.
---

# qa-acceptance

Say, before the code exists, what "done" means for one task: measurable criteria that
prove every part of it works, that do not contradict each other, and that point at the
modules' baselines instead of repeating them.

## When to use

- A task is agreed and the user wants its acceptance criteria, test plan or definition of done.
- A reviewer asks "how will we know this works?" before implementation starts.

## When not to use

- The criteria are for a whole module (what must never break), not one task: use
  `qa-acceptance-baseline`.
- You need the modules and files the task touches, not criteria: use `module-discover`.
- A UI change needs a design review: use `designer-review`.

## Scope

Writes: one Markdown file with the criteria, at the path the user names. It never edits code,
module docs or a `*.legacy.md` file, and never commits.

If `modsys` is not found, tell the user how to install it — the `modsys` plugin for Claude Code, `uv tool install git+ssh://git@github.com/<owner>/<repo>.git`, or `pipx install git+ssh://git@github.com/<owner>/<repo>.git` — and stop until it runs.

## Steps

1. Find the modules. Put the task text in a temporary file outside the repository, then

   ```bash
   modsys discover --task-file <file> --match lexical --json
   ```

   Keep the `modify` modules and the `reference` modules whose docs really bear on the task.

2. Read what the modules already guarantee and how they are tested.

   ```bash
   modsys show <module> --role qa_acceptance --json
   modsys show <module> --role qa --json
   ```

   The `qa_acceptance` doc is the module's baseline (criteria with ids, P0 / P1 / P2); the `qa`
   doc says how the module is tested. A missing doc (`exists: false`, or exit 2 "unknown role"
   when the `qa` pack is not enabled): work from the module's other docs and say so.

3. Check the task before writing criteria: contradictions, missing cases, words two readers
   would read differently, behaviour that disagrees with a baseline criterion. List each as a
   spec issue with a proposed resolution.

4. Split the task into sub-tasks (what data, what behaviour, what interfaces, what side
   effects it changes). For each, pick the technique that fits and derive the conditions:

   - **equivalence partitioning** — input classes that behave alike, one case each;
   - **boundary value analysis** — the values at and just past each limit;
   - **decision table** — every combination of conditions that changes the outcome;
   - **state transition** — every allowed and every refused move between states.

   Give each sub-task a risk (critical, high, medium, low) from its impact and likelihood.

5. Write the criteria.

   - Prerequisites `PRE-NNN`: quick checks that the ground is ready (a service answers, a
     fixture exists), each with the check and the expected result.
   - Criteria `AC-NNN`: **Given** a starting state, **When** one action, **Then** an observable
     result — an exact value, message, status code or file, never "works correctly". Tag each
     with its sub-task, technique, risk and how it is verified (unit, integration, manual).
   - Coverage first: behaviour a baseline criterion already covers and the task does not
     change is referenced by id ("covered by `<module>` AC-007") instead of restating it;
     behaviour the task changes gets a new criterion, and the old baseline id goes into a
     "baseline updates needed" list.

6. Close the loop: every sub-task has at least one criterion; no two criteria contradict;
   every sub-task has a criterion from a technique of step 4, not only judgement; and if every
   criterion passed, the task would really be done. Fix any gap before writing.

7. Write the file at the path the user named (ask for one first): summary, spec issues,
   sub-tasks, prerequisites, criteria, baseline updates needed, gaps. Ask the user to review
   and commit it.

## Gates

- Before writing: the file path, when the user has not named it.
- A spec issue that blocks a criterion (two readings that lead to different tests): ask which
  reading is meant, with your recommendation.

## Exit codes

`0` ok · `2` from `discover` or `show` = a usage or config error: read stderr (an unknown role
means the `qa` pack is not enabled here — step 2).
