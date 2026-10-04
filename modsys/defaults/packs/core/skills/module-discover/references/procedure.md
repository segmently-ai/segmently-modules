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

   If a temporary file cannot be written (a read-only sandbox), pass the task through a quoted
   heredoc and read the order from stdout instead of a file:

   ```bash
   modsys choose --task-file - <<'EOF'
   <the task text, verbatim>
   EOF
   ```

2. Verify each candidate by its description and the head of its main doc (a split module: its
   INDEX). Keep those the task is about and, in a split module, the child the task is in
   (`modsys show <module> --json` lists `submodules`; a pick may be one); drop the rest and say
   why.

3. Go to the code: `modsys code-map files <candidate> --json`; its code is the files whose `via`
   holds more than `docs`. A picked child or a docs-only module has no code of its own: search its
   parent's code paths (when it has a parent) for the task's terms and let step 4's `--files` name
   the owner. Search its source files first — tests, fixtures and plans last — for the terms of
   `<file>` and their code forms ("trial days" → `trialDays`):
   `git grep -n -e <term> -- <path> …` (no shell glob); the rest of the repository only when that
   gives nothing. For a wrong value, find where it is computed and set, not only the lines that
   read it. Note each code hit as file:line.

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

   A module step 2 kept is a verified pick: it stays in the report even when step 4's `discover`
   gives its files to another module or to none. Its `usage` in the report is set by the task,
   not by `discover`'s `usage`. It is `modify` when the task changes its behaviour, with the files
   step 3 found for it and a note in its why: "code in `<owner>`" (the module `discover` gives
   them to) or "outside every module". When the task only reads it, it stays a `reference` with
   its why. Drop a kept pick only with a stated reason, listed with the dropped modules; never
   drop one silently. A run that starts at step 4 has no kept picks.

6. Read the `modify` modules' `docs_to_read` for the rules the task must respect; keep a
   `reference` module only when its main doc helps (a component to reuse, a rule), drop the rest
   and say why.

   This keep-or-drop is only for the `reference` modules step 2 did not keep; a kept pick stays
   as step 5 says.

7. Report the touch-set, every `modify` row with its code at file:line:

   | module | usage | why | docs to read | docs to update | code (file:line) |
   |---|---|---|---|---|---|

   then the files outside every module (each needs `module-create` or a `[[code_map]]` rule), the
   missing files and the dropped modules. JSON on request: write the `discover` result's `data` as
   it came to the path the user names.

   The docs-to-update column holds every doc `discover` lists under `docs_to_update` — the role docs
   too, not only `MODULE.md`.

   The code column holds the files the change edits or adds: the line that computes or sets the
   value, the files to edit, the tests to add or change. Files read only as evidence go on one
   line under the table; start that line with "read for evidence:". They never go in the code
   column.

## Exit codes

`0` ok · `2` = a usage or config error: read stderr, fix the input or report it; never retry the
same command.

## Scope

Read-only: modsys read verbs, docs, code search. It writes only temporary files outside the
repository and, at a path the user names, the JSON result; it never edits docs or code and never
commits.

If `modsys` is not found, tell the user how to install it — the `modsys` plugin for Claude Code, `uv tool install git+ssh://git@github.com/<owner>/<repo>.git`, or `pipx install git+ssh://git@github.com/<owner>/<repo>.git` — and stop until it runs.

## Gates

No gates — read-only: it reports and stops. It asks only for a missing input or a JSON file's path.
