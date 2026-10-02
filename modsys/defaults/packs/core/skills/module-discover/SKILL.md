---
name: module-discover
description: Maps a confirmed task, or a change on a branch, to the modules it touches before planning or review, read-only. Runs modsys discover to list each module as modify or reference with the docs to read and to update, lists the code files of every module to modify, and names the files that belong to no module. Can save the result as JSON at a path the user gives. Use when the user asks which modules or files a task will touch, says "do discovery", after a plan is agreed, or when a pipeline needs the touch-set of a change.
---

# module-discover

## When to use

- A task is agreed, or a branch or a list of changed files needs its modules, docs and code files.

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

A change without a task (a branch, changed files) starts at step 4.

1. Choose the candidate modules.

   Run `modsys catalog --json`; read `match` and `search`. The text: the task as given. For the
   keyword half write 1–3 short English queries to a temporary `<file>`: the domain terms and code
   identifiers the task implies (the registry's keywords are English and match whole words). The
   mode: the user's words ("only lexical", "only by meaning"), else `match.mode` unless `lexical`,
   else `hybrid`; the user may also set the depth ("search deep") or the model ("use opus").

   - By meaning (`semantic`, `hybrid`):
     `modsys choose --task "<the text, verbatim, any language>" --json` prints a work order. Answer
     it in Claude Code by a subagent (`model: <search.claude_model>`), in Codex by
     `codex exec -m <search.codex_model> -c model_reasoning_effort=<reasoning> --output-schema <schema file> -`
     (the order on stdin, `answer_schema` in the file; `low`, `medium`, `high` for `quick`,
     `standard`, `deep`), else answer it in this session, at the depth its rules set: `quick` the
     cards only, `standard` also the INDEX or the main doc's head of up to 3 candidates, `deep`
     also their docs and code. Pipe the answer to `modsys choose --apply - --json`: `picks` with
     their `read` docs.
   - By keyword (`lexical`, `hybrid`): `modsys discover --task-file <file> --json`.
   - `hybrid`: merge the lists; a module found both ways ranks first. Pass `--match semantic` or
     `--match hybrid` only when `match.semantic` is true: else modsys has no agent to ask.

2. Verify each candidate by its description and the head of its main doc (a split module: its
   INDEX). Keep those the task is about and, in a split module, the child the task is in (a pick
   may be one; `modsys show <module> --json` lists them as `submodules`); drop the rest and say
   why.

3. Go to the code: `modsys code-map files <candidate> --json` lists each kept module's files (a
   child with none: its parent's). Grep the task's identifiers and domain terms inside these files
   first, the rest of the repository only when they give nothing. Note each hit as file:line.

4. Get the touch-set.

   ```bash
   modsys discover --files <found files> --task-file <file> --json
   modsys discover --from-diff <base>..HEAD --task-file <file> --json
   ```

   Changed files go to `--files`, a branch to the second form; without a task, drop `--task-file`.
   `<base>` is where the branch left its target: `git merge-base <target> HEAD` prints it — never
   the target's own name, whose later commits would count as touched.

5. Read the result. Per module, best first: `usage` (`modify`: its files change; `reference`: only
   its keywords matched), `sources`, `touched_files`, `docs_to_read`, `docs_to_update`, on a split
   parent `children` (name the one the change is in); then `files_outside_modules` (no module owns
   them) and `missing_files` (not on disk).

6. Read the `docs_to_read` of the `modify` modules: the rules the task must respect. Keep a
   `reference` module only when its main doc helps (a component to reuse, a rule); drop the others
   and say why.

7. Report the touch-set, every `modify` row with its code at file:line:

   | module | usage | why | docs to read | docs to update | code (file:line) |
   |---|---|---|---|---|---|

   then the files outside every module (each needs `module-create` or a `[[code_map]]` rule), the
   missing files and the dropped modules. JSON on request: write the `discover` result's `data` as
   it came to the path the user names.

## Gates

No gates — read-only: it reports and stops. It asks only for a missing input or the path of a JSON
file.

## Exit codes

`0` ok · `2` = a usage or config error: read stderr, fix the input or report it; never retry the
same command.
