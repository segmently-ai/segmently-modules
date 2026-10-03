---
name: module-discover
description: Maps a confirmed task, or a change on a branch, to the modules it touches before planning or review, read-only. Runs modsys discover to list each module as modify or reference with the docs to read and to update, lists the code files of every module to modify, and names the files that belong to no module. Can save the result as JSON at a path the user gives. Use when the user asks which modules or files a task will touch, says "do discovery", after a plan is agreed, or when a pipeline needs the touch-set of a change.
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

A change without a task starts at step 4.

1. Choose the candidate modules.

   Run `modsys catalog --json`; read `match.mode` and `search`. The text: the task as given. For the
   keyword half write 1–3 short English queries to a temporary `<file>` (step 4 uses it too): the
   domain terms and code identifiers the task implies (registry keywords are English and match whole
   words). The mode: `hybrid` unless the user says otherwise ("only lexical", "by meaning", in any
   language) or `match.mode` is `semantic`; a `lexical` config is only the command line's default
   and never skips the search by meaning, which needs no setting; the keyword commands always pass
   `--match lexical`. The user may set the model ("use opus") and the depth ("search deep":
   `choose --effort deep`; `<reasoning>` follows it).

   - By meaning (`semantic`, `hybrid`): write the text, verbatim, to `<task file>`. **Claude Code:**
     `modsys choose --task-file <task file> > <order file>`; give `<order file>`'s path to the
     `modsys:module-chooser` agent with `model: <search.claude_model>` (without that agent: a
     subagent told "this file is your whole task; answer with its JSON only; change nothing"); its
     reply is the answer. **Codex:** the same with `--json`, its `answer_schema` written to
     `<schema file>`, then
     `codex exec -m <search.codex_model> -c model_reasoning_effort=<reasoning> --sandbox read-only --output-schema <schema file> - < <order file>`
     (`low`, `medium`, `high` for `quick`, `standard`, `deep`). **Elsewhere** (no subagent, no
     `codex exec`): answer the order yourself, every card read, by its rules. Pipe the answer to
     `modsys choose --apply - --json`.
   - By keyword (`lexical`, `hybrid`): `modsys discover --task-file <file> --match lexical --json`.
   - `hybrid`: merge the lists; a module found both ways ranks first.

2. Verify each candidate by its description and the head of its main doc (a split module: its
   INDEX). Keep those the task is about and, in a split module, the child the task is in
   (`modsys show <module> --json` lists `submodules`; a pick may be one); drop the rest and say
   why.

3. Go to the code: `modsys code-map files <candidate> --json`; its code is the files whose `via` is
   not `docs` (a child without code: its parent's). Grep the terms of `<file>` inside that code
   first, the rest of the repository only when it gives nothing. Note each code hit as file:line.

4. Get the touch-set.

   ```bash
   modsys discover --files <found files> --task-file <file> --match lexical --json
   modsys discover --from-diff <base>..HEAD --task-file <file> --match lexical --json
   ```

   Changed files go to `--files`, a branch to the second form; without a task, drop `--task-file`.
   `--files` takes the paths as separate arguments (`--files a.ts b/c.ts`); one quoted string is one
   path.
   `<base>` is where the branch left its target: `git merge-base <target> HEAD` prints it — never
   the target itself, whose later commits would count as touched.

5. Read the result. Per module, best first: `usage` (`modify`: its files change; `reference`: only
   its keywords matched), `sources`, `touched_files`, `docs_to_read`, `docs_to_update`, on a split
   parent `children` (name the one the change is in and add its `doc` to the docs to update); then
   `files_outside_modules` (no module owns them) and `missing_files` (not on disk).

6. Read the `modify` modules' `docs_to_read` for the rules the task must respect; keep a
   `reference` module only when its main doc helps (a component to reuse, a rule), drop the rest
   and say why.

7. Report the touch-set, every `modify` row with its code at file:line:

   | module | usage | why | docs to read | docs to update | code (file:line) |
   |---|---|---|---|---|---|

   then the files outside every module (each needs `module-create` or a `[[code_map]]` rule), the
   missing files and the dropped modules. JSON on request: write the `discover` result's `data` as
   it came to the path the user names.

## Gates

No gates — read-only: it reports and stops. It asks only for a missing input or a JSON file's path.

## Exit codes

`0` ok · `2` = a usage or config error: read stderr, fix the input or report it; never retry the
same command.
