---
name: designer-review
description: Reviews a change to a user interface against the designer docs of the modules it touches. Finds the modules with modsys discover, reads each designer doc with modsys show, checks the change against every UX invariant, interaction state, layout and accessibility rule and visual pattern, runs the team's design checker only when the designer doc names one, and writes a review with Must-fix, Should-fix and Nit items and a pass or fail line. Use before a UI task is called done, or when the user asks for a design, UI or UX review of a change.
---

# designer-review

Check a UI change against the rules the team wrote down for each module it touches, and say
plainly whether it may ship: every Must-fix blocks, everything else is advice.

## When to use

- A change touches what users see (screens, dialogs, components, layout, styling) and is about
  to be called done.
- The user asks for a design, UI or UX review of a branch or of changed files.

## When not to use

- You need to understand a UI module, not review a change: use `module-scout`.
- You need acceptance criteria before the work starts: use `qa-acceptance`.
- The designer docs themselves are out of date after the change: report it here, then use
  `module-sync`.

## Scope

Writes: one review file, and only at a path the user names (otherwise the review stays in the
conversation). It never edits code, module docs or a `*.legacy.md` file, and never commits.

## Steps

1. Find the modules the change touches.

   ```bash
   modsys discover --from-diff <base>..HEAD --json
   modsys discover --files <path> <path> --json
   ```

   `<base>` is the fork point of the branch under review — `git merge-base <target> HEAD`
   gives it; the target branch's name itself would add every change the target received since
   the fork. For changes not committed yet, hand `--files` the output of
   `git diff --name-only <base>` together with `git ls-files --others --exclude-standard`
   (new files are listed one by one; a directory is refused).

   Keep the `modify` modules; the files each one touched are its `touched_files`.

2. Load each module's designer doc.

   ```bash
   modsys show <module> --role designer --json
   ```

   The `role:designer` row of `read[]` is the doc (for a child, the parent's designer doc is
   its baseline and applies too). `exists: false`, or no such row: the module has no designer
   doc — review against the general rules below only, and say in the review that the module
   needs one. Exit 2 "unknown role 'designer'": the team has not enabled the role; tell the
   user and review against the general rules.

3. Read the designer docs: the UX invariants, the interaction states, the layout and
   accessibility rules, the visual patterns, and the design checker section.

4. Read the change: `git diff <base>..HEAD -- <the touched files>` when it is committed, or
   `git diff <base> -- <the touched files>` when part of it is still in the working tree (a new,
   untracked file has no diff: read it whole). Read the files around it too when a rule depends
   on context (a parent layout, a shared component).

5. Check every rule of every designer doc against the change. For each: kept · broken (with
   file:line) · cannot be told from the code (then say how to check it — which screen, which
   state, which size). Also check these general rules when the docs say nothing: every state a
   user can reach (loading, empty, error, disabled) shows something sensible; nothing is
   reachable by pointer only; labels and messages say what happens; no new component copies
   an existing shared one.

6. Run the team's design checker only when a designer doc names one (its "Design checker"
   section): run exactly that command, report its result, and turn each of its errors into a
   finding. Never install a tool and never guess a checker the docs do not name.

7. Write the review:

   - **Must-fix** — breaks a rule of a designer doc, or leaves users stuck, misled or excluded;
   - **Should-fix** — hurts usability or consistency, but nobody is blocked;
   - **Nit** — polish;
   - for each item: the module, the rule (quoted), file:line, and the fix you suggest;
   - the modules without a designer doc, and the rules you could not verify from the code;
   - the last line: `Result: PASS` when there is no Must-fix, else `Result: FAIL (<n> Must-fix)`.

   Save it where the user asked, or show it. Ask the user to review and commit any file.

## Gates

The verdict is the gate: a UI task is not done while a Must-fix is open. Only the user can
waive a Must-fix, and the waiver is written into the review with its reason.

## Exit codes

`0` ok · `2` from `discover` or `show` = a usage or config error: read stderr — an unknown
role means the `ui` pack is not enabled here (step 2).
