# refresh: a module whose baseline must catch up

Step 5 of `qa-acceptance-baseline` — write the doc — when step 1 found a `role:qa_acceptance`
row with `exists: true` and you noted its highest `AC-NNN` (when it found none, there is no
doc to refresh: follow `references/create.md` instead).

1. Ids, when refreshing: an unchanged criterion keeps its id and text; a changed one keeps its
   id and is edited in place; a new one takes the next id after the highest existing
   `AC-NNN` — continue the numbering, never renumber and never reuse an id; a criterion that
   no longer applies moves to the "Retired" section with its id and the reason.

2. It exists: edit it in place, section by section (P0, P1, P2, Retired).
