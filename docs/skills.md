# Agent skills

> Start here: [README](../README.md). Packs in general: [writing-a-pack.md](writing-a-pack.md).
> Every config key: [configuration.md](configuration.md).

Segmently Modules ships agent skills in three built-in packs. A skill is a directory with a `SKILL.md`
(the Agent Skills format) that Claude Code reads from `.claude/skills/<skill>/` and Codex from
`.agents/skills/<skill>/`. Each one drives the Segmently Modules CLI — it asks `segmently-modules` for modules, docs
and roles instead of assuming a layout — and none of them edits code or commits: the writers
edit module docs and registry fields, then ask you to review and commit.

| Pack | Adds | Skills |
|---|---|---|
| `core` | — | `module-scout`, `module-discover`, `module-research`, `module-sync`, `module-roles`, `module-create`, `module-split`, `module-lint`, `module-init`, `module-adopt`, `module-assistant` |
| `ui` | the `designer` role (`roles/designer.md`) | `designer` |
| `qa` | the `qa_acceptance` role (`roles/qa_acceptance.md`) | `qa-acceptance`, `qa-acceptance-baseline` |

## Enable them

A built-in pack is active only when the team config lists it. `segmently-modules init` writes
`builtin = ["core"]` into its starter config; a repository set up earlier adds it by hand:

```toml
[packs]
builtin = ["core", "ui", "qa"]   # the engine's packs to enable
agents = ["claude", "codex"]     # where packs sync writes skills
```

Then copy the skills where the agents read them, tell the agents about them, and commit both:

```bash
segmently-modules packs list                                          # core, qa, ui … built-in
segmently-modules packs sync --agent claude --agent codex             # 14 skills × 2 agents: created
segmently-modules agents-md --target CLAUDE.md --target AGENTS.md     # the managed block lists the skills
git add .claude/skills .agents/skills .codex/agents CLAUDE.md AGENTS.md
```

`segmently-modules packs sync --check --agent claude --agent codex` in CI fails when a copy is stale. An
enabled built-in pack is a pack layer below every repository pack (its roles and fields merge
first, so a team pack and the team config override them). Removing an id from `builtin` and
syncing again removes that pack's skills from the agents' directories — unless a copy was edited
locally (a conflict, left in place) or ejected (below).

## From the repository or from a plugin

The built-in skills reach an agent one of two ways — never both, or the agent sees every skill
twice and cannot tell which to trigger:

- **`builtin_delivery = "repo"`** (the default): `segmently-modules packs sync` copies them into
  `.claude/skills/` and `.agents/skills/`, and the team commits the copies.
- **`builtin_delivery = "plugin"`**: the Segmently Modules plugins provide them — `core` in the plugin
  `segmently-modules`, `ui` in `segmently-modules-ui`, `qa` in `segmently-modules-qa` (install the ones whose packs `builtin`
  enables). Set it when the team installs the plugins:

  ```toml
  [packs]
  builtin = ["core"]
  builtin_delivery = "plugin"   # the plugins provide the built-in skills
  ```

  `segmently-modules packs sync` then copies no built-in skill, removes the copies it made earlier (an
  edited copy is a conflict and stays) and prints a `note:` naming the plugins; plain `lint`
  reports each copy still there (MS067, info) with the sync that removes it (`--agent <agent>`
  when `[packs] agents` leaves that directory out). `segmently-modules eject` of a built-in skill is refused
  (ejecting means owning a copy: that needs `"repo"`), and a skill ejected earlier is a `packs
  sync` conflict until the copy is deleted or the delivery goes back to `"repo"`. The built-in
  packs' roles and templates and every repository pack's skills are the same under both;
  the `agents-md` block words the skill list's lead-in by delivery.

- **A table, one value per agent**: `builtin_delivery = { claude = "plugin", codex = "repo" }`:
  Claude Code from the plugin, Codex as copies (Codex enables a plugin only for the user, in
  every repository). An agent the table leaves out takes the value of an agent that reads the
  same directory, else `"repo"`; agents that share `.agents/skills` need the same value. `packs
  sync` copies the built-in skills only for the `"repo"` agents and a repository pack's skills
  for every agent; MS067 looks only where a plugin delivers; `eject` of a built-in skill needs
  `"repo"` for every agent.

The engine cannot see which plugins an agent has installed: installing the plugin in a
repository that keeps `"repo"` delivery gives the agent each built-in skill twice — set
`"plugin"` there, or leave the plugin out. Cursor, Gemini CLI and GitHub Copilot have no Segmently Modules
plugin: they get the built-in skills only with `"repo"` delivery (`packs sync` says so).

`module-discover`, `module-scout` and `module-research` run in the user's conversation, like the
other skills: their steps are in `SKILL.md`, the shared choice of candidates and the output
templates in `references/`. Each also has an agent (`module-discover-agent`, `module-scout-agent`,
`module-research-agent`) for a caller that wants the reads out of its context: the agent only runs
its skill on the handed task and returns the skill's output unchanged — the report, or the
question the skill asks (scout's proposal of candidates). No skill text is copied into an agent.
In Claude Code the task can follow the skill's name,
`/module-discover <task>`, and reaches the skill whole: the three skills have no `arguments:` key
and no placeholder, so Claude Code appends the text as an `ARGUMENTS:` line (in Codex the
request's words carry it).

## Other agents

```bash
segmently-modules packs sync --agent cursor                   # Cursor
segmently-modules packs sync --agent gemini --agent copilot   # Gemini CLI and GitHub Copilot: one write
segmently-modules packs sync --agent cursor --remove          # take the copies out again
```

`segmently-modules packs sync --agent cursor`, `--agent gemini` and `--agent copilot` write the skills into
`.agents/skills/` — the directory Codex reads too, written once however many of these agents
sync. GitHub Copilot also reads `.claude/skills/`: a repository that syncs for `claude` and for
an agent of `.agents/skills` gives Copilot every skill twice (`packs sync` prints a note) — where
Copilot works, keep one of the two directories. `segmently-modules packs sync --agent cursor --remove`
takes the copies out again: every copy `packs sync` made in that directory is removed, an edited
copy stays (a conflict), and nothing else there is touched; it refuses while `[packs] agents`
lists another agent that reads the same directory, and a note says when `[packs] agents` still
lists the agent (the next `packs sync` copies its skills again).

## The core skills

| Skill | Use it when | Scope | Main commands |
|---|---|---|---|
| `module-scout` | a task is still being discussed: a short context brief for the modules it names (by name or doc path) and the modules they hard-link, or — none named — a proposal of candidates it loads only after the user says so | read-only | `catalog`, `choose`, `show`, `related`, `context` |
| `module-discover` | a task is agreed and the plan needs its complete context, or a branch needs review: the modules (verified by four questions, one hop of links, usage modify / consume / reference), what their docs say for every role that bears on the task, the existing code touch points (`file:line — symbol — why`, never the files the work will create), docs to update; JSON on request | read-only | `catalog`, `choose`, `show --all-roles`, `related`, `discover`, `code-map files` |
| `module-research` | one question about a module needs a deep answer with file:line evidence and doc/code gaps | read-only | `catalog`, `choose`, `show --all-roles`, `related`, `code-map files`, `lint` |
| `module-sync` | a work session is done — it changed module code or only revealed module knowledge: takes the session's plan goal, decisions with the rejected alternatives, discoveries, gotchas and rules first and the change second, prints its findings and a proposal per module (interactive on request: `ok / skip / edit`), places each item in the doc its readers look in (a doc another skill owns is flagged, never hand-edited), brings keywords and links in line, runs the sync hooks, checks `ci`, reports its decisions and the budget action items | writes docs and registry fields | `sync-instructions` (`--module` for a session without a code change), `catalog`, `choose`, `registry`, `propose`, `sync`, `ci` |
| `module-roles` | a role is new and the existing modules lack its doc: declares the role when it is undeclared, shows a dry run, writes one doc per module, fills each from that module's code and docs, then `lint` and `next` | writes the role's docs (never over an existing one) | `roles list`, `roles add`, `lint`, `next` |
| `module-create` | a new module or child: asks the status and the artifacts one question at a time, analyses existing code (components, imports, usages, critical rules, dependencies both ways) and proposes the description and keywords from it, shows a dry run, waits for a yes, fills the docs to a minimum (components with real paths, a right and a wrong usage, real imports, no template comment), seeds its links, adds a child's row to the parent's routing table, shows that a typical task matches it first | writes the new module | `create --dry-run`, `create`, `related`, `registry append`, `code-map add`, `lint`, `match` |
| `module-split` | a module doc is over budget (MS030 / MS031) — below that it refuses unless you override: proposes three to six children with a section table per doc, stops for confirmation, freezes the docs, moves sections verbatim, rewrites the parent as an index (legacy file named, routing table with line counts) and baselines; a child gets only the role docs with content; an already-split module: add a child, rebalance, or report sizes | writes the children and the parent index | `show`, `create --parent --no-standard-roles`, `code-map add`, `lint` |
| `module-lint` | the gate fails: explains each finding, fixes the safe ones, leaves decisions to you | writes safe fixes | `ci`, `lint`, `registry` |
| `module-init` | a codebase without modules: maps the code, stops for you to confirm the candidates (gate 3), has one writer per module document it (subagents, or one at a time), reconciles, measures routing, stops again before anything lands (gate 7) | writes through `init`, after your yes | `init status`, `init map`, `init confirm`, `init fanout`, `init next`, `init done`, `init reconcile`, `eval routing --prompt`, `init verify`, `init finish` |
| `module-adopt` | a registry and docs another tool wrote: infers the config, explains each inference, writes it, shows lint by code, then asks what it cannot guess, fixes nothing (hands that to `module-lint`) | writes the config `adopt` infers | `adopt --dry-run`, `adopt`, `lint` |
| `module-assistant` | work on the module system itself — set it up (it picks setup, `module-init` or `module-adopt` from the repository's state and asks the agents, files and packs in one round), how to do something (in plain words, then it does it; the commands — checked against `--help` — only when you ask for them), what needs attention (`next` turned into a short plan: mechanical steps it runs, judgement steps it hands to their skill), or a goal that takes several skills (at most four phases, a check each); short replies in your terms — modules, docs, roles, templates — and an OK that says what will happen before any write | writes what the approved plan names, through the verbs or the skills it hands steps to | `next`, `setup --dry-run`, `templates list`, `packs sync`, `code-map add`, `ci` |

A typical task: `module-scout` while it is discussed, `module-discover` once it is agreed,
the work, then `module-sync`; `module-roles` when a role is new, `module-create`,
`module-split` and `module-lint` when the registry itself needs work; `module-init` or `module-adopt` once, to start; `module-assistant` when you do not know which of them, or what the repository needs now (`segmently-modules next`). The writers never edit a frozen `*.legacy.md` file. `module-sync`
decides on its own and asks only in four cases (an update that fits two children equally, new
work that may be a new module or a child, a change that contradicts a doc claim nobody
confirmed, text whose only home is a frozen file); `module-create` and `module-split` stop for a
yes before they write.

`module-init` stops twice: after `init map`, for you to confirm, merge, split, rename or drop the
candidate modules (gate 3), and after `init verify`, before anything lands in the repository
(gate 7); it asks you about keyword ties, reports duplicate names, keeps its routing task writer
blind to the keywords, and never commits. `module-adopt` never changes the registry or a doc: it
explains what `adopt` inferred, asks only what `adopt` never guesses (a role's `applies_when`, a
field's `deprecated`, a budget) and hands lint fixes to `module-lint`. The whole init flow:
[init.md](init.md).

`module-sync` reads the plan from one command — per touched module the docs to update, the
drift and the `sync_hint` of every field ([configuration.md](configuration.md#fieldsname)):

```bash
BASE=$(git merge-base main HEAD)   # where the branch left main — never main itself
segmently-modules sync-instructions --from-diff "$BASE..HEAD" --json
```

Before it edits, `module-sync` saves the gate (`segmently-modules ci --base "$BASE" --json` to a file
outside the repository) and checks its own result with
`segmently-modules ci --base "$BASE" --baseline <that file> --json`: a finding the saved gate already holds
is `known` and only reported, unless the change itself caused it (a moved or deleted path) — that
one it fixes. MS050 and MS051 are never `known`: they describe the change since the base.

## Choosing modules by meaning

Four skills (`module-scout`, `module-discover`, `module-research`, `module-sync`) share one
module-choice step. The skill runs `segmently-modules catalog --json`, reads `match.mode` and `search` (the
models and the depth), then:

- **By meaning** (`semantic` or `hybrid`): the skill writes the text, verbatim and in any
  language, to a task file. In Claude Code, `segmently-modules choose --task-file <task file> > <order file>`
  writes the work order's text form (one line per card), and the skill gives the order file's path
  to the `segmently-modules:module-chooser` agent with `model: <search.claude_model>`; when that agent is not
  available, to a subagent told "this file is your whole task; answer with its JSON only; change
  nothing". In Codex the same command adds `--json`, its `answer_schema` goes to a schema file,
  and
  `codex exec -m <search.codex_model> -c model_reasoning_effort=<reasoning> --sandbox read-only --output-schema <schema file> - < <order file>`
  answers it (`<reasoning>` is `low`, `medium` or `high` for the depth `quick`, `standard` or
  `deep`; add `--skip-git-repo-check` outside a git repository). Elsewhere (no subagent, no
  `codex exec`, or it fails, as inside a sandbox) the skill answers the order itself, every card read, by its rules. Every path ends
  in `segmently-modules choose --apply - --json`, which prints the picks with the docs to read (`--apply`
  takes the answer itself or the agent's JSON envelope, as `--run` does). How much the chooser
  reads is one of the order's rules, set by the depth (see the `choose/rules.md` template below).
- **By keyword** (`lexical`, `hybrid`): the keyword half — short English queries (the registry's
  keywords are English whole words) in a file, through `discover --task-file` or
  `context --task-file`. In `hybrid` the skill merges both lists; a module found both ways ranks
  first.

Every task text reaches Segmently Modules through a file (`--task-file`), never as a quoted argument: an
apostrophe, a `$name` or a backtick in it arrives as written.

**Hybrid is the default**: the mode is `hybrid` unless you say otherwise ("only lexical", "by
meaning", in any language) or `match.mode` is `semantic`. A `lexical` config — the engine's own
default `[match] mode = "lexical"` too — is only the command line's default and never skips the
search by meaning, which needs no setting (the mode a plain `segmently-modules match` uses and the mode of
the skills are separate: a skill always has your agent). Say "use opus" for the model (the Agent
tool's `model:`, `codex exec -m`) and "search deep" for the depth: the skill adds
`--effort deep` to `segmently-modules choose`, and on the Codex path `<reasoning>` follows it. Set the models
and the depth once in the team or personal config (`[search] claude_model`, `codex_model`,
`effort`; `claude_model` is a Claude Code subagent model alias — `sonnet`, `opus` or `haiku` — as
a subagent takes no full model id; see
[configuration.md](configuration.md#the-agent-command-and-search)).
`[match] mode = "semantic"` makes meaning-only the skills' default. A plain CLI `match`, `context`
or `discover --task` call runs it only with `SEGMENTLY_MODULES_AGENT_ALLOW_REPO_MODE=1` in the user's
environment (without it the run is lexical, with one stderr note; with it and without
`SEGMENTLY_MODULES_AGENT_COMMAND` the call refuses, exit 2). It never stops a skill: the skills' keyword
commands always pass `--match lexical` (`module-create` and `qa-acceptance` too, and the
`agents-md` block), and the by-meaning half goes through `segmently-modules choose`, which needs no agent
command in the environment.
The engine holds no model, key or network code and ships no model: the agent that chooses is the
one you already run, under your own credentials.

**The choosing agent.** The `segmently-modules` plugin ships one read-only Claude Code subagent,
`module-chooser` (`segmently-modules:module-chooser`; tools Read, Grep, Glob), and the skills hand it the
file of a `segmently-modules choose` work order, calling it with `model: <search.claude_model>`. Its own
`model: sonnet` line covers only a call without a model (an @-mention): the Agent tool's `model`
wins, and `inherit` is not used, so the chooser never costs as much as the session model. The agent
is thin; the rules it follows are in the work order. The agent reads the whole work order in its own
context: on a registry of about 170 modules (an 80 KB order) a call costs about 55k tokens with the
plugin's agent and about 47k with `codex exec` (measured 2026-10-03). To change how modules are chosen, use
`segmently-modules templates override choose/rules.md`, not the agent file: every plugin update replaces the
agent file in the plugin cache.

**The skills' agents.** In all, the `segmently-modules` plugin ships four agents: `module-chooser` above,
and `module-discover-agent`, `module-scout-agent` and `module-research-agent`
(`segmently-modules:module-discover-agent`, …; tools Read, Grep, Glob, Bash, Agent, Skill; `model: sonnet`).
The plugin build generates each of the three from the agent table: its front matter preloads its
skill (`skills: [segmently-modules:module-<x>]`), and its body only runs that skill on the handed task and
returns the skill's output unchanged (if the skill's text is not in its context, it loads it with
the Skill tool first) — so a read-heavy skill can run in the agent's own context and hand back
only its report. Codex gets the same three agents from
`segmently-modules packs sync` and `segmently-modules setup`, whenever the agents they sync for include `codex` (under
either delivery: a plugin cannot place them): `.codex/agents/module-discover-agent.toml`,
`module-scout-agent.toml` and `module-research-agent.toml`, each with `name`, `description` and
`developer_instructions` (run the skill, return its output; only when the skill is not available
to it, read `.agents/skills/module-<x>/SKILL.md` and follow it) and no `sandbox_mode`, so the agent runs in the
session's own sandbox. They are managed files, like the skill copies: the first line is a
`# segmently-modules-managed:` marker (pack, skill, version and the SHA-256 of the rest),
`packs sync --check` reports one that is stale, `data.agent_files` lists them in `--json`, and a
skill that no enabled pack declares any more (or `packs sync --remove --agent codex`) takes its
file away. A locally edited file and a file without the marker are conflicts that are never
written over. Nothing is written or removed through a symlinked or non-directory
`.codex/agents`: while the repository wants the agents, all three are conflicts; when it wants
none (`core` disabled, a repository `core` without the wrapped skills, or `--remove`), only an
agent file with the marker behind a symlinked `.codex/agents` is one — it cannot be removed
through the link — and otherwise that directory is left alone, with no agent rows. Nothing else
under `.codex/` is read or changed. A run that names its agents without `codex` never opens
`.codex/`; a bare run under `builtin_delivery = "plugin"` reads `.codex/agents/` only to infer
codex. An ejected skill's agent runs the ejected copy, so editing the copy never changes the
agent file. Claude Code with `builtin_delivery = "repo"` has no agent — only the plugin ships
them — and needs none: the skills run in the conversation. `segmently-modules next` names an agent file that is
not in sync, as it names a stale skill copy.

Also in these skills: `module-discover` goes from the verified modules to their docs
(`show --all-roles`) and code (`code-map files`, then `discover --files … --task-file …` for the
owners and the docs to update) and reads the `children` list of a split parent to pick the child
the change is in; `module-sync` updates that child's doc (which
clears the parent's MS050) and adds a keyword only for a new feature, command or concept that no
keyword or the description covers yet, never a code identifier and never one per task.

## The ui and qa packs

- **`ui`** adds the role `designer` (`standard = false`, `applies_when = "ui"`): `segmently-modules create
  NAME … --tag ui` (or `--role designer`) scaffolds `roles/designer.md` with the sections Surface
  map, UX invariants (numbered, each with its reason), interaction states, layout and
  accessibility, visual patterns, Key flows, tokens and colour schemes, Anti-patterns and an
  optional design checker. The `designer` skill designs and reviews UI work against the designer
  docs of the modules it touches, in three routes: **prototype** (a brief and standalone HTML
  mocks from the team's tokens, a checker self-check, then it waits for approval before any
  code), **rework-audit** (an existing flow's path trace, dead ends, preserve list and mapping
  before a redesign) and **review** (screenshots of the running app — required; without a capture
  tool it asks the user for them — checked in thirteen categories with the flow patterns
  FP-1…FP-11; `DESIGN_REVIEW.md` always written, ending `PASS` or `BLOCKED: N must-fix` — a UI
  task is not done while a Must fix is open). Its artifacts go to `<artifacts>/<feature>/`. The
  team names its design settings once in a `[ui]` table of `.segmently-modules/config.toml` (or
  `config.user.toml`), which the skill reads — the engine does not check it:

  ```toml
  [ui]
  rules = ["docs/design/rules.md"]       # read on every run: design rules, token tables, surface kinds
  tokens = ["src/styles/tokens.css"]     # the token values the mocks use
  capture = "npm run screenshot --"      # how to screenshot the running app (or the browser tool to use)
  sizes = ["1280x800", "375x812"]
  schemes = ["light", "dark"]
  checker = "npm run lint:design"        # a designer doc's "Design checker" replaces it for its module
  artifacts = ".design"                  # the default
  ```
- **`qa`** adds the role `qa_acceptance` (`applies_when = "qa"`): the module's acceptance
  baseline, P0 / P1 / P2 criteria with stable ids `AC-NNN` in Given / When / Then form.
  `qa-acceptance` writes one task's criteria (`PRE-NNN`, `AC-NNN` with Title, Sub-task,
  Technique, Risk and Verification `unit | e2e | manual`) before code, reusing baseline ids, plus
  one runnable scenario per `e2e` criterion in the format the module's `qa` doc names, and shows
  them in the conversation (a file only at a path the user names); `qa-acceptance-baseline`
  creates or refreshes a module's baseline block by block (`REQ-NNN` requirements, criteria
  with REQ, Technique, Risk, Dimension and Verification), continuing the highest id and never
  renumbering; a large baseline splits into an index and per-block files. Both share one method
  (`references/method.md`, `references/techniques.md`): ten test dimensions, risk → depth,
  decomposition rules, criterion quality, a self-check and a Quality Score.

```bash
segmently-modules create reviews --non-interactive --tag ui --tag qa \
  --description "Customer reviews of books: ratings, comments and moderation." \
  --keywords "review, rating, stars, comment, moderation"
segmently-modules templates list   # roles/designer.md  role-template:ui  …/defaults/packs/ui/roles/designer.md
```

## Skills with more than one scenario

A skill that serves more than one request keeps a **Route** at the head of its steps: one line
per scenario, naming the file under `references/` that holds that scenario's steps. The agent
reads only the file of its scenario; the steps every scenario shares stay in `SKILL.md`. In
Claude Code the scenario can follow the skill's name and its module —
`/qa-acceptance-baseline <module> refresh` — since the skill declares
`argument-hint: "[module] [scenario] [block]"` and `arguments: module scenario block`; without
them, and in every other agent, the words of the request pick the line. A failed command's handling and the
exit codes sit behind an "if" line in their own file (`references/exit-codes.md`), read only when
a command fails.

`module-assistant` routes `start`, `how-to`, `next` and `plan` (its `how-to` keeps a catalog
split by topic under `references/how-to/`, read one topic at a time; Claude Code:
`/module-assistant next`, `/module-assistant plan <goal>`). `qa-acceptance-baseline` routes
`create`, `refresh` and `block`: a module without a
baseline, one whose baseline must catch up after a change, and a baseline split into per-block
files (an index plus one file per block; `block` names one, `<category>/<name>`). The other
skills serve one request each and keep their steps inline; the longer ones point into
`references/` by step. `packs sync`, `eject` and the plugins carry `references/` with the
skill, like every other file of it.

## Keeping them current

A built-in pack has no version of its own: its version is the engine's (`segmently-modules --version`).
The managed marker records the version, so after an upgrade of Segmently Modules `segmently-modules packs sync`
reports every copy as `updated` — a skill whose files did not change gets a new marker — and
`packs sync --check` is stale until it has run. That is intended: each agent copy names the
engine it came from. A copy edited in an agent's directory stays a conflict, and an ejected
skill is left alone.

## Owning one skill: eject

```bash
segmently-modules eject module-sync         # copies it to .segmently-modules/overrides/skills/module-sync/
segmently-modules packs sync --agent claude --agent codex
segmently-modules eject module-sync --diff  # later: what the engine changed since
segmently-modules eject module-sync --rebase   # after taking that change by hand: MS063 clears
```

Edit the ejected copy: the agents get it and the engine never overwrites it. When a later
engine changes the skill's files, plain `segmently-modules lint` reports MS063 (`ejected skill
'module-sync' is behind pack 'core' (the pack's files changed since the eject) …`); an engine
upgrade alone, with the skill's files unchanged, does not. Review the change with
`segmently-modules eject module-sync --diff`, take what the team wants into the ejected copy by hand, then
run `segmently-modules eject module-sync --rebase`: it records the engine's current version and file hashes
in the copy's `.segmently-modules-ejected` (never touching the copy's files), so `--diff` says up to date
and MS063 clears. Or delete the copy and run `packs sync` — the agents get the engine's version
again. An ejected copy stays the skill's source even when its pack is disabled. The rules are the same as for any pack skill ([writing-a-pack.md](writing-a-pack.md)).

## Owning a whole pack: copy it

A repository pack with a built-in id replaces that built-in pack — enabled or not — and ranks
like any repository pack. Copy the directory its `packs list` row names:

```bash
segmently-modules packs list --json                  # the built-in row's "dir"
cp -R <that dir> .segmently-modules/packs/ui         # then edit .segmently-modules/packs/ui/
```

The ids `core`, `qa` and `ui` are reserved: `segmently-modules packs new ui` is refused and says how to
enable the built-in pack instead. A team pack that declares a skill with a core skill's name
shadows it (plain `lint` reports MS065 for the built-in one); a hand-written
`.claude/skills/module-scout/` is a `packs sync` conflict and is never overwritten.

## Evals

Whether the skills fire on the requests they are written for is measured with `claude plugin
eval`: `evals/skills/` in the Segmently Modules repository holds a trigger case per skill, an outcome case
per writer (`module-sync`, `module-create`, `module-split`) and a negative case, and
`evals/skills/run.py` runs them against a plugin assembled from the built-in packs — see
`evals/skills/README.md` there. Every run is a billed model call, so that suite is run by hand,
never by the unit suite or CI; before a stable release the outcome cases and a trigger check run
as subagents of a Claude Code session ([releasing.md](releasing.md)).
