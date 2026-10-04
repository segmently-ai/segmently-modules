---
name: module-research
description: Answers one question about one or more modules in depth, from their docs and their code, read-only. Reads every role doc, the module's links in both directions, the code files modsys maps to it and its lint findings, then writes a brief with file:line evidence that names every place where the docs and the code disagree. Use for "how does X really work", "is the doc of X still true", "explain module X in depth", or before a risky change to X.
argument-hint: "[task]"
---

# module-research

## When to use

- A question about a module needs proof from the code: is its doc still true, what does it do
  before a risky change.

## When not to use

- The gist of a module while a task is discussed: use `module-scout`.
- The touch-set of a confirmed task: use `module-discover`.
- The docs must be fixed, not just checked: report the gaps here, then `module-sync` (after a
  change) or `module-lint` (for findings).

## Scope

Read-only: modsys read verbs, docs, code; it writes only temporary files outside the repository,
never edits a file — gaps are reported, not fixed — and never commits.

If `modsys` is not found, tell the user how to install it — the `modsys` plugin for Claude Code, `uv tool install git+ssh://git@github.com/<owner>/<repo>.git`, or `pipx install git+ssh://git@github.com/<owner>/<repo>.git` — and stop until it runs.

## Steps

1. Delegate: hand the user's task verbatim, with what the user settled in this
   conversation (files, constraints, the depth), to your platform's agent and give its report as
   yours. Claude Code: the `modsys:module-research-agent` agent. Codex: spawn the
   `module-research-agent` custom agent (`.codex/agents/`). Only when no such agent exists, read
   `references/procedure.md` and follow it. A request that also says "change nothing" is still a
   hand-off: the agent is read-only.

## Gates

No gates — read-only: it reports and stops. It asks only when the question is too broad to answer
with evidence (then it proposes a narrower one).
