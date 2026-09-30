---
name: module-discover
description: Maps a confirmed task, or a change on a branch, to the modules it touches before planning or review, read-only. Runs modsys discover to list each module as modify or reference with the docs to read and to update, lists the code files of every module to modify, and names the files that belong to no module. Can save the result as JSON at a path the user gives. Use when the user asks which modules or files a task will touch, says "do discovery", after a plan is agreed, or when a pipeline needs the touch-set of a change.
---

# module-discover

Turn a confirmed task, or a change, into its touch-set: which modules it modifies or only
references, which docs to read first and which to update afterwards, and which code files
belong to the modules it modifies.

## When to use

- The task is agreed and you are about to plan or implement it.
- A branch or a list of changed files needs its modules (review, CI, a pipeline step).
- The user asks "which modules / docs / files does this touch?".

## When not to use

- The task is still being discussed and you only need background: use `module-scout`.
- One question needs a deep answer with evidence from the code: use `module-research`.
- The change is done and the docs must be updated: use `module-sync`.

## Scope

Read-only: it runs modsys read verbs, reads docs and searches code. The only file it may write
is the JSON result, and only at a path the user names. It never edits the repository's docs or
code and never commits.

If `modsys` is not found, tell the user how to install it — the `modsys` plugin for Claude Code, `uv tool install git+ssh://git@github.com/<owner>/<repo>.git`, or `pipx install git+ssh://git@github.com/<owner>/<repo>.git` — and stop until it runs.

## Steps

1. Pick the input.

   - A task: put its full text in a temporary file outside the repository (or give it on
     stdin with `--task-file -`), then

     ```bash
     modsys discover --task-file <file> --json
     ```

   - A change: the commit range, or the changed files. `<base>` is where the branch left
     its target: `git merge-base <target> HEAD` prints it. The target branch's own name is
     no base — anything merged into it since the branch started would be listed as touched
     (`<target>...HEAD`, with three dots, is accepted as the same range).

     ```bash
     modsys discover --from-diff <base>..HEAD --json
     modsys discover --files <path> <path> --json
     ```

   - Both, when a task comes with a branch:

     ```bash
     modsys discover --task-file <file> --from-diff <base>..HEAD --json
     ```

   Exit 2: read stderr — an unknown ref, a directory given as a file, a missing registry — fix
   the input and run it again once.

2. Read the result. Per module (best first): `usage` — `modify` (the change touches its files)
   or `reference` (only its keywords matched the task) —, `sources` (why it is listed:
   `keyword`, `diff`, `path`), `touched_files`, `docs_to_read`, `docs_to_update`. Then
   `files_outside_modules` (changed files no module owns) and `missing_files` (listed files
   that are not on disk: a typo, or a deletion).

3. For every `modify` module, list its code.

   ```bash
   modsys code-map files <module> --json
   ```

   `files[]` are the files routed to the module and `via` the rule that routes each one.
   Search only there for the symbols the task names, and note each hit as file:line.

4. For every `reference` module, read its `docs_to_read` — usually just the main doc — and keep
   it only when it really helps the task (an existing component to reuse, a rule to respect).
   Drop the others and say why, so nobody checks them again.

5. Read the `docs_to_read` of the `modify` modules; note the rules the task must respect.

6. Report the touch-set:

   | module | usage | why | docs to read | docs to update | code (file:line) |
   |---|---|---|---|---|---|

   then the files outside every module (each needs a module or a routing rule — suggest
   `module-create`, or a `[[code_map]]` rule the team adds), the missing files, and the
   modules you dropped with the reason.

7. JSON on request: when the user names a path, write the `data` object of the `discover`
   result there as it came (add nothing the engine did not return), and say where it is.

## Gates

No gates — read-only: it reports and stops. It asks only for a missing input (no task text,
no range) or before writing the JSON file when the user has not named its path.

## Exit codes

`0` ok · `2` = a usage or config error: read stderr, fix the input or report the message; do
not retry the same command.
