# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `modsys roles list` shows each module's role docs; `modsys roles add` adds a role doc to
  existing modules and registers it.
- `modsys next`: one ranked list of what the repository needs, each item with the command
  that does it (read-only).
- `modsys setup`: one idempotent command for a repository — the starter config, the skill
  copies and the agents-md block.
- Release notes: the engine's `CHANGELOG.md`. A stable release needs notes under
  `[Unreleased]`, its release commit dates them, and the publish repository's changelog entry
  carries them.

### Fixed

- The tests no longer depend on the engine's version or on where `gh` lives.
- CI runs on pull requests too, with Node 24 actions.
- Token-budget tests keep the shipped skills, their descriptions and the `context` / `show`
  output within set sizes.

## [0.1.0] - 2026-10-01

- The first release: three plugins for Claude Code and Codex — `modsys` (the `core` skills
  and the `modsys` command line), `modsys-ui` (the designer-review skill) and `modsys-qa`
  (the acceptance-criteria skills).
- The `modsys` command line (Python 3.11 or newer, stdlib only): 27 verbs over a
  module registry, per-module interface docs and per-role context files, each with a `--json`
  envelope and exit codes a pipeline can branch on.
- The built-in skill packs `core`, `ui` and `qa`; `modsys packs sync` copies them for Claude
  Code, Codex, Cursor, Gemini CLI and GitHub Copilot.
