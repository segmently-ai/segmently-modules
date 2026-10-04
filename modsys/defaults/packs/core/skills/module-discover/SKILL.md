---
name: module-discover
description: Maps a confirmed task, or a change on a branch, to the modules it touches before planning or review, read-only. Runs modsys discover to list each module as modify or reference with the docs to read and to update, lists the code files of every module to modify, and names the files that belong to no module. Can save the result as JSON at a path the user gives. Use when the user asks which modules or files a task will touch, says "do discovery", after a plan is agreed, or when a pipeline needs the touch-set of a change.
argument-hint: "[task]"
arguments: task
---

# module-discover

## When to use

- A task is agreed, or a branch or changed files need their modules, docs and code files.

## When not to use

- The task is still being discussed: use `module-scout`.
- One question needs a deep answer with code evidence: use `module-research`.
- The change is done and the docs must catch up: use `module-sync`.

## Scope

Read-only: modsys read verbs, docs, code search. It writes only temporary files outside the
repository and, at a path the user names, the JSON result; it never edits docs or code and never
commits.

If `modsys` is not found, tell the user how to install it — the `modsys` plugin for Claude Code, `uv tool install git+ssh://git@github.com/<owner>/<repo>.git`, or `pipx install git+ssh://git@github.com/<owner>/<repo>.git` — and stop until it runs.

## Steps

1. Delegate: hand the user's task verbatim (`$task`), with what the user settled in this
   conversation (files, constraints, the depth), to the `module-discover-agent` agent (Claude Code:
   `modsys:module-discover-agent`) and give its report as yours; without that agent, read
   `references/procedure.md` and follow it.

## Gates

No gates — read-only: it reports and stops. It asks only for a missing input or a JSON file's path.
