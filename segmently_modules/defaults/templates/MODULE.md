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

<!-- What a change here must never break. One `###` heading per rule, the heading stating the rule
("### Writes to nested fields use dot-notation, never set(..., {merge: true})"), then why, what to
do and what not to do. show and discover list these headings, so an agent sees them without
reading the whole doc. -->

## Usage

<!-- The two or three things a reader must know to use this module correctly. -->
