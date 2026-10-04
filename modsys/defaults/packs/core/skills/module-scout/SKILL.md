---
name: module-scout
description: Quick, read-only context on the modules a task is about, while the task is still being discussed. Asks the modsys CLI what each named module is, which docs to read and which modules it is linked to, reads those docs and reports a short brief. No plan, no edits. Use when the user says "look at module X", "load the context for", "what do we know about", or describes a change and names modules before a plan exists.
argument-hint: "[task]"
arguments: task
---

# module-scout

## When to use

- A change is being discussed, or the user names modules (`parent/child` or a doc path) and wants
  their context: a short brief, no plan, no edits.

## When not to use

- The task is confirmed and needs its touch-set: use `module-discover`.
- One question needs a deep answer from the docs and the code: use `module-research`.
- Work is finished and the docs must catch up: use `module-sync`.

## Scope

Read-only: modsys read verbs, reading files; it writes only temporary files outside the
repository, never edits a file, never runs a writer verb, never commits. The registry, layout and
roles come from `modsys`, never from an assumed path.

If `modsys` is not found, tell the user how to install it — the `modsys` plugin for Claude Code, `uv tool install git+ssh://git@github.com/<owner>/<repo>.git`, or `pipx install git+ssh://git@github.com/<owner>/<repo>.git` — and stop until it runs.

## Steps

1. Delegate: hand the user's task verbatim (`$task`), with what the user settled in this
   conversation (files, constraints, the depth), to the `module-scout-agent` agent (Claude Code:
   `modsys:module-scout-agent`) and give its report as yours; without that agent, read
   `references/procedure.md` and follow it.

## Gates

No gates — read-only: it never stops for a confirmation. It asks only when no module is found and
the near misses leave it open.
