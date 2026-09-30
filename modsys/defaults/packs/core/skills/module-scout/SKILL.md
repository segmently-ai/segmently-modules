---
name: module-scout
description: Quick, read-only context on the modules a task is about, while the task is still being discussed. Asks the modsys CLI what each named module is, which docs to read and which modules it is linked to, reads those docs and reports a short brief. No plan, no edits. Use when the user says "look at module X", "load the context for", "what do we know about", or describes a change and names modules before a plan exists.
---

# module-scout

Give the conversation the module context it needs before anything is decided: what each module
is for, the rules its docs state, and its neighbours. A short brief — no plan, no edits.

## When to use

- The user names one or more modules (a module, `parent/child`, or a path to a module doc) and
  wants to understand them before deciding anything.
- A change is being discussed and you need to know what the modules involved say about it.
- You are about to answer a question about a module whose docs you have not read yet.

## When not to use

- The task is confirmed and you need the touch-set — modules, docs to update, code files: use
  `module-discover`.
- One question needs a deep answer from the docs AND the code, with file:line evidence: use
  `module-research`.
- Work is finished and the module docs must catch up: use `module-sync`.

## Scope

Read-only: it runs modsys read verbs and reads files. It never edits a file, never runs a
writer verb and never commits. Everything it knows about the registry, the module layout and
the roles comes from `modsys` — never from a path it assumes.

If `modsys` is not found, tell the user how to install it — the `modsys` plugin for Claude Code, `uv tool install git+ssh://git@github.com/<owner>/<repo>.git`, or `pipx install git+ssh://git@github.com/<owner>/<repo>.git` — and stop until it runs.

## Steps

1. Make sure modsys answers here.

   ```bash
   modsys list --json
   ```

   Exit 2 means no registry or no config: tell the user what stderr says (usually "run modsys
   init") and stop.

2. For every module the user names, get its read set.

   ```bash
   modsys show <module> --json
   ```

   - `read[]` is the list of docs to open, in order; `exists: false` means the registry points
     at a doc that is missing — say so in the brief.
   - A split module (the result has `submodules`, and its first doc is labelled the parent
     INDEX): read the index, then only the children the topic touches —
     `modsys show <module>/<child> --json` — never all of them.
   - A pointer stub (exit 1, the result has `stub`): the module was retired or merged; report
     what the stub says instead of guessing.
   - The talk is clearly about one audience (testing, design, product): add that role —
     `modsys show <module> --role <role> --json`. The configured roles are the `roles/<role>.md`
     rows of `modsys templates list --json`; never guess a role name.

3. Find the neighbours.

   ```bash
   modsys related <module> --json
   ```

   `edges` are what this module points at, `reverse` what points at it. Read the main doc of
   a forward edge only when its relation says this module needs the other one (for example
   `depends-on`); name the rest — reverse edges included — with their relation, without reading
   them.

4. No module named? Rank them from the topic instead.

   ```bash
   modsys context --task "<the topic in one sentence>" --json
   ```

   Read the `read[]` docs of the top `modules`. When `modules` is empty but `near_misses` is
   not, list the near misses (module and the words that almost matched) and ask which module is
   meant. Never widen the list on your own.

5. Read the docs from steps 2–4. Skim for what the topic needs: purpose, components, rules
   (words like "never", "always", "must"), known pitfalls. Do not open code files — that is
   `module-research`.

6. Report the brief, per module:

   - what it owns, in one or two lines;
   - the rules and constraints that bear on the topic, quoted short, with the doc they come
     from;
   - its neighbours: which were read and why, which were only named;
   - missing docs or stubs;
   - the next step: `module-discover` once the task is confirmed, or `module-research` for a
     question that needs the code.

Keep the brief short enough to read in a minute. No plan, no file list for the change.

## Gates

No gates — read-only: it never stops for a confirmation. It asks the user only when `context`
finds no module and the near misses leave the choice open.

## Exit codes

`0` ok · `1` from `show` or `related` = a pointer stub (step 2) · `2` = a usage or config
error: read stderr, fix the command or report the message; do not retry the same command.
