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

## Critical Rules

${indexed}

<!-- This doc's rules index: every rule of this doc a change here must never break, and the rules of
the module's other docs that are not role docs (each role doc indexes its own). One entry per rule,
stating it so the forbidden approach is named, with the numbers it depends on: a `###` heading per
rule ("### Writes to nested fields use dot-notation, never set(..., {merge: true})"), then why, what
to do and what not to do — or one list item per rule with the doc:line of its detail; one form per
section. show, rules, module-discover and module-check read them, so an agent sees them without
reading every doc. Keep the `Indexed:` line first; module-sync refreshes its date. -->

## Usage

<!-- The two or three things a reader must know to use this module correctly. -->
