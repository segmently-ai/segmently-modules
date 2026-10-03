---
name: module-sync
description: Brings module docs and registry fields in line with finished work. Asks modsys sync-instructions which modules the change touched, which docs to update, which drift checks fail and what each field's sync hint says, then edits the docs, updates keywords and links, runs the team's sync hooks and checks the result with modsys ci. Autonomous, it asks only in four ambiguous cases and never commits. Use at the end of a task that changed module code, when the user says "sync the docs", "update the module docs", or when a CI drift check fails.
---

# module-sync

## When to use

- A task changed module code and is done, the gate reports drift (MS050), or the user asks to
  sync the module docs.

## When not to use

- Nothing changed yet: use `module-scout` or `module-discover`.
- The work needs a new module: use `module-create` first.
- A module doc grew too long (lint MS030 / MS031): use `module-split`.
- Only lint findings need fixing: use `module-lint`.

## Scope

Writes: the docs of the modules the change touched or made untrue, and their registry fields (the
`registry` verb or queued proposals). It never edits a `*.legacy.md` file, never edits code, never
commits, and never touches another module unless the user asks. Temporary files go outside the
repository.

If `modsys` is not found, tell the user how to install it — the `modsys` plugin for Claude Code, `uv tool install git+ssh://git@github.com/<owner>/<repo>.git`, or `pipx install git+ssh://git@github.com/<owner>/<repo>.git` — and stop until it runs.

## Steps

1. Pin the change. `<base>` is where the work branched off: `git merge-base <target> HEAD`,
   `<target>` being the branch it merges into (ask when unclear) — never the target itself (its
   later commits would drag in untouched modules). Committed work is `<base>..HEAD`;
   uncommitted work is the files `git diff --name-only <base>` prints plus the new ones
   `git ls-files --others --exclude-standard` prints, all to `--files` (never a directory).

   Before you edit, save the gate: `modsys ci --base <base> --json > <ci file>` (outside the
   repository; ignore its exit code).

2. Ask modsys what to update.

   ```bash
   modsys sync-instructions --from-diff <base>..HEAD --json
   modsys sync-instructions --files <path> <path> --json
   ```

   Per module row: `docs_to_update`; `children` on a split parent: pick the child the change is in
   and update its doc too (it clears the parent's MS050); `drift` (MS050 = code changed, no doc;
   MS051 = a frozen snapshot was touched — restore it from git, never "fix" it); `fields` with
   their `sync_hint`; `proposals_pending` (changes already queued). Report `files_outside_modules`
   (no module owns them: `module-create` or a routing rule).

3. Find the modules whose docs describe what changed (the code map misses one that only documents
   it).

   Run `modsys catalog --json`; read `match.mode` and `search`. The text: a summary of the change
   with its identifiers, as the code spells them. The mode: `hybrid` unless the user says otherwise
   ("only lexical", "by meaning", in any language) or `match.mode` is `semantic`; a `lexical` config
   is only the command line's default and never skips the search by meaning, which needs no setting;
   the keyword commands always pass `--match lexical`. The user may set the model ("use opus") and
   the depth ("search deep": `choose --effort deep`; `<reasoning>` follows it).

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
     `modsys discover --task-file <the changed identifiers and domain terms, in English, in a file> --match lexical --json`.
   - `hybrid`: merge the lists; a module found both ways ranks first.

   Each candidate whose docs describe the change joins the modules to update, with the
   docs the search listed.

4. Per module to update, read the change (`git diff <base>..HEAD -- <its files>`; uncommitted:
   `git diff <base> -- <its files>` and each new file in full) and its `docs_to_update` (a child's
   list holds the parent's docs too: module-wide rules go in the parent, area-specific ones in the
   child). Put each text where its readers look: what the module is and its
   rules in the module doc, how to change the code in the developer doc, how to test it in the qa
   doc, other roles by their headings. Add what the change introduced (a component, a rule, a
   limit, a pitfall), correct what it made untrue, remove nothing still true. Short, factual,
   linked to code paths, never copied code.

5. Update the registry fields the hints point at.

   ```bash
   modsys registry append <module> keywords '"<new word>"' --json
   modsys related <module> --json
   modsys registry append <module> related_modules '{"module": "<other>", "relation": "<relation>", "description": "<why>"}' --json
   ```

   - `keywords`: most changes add none — add one only for a new feature, command or concept later
     tasks will name, never a code identifier (class, function, file or variable: code search finds
     those). Keywords only grow; a split parent keeps all of them — never remove one from it.
   - `related_modules`: when the change made this module rely on another (or share a contract), add
     the edge after checking `related`; an unknown relation is refused with the allowed ones.
   - A refused write (exit 2) names the rule it broke: fix the value, never force it.

   Where agents must not write the registry, queue the changes and apply them at once:

   ```bash
   modsys propose --module <module> --op append --field keywords --value '"<new word>"' --reason "<why>" --json
   modsys sync --from-diff <base>..HEAD --apply-proposals --json
   ```

6. Run the team's sync hooks (the second form for uncommitted work). Skip this step when step 5 ran
   `sync --apply-proposals` (it ran them).

   ```bash
   modsys sync --from-diff <base>..HEAD --json
   modsys sync --files <path> <path> --json
   ```

   Report every hook message. A failed required hook (exit 1): stop, never work around it.

7. Check: `modsys ci --base <base> --baseline <ci file> --json`. Its steps (`lint`, `drift`,
   `coverage`) should pass or be report-only; a `known` finding predates your edits: report it, but
   fix one the change caused (a moved or deleted path). Fix what your updates caused and rerun.

8. Report per module: the docs changed, the fields and edges, the hook messages, the `ci` result,
   the files no module owns. Ask the user to review and commit.

## A new role

When the team (or a newer modsys) adds a role, the existing modules lack its doc.

If `modsys roles list --json` does not list the role, declare it first: a [roles.ROLE] table with
order, standard = true (every module gets the doc) and a one-line description in the team config,
.modsys/config.toml, or in a pack the team owns — ask the user what the role is for when unclear.
Then continue with step 1.

1. `modsys roles add ROLE --all --dry-run` — show the user the docs it would create or register and
   the registered ones missing on disk.
2. `modsys roles add ROLE --all --json` — writes them, never over an existing doc; `--recreate`
   only for a registered doc whose file is gone.
3. Fill each new doc with what that role needs for that module, from its code and docs — one module
   at a time, never inventing components.
4. `modsys lint --json` — fix what the new docs caused.
5. `modsys next --json` — report what is left.

## Gates

Autonomous by default: it decides and applies. It stops and asks only when:

1. an update fits two children of a split module equally well;
2. new work may be a new top-level module or a child of an existing one;
3. the change contradicts a claim in the docs that nobody confirmed in this session (rewrite the
   claim, or only flag the drift?);
4. the only home for the new text is a `*.legacy.md` file — never edited; ask where it should go
   instead.

## Exit codes

`0` ok · `1` = findings, a failed `ci` step or required hook, a rejected proposal: read the result
and act · `2` = a usage or config error or a refused write: read stderr, fix the input, run again
once.
