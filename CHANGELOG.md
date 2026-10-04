# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Lint **MS068** (warning): a pack skill's `SKILL.md`, or one `references/*.md` file, is longer than
  `[budgets] skill_split_signal` (default 9000 characters); **MS069** (warning): a pack's `SKILL.md`
  files together are longer than `[budgets] pack_split_signal` (default 53600; `references/` and
  ejected copies are not counted). Size is a decomposition signal — route, split, or discuss —
  never a cap. Both keys are integers >= 1 in any layer (else exit 2 naming the key) and apply to
  every pack; plain `lint` only. The engine's budget test fails on a shipped crossing that is not
  recorded in `SPLIT_DECISIONS`; the fixed `SKILL_MAX` / `CORE_MAX` are gone.
- Lint **MS062** (error) also reports a `references/<file>` that a skill's `SKILL.md` or one of its
  `references/*.md` files names and that does not exist or lies outside the skill directory (plain
  `lint` only; `packs sync` and `eject` are unchanged). `argument-hint` and `arguments` in a skill's
  front matter raise nothing.
- The core skill `module-roles` (13 built-in skills, core 10): a new role's doc added to every
  existing module — declare the role when it is undeclared, `roles add ROLE --all --dry-run`, `roles
  add ROLE --all`, fill each doc, `lint`, `next`; it also starts from a `next` item that names
  `roles add`. The scenario moved word for word out of `module-sync`, which keeps everything else;
  its keyword rule now says to add a keyword only when no keyword or the description covers the
  concept yet, and never one per task.
- `modsys ci --baseline FILE|-` takes the `--json` output of an earlier `ci` run and marks each
  finding of the `lint` and `drift` steps `known` (same code, module, path and message, digits in the
  message ignored; MS050 / MS051 never known): a step fails only on findings that are not known, the
  two summaries gain `known`, `data` gains `baseline`, and the text marks known findings.
- The `modsys` plugin ships three more agents, `module-discover-agent`, `module-scout-agent` and
  `module-research-agent` (tools Read, Grep, Glob, Bash, Agent; `model: sonnet`): the build
  generates each from the `references/procedure.md` of `module-discover`, `module-scout` and
  `module-research` (new: today's steps of each skill), named and described by one engine table;
  a procedure that is missing or untracked, or a tracked agent file of the same name, stops the
  build (exit 2). The build ships only the files directly in `modsys/defaults/agents/` besides
  them (a subdirectory never ships).
- `modsys packs sync` and `modsys setup` write the same three agents for Codex as
  `.codex/agents/<name>.toml` (`name`, `description`, `developer_instructions` = the procedure)
  whenever the agents they sync for include `codex`, under either delivery: managed files whose
  first line is a `# modsys-managed:` marker, listed in `data.agent_files` (after `data.skills`;
  `data.summary` still counts the skills), checked by `--check`, removed with their skill or by
  `--remove --agent codex`; a locally edited or foreign file is a conflict, and nothing is
  written or removed through a symlinked or non-directory `.codex/agents` (all three files are
  conflicts while the agents are wanted; when none is, only a file with the marker behind a
  symlink is one). Without `codex` nothing under `.codex/` is read or written.
- `module-discover`, `module-scout` and `module-research` are thin: their `SKILL.md` keeps the
  description, When to use / not, Scope and Gates and one step that hands the task (`$task`) to the
  skill's agent (`module-<x>-agent`; Claude Code `modsys:module-<x>-agent`) and gives its report as
  the skill's; the steps and exit codes live in `references/procedure.md`, which the agent runs
  (without that agent the skill says to read it). Front matter gains `argument-hint: "[task]"` and
  `arguments: task`. Changed in the procedures: `module-discover` step 3 searches code files
  first (tests, fixtures and plans last) with `git grep -n -e <term> -- <path> …` (no shell glob),
  takes the files whose `via` holds more than `docs`, searches a picked child's or a docs-only
  module's parent for the task's terms, and looks for where a wrong value is computed and set, not
  only where it is read; step 7 lists every doc `discover` returns under `docs_to_update`, the
  role docs too. Each procedure holds one line for a read-only sandbox: the task through
  `modsys choose --task-file -` from a quoted heredoc, the order read from stdout.
- The `modsys` plugin ships the read-only subagent `module-chooser` (`modsys:module-chooser`; tools
  Read, Grep, Glob; `model: sonnet` only for a call without a model): the build copies the tracked
  files directly in `modsys/defaults/agents/` into the plugin's `agents/`; the manifests are
  unchanged.
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
  code; `module-sync` picks the child and adds a keyword only for a new feature, command or
  concept, never a code identifier.
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

- `tools/release.py` step 3 runs each `tests/test_*.py` module in its own process, `--jobs N` at
  a time (1–32, default `min(4, CPU count)`), the `test_release*` modules first; the step line is
  `Ran <N> tests in <M> modules (<J> jobs), OK …`, a failure names the failing modules, and
  Ctrl-C, SIGTERM or SIGHUP stop every running test process group before the put-back (SIGINT,
  then SIGKILL after at most 2 s); the guard, the adoption eval, `claude` and the tool's own git
  calls (not the build's) that the interrupt ends are reaped too.
  `--suite-passed TREE` skips the unit suite when TREE is the engine's `HEAD^{tree}` (step 2
  refuses any other tree); the adoption eval always runs. The release tests are split into
  `tests/test_release*.py` modules.
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
- The core skills: `module-sync` adds a keyword only for a new feature, command or concept later
  tasks will name, never a code identifier; `module-discover` searches the candidates' own code
  for the task's terms (`git grep -n -e <term> -- <paths>`, the rest of the repository only when
  that finds nothing) and, for a wrong value, the line that computes it; `module-sync` saves the
  gate (`modsys ci --base <base> --json`, to a file outside the repository) before it edits and
  checks its result with `ci --baseline` against that file — a finding the saved gate holds is
  reported, one the change caused (a moved or deleted path) is fixed (MS050 and MS051 are never known). The `agents-md` block and
  the skill `packs new` scaffolds write the task to a temporary file outside the repository: run
  `modsys agents-md` and `modsys packs sync` after the upgrade — `--check` reports the old block
  and stale copies until then.
- `catalog` with a malformed `MODSYS_AGENT_COMMAND` or `MODSYS_AGENT_TIMEOUT` exits 0 with
  `match.semantic` false and one stderr note (`modsys: note: <variable>: <problem> —
  match.semantic is false`) instead of exit 2; the verbs that run the agent still refuse it (exit
  2), and an `[agent]` table in a config file stays exit 2.
- The text work order (`modsys choose --task`) wraps card lines longer than 2,000 characters over
  following lines indented by four spaces (at the last space that fits, else at the limit); the
  task and rule lines, the JSON form, `catalog_digest` and the agent's work order are unchanged.

### Fixed

- With stderr closed at start (`modsys … 2>&-`) no line meant for stderr reaches stdout: the run
  puts the null device on fd 2 itself, so a refusal leaves stdout empty, no file the run opens
  becomes fd 2 and a child that inherits stderr writes to the null device.
- Template resolution: a candidate that exists but cannot be read (a directory, a FIFO, a dangling
  symlink, no permission on it or a parent) is exit 2 `cannot read <path>: <reason>` instead of
  silently falling through to a lower layer; a missing one still falls through. A template that
  is not UTF-8 is `cannot read <path>: not valid UTF-8` (exit 2) instead of an internal error.
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
