Pin the question in one sentence.

1. No module named? Choose the candidates.

   Run `modsys catalog --json`; read `match.mode` and `search`. The text: the user's topic or
   question. The mode: `hybrid` unless the user says otherwise ("only lexical", "by meaning", in any
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
   - By keyword (`lexical`, `hybrid`):
     `modsys context --task-file <the domain terms and code identifiers, in English, in a file> --match lexical --json`:
     its `modules`; none but `near_misses`: list them, ask which is meant.
   - `hybrid`: merge the lists; a module found both ways ranks first.

   Keep the top 3; never widen the list on your own.

2. Load every doc of each module: `modsys show <module> --all-roles --json`. A split module
   (`submodules`): read the parent index, then the children the question touches —
   `modsys show <module>/<child> --all-roles --json` (the parent's role docs are the child's
   baseline). Read the docs fully.

3. Its links, both ways: `modsys related <module> --json`. `edges`: the modules it relies on;
   `reverse`: those pointing at it, which a change would affect. Read a linked module's main doc
   only when the question crosses into it.

4. Its code: `modsys code-map files <module> --json` (`via`: the routing rule; `show` adds `code`
   and `code_globs`). Search it for the names the docs and the question use; read what answers it.
   Nothing routed? Say so and search by the component names its main doc lists.

5. Its lint state: `modsys lint --json`. Keep the findings of the module and its children; findings
   with module `*` only when they name it.

6. Compare. For each doc statement that bears on the question — a component, a rule, a flow, a
   limit — find the code that implements it. Record each disagreement as "the docs say X
   (doc:line), the code does Y (file:line)", the doc statements the code does not show, and code
   behaviour the docs never mention.

7. Write the brief: the answer first, in a few sentences; file:line evidence for every claim; the
   gaps table (doc claim · code reality · file:line · how sure); who is affected (`reverse`) when
   it is about a change; the lint findings that matter; next: `module-sync` after a change,
   `module-lint` for findings.
