# The rules of a module to modify (step 5)

Every doc of a module — its module doc and each role doc, a child's and its parent's — holds its own
critical-rules section, the doc's rules index; its first line `Indexed: every rule of this doc,
YYYY-MM-DD.` says the index is complete. `segmently-modules show <module> --json` gives
`rules_mode` and `rules_index` (`complete`, `missing`: the docs without the line);
`segmently-modules rules <module> --json` gives every rule of every doc, whole, each with its doc and role.

**The mode.** The user's words for this run win ("only the index", "build the index", "just read
the docs"); otherwise `rules_mode`:

| Mode | A `modify` module whose `rules_index.complete` is true | One whose index is not complete |
|---|---|---|
| `build` (the default) | its `Rules:` block quotes `rules <module> --json` | its missing docs are indexed first (below), then the block quotes `rules <module> --json` |
| `index` | its `Rules:` block quotes `rules <module> --json`; no doc is read again for its rules | the block quotes `rules <module> --json` as it is and names the docs with no index |
| `read` | no `Rules:` block: the docs are read and extracted as step 5 says | the same |

A `consume` or `reference` module gets no `Rules:` block in any mode: its rules reach the report as
step 5's extracts.

**Building, in `build` mode.** For each `modify` module whose `rules_index.missing` is not empty,
start one subagent, all of them together, each handed:
- the module (`<module>` or `<module>/<child>`) and the docs to index (`missing`);
- the procedure: the rules index of the `module-sync` skill (its `rules-index.md` reference),
  "Build or refresh", steps 1–6, for those docs only;
- its limits: it writes only the critical-rules sections of those docs (entries and the `Indexed:`
  line), never another part of a doc, a registry field or code, and never commits; it returns the
  entries it added per doc and the contradictions it found.

Wait for every subagent, then run `segmently-modules show <module> --json` again. A doc still in
`missing` (the subagent failed or found the doc unreadable) is named in the block's last line, and
its rules come from step 5's reading. The index each subagent wrote stays: the next run reads it
without building.

**The block.** Under the module's `Why:` line, `Rules:` and then one line per rule of
`rules <module> --json`, in its order, the rule's first line verbatim: `` - `<doc>:<line>` (<role>) — <rule> ``;
`(all)` for the module doc. Its last line says where the index came from: `index: built this run`,
`index: from <the oldest Indexed date>`, or `index: incomplete — <doc>, …`. Step 5's extracts for
this module still follow on its `Docs:` lines; a rule already in the block is not repeated there.
