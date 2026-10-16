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

<!-- The must-know index: every rule a change here must never break, whichever doc holds its detail.
One entry per rule, stating it so the forbidden approach is named: a `###` heading per rule
("### Writes to nested fields use dot-notation, never set(..., {merge: true})"), then why, what to
do and what not to do — or one list item per rule with the doc:line of its detail; one form per
section. show, rules and module-check read them, so an agent sees them without reading every doc. -->

## Usage

<!-- The two or three things a reader must know to use this module correctly. -->
