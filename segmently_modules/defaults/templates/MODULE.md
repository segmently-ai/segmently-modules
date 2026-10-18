# ${title}

> ${description}

## Purpose

${description}

<!-- What this module does, why it exists, and when a change belongs here. -->

## EXISTING Components - DO NOT CREATE NEW

<!-- For agents: what already exists here, so nobody builds it twice. Put each path in
backticks (`src/<module>/service.py`); lint MS040 checks that it exists. This table does not
wire code to the module: [[code_map]] rules or code_pointer fields in .segmently-modules/config.toml do
(see docs/configuration.md). -->

| Name | Path | Purpose |
|------|------|---------|

## Usage

<!-- The two or three things a reader must know to use this module correctly. -->

## Critical Rules

<!-- This doc's rules index (module-sync's rules-index procedure): one entry per rule of this doc a
change must never break, and per rule of the module's docs that are not role docs (each role doc
indexes its own), stating it so the forbidden approach is named, with the numbers it depends on: a
`###` heading per rule ("### Writes to nested fields use dot-notation, never set(..., {merge: true})")
or one list item per rule with the doc:line of its detail; one form per section. Once every rule of
this doc is listed, the section's first line reads `Indexed: every rule of this doc, YYYY-MM-DD.` —
written only by whoever read the doc to the end. show, rules, module-discover and module-check read
the section, so an agent sees the rules without reading every doc. -->
