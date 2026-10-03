# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `modsys ci --baseline FILE|-` takes the `--json` output of an earlier `ci` run and marks each
  finding of the `lint` and `drift` steps `known` (same code, module, path and message, digits in the
  message ignored; MS050 / MS051 never known): a step fails only on findings that are not known, the
  two summaries gain `known`, `data` gains `baseline`, and the text marks known findings.
- The `modsys` plugin ships the read-only subagent `module-chooser` (`modsys:module-chooser`; tools
  Read, Grep, Glob; `model: sonnet` only for a call without a model): the build copies every tracked
  file of `modsys/defaults/agents/` into the plugin's `agents/`; the manifests are unchanged.
- `[search] card_keywords` (default 10, an integer >= 0) caps the keywords of each card in the
  `modsys choose` work order (also `--run` and semantic / hybrid matching); `catalog` keeps every
  keyword, and `catalog_digest` covers the capped cards.
- `modsys choose --effort quick|standard|deep` overrides `[search] effort` for one run (the
  depth rule, the order's `search.effort`, `--run`'s `{effort}` / `{reasoning}`).
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

### Changed

- A `[match] mode` of `semantic` or `hybrid` from a config file now runs the agent command only with
  `MODSYS_AGENT_ALLOW_REPO_MODE=1` in the user's environment; without it `match`, `context` and
  `discover --task` run lexically (stdout identical to `--match lexical`) and print one stderr
  line `modsys: note: …` after a successful run. `--match`, `choose --run` and `catalog` need no
  opt-in; any value other than `1` / `0` / empty is exit 2 (checked only when a config file sets a
  non-lexical mode and no `--match` is given).
- The skills that find modules (`module-discover`, `module-sync`, `module-scout`,
  `module-research`) search both ways (`hybrid`) unless the user says otherwise or `match.mode`
  is `semantic`: a `lexical` config no longer skips the search by meaning. In Claude Code they
  write the work order's text form to a file and hand its path to `modsys:module-chooser`; in
  Codex they run
  `codex exec … --sandbox read-only --output-schema <schema file> - < <order file>`; elsewhere
  they answer the order themselves. The user's depth goes to `choose --effort`. `module-discover`
  says that `--files` takes the paths as separate arguments.
- `catalog` with a malformed `MODSYS_AGENT_COMMAND` or `MODSYS_AGENT_TIMEOUT` exits 0 with
  `match.semantic` false and one stderr note (`modsys: note: <variable>: <problem> —
  match.semantic is false`) instead of exit 2; the verbs that run the agent still refuse it (exit
  2), and an `[agent]` table in a config file stays exit 2.
- The text work order (`modsys choose --task`) wraps card lines longer than 2,000 characters over
  following lines indented by four spaces (at the last space that fits, else at the limit); the
  task and rule lines, the JSON form, `catalog_digest` and the agent's work order are unchanged.

### Fixed

- With stderr closed at start (`modsys … 2>&-`) no line meant for stderr reaches stdout: the run
  puts the null device on fd 2 itself, so a refusal leaves stdout empty and no file the run opens
  becomes fd 2.
- Template resolution: a candidate that exists but cannot be read (a directory, a FIFO, a dangling
  symlink, no permission on it or a parent) is exit 2 `cannot read <path>: <reason>` instead of
  silently falling through to a lower layer; a missing one still falls through.
- The README's `codex exec` agent-command example gains `--sandbox read-only`.
- A closed stdout reader (`modsys catalog --json | head -1`) ends the output silently: no
  `internal error`, no `Exception ignored` at exit, the verb runs to its end and the exit code is
  its own (also for `--help` and `--version`, and with stderr closed too); any other stdout write
  error is exit 2 with one line `modsys: error: cannot write stdout: …`.
- `packs sync` notes the skill copies git ignores: it probes each copy it wrote (or would write)
  with one `git check-ignore` per skills directory and names only the ignored copies (`git ignores <n> of the <m> skill copies in <dir> (…)`); an allow-list such as
  `!.agents/skills/module-*/` no longer gives a false note, before or after the copies exist.
- The contract says `code-map files --json` `via` is a list of sources.
- `show` gives a child its own description; `related parent/child` names the child and says
  `inherited_from` when the edges are the parent's.
- A repeated `--files` adds up (`sync`, `discover`, `sync-instructions`).
- MS050: a doc update of a child counts for its parent.
- `init` hints `modsys next` on a registry that has modules and git-ignores
  `.modsys/config.user.toml`.
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
- A first Ctrl-C, SIGTERM or SIGHUP at the very start or end of an agent call no longer leaves the
  temp directory or a handler behind (exit 130).
- A task file or stdin that is not UTF-8 is exit 2 `cannot read <path>: <reason>` (`<stdin>` for
  `-`, the same in every locale) in `choose`, `context` and `discover`, instead of an internal
  error; an unreadable task file says so in the same words.
- `choose --apply` reads an answer as `choose --run` does: its bytes decoded as UTF-8 with
  replacement, then one reader strips, parses and unwraps it — a trailing no-break space or an
  invalid byte in a `reason` no longer splits the two; `--apply`'s refusals start with the file
  or `stdin`.
- `match` and `context` with `--match semantic --top 0` print `no module matched (--top 0)`
  instead of the agent's wording (no agent was asked).
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
