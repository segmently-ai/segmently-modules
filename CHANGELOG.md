# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- The rules of the `modsys choose` work order are the overridable template `choose/rules.md`
  (`modsys templates list` shows it; `modsys templates override choose/rules.md` copies it):
  a `- ` line is a rule, `$max_picks` and `$depth` are filled in; a template without a rule, or
  one that cannot be read, is exit 2. The default rules gain three: read every card, pick the
  child of a split module, best first.
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
- The agent command's argv items may use `{claude_model}`, `{codex_model}`, `{effort}` and
  `{reasoning}` (`quick` low, `standard` medium, `deep` high), filled in without a shell (`{{` /
  `}}` are literal braces). `--match semantic` without a command is refused (exit 2); `hybrid`
  without one runs lexically with a note; a failing agent (exit, timeout, bad answer) is exit 2.
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
- `modsys choose --task-file FILE|-` reads the task text from a file or stdin, as `context` and
  `discover` do; the four skills that choose modules pass every task text through a file, so an
  apostrophe, a `$name` or a backtick reaches modsys as written.

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
- The `agents-md` block, `module-create`, `qa-acceptance` and a skill `packs new` scaffolds run
  their keyword commands with `--match lexical`, like the four skills that choose modules: a
  committed `[match] mode = "semantic"` no longer makes them exit 2, nor starts the user's agent.
  The block and the scaffolded skill pass the task through `--task-file`.
- `choose --apply` reads an agent's JSON envelope (`structured_output`, `result`, a fenced
  `result`) as `choose --run` does.
- A registry without modules no longer costs an agent call (`--match semantic|hybrid`,
  `choose --run`: a note says so); `catalog` prints `no modules in the registry`; `context` in
  `semantic` mode without a pick says the agent chose no module instead of the keyword hint.
- The agent command reads the work order as compact JSON (stdin and `MODSYS_WORK_ORDER`).
- A repeated Ctrl-C or SIGTERM during an agent call still kills an agent that ignores SIGTERM
  and removes the temp files (exit 130).
- `MODSYS_AGENT_TIMEOUT` is an integer from 1 to 3600 written with at most 4 digits: a longer
  value is refused (exit 2) instead of an internal error; the agent command's errors and
  `choose --help` name `MODSYS_AGENT_COMMAND`, not a config table.
- The docs: a repository cannot choose the agent command, but its `[match] mode` decides whether
  `match`, `context` and `discover --task` run it (set the variable per CI job or shell session
  for repositories you do not trust); `[search] claude_model` is a Claude Code subagent alias.
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
