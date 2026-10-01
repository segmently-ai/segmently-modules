---
name: module-sync
description: Brings module docs and registry fields in line with finished work. Asks modsys sync-instructions which modules the change touched, which docs to update, which drift checks fail and what each field's sync hint says, then edits the docs, updates keywords and links, runs the team's sync hooks and checks the result with modsys ci. Autonomous, it asks only in four ambiguous cases and never commits. Use at the end of a task that changed module code, when the user says "sync the docs", "update the module docs", or when a CI drift check fails.
---

# module-sync

After a change, make the module docs and the registry tell the truth again: every module the
change touched gets its docs updated, its keywords extended, its links added — then the team's
gate says so.

## When to use

- A task changed code in one or more modules and is done (or nearly).
- The modsys gate (the `ci` verb, or `lint --changed`) reports drift (MS050: code changed, no
  doc).
- The user asks to update, refresh or sync the module docs.

## When not to use

- Nothing changed yet and you need context: use `module-scout` or `module-discover`.
- The work belongs in a module that does not exist yet: use `module-create` first.
- A module doc has grown too long to update sensibly (lint MS030 / MS031): use `module-split`.
- Only lint findings need fixing, not a change: use `module-lint`.

## Scope

Writes: the docs of the modules the change touched (their module doc and role docs) and their
registry fields (through the `registry` verb or queued proposals). It never edits a `*.legacy.md`
file, never edits code, never commits, and never touches a module the change did not reach
unless the user asks.

If `modsys` is not found, tell the user how to install it — the `modsys` plugin for Claude Code, `uv tool install git+ssh://git@github.com/<owner>/<repo>.git`, or `pipx install git+ssh://git@github.com/<owner>/<repo>.git` — and stop until it runs.

## Steps

1. Pin the change. `<base>` is the commit this work branched off: the output of
   `git merge-base <target> HEAD`, where `<target>` is the branch the work will merge into
   (ask the user when it is not obvious). Never pass the target branch itself as the base: its
   own later commits would count as part of this change and drag in modules it never touched.

   - Committed work: the range `<base>..HEAD` (modsys also accepts `<target>...HEAD` — three
     dots — for the same range).
   - Work not committed yet: its files are those `git diff --name-only <base>` prints plus the
     new ones `git ls-files --others --exclude-standard` prints; pass all of them to `--files`.
     (`git status --short` shows a new directory as one entry, and `--files` refuses a
     directory.)

2. Ask modsys what to update.

   ```bash
   modsys sync-instructions --from-diff <base>..HEAD --json
   modsys sync-instructions --files <path> <path> --json
   ```

   Per module row: `docs_to_update`, `drift` (MS050 = code changed but none of its docs; MS051
   = a frozen snapshot was touched — restore it from git, never "fix" it), `fields` (each with
   its `sync_hint`: when that field needs an update) and `proposals_pending` (changes other
   agents already queued). `files_outside_modules` lists changed files no module owns — report
   them; they may need `module-create` or a routing rule.

3. For every module row, read what changed and what the docs say.

   - The change: `git diff <base>..HEAD -- <the files of that module>` for committed work;
     with uncommitted work, `git diff <base> -- <the files of that module>` (the working tree
     against the base), and read each new, untracked file in full.
   - The docs: every path in `docs_to_update`. For a child of a split module the list also
     holds the parent's docs: put module-wide rules in the parent, area-specific ones in the
     child.

4. Update the docs by editing the files. Keep each kind of text where its readers look: what
   the module is and its rules in the module doc; how to change the code in the developer doc;
   how to test it in the qa doc; other roles as their headings say. Add what the change
   introduced (a component, a rule, a limit, a pitfall), correct what it made untrue, and remove
   nothing that is still true. Short, factual, linked to code paths instead of copied code.

5. Update the registry fields the hints point at.

   ```bash
   modsys registry append <module> keywords '"<new word>"' --json
   modsys related <module> --json
   modsys registry append <module> related_modules '{"module": "<other>", "relation": "<relation>", "description": "<why>"}' --json
   ```

   - `keywords` only grow: add the words a task about the module would now use. A split
     parent keeps all its keywords — never remove one from it.
   - `related_modules`: when the change made this module rely on another one (or share a
     contract with it), add the edge — check `related` first so it is not added twice. An
     unknown relation is refused with the list of allowed ones; pick from it.
   - A refused write (exit 2) names the rule it broke: fix the value, never force it.

   In a pipeline where agents must not write the registry directly, queue the same changes
   instead and apply them in one step:

   ```bash
   modsys propose --module <module> --op append --field keywords --value '"<new word>"' --reason "<why>" --json
   modsys sync --from-diff <base>..HEAD --apply-proposals --json
   ```

6. Run the team's sync hooks (they may check other content that depends on the modules).
   Skip this step when step 5 ran `sync --apply-proposals`: that run already ran the hooks.

   ```bash
   modsys sync --from-diff <base>..HEAD --json
   modsys sync --files <path> <path> --json
   ```

   (The second form for work that is not committed.) Report every hook message. A failed
   required hook is exit 1: report it and stop — do not work around it.

7. Check the result.

   ```bash
   modsys ci --base <base> --json
   ```

   All three steps (`lint`, `drift`, `coverage`) should pass or be report-only. Fix what your
   updates caused and run it again; report anything that was already failing before you
   started.

8. Report: per module, the docs changed (one line each), the fields changed, the edges added,
   the hook messages, the `ci` result, and the files no module owns. Ask the user to review
   and commit — never commit yourself.

## A new role

When the team (or a newer modsys) adds a role, the existing modules lack its doc. Add it to all
of them, one step at a time:

1. `modsys roles add ROLE --all --dry-run` — show the plan to the user: which docs would be
   created or registered, and which registered docs are missing on disk.
2. `modsys roles add ROLE --all --json` — writes the docs; one that already exists is never
   overwritten. Add `--recreate` only for a registered doc whose file is gone.
3. Fill each new doc with what that role needs for that module, from the module's code and
   docs — one module at a time, never inventing components.
4. `modsys lint --json` — fix what the new docs caused.
5. `modsys next --json` — report what is left.

## Gates

Autonomous by default: it decides and applies. It stops and asks only when:

1. an update fits two children of a split module equally well;
2. new work may be a new top-level module or a child of an existing one;
3. the change contradicts a claim in the docs that nobody confirmed in this session (ask
   whether to rewrite the claim or only flag the drift);
4. the only home for the new text is a `*.legacy.md` file — those are never edited; ask where
   it should go instead.

## Exit codes

`0` ok · `1` = findings, a failed `ci` step, a failed required hook or a rejected proposal:
read the result and act · `2` = a usage or config error or a refused write: read stderr, fix
the input, run again once.
