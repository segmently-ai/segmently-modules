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
- `modsys catalog`: one card per module and child (name, status, its own description, keywords),
  and the configured match mode — the input an agent reads to choose modules by meaning.
- `modsys choose`: the work order (`modsys.choose/1`) for an agent to pick modules by meaning,
  `--apply FILE|-` to check its answer offline, `--run` to ask the user's own agent command.
- `[match] mode` (`lexical` by default, `semantic`, `hybrid`) and `--match` on `match`,
  `context` and `discover --task`; hybrid fuses both rankings (reciprocal rank fusion) and a row
  names its `sources` and `confidence`. Lexical output does not change.
- The user's own agent command, read only from the environment (`MODSYS_AGENT_COMMAND`,
  `MODSYS_AGENT_TIMEOUT`) — an `[agent]` table in a config file is refused. The engine holds no
  model, no API key and no network code. `[search]` sets the models and the depth the skills use.
- `module-scout`, `module-discover`, `module-research` and `module-sync` choose modules by meaning
  through `modsys choose` (hybrid by default); `module-discover` goes from the candidates to the
  code; `module-sync` picks the child and adds a keyword only for a new public name.
- A split module's child without its own role doc is `inherited` in `roles list`; `next` does not
  ask for it and `roles add --all` does not create it.
- `children` (child, description, doc) on a split parent's `modify` row in `discover` and
  `sync-instructions`.
- Release notes: the engine's `CHANGELOG.md`. A stable release needs notes under
  `[Unreleased]`, its release commit dates them, and the publish repository's changelog entry
  carries them.

### Fixed

- `show` gives a child its own description; `related parent/child` names the child and says
  `inherited_from` when the edges are the parent's.
- A repeated `--files` adds up (`sync`, `discover`, `sync-instructions`).
- MS050: a doc update of a child counts for its parent.
- `init` hints `modsys next` on a registry that has modules and git-ignores
  `.modsys/config.user.toml`; `packs sync` notes a skills directory that git ignores.
- `agents-md`: the skill list is one line per skill (the description's first sentence); under
  `builtin_delivery = "plugin"` the enabled built-in skills get the plugins lead-in and a
  repository pack's skills keep the `packs sync` one.
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
