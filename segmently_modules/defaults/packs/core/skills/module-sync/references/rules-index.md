# The rules index (module-sync)

Every doc of a module — its module doc (`context_files.universal`) and each role doc, a child's
as well as the parent's — has its own critical-rules section (`[lint] critical_rules_heading`):
that doc's must-know rules index. `rules` hands every doc's section to `module-check` and to
`module-discover`'s `Rules:` block, `show` to every agent that reads the module, each rule tagged
with its doc's role. A rule written only deep in a doc reaches none of them, so its doc's own
section names it.

**Build or refresh** — the user asks for a module's rules index; `module-discover` in `build`
mode asks for the docs `show --json`'s `rules_index.missing` names; `module-check` reported a
module with no rules:

1. Read each doc to index to the end (`segmently-modules show <module> --all-roles --json` lists the
   docs; a split module: the parent and each child, `show <module>/<child> --all-roles --json`).
2. List every rule in it that a change to the module, or a use of it, must not break: constraints,
   invariants, "never / always / must" statements, required patterns and the traps someone already
   fell into — for every role: code and data rules, test rules, UX invariants (sizes, layouts,
   states), architecture limits, business rules. Not feature descriptions, history or how-to steps.
   The module doc also takes the rules of the module's docs that are not role docs (other
   `context_files` docs, a deep-dive doc), citing that doc.
3. Compare with `segmently-modules rules <module> --json` (each rule names its `doc`), and add each
   missing rule to the critical-rules section of the doc that holds it: the module doc's to the
   module doc, a role doc's to that role doc, a child's area to the child's docs, the whole
   module's to the parent's. Use the section's form — a `###` per rule, or one list item per
   rule; a new section: list items, placed after the doc's title and summary. Each entry states
   the rule so the forbidden approach is named, keeps the numbers it depends on (a size, a limit, a
   count), at most about 200 characters, then the `doc:line` of its detail; a rule written in
   several docs gets an entry in each, citing its own line. The rules that cause damage when
   broken first.
4. Make the section's first line, before any rule, `Indexed: every rule of this doc, YYYY-MM-DD.`
   with today's date (an existing line gets today's date): it says this doc's index is complete,
   and `show`'s `rules_index` reads it.
5. Never remove a rule, reword an existing one or move its detail: the section only gains entries.
   A rule another doc contradicts: report both places, never pick one silently. A subsection
   inside the section that describes a feature instead of stating a rule buries the rules (a
   check reads the whole section): report it, so its text moves out and an entry stays.
6. Report per doc the entries added and the contradictions; a doc pushed past its budget is an
   action item (budget watch in `references/placement.md`).

Each doc is indexed on its own: the docs of a module can be indexed in parallel (a subagent per
doc or per module), and a later run indexes only the docs `rules_index.missing` names.

**Keep it current** — in an ordinary sync, a new rule placed in any doc of the module gets its
entry in that doc's section; when the doc's index then covers the whole doc, its `Indexed:` line
gets today's date.
