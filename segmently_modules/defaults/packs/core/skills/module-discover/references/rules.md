# The rules of a module to modify (step 5)

Every doc of a module — its module doc and each role doc, a child's and its parent's — may hold a
critical-rules section with the rules of that doc; a first line `Indexed: every rule of this doc,
YYYY-MM-DD.` says the section lists them all (the doc's rules index). The index is optional: a
hand-written section counts the same, and a module may have none.
`segmently-modules show <module> --json` gives `rules_setting` (`[rules] index`) and `rules_index`
(`complete`; `missing`: the docs without the line; a doc another skill owns is never missing);
`segmently-modules rules <module> --json` gives every rule of every doc, whole, each with its doc
and role.

**What to do.** This skill never writes a doc. Whatever `rules_setting` says, a `modify` module
whose index is complete: its `Rules:` block quotes `rules <module> --json`, and its docs are not
read again for those rules. One whose index is not complete: read each of its `missing` docs to
the end in step 5 and give every rule they state as an extract; its `Rules:` block quotes what
`rules` gives and its last line names the docs left without an index. Under `sync` (the default),
module-sync indexes them after the change.

Under `discover`, the engine writes the index itself: step 7's `discover --files` gives
`rules_build` — the docs without an index of the modules the files belong to (a parent's too) and
what happened to them:
- `started` or `running`: writers it started index them in the background (one per doc; every
  change checked to stay inside the critical-rules section); this run reads them in full, the
  next one reads the index;
- `complete`: nothing was missing;
- `not_allowed`, `no_writer`, `skipped`: nothing is written; its `note` says why (the user's own
  permission `SEGMENTLY_MODULES_ALLOW_INDEX_WRITER=1` is not set, there is no writer, a pipeline
  run). Give the note in the block's last line.
A branch review (`references/from-diff.md`) never builds. `segmently-modules rules --build <module> --json`
builds on request, the same way, and waits (`--json`: per doc its `status`).

A `consume` or `reference` module has no `Rules:` block: its rules reach the report as step 5's
extracts.

**The block.** Under the module's `Why:` line, `Rules:`, then one line per rule of
`rules <module> --json` in its order, verbatim: `` - `<doc>:<line>` (<role>) — <rule> `` (`(all)` for
the module doc; a rule that is a group heading — "DO", "DON'T", "Common Mistakes" — quotes its
items instead). The parent's rules appear under the first of its children in the report, not again.
The last line says where the rules came from: `index: complete (<the oldest Indexed date>)`,
`index: building in the background — <doc>, …` (`rules_build` `started` or `running`), or
`index: incomplete — <doc>, …` with the reason (a `rules_build` note). A rule already in the block
is not repeated on its `Docs:` lines.
