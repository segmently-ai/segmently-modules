---
name: module-discover
description: Maps a confirmed task, or a change on a branch, to the modules it touches before planning or review, read-only. Runs discover to list each module as modify or reference with the docs to read and to update, lists the code files of every module to modify, and names the files that belong to no module. Saves its result to a task context file. Use when the user asks which modules or files a task will touch, says "do discovery", after a plan is agreed, or when a pipeline needs the touch-set of a change.
argument-hint: "[task]"
---

# module-discover

Pulls into the conversation the complete context a task needs before it is planned, so that
nothing important is missed in the discussion or the plan: the modules it touches, what their docs
say for every role that bears on the task, and the existing code it touches. It does not look for
a bug's cause — the conversation does that; discover gives it the map.

## When to use

- A task is agreed, or nearly, and the plan needs its whole context.
- A branch or changed files need their modules and docs: follow `references/from-diff.md`.

## When not to use

- The task is still being discussed and a quick load is enough: use `module-scout`.
- One question needs a deep answer with code evidence: use `module-research`.
- The change is done and the docs must catch up: use `module-sync`.

## Scope

Read-only: Segmently Modules read verbs, docs, code search. It writes only temporary files outside the
repository and its saved result (step 9); under `[rules] index = "discover"` it offers
to index docs after the report (step 7). Never a commit. A caller that wants a clean context runs it
through the `module-discover-agent` agent, which returns this report unchanged.

If `segmently-modules` is not found, tell the user how to install it — the `segmently-modules` plugin for Claude Code, `uv tool install git+https://github.com/segmently-ai/segmently-modules.git`, or `pipx install git+https://github.com/segmently-ai/segmently-modules.git` — and stop until it runs.

## Steps

The steps say what to find and what the report must hold; how to search is your call. What
they name is read whole, to the end: a command's text output (never `--json`) through a temp
file, a doc with your file-read tool; only code is read in part. Run independent reads together.

1. **Candidates.** Follow `references/choose.md`.

   Modules the user named are verified like the rest but never dropped, and the list is never
   limited to them.

2. **Verify.** Read each candidate's main doc to the end (`segmently-modules show <module> > <temp file>` names it;
   a split module: its INDEX, then the child the task is in; exit 1 is a pointer stub: read its
   successor). Score how much the task needs the module, 0–10, and keep it at 5 or more; a
   dropped candidate goes on the rejected list with its score or "off-topic by its description".

3. **One hop out.** `segmently-modules related <module> > <temp file>` of a kept module may show another
   module the task needs (follow forward edges only); verify it as in step 2.

4. **Usage.** Each kept module (and child) is `modify` (the task changes its code or contracts),
   `consume` (calls its API as it is) or `reference` (follows its patterns or rules).

5. **Docs for every role.** A `modify` or `consume` module: every doc
   `segmently-modules show <module> --discover > <temp file>` lists, each read to the end; a `reference` module: its main
   doc only. Never `MODULE.legacy.md` or `roles/*.legacy.md`. Take from each doc what bears on the
   task — rules, constraints, contracts, pitfalls — as short extracts with the doc's path and
   role; a doc with nothing for the task gets "read, nothing for this task". Never a retelling.
   `segmently-modules rules <every kept module> > <temp file>`, read to the end, gives their critical
   rules whole: every rule that applies to the task, or may once the change is
   designed, is an extract, chosen by meaning (`references/rules.md`).

6. **Code touch points.** For each `modify` or `consume` module, find the existing code the task
   touches. Its code: `show`'s `code` and `code_globs`, or
   `segmently-modules code-map files <module> --source-only --paths`; look outside it only when it
   has nothing. Read just enough code to name the symbol and what changes. Record
   existing code only, as `<edit | read> — file:line — symbol — why` under the rules of
   `references/report.md`; the files the work will create are the plan's decision and are never
   listed. No code search for a `reference` module.

7. **Owners and docs to update.**

   ```bash
   segmently-modules discover --files <edit files> --task-file <file> --match lexical --modify <modify> --consume <consume> > <temp file>
   ```

   Read the file to the end. `--files` takes the paths as separate arguments (`--files a.ts b/c.ts`); one quoted string is one path. `--modify`
   / `--consume`: step 4's marks; `rules_build`: `references/rules.md`. Per module: its
   `docs_to_update` (role docs too, not only the main doc); a module that owns a touch point but
   is not on your list — verify it (step 2) or name it in the risks; `files_outside_modules` (no
   module owns them: each needs `module-create` or a `[[code_map]]` rule); `missing_files`. A
   module step 2 kept stays in the report even when this gives its files to another module or to
   none — its why says "code in `<owner>`" or "outside every module"; drop a kept module only
   with a stated reason, on the rejected list.

8. **Report** in the conversation, in the shape of `references/report.md` (the search line
   first, every section there, the rejected candidates included, every `Code:` line tagged
   `edit` or `read`). The extracts are in the report, so they reach the
   conversation through an agent too. Once a plan is written from it,
   `module-check` reads the plan against every rule of these modules.

9. **Save the result** under `[discover] save` (step 1's settings), as `references/report.md` says.

## Exit codes

`0` ok · `1` from `show` or `related` = a pointer stub · `2` = a usage or config error: read
stderr, fix the input or report it; never retry the same command.

## Gates

No gates — read-only: it reports and stops. It asks only for a missing input or, after the
report, whether to save (`save = "ask"`) or index docs (step 7); run by the agent, a question is its output.
