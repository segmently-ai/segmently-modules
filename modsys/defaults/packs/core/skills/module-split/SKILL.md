---
name: module-split
description: Splits an oversized module into two to six child modules. Analyses the module's docs section by section, proposes the children with a section-to-child table per doc and what stays in the parent, and stops for confirmation. Then freezes each split doc as a legacy copy, creates the children with modsys create, moves the sections word for word, rewrites the parent as an index, routes the code and validates with modsys lint. Use when lint reports a module doc over its size budget, or the user says "split this module", "too big", "break X into submodules".
---

# module-split

Turn one module whose docs outgrew their budget into a parent index plus two to six children,
without losing a line: every moved section lands verbatim in one child, the originals stay
frozen next to the new docs, and routing keeps working.

## When to use

- Lint reports MS030 (a module doc past the split signal) or MS031 (past the hard stop) for
  the module.
- The user asks to split, decompose or break a module into submodules.
- `module-sync` would have to grow a doc that is already at its budget.

## When not to use

- The module is not large — move detail from the module doc into its role docs instead (a
  `module-sync` job).
- The module is split already (it has `submodules`): add one child with `module-create`
  (`--parent`), or move sections between children by hand.
- A brand-new area is not a split: use `module-create`.

## Scope

Writes: frozen `*.legacy.md` copies of the docs it splits, the new children (docs and registry
entries, through the `create` verb), the parent's module doc and role docs (rewritten as an
index and baselines), and routing rules for the children's code (the `code-map add` verb). A
`*.legacy.md` file is written once, as a byte copy, and never edited afterwards. It never
changes the parent's keywords, never edits code, and never commits.

## Steps

1. Analyse.

   ```bash
   modsys show <module> --all-roles --json
   modsys lint --json
   modsys related <module> --json
   modsys code-map files <module> --json
   ```

   - Stop if the result has `submodules` (already split) or no MS030 / MS031 finding and the
     user gave no other reason: explain and suggest the right skill.
   - Size up each doc in `read[]` as an outline table — heading (level two) · first–last line ·
     length · topic in a few words — under the doc's total length.
   - Draft candidate children by cohesion: headings about one feature, one kind of data or one
     flow belong to the same child. Then hold the draft against the code: where
     `code-map files` puts the module's files under separate paths, the children should follow
     those paths.

2. Propose, then **stop**.

   - Two to six children: a name (lowercase words joined by `-`), a one-line scope, keywords
     taken from the parent's (each child needs at least one), expected line counts.
   - For every doc to split, a table: section · lines · target (a child, or the parent).
   - What stays in the parent: rules that hold for the whole module, shared tables, anything
     other modules link to.

   Wait for the user's confirmation. Apply every correction (merge, rename, re-scope) and show
   the table again before writing anything.

3. Freeze. For each doc you will split, copy it byte for byte to a sibling named
   `<name>.legacy.md` — for example `MODULE.md` → `MODULE.legacy.md`, `roles/qa.md` →
   `roles/qa.legacy.md`.
   If such a file exists already, stop: an earlier split left it, and it is never overwritten.
   From here on the legacy copies are read, never edited.

4. Create the children, one command per child, with the roles whose docs receive sections:

   ```bash
   modsys create <child> --parent <module> --non-interactive --description "<scope>" --keywords "<k1, k2>" --role <role> --json
   ```

   `create` also scaffolds every standard role doc, whether or not it gets a section. A
   scaffolded role doc that receives no section stays as `create` wrote it: do not fill it
   from the parent — the parent's doc for that role is already the child's baseline. List it
   as a follow-up in the report (step 9).

5. Move the sections verbatim — no rewording — into the child docs `create` wrote, replacing
   their template prompts. Fix relative links for the new directory depth. Start each child
   doc with one line saying it is part of the parent and is read together with the parent's
   docs.

6. Rewrite the parent.

   - Its module doc becomes an index: the header, a routing table (child · scope · keywords),
     then only the module-wide content that stayed.
   - Each split role doc becomes the module-wide baseline for that role, naming which children
     now hold the rest.
   - The parent's keywords stay unchanged: never remove one (tasks that match them still land
     on the parent and its routing table).

7. Route the code: for each child whose code has its own paths,

   ```bash
   modsys code-map add <rule id> --glob "<glob>" --module <module>/<child> --exclusive --dry-run
   modsys code-map add <rule id> --glob "<glob>" --module <module>/<child> --exclusive --json
   ```

   `--exclusive` keeps a broader rule of the parent from claiming the same files.

8. Validate.

   ```bash
   modsys lint --json
   modsys lint --changed --base HEAD --json
   modsys show <module> --json
   ```

   (`HEAD` is the state before the split while nothing is committed; after a commit, pass the
   commit the split started from.)

   - No MS030 / MS031 left for the parent; every child under its budgets.
   - `lint --changed` stays clean of MS051: adding the legacy copies is fine, editing or
     deleting one is not.
   - The parent's `keywords` equal what they were before step 3.
   - Every relative link in the new and rewritten docs resolves from its own directory.
   - Line accounting: children plus what the parent kept is close to the legacy total; explain
     any loss over 5 %.

9. Report the children (scope, line counts), the line accounting, the routing rules added and
   the follow-ups (a role doc a child still lacks). Ask the user to review and commit.

## Gates

- After the proposal (step 2): **STOP** until the user confirms the children and the tables.
  Nothing is written before that.
- Before each routing rule (step 7): show the dry run.

## Exit codes

`0` ok · `1` from `lint` = findings (fix what the split caused) · `2` = a refused input or a
config error: read stderr, fix, run again.
