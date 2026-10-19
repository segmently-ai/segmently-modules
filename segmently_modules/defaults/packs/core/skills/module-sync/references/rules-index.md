# The rules index (module-sync)

Every doc of a module — its module doc (`context_files.universal`) and each role doc, a child's
as well as the parent's — may hold its own critical-rules section (`[lint] critical_rules_heading`)
with the rules that doc states. A section whose first line reads `Indexed: every rule of this doc,
YYYY-MM-DD.` is that doc's complete rules index; a section without it is hand-written and counts
all the same. `rules` hands every doc's rules to `module-check` and to `module-discover`'s `Rules:`
block, `show` to every agent that reads the module, each rule tagged with its doc's role. The
index is optional: `[rules] index` (`show --json`'s `rules_setting`) says who writes it — `sync`
(the default): this skill, create, init, roles and split; `discover`: also the engine's writers
(`rules --build`, started by `discover --files`), each handed the procedure below; `off`: nobody.

A doc another skill owns (its role has `rules_index = false`, such as `qa_acceptance`) is never
indexed by hand: never write into it, never list it as missing.

**Build or refresh** — a doc's index is written here and nowhere else. It runs when the user asks
("index module X", "index the modules missing one"), in each of the engine's writers under
`discover`, and in a sync (step 6) for each module the session changed whose `rules_index` lists
docs as `missing`, unless the setting is `off`:

1. Read each doc to index to the end (`segmently-modules show <module> --all-roles --json` lists the
   docs; a split module: the parent and each child). Note its lines against `[budgets]`.
2. List the rules in it that a change to the module, or a use of it, must not break, for every
   role (code and data, tests, UX invariants — sizes, layouts, states —, architecture limits,
   business rules), each passing all three tests: important (breaking it silently breaks money,
   data, security, a UX invariant or another module's contract); not evident from the code it is
   about (not what that code plainly does, not what a type, a test or a linter already enforces);
   in force now (not history, a plan step, a status or something the doc says was replaced).
   Feature descriptions and how-to steps are not rules. The module doc also takes the rules of the
   module's docs in its own folder that are not role docs (other `context_files` docs, a deep-dive
   doc), citing that doc. Past `[budgets] rules_index_entries` entries (25) lint warns (MS071):
   check each entry against the three tests again.
3. Compare with `segmently-modules rules <module> --json` (each rule names its `doc`), and add each
   missing rule to the critical-rules section of the doc that holds it: the module doc's to the
   module doc, a role doc's to that role doc, a child's area to the child's docs, the whole module's
   to the parent's. A rule written only inside another entry's body, which that entry's title does
   not name, is missing too: give it its own entry, citing its line; the body stays. Use the
   section's form — a `###` per rule, or one list item per rule; a new section: list items, at the
   end of the doc. Each entry states the rule so the forbidden approach is named, keeps the numbers
   it depends on (a size, a limit, a count), at most about 200 characters, then the `doc:line` of
   its detail; a rule written in several docs gets an entry in each, citing its own line. The rules
   that cause damage when broken first.
4. Re-read the doc as written and set each entry's `doc:line` to the line its detail is on now
   (`roles/developer.md:16` for a role doc, the module directory as the root).
5. Make the section's first line, before any rule, `Indexed: every rule of this doc, YYYY-MM-DD.`
   with today's date (an existing line gets today's date): only a reader of the whole doc writes or
   re-dates it.
6. Write with your file-edit tool only, never through a shell (`sed -i`, a script, a redirect into
   a doc): a shell write reaches any file and BSD `sed -i -e` leaves a `<doc>-e` backup next to it.
   Never remove a rule, reword an existing one or move its detail while building: the section only
   gains entries. An entry for a rule the module doc indexed for a role doc moves to that role
   doc's section when the role doc is built. A rule another doc contradicts: report both places,
   never pick one silently. A subsection inside the section that describes a feature instead of
   stating a rule buries the rules (a check reads the whole section): report it, so its text moves
   out and an entry stays.
7. Run `segmently-modules lint --json` and report, per doc, the entries added, the contradictions and
   each MS030 / MS031 / MS032 the entries caused (an action item, as in `references/placement.md`).

Each doc is indexed on its own: the docs of a module can be indexed in parallel, one writer per
doc, and a later run indexes only the docs `rules_index.missing` names.

**Keep it current** — in an ordinary sync (unless the setting is `off`), the rules the session
placed, changed, retired or moved: a new rule gets its entry in its doc's section (a doc with no
section gets one only when it is indexed, or when it is a new doc); a changed rule's entry is
reworded with it; a retired rule's entry is removed; a moved rule's entry moves with it; every
entry citing text the session moved gets its new `doc:line`. A sync never adds or re-dates an
`Indexed:` line except by building the doc as above.
