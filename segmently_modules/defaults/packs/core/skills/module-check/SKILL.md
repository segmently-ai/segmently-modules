---
name: module-check
description: Checks a written plan, or a diff before commit, against every critical rule of the modules it touches; reports conflicts quoting the plan and at most five reminders. Read-only.
---

# module-check

At discovery a task's words rarely name the rule it will break; a plan's words do
(`set(…, {merge: true})` against "nested fields: dot-paths, never merge"). Check the plan.

## When to use

- A plan, a design or a report that names the approach is written and not carried out yet.
- A change is ready to commit: the diff since its base.

## When not to use

- No plan yet: `module-discover` maps the task first.
- The docs must change: `module-sync`.

## Scope

Read-only: it writes only a temporary file outside the repository. It never edits the plan, the
code or a doc, and never commits.

If `segmently-modules` is not found, tell the user how to install it — the `segmently-modules` plugin for Claude Code, `uv tool install git+https://github.com/segmently-ai/segmently-modules.git`, or `pipx install git+https://github.com/segmently-ai/segmently-modules.git` — and stop until it runs.

## Steps

1. The modules: every module the plan or its discovery report names, and the files the plan
   edits (or the change's files).
2. The rules, whole: `segmently-modules rules <module>… --files <path>… > <temp file>` (a
   change: `--from-diff <base>..HEAD`, `<base>` being where the work branched off,
   `git merge-base <target> HEAD`); read the file to the end.
3. Check with `references/prompt.md`: in a fresh agent with no tools when the agent can start
   one (it sees only the plan and the rules), else yourself.

## Report

- `Conflicts:` each — the rule with its `doc:line`, the plan's words quoted, the fix; or `none`.
- `Reminders:` at most five — the rule with its `doc:line`, why it bears on this plan.
- `Not checked:` the modules with no rules (`module-sync` writes their index) and the files
  outside modules; a module whose rules run past about 30,000 characters is checked but named
  here too: a section that took in feature text buries its rules (`module-sync` keeps it to rules).

## Exit codes

`0` ok · `2` from `rules` = a usage error (an unknown module, no module and no file): read stderr,
fix the command.

## Gates

No gates — read-only: it reports and stops; the user decides what to change.
