# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `[search] chooser` (`always`, the default; `when_unsure`; `never`) sets when module-discover asks the chooser to pick modules by meaning, and `discover --json` says how sure its keyword result is (`lexical_confidence`: `sure` or `unsure` with the reason `no_hits`, `tie` or `low_score` against `[search] sure_min_score`, and the modules at the top score). With `when_unsure` the keyword command runs first and the chooser only on an unsure result; the user's words for a run still win.
- `choose --cards brief` (or `[search] cards = "brief"`): a smaller work order whose cards hold each module's name, description and children, without keywords; `full` stays the default.
- `catalog --settings` prints only the `[match]` and `[search]` settings, every key with its default filled in; module-discover reads them there instead of the whole catalog.
- `code-map files TARGET --source-only` lists the module's source files only — no docs, no tests — and `--paths` prints them one per line, so an agent reads a short list instead of the full JSON; module-discover's code pass uses `code-map files <module> --source-only --paths`.
- `[tests] globs`: the globs of test files that `--source-only` leaves out, added to the built-in ones (`**/tests/**`, `**/*.test.*`, `**/test_*.py` and the like, each at the root too).

### Changed

- module-discover's report tags every `Code:` line `edit` (an existing file the change edits, with what changes there in one clause) or `read` (called or consulted as it is, a consumer, a pattern to follow, an alternative); an existing test is an `edit` line only when it asserts the changed behaviour, else the module gets `Tests: add new — <what to cover>`; `Likely consequence:` lines under the risks name what the work will probably also need without putting a new path in `Code:`; the first line under the title, `Search: …`, says how the candidates were chosen; `discovery-results.json` is `version` `1.1`, each `files[].reason` starting with `edit — ` or `read — `.

## [0.3.0] - 2026-10-14

### Added

- `eval routing` and `init verify` say how precise the routing is, not only whether the module is among the first three: `top1_hit_rate`, `mean_matched` (the modules a task matched on average) and, per module, `top1_hits` and `unused_keywords` (no task matched the keyword and no code file of the module holds it). None of them fails a run.
- `init verify` checks the keywords of every new module: more distinct words than `[create] max_keywords` (40) or a generic word fails it (`keywords` in `verify.json`).
- lint MS023 (info): a keyword is a generic word — the CRUD verbs, `user`, `screen`, `app`, `module`, `test` and the words `create` warned about before, any form, plus `[create] generic_keywords`; never a word of the module's own name.
- `init map` gives a candidate with more lines of code than `[init] split_hint_lines` (10000) a `split` hint listing its subdirectories with their lines (`children`).

### Changed

- The READMEs say what Segmently Modules is for — an AI coding agent is an excellent worker with amnesia and a memory of limited size, and the notes solve both: written for any part of the project, found before a task, updated after it, kept per role — in a section of its own, and carry a one-prompt install for Claude Code and for Codex (paste it into a fresh session; it sets the machine up and stops: the agent picks the plugin up after `/reload-plugins` in Claude Code, or in a new session). The prompt's first request names the way in — adopt an existing registry (`module-adopt`), or `segmently-modules setup` and then `module-init` for code without one, `module-create` for a new repository — and a note says what `setup` adds to `CLAUDE.md` and `AGENTS.md`, so nothing is written there by hand. The by-hand install lines name the reload too. The engine's README, the core plugin's README, the plugin marketplace's README section and the npm README share the text; the core plugin's and the marketplace's descriptions say it in one line. The Codex install lines take the command line from npm first.
- Routing ignores word endings: a keyword and a task word match when one is a form of the other (`save`, `saves`, `saved`, `saving`; `entry`, `entries`), so one form of a word is enough. A module that lists several forms scores the word once, so registries written with every form keep their scores. `[match] normalize = "none"` keeps the exact matching of 0.2.1.
- The init writer's prompt asks for at most `[create] max_keywords` words that point to this module and no other — one form per word, no generic word, nothing another module owns, no word for the developer's own tools — and lists the other modules of the repository. `init done` refuses more than `max_keywords` distinct words and warns about generic keywords.
- `create` no longer asks for the missing plural: it says when a keyword is a form of another one, and warns about generic words in any form and about more than `max_keywords` words (the plural hint stays under `normalize = "none"`).
- `init reconcile` drops a keyword no holder's code holds from every module that holds it (as far as the keyword minimum allows; `dropped` in `reconcile.json`) and treats the forms of one word held by different modules as one collision. On the 76 ties of a real run this drops 68 words and leaves the 8 real disputes. The evidence stays a listed form, whole, in a file's path or text: counting every form and the parts of identifiers made generic verbs look owned by most modules.
- The refusal of a root that still holds `.modsys/` stays, though 0.2.0 said it would go in this release: teams are still moving from modsys, and without it an un-migrated checkout would be read with the engine defaults. It goes once the old repositories are archived.

### Fixed

- A backticked path with a space or a `#` in it (`…/Custom cells/Row.swift`, `…/onboarding-v#1-47.json`) is checked as the path it names when it exists — `init done`, `init verify` and lint MS040 cut it or skipped it before.
- The README's one-prompt install no longer has a line starting with the command's name inside its text block, which broke the docs test on `main`.

## [0.2.1] - 2026-10-14

### Added

- npm: `tools/build_npm.py` builds the package `@segmently/modules` — the command line on macOS and Linux with `npm install -g @segmently/modules` or `npx @segmently/modules`. It carries the engine and the plugin's launcher and runs with the Python 3.9 or newer it finds; Node runs nothing. Publishing is a maintainer's step after a release ([docs/releasing.md](docs/releasing.md#npm)).

### Changed

- Python 3.9 or newer (was 3.11): the `python3` of macOS's Command Line Tools (3.9, the package that brings git) runs the command line and the plugins, so a Mac needs no other Python. On Python 3.9 and 3.10 the TOML reader is tomli 2.3.2, vendored unchanged under `segmently_modules/_vendor/` (MIT) — the reader that became Python's own `tomllib` in 3.11, which 3.11 and newer keep using.
- The plugin launcher (`bin/segmently-modules`) also looks for `python3.10` and `python3.9`, and runs the engine through `python -c` instead of `python -P` (3.11+), to the same effect: the working directory never shadows the plugin's engine.

## [0.2.0] - 2026-10-13

### Added

- The repository is public under the MIT license: `LICENSE`, `CONTRIBUTING.md` (how to run the tests, the skill-text rules, pull requests) and `SECURITY.md` (private reports, the trust model). The README installs over https from the public repositories, pinned to the latest release; a stable release moves the pin.
- The plugins' Claude Code manifests name their homepage, repository and license; the plugin READMEs and the marketplace README carry the real install lines.

### Changed

- Renamed: modsys is now Segmently Modules. Every surface of the old name changes at once:
  - the command `modsys` → `segmently-modules` (also the `argparse` prog and the `segmently-modules: error: …` / `segmently-modules: note: …` prefixes on stderr);
  - the Python distribution → `segmently-modules`, the import package and `python -m` → `segmently_modules`;
  - the config directory `.modsys/` → `.segmently-modules/` (`config.toml`, `packs/`, `overrides/`, `config.user.toml`, `proposals/`, `init/`), and the `init --open-pr` branch → `segmently-modules/init`;
  - the environment variables `MODSYS_*` → `SEGMENTLY_MODULES_*` (same suffixes);
  - the JSON envelope and file schema ids `modsys.<verb>/1` → `segmently-modules.<verb>/1` (also `.managed/1`, `.ejected/1`, `.proposal/1`, `.init-state/1`, `.init-proposal/1`, `.init-preflight/1`); the data shapes are unchanged;
  - the agents' block markers → `<!-- segmently-modules:begin v1 -->` / `<!-- segmently-modules:end -->` under `## Module docs (Segmently Modules)`;
  - the managed-copy markers → `.segmently-modules-managed` / `.segmently-modules-ejected`, and a managed Codex agent's first line → `# segmently-modules-managed: …`;
  - the plugins → `segmently-modules`, `segmently-modules-ui`, `segmently-modules-qa`; the marketplaces → `segmently-modules` (stable) and `segmently-modules-dev`; the skills → `/segmently-modules:<skill>`, the chooser agent → `segmently-modules:module-chooser`;
  - the plugin launcher → `bin/segmently-modules` (`SEGMENTLY_MODULES_PYTHON`).
- The lint codes stay `MS001`…`MS069`, so a `ci --baseline` key and a doc that names a code need nothing.
- A root that holds `.modsys/` and no `.segmently-modules/` is refused (exit 2) with the rename command, so an un-migrated checkout is never read with the engine defaults; an explicit `--config-dir` is accepted. The refusal goes in 0.3.0.
- `[budgets] pack_split_signal` default 60000 → 64000 (the longer name grows every skill text).
- The skill descriptions name the verbs without the product name (`Runs discover …`, `with ci (or lint …)`).

### Upgrading from modsys 0.1.x

0. With modsys 0.1.x still installed: apply or drop pending proposals (`modsys sync --apply-proposals`) and finish or drop an `init` run in progress — their files carry the old schema ids, which 0.2.0 does not read.
1. Install the `segmently-modules` command line and plugins (README → Install), then remove the old ones: `claude plugin uninstall modsys@modsys`, `claude plugin marketplace remove modsys`, `uv tool uninstall modsys`.
2. `git mv .modsys .segmently-modules`; in `.gitignore` rename the `.modsys/` lines.
3. Delete every skill copy that holds a `.modsys-managed` file and every `.codex/agents/*.toml` whose first line starts with `# modsys-managed:`, then run `segmently-modules packs sync`. An ejected skill keeps its copy: rename its `.modsys-ejected` record (under `.segmently-modules/overrides/skills/<skill>/`) to `.segmently-modules-ejected` and set its `schema` to `segmently-modules.ejected/1`.
4. In each instruction file with a managed block, rename `<!-- modsys:begin v1 -->` to `<!-- segmently-modules:begin v1 -->` and `<!-- modsys:end -->` to `<!-- segmently-modules:end -->`, then run `segmently-modules agents-md`.
5. Rename `MODSYS_*` variables (your shell, CI, hooks) to `SEGMENTLY_MODULES_*`; skills are now `/segmently-modules:<skill>`, the chooser agent `segmently-modules:module-chooser`.
6. A pipeline that checks `schema` reads `segmently-modules.<verb>/1`; write a new `ci --baseline` file.

## [0.1.4] - 2026-10-13

### Added

- lint checks the module docs as files. MS005 (error): a registered doc that holds NUL bytes or is not valid UTF-8 — a damaged doc used to pass with only its length checked. MS016 (warning): a doc in a module's `roles/` directory that no registry entry names, with the role its name reads as (`ARCHITECTURE.md` → `architect`) and how to register it. MS017 (info, one per module): unregistered docs directly in a module's directory. MS041 (`[lint] link_severity`, default warning): a link in a registered doc whose target is missing — a root-relative `src/x.ts` counts when it exists from the root, and a wrong `../` depth is named. MS042 (info): an anchor that names no heading of its target doc. MS043 (info, one per module, plain `lint` only): backticked repository paths outside the components table that are missing on disk (read from the root, next to the doc and under the module's code directories; build output and git-ignored directories are never checked). The doc checks read only `*.md` docs inside the root.
- lint MS054 (info): an active module that maps no code file, so drift never fires for it; `[coverage] doc_only` names the modules that own no code on purpose (a name that is no module is MS056). `modsys next` lists the MS054 modules in a `no-code` item.
- `modsys next`: a `role` item names its modules (the first five in the summary, all of them in `modules`); with `--base`, `base` names the commit it resolved to.
- `modsys ci`: `base_commit` names the commit `--base` resolved to (the drift line says `since <REF> at <hash>`), a note says when that commit is not an ancestor of HEAD and names the merge base (or, in a shallow clone, says to fetch the history), and a failed step's line names the severity it fails at (`— fails at warning`).
- `modsys registry OP TARGET context_files.<key>`: one doc key of `context_files` — `registry append catalog context_files.supplementary '"modules/catalog/history.md"'` registers a supplementary doc in one command without rewriting universal and roles; a new path must exist on disk and lie inside the root (proposals check it too); role docs stay with `roles add` / `roles skip`.
- `[[code_map]] shared = true` (`code-map add --shared`): the files a rule routes belong to its module and to the modules other rules route them to, on purpose (a feature module and the service that ships it) — both keep them and MS053 leaves the pair alone.
- The skills route a doc that is too long to the trim first: `module-lint`, `module-split`, `module-sync` and `module-assistant` move dated history, API dumps and checklists into a supplementary doc before they propose a split.
- Two of the new findings are warnings and can fail a gate after the upgrade: MS016 and MS041 (`[lint] link_severity = "info"` keeps the gate green while the links are fixed). The messages of the existing findings are unchanged, so a `ci --baseline` file still matches them.

## [0.1.3] - 2026-10-12

### Added

- `modsys roles skip ROLE TARGET… [--note TEXT]`: a module that needs no doc for a role says so in the registry — `context_files.roles.<role>` = `false`, or `{"skip": TEXT}` with a note on why. `roles list` counts it as `skipped` (`not needed N`), not `missing`; `modsys next` stops asking for its doc; `roles add --all` leaves it alone, while `roles add ROLE TARGET` writes the doc in place of the mark; `show --role` names the role as not needed, with the note. A module with the role's doc on disk is refused. The `module-roles` and `module-assistant` skills offer the mark when a module does not need a role.
- lint MS013 flags a `context_files.roles` value that is neither a doc path, a list of doc paths nor a not-needed mark (such a value used to drop the module silently from `roles list` and `next`).

## [0.1.2] - 2026-10-12

### Added

- `[packs] builtin_delivery` per agent: a table such as `{ claude = "plugin", codex = "repo" }` gives Claude Code the built-in skills from the plugin and Codex as copies, so a repository pack's skills reach both agents through `packs sync` without a second copy of a built-in skill next to the plugin. An agent the table leaves out takes the value of an agent that reads the same directory, else "repo"; agents that share `.agents/skills` need the same value. Under a table, MS067 looks only where a plugin delivers, `eject` of a built-in skill needs "repo" for every agent, and the agents' block names the agents the plugins serve. A string keeps its meaning (every agent); a value of the wrong type now reads "expected a string or a table".

### Fixed

- Five documentation tests read only `[Unreleased]` and failed once a release took their entries (CI red after 0.1.1); they now read every entry since the first release.

## [0.1.1] - 2026-10-12

### Added

- The core skill **`module-assistant`** (14 built-in skills, core 11): the module system's entry point.
  It routes four scenarios from a thin `SKILL.md` into `references/` — `start` (setup, `module-init` or
  `module-adopt`, picked from the repository's state), `how-to` (what to do in plain words, then it does it;
  the commands, from a catalog split by topic and checked against `--help`, only on request), `next`
  (`modsys next` turned into a short plan: mechanical steps it runs, judgement steps it hands to their
  skill) and `plan` (a goal that takes several skills, at most four phases with a check each). Its replies
  are short and in the user's terms — modules, docs, roles, templates, never commands or paths unless
  asked — and it asks for an OK that says what will happen before any write. The agents' block tells agents to run `modsys next` at the start of module work and names the
  assistant. The skills' descriptions budget is 7000 characters (was 6600) and `[budgets]
  pack_split_signal` defaults to 60000 (was 53600), so the core pack with it stays below the signal.
- `modsys create CHILD --parent MODULE --no-standard-roles` scaffolds only the `--role` / `--tag`
  roles' docs for a child: the parent's docs cover its other roles (`roles list` shows it
  `inherited`). Without `--parent` it is refused (exit 2) before any prompt.
- Lint **MS068** (warning): a pack skill's `SKILL.md`, or one `references/*.md` file, is longer than
  `[budgets] skill_split_signal` (default 9000 characters); **MS069** (warning): a pack's `SKILL.md`
  files together are longer than `[budgets] pack_split_signal` (default 60000; `references/` and
  ejected copies are not counted). Size is a decomposition signal — route, split, or discuss —
  never a cap. Both keys are integers >= 1 in any layer (else exit 2 naming the key) and apply to
  every pack; plain `lint` only. The engine's budget test fails on a shipped crossing that is not
  recorded in `SPLIT_DECISIONS`; the fixed `SKILL_MAX` / `CORE_MAX` are gone.
- Lint **MS062** (error) also reports a `references/<file>` that a skill's `SKILL.md` or one of its
  `references/*.md` files names and that does not exist or lies outside the skill directory (a
  link's `#section` or `?query`, a table cell's `|`, an em or en dash and Markdown emphasis around
  the name are not part of it; plain `lint` only; `packs sync` and `eject` are unchanged).
  `argument-hint` and `arguments` in a skill's front matter raise nothing.
- The core skill `module-roles` (13 built-in skills, core 10): a new role's doc added to every
  existing module — declare the role when it is undeclared, `roles add ROLE --all --dry-run`, `roles
  add ROLE --all`, fill each doc, `lint`, `next`; it also starts from a `next` item that names
  `roles add`. The scenario moved word for word out of `module-sync`, which keeps everything else.
- `modsys ci --baseline FILE|-` takes the `--json` output of an earlier `ci` run and marks each
  finding of the `lint` and `drift` steps `known` (same code, module, path and message, digits in the
  message ignored; MS050 / MS051 never known): a step fails only on findings that are not known, the
  two summaries gain `known`, `data` gains `baseline`, and the text marks known findings.
- The `modsys` plugin ships three more agents, `module-discover-agent`, `module-scout-agent` and
  `module-research-agent` (tools Read, Grep, Glob, Bash, Agent, Skill; `model: sonnet`), named and
  described by one engine table: each preloads its skill (`skills: [modsys:module-<x>]`) and only
  runs it on the handed task, returning the skill's output unchanged — the report, or the question
  the skill asks; no skill text is copied into an agent. A table skill the core pack does not
  declare, or a tracked agent file of the same name, stops the build (exit 2). The build ships only the files directly in `modsys/defaults/agents/` besides
  them (a subdirectory never ships).
- `modsys packs sync` and `modsys setup` write the same three agents for Codex as
  `.codex/agents/<name>.toml` (`name`, `description`, `developer_instructions`: run the skill and
  return its output; read `.agents/skills/module-<x>/SKILL.md` only when the skill is not available)
  whenever the agents they sync for include `codex`, under either delivery: managed files whose
  first line is a `# modsys-managed:` marker, listed in `data.agent_files` (after `data.skills`;
  `data.summary` still counts the skills), checked by `--check`, removed with their skill or by
  `--remove --agent codex`; a locally edited or foreign file is a conflict, and nothing is
  written or removed through a symlinked or non-directory `.codex/agents` (all three files are
  conflicts while the agents are wanted; when none is, only a file with the marker behind a
  symlink is one). A run that names its agents without `codex` never opens `.codex/`; a bare run
  under `builtin_delivery = "plugin"` reads `.codex/agents/` only to infer codex. `modsys next`
  names the agent files that are not in sync in its `skills` item (under
  `builtin_delivery = "plugin"` they can be all `packs sync` writes), and `packs sync` notes the
  ones git ignores.
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
  code; `module-sync` picks the child.
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

- `module-discover`, `module-scout` and `module-research` keep their steps in `SKILL.md` and
  follow the job and the output of the originals they were written from; the shared choice of
  candidates moves to each skill's `references/choose.md` (also `module-sync`'s). **module-discover** pulls the complete context a task needs
  before it is planned — candidates verified by four questions (0–10, average ≥ 5, the score in the
  report), one hop of `depends-on` / `implemented-in` / `shares-contract` links, usage `modify`,
  `consume` or `reference`, every role doc of a `modify` / `consume` module (a `reference`
  module: its main doc only, even a long one that links its role docs) with the extracts
  that bear on the task (or "read, nothing for this task"), existing code touch points as
  `file:line — symbol — why` (never the files the work will create), docs to update, risks, the
  rejected candidates; a report template in `references/report.md` and a `discovery-results.json`
  shape on request; a branch without a task in `references/from-diff.md`. The rule that looked for
  where a wrong value is computed and set, and the filter that kept only the files the change
  edits, are gone; a verified module still never drops silently. **module-scout** takes module
  names or doc paths (a path outside the registry is read as it is), proposes candidates and
  loads nothing when no module is named, never adds modules to the named ones, loads the
  `depends-on` / `implemented-in` / `shares-contract` targets one hop out (each one, even one
  that looks off the topic) and only names
  `complements` targets and reverse edges, reads a role doc only when the discussion is about that
  role (one the main doc points to goes in the next reads, unread), and ends with "Suggested
  next reads" (`references/brief.md`). **module-research** reads a
  stub's successor.
- The writing skills follow the job and the output of the originals they were written from again,
  their steps in `SKILL.md` and each step's detail in `references/`. **module-sync** takes the
  session first: the plan goal, decisions with the rejected alternatives, discoveries, patterns,
  gotchas, new dependencies and critical rules, each mapped to a module and written even when the
  change does not show it (`references/session.md`); a session without a code change syncs through
  `sync-instructions --module`. It prints its findings and one proposal per module before it
  applies them (an interactive mode on request: `ok / skip / edit`), places each item by its
  readers — a role doc another skill owns is flagged, never hand-edited; po only on a business
  change, designer only on a UI change; the module doc stays short; "Related Modules" prose agrees
  with `related_modules`; a child's area content gets its own role doc (`roles add`)
  (`references/placement.md`) — and reports the plan goal, every decision it took and question it
  asked, and the budget findings as action items (`references/report.md`). Its description now
  also names a session that only revealed module knowledge. **module-create** asks the status
  (code exists → `active`) and the artifacts, analyses existing code before the dry run and
  proposes the description and keywords from it, asks whether the module renders UI (`--tag ui`),
  fills the docs to a minimum for an active module, seeds `related_modules`, adds a child's row to
  the parent's routing table, and shows that `match` on a typical task ranks the new module first.
  **module-split** refuses a module under the size signals unless the user overrides, proposes
  three to six children (two with a reason) from a level-two and level-three outline, keeps in the
  parent every section a tool or another module reads from it, gives a child only the role docs
  with content, names the legacy file in the index and the baselines, gives the routing table a
  Lines column and checks that it lists every child; an already-split module gets three paths —
  add a child, rebalance, report sizes (`references/already-split.md`).
- The QA skills follow the job and the output of the originals they were written from again. Both
  share one method (`references/method.md`, `references/techniques.md`, the same text in each
  skill): ten test dimensions with an enforcement matrix and a minimum per dimension, risk →
  depth, decomposition rules, criterion quality, coverage first, a self-check and a Quality Score;
  equivalence partitioning, boundary values, decision tables, state transitions, pairwise, use
  case and error guessing. **qa-acceptance** gives each criterion a Title, Sub-task, Technique,
  Risk and Verification `unit | e2e | manual` (`e2e` is back), sorts the criteria into five
  categories with Regression Safety filled from the touched modules' P0 criteria
  (`baseline-ref: <module> AC-NNN`), writes Part A in a fixed shape (`references/output.md`) and a
  Part B of runnable scenarios, one per `e2e` criterion, coverage first (`new`, `covered-by`,
  `updates-existing`) in the format and against the coverage map the module's `qa` doc names; it
  shows them in the conversation and waits for the user's OK — a file only at a path the user
  names (its description says so). **qa-acceptance-baseline** writes the baseline by block: Gate 1
  adds the integration and dependencies table and the dimension check, Gate 2 a `REQ-NNN` table with its sources,
  each criterion carries REQ, Technique, Risk, Dimension and Verification, a final confirmation
  comes before the write, and the doc (the `qa_acceptance` template) has a Summary, a Priority
  Matrix, per-block requirements and P0 / P1 / P2, Architecture Rule Coverage, Regression Risks,
  Specification Issues, a Dimension Coverage Matrix, a Gap Analysis, a Quality Score and Retired;
  a large module's baseline splits into an index and per-block files (`references/block.md`).
- The `ui` pack's skill is **`designer`** (it was `designer-review`; `packs sync` removes the old
  copy) and does the job of the original it was written from again, in three routes:
  **prototype** — the open questions with a recommended answer, `DESIGN_BRIEF.md`, standalone HTML
  mocks from the team's tokens (one, or variants on different axes), a checker self-check and mock
  screenshots, then it waits for the user's approval before any code; **rework-audit** —
  `AS_IS_AUDIT.md` with the as-is path trace against its budget, a dead-end inventory, a preserve
  list, the mapping and a live check of the output; **review** — a tier (checker only, checklist and
  checker, or a two-reviewer critique, which surfaces that show money, verdicts or counts always
  get), screenshots of the running app at every size and colour scheme (without a capture tool it
  asks the user for them; a review without them says "degraded"), thirteen categories with the
  flow patterns FP-1…FP-11, and `DESIGN_REVIEW.md` always written with Must fix, Should fix, Could
  improve, What works well and `PASS` or `BLOCKED: N must-fix`. The team's design settings are a
  `[ui]` table of the team config that the skill reads (`rules`, `tokens`, `capture`, `sizes`,
  `schemes`, `checker`, `artifacts`, default `.design`; the engine does not check it). The
  `designer` role template gains a Surface map, numbered UX invariants with their reason, Key
  flows, Tokens and colour schemes, and Anti-patterns. Its description names the three routes.
- The skill-eval graders of `module-discover`, `module-scout` and `module-research` look for their
  own `modsys` command (the skills run in the conversation; their agents only on request).
- `qa-acceptance-baseline`: a `roles/qa_acceptance.md` on disk that the registry does not list is the
  doc to refresh. Step 1 finds it with `roles add qa_acceptance <module> --dry-run --json` (status
  `registered`); the refresh route registers it with `roles add` after Gate 3 and never writes a new
  doc over it.
- `qa-acceptance-baseline` routes its three scenarios: a Route at the head of its steps sends
  `create` (a module without a baseline) to `references/create.md`, `refresh` (a baseline that
  must catch up after a change) to `references/refresh.md` and `block` (a baseline split into
  per-block files) to `references/block.md`, picked by the words after the skill's name in Claude
  Code (`argument-hint: "[module] [scenario] [block]"`, `arguments: module scenario block`) or else
  by the words of the request; the exit codes and the unknown-role stop moved to `references/exit-codes.md`,
  read when a command exits 1 or 2. Every sentence of the skill is kept. The other built-in skills
  serve one scenario each and are unchanged.
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
  `codex exec … --sandbox read-only --output-schema <schema file> - < <order file>`; elsewhere,
  or when that `codex exec` fails (inside a sandbox), they answer the order themselves. The user's depth goes to `choose --effort`. `module-discover`
  says that `--files` takes the paths as separate arguments.
- The core skills: `module-sync` adds a keyword only for a new feature, command or concept that
  later tasks will name and that no keyword or the description covers yet — never a code
  identifier, never one per task; `module-discover` searches the candidates' own code for the
  task's terms, source files first and tests, fixtures and plans last, with
  `git grep -n -e <term> -- <paths>` (no shell glob; the rest of the repository only when that
  finds nothing), takes a module's code as the files whose `via` holds more than `docs`, searches
  a picked child's or a docs-only module's parent for those terms, and lists every doc `discover` returns under
  `docs_to_update` in its report, the role docs too; `module-sync` saves the gate (`modsys ci --base <base> --json`, to a file outside the repository) before it edits and
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
- The `po` role template describes the product meaning of a module: purpose and scope (what it
  owns, where it ends), job stories (**When** … **I want to** … **so that** …, a stable ID, a status
  from the delivery or QA record or Unknown, the product conditions that change the story), shared
  product conditions, open product questions and references; the writing guidance sits in template
  comments the writer removes. The role's description follows ("Product meaning: the jobs the
  module serves, their conditions and its boundaries"), `module-create` fills the PO doc with job
  stories, and a role template may run to 60 lines (was 40). Existing PO docs are unchanged.

### Fixed

- Lint **MS062**: a `references/` name holding `*`, `?` or `[` is a pattern, not a file, and is no longer
  reported (`references/route-*`, `references/x?.md`, `references/[ab].md`); a `?` after the extension or
  closing the name still ends it, so a real missing file is still reported.
- A bare `packs sync` and `next` under `builtin_delivery = "plugin"` infer codex from a `.codex/agents/`
  that holds a marked agent file (no skill copy needs a marker), so a stale agent file shows in `next`;
  `setup`'s agent choice and `"repo"` delivery are unchanged.
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
- Token-budget tests keep the shipped skills' descriptions within a set total and the `context` /
  `show` output within set lengths; skills, route files and packs stay within their split signals
  unless a decision is recorded.
- `show` (and every read set built from it: `context`, `choose`, `discover`, `sync-instructions`)
  lists a module's extra docs in every shape lint checks: a `context_files` map of strings or
  arrays (`"docs": {"thesis": "…"}`) now reads as `docs.thesis`; strings and arrays read as before.
  `show` also returns `fields` — the target's own values of the declared data fields (core fields
  and code pointers excluded; `{}` when none; text: a `field` line each) — so a hook or a skill reads
  a team's own fields without parsing the registry; and a child's `code` lists its own code pointers
  before its parent's.

## [0.1.0] - 2026-10-01

- The first release: three plugins for Claude Code and Codex — `modsys` (the `core` skills
  and the `modsys` command line), `modsys-ui` (the designer-review skill) and `modsys-qa`
  (the acceptance-criteria skills).
- The `modsys` command line (Python 3.11 or newer, stdlib only): 27 verbs over a
  module registry, per-module interface docs and per-role context files, each with a `--json`
  envelope and exit codes a pipeline can branch on.
- The built-in skill packs `core`, `ui` and `qa`; `modsys packs sync` copies them for Claude
  Code, Codex, Cursor, Gemini CLI and GitHub Copilot.
