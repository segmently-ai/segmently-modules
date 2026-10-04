## Steps

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

   If a temporary file cannot be written (a read-only sandbox), pass the task through a quoted
   heredoc and read the order from stdout instead of a file:

   ```bash
   modsys choose --task-file - <<'EOF'
   <the task text, verbatim>
   EOF
   ```

2. For each module, named or chosen: `modsys show <module> --json`.

   - `read[]`: the docs to open, in order; `exists: false` = a missing doc: say so.
   - A split module (`submodules`; its first doc is the parent INDEX): read the index, then only
     the children the topic touches (`modsys show <module>/<child> --json`) — never all of them.
   - A pointer stub (exit 1, `stub`): retired or merged; report the stub, never guess.
   - One audience (testing, design, product): add
     `modsys show <module> --role <role> --json`; the roles are the `roles/<role>.md` rows of
     `modsys templates list --json` — never guess one.

3. Its neighbours: `modsys related <module> --json` (`edges` out of it, `reverse` into it). Read a
   forward edge's main doc only when its relation says this module needs the other (e.g.
   `depends-on`); name the rest with their relation, unread.

4. Read the docs for what the topic needs: purpose, components, rules ("never", "always", "must"),
   pitfalls. No code — that is `module-research`.

5. Report the brief, per module: what it owns (a line or two); the rules bearing on the topic,
   quoted short with their doc; the neighbours read and why, and those only named; missing docs or
   stubs; next: `module-discover` once the task is confirmed, `module-research` for a question that
   needs the code. Readable in a minute: no plan, no file list.

## Exit codes

`0` ok · `1` from `show` or `related` = a pointer stub · `2` = a usage or config error (no
registry: "run modsys init"): read stderr, fix the command or report it; do not retry the same
command.
