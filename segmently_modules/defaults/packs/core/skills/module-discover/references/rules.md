# The rules of a module to modify (step 5)

Every doc of a module — its module doc and each role doc, a child's and its parent's — may hold a
critical-rules section with the rules of that doc; a first line `Indexed: every rule of this doc,
YYYY-MM-DD.` says the section lists them all (the doc's rules index). The index is optional: a
hand-written section counts the same, and a module may have none.
`segmently-modules show <module> --json` gives `rules_setting` (`[rules] index`) and `rules_index`
(`complete`; `missing`: the docs without the line; a doc another skill owns is never missing);
`segmently-modules rules <module> --json` gives every rule of every doc, whole, each with its doc
and role.

**What to do, by `rules_setting`** (the user's words for this run win: "build the index", "do not
write docs"):

- `sync` (the default) and `off` — read-only. A `modify` module whose index is complete: its
  `Rules:` block quotes `rules <module> --json`, and its docs are not read again for those rules.
  One whose index is not complete: read each of its `missing` docs to the end in step 5 and give
  every rule they state as an extract; its `Rules:` block quotes what `rules` gives and its last
  line names the docs left without an index. Under `sync`, module-sync indexes them after the
  change.
- `discover` — the same, except that the missing docs are indexed before the report (below). A
  branch review (`references/from-diff.md`), a run inside a pipeline (`SEGMENTLY_MODULES_RUN_ID`
  set, or the caller says the docs must not be edited), or a host where no subagent can write
  files: act as `sync` and say why on the block's last line.

A `consume` or `reference` module has no `Rules:` block: its rules reach the report as step 5's
extracts.

**Indexing, under `discover`.** Take the union of the `missing` docs of every `modify` module — a
parent's docs once, however many of its children are modified — and give each doc to exactly one
subagent that can edit files (Claude Code: a general-purpose subagent; Codex: `codex exec
--sandbox workspace-write`), several at once. Each subagent is handed:
- its docs and their module (`<module>` or `<module>/<child>`);
- the procedure: the rules index of the `module-sync` skill, "Build or refresh", for those docs
  only (load the `module-sync` skill and read its `rules-index.md` reference; on Codex, the copy
  under `.agents/skills/module-sync/`);
- its limits: it writes only the critical-rules section of those docs — the entries and the
  `Indexed:` line — never another part of a doc, a doc another skill owns, a registry field or
  code, and never commits; it returns, per doc, the entries added, the contradictions found and
  any budget finding of `segmently-modules lint --json` for that doc.

Wait for every subagent, then run `segmently-modules show <module> --json` again; a doc still
missing is named on the block's last line and its rules come from step 5's reading.

**The block.** Under the module's `Why:` line, `Rules:`, then one line per rule of
`rules <module> --json` in its order, verbatim: `` - `<doc>:<line>` (<role>) — <rule> `` (`(all)` for
the module doc; a rule that is a group heading — "DO", "DON'T", "Common Mistakes" — quotes its
items instead). The parent's rules appear under the first of its children in the report, not again.
The last line says where the rules came from: `index: complete (<the oldest Indexed date>)`,
`index: built this run — <doc> (+<n> entries), …`, or `index: incomplete — <doc>, …` with the
reason. The contradictions and budget findings the subagents returned go under the module's
`Risks / unknowns`. A rule already in the block is not repeated on its `Docs:` lines.
