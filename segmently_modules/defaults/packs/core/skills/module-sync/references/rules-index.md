# The rules index (module-sync)

A module doc's critical-rules section (`[lint] critical_rules_heading`) is the module's must-know
rules index: the `rules` verb hands it to `module-check`, `show` to every agent that reads
the module. A rule written only deep in a role doc, a feature section or a gotcha list reaches
neither, so the index names it too.

**Build or refresh** — the user asks for a module's rules index, or `module-check` reported a
module with no rules:

1. Read every doc of the module to the end: `segmently-modules show <module> --all-roles --json`;
   a split module: the parent and each child (`show <module>/<child> --all-roles --json`).
2. List every rule a change to the module, or a use of it, must not break: constraints,
   invariants, "never / always / must" statements, required patterns and the traps someone already
   fell into — for every role: code and data rules, test rules, UX invariants (sizes, layouts,
   states), architecture limits, business rules. Not feature descriptions, history or how-to steps.
3. Compare with `segmently-modules rules <module> --json`, and add each missing rule to the
   critical-rules section of the module doc (`context_files.universal`; a child's area: the child's
   module doc, the whole module: the parent's) — never to a role doc: a role doc's rule gets its
   entry there, citing the role doc. Use the section's form — a `###` per rule, or one list item
   per rule; a new section: list items. Each
   entry states the rule so the forbidden approach is named, at most about 200 characters, then the
   `doc:line` of its detail; a rule in several docs is one entry with each source. The rules that
   cause damage when broken first.
4. Never remove a rule, reword an existing one or move its detail: the section only gains entries.
   A rule another module's doc contradicts: report both places, never pick one silently. A
   subsection inside the section that describes a feature instead of stating a rule buries the
   rules (a check reads the whole section): report it, so its text moves out and an entry stays.
5. Report per module the entries added and the contradictions; a doc pushed past its budget is an
   action item (budget watch in `references/placement.md`).

**Keep it current** — in an ordinary sync, a new rule placed in any doc of the module also gets
its entry in the index.
