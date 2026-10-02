# Agent skills

> Start here: [README](../README.md). Packs in general: [writing-a-pack.md](writing-a-pack.md).
> Every config key: [configuration.md](configuration.md).

modsys ships agent skills in three built-in packs. A skill is a directory with a `SKILL.md`
(the Agent Skills format) that Claude Code reads from `.claude/skills/<skill>/` and Codex from
`.agents/skills/<skill>/`. Each one drives the modsys CLI — it asks `modsys` for modules, docs
and roles instead of assuming a layout — and none of them edits code or commits: the writers
edit module docs and registry fields, then ask you to review and commit.

| Pack | Adds | Skills |
|---|---|---|
| `core` | — | `module-scout`, `module-discover`, `module-research`, `module-sync`, `module-create`, `module-split`, `module-lint`, `module-init`, `module-adopt` |
| `ui` | the `designer` role (`roles/designer.md`) | `designer-review` |
| `qa` | the `qa_acceptance` role (`roles/qa_acceptance.md`) | `qa-acceptance`, `qa-acceptance-baseline` |

## Enable them

A built-in pack is active only when the team config lists it. `modsys init` writes
`builtin = ["core"]` into its starter config; a repository set up earlier adds it by hand:

```toml
[packs]
builtin = ["core", "ui", "qa"]   # the engine's packs to enable
agents = ["claude", "codex"]     # where packs sync writes skills
```

Then copy the skills where the agents read them, tell the agents about them, and commit both:

```bash
modsys packs list                                          # core, qa, ui … built-in
modsys packs sync --agent claude --agent codex             # 12 skills × 2 agents: created
modsys agents-md --target CLAUDE.md --target AGENTS.md     # the managed block lists the skills
git add .claude/skills .agents/skills CLAUDE.md AGENTS.md
```

`modsys packs sync --check --agent claude --agent codex` in CI fails when a copy is stale. An
enabled built-in pack is a pack layer below every repository pack (its roles and fields merge
first, so a team pack and the team config override them). Removing an id from `builtin` and
syncing again removes that pack's skills from the agents' directories — unless a copy was edited
locally (a conflict, left in place) or ejected (below).

## From the repository or from a plugin

The built-in skills reach an agent one of two ways — never both, or the agent sees every skill
twice and cannot tell which to trigger:

- **`builtin_delivery = "repo"`** (the default): `modsys packs sync` copies them into
  `.claude/skills/` and `.agents/skills/`, and the team commits the copies.
- **`builtin_delivery = "plugin"`**: the modsys plugins provide them — `core` in the plugin
  `modsys`, `ui` in `modsys-ui`, `qa` in `modsys-qa` (install the ones whose packs `builtin`
  enables). Set it when the team installs the plugins:

  ```toml
  [packs]
  builtin = ["core"]
  builtin_delivery = "plugin"   # the plugins provide the built-in skills
  ```

  `modsys packs sync` then copies no built-in skill, removes the copies it made earlier (an
  edited copy is a conflict and stays) and prints a `note:` naming the plugins; plain `lint`
  reports each copy still there (MS067, info) with the sync that removes it (`--agent <agent>`
  when `[packs] agents` leaves that directory out). `modsys eject` of a built-in skill is refused
  (ejecting means owning a copy: that needs `"repo"`), and a skill ejected earlier is a `packs
  sync` conflict until the copy is deleted or the delivery goes back to `"repo"`. The built-in
  packs' roles and templates and every repository pack's skills are the same under both;
  the `agents-md` block words the skill list's lead-in by delivery.

The engine cannot see which plugins an agent has installed: installing the plugin in a
repository that keeps `"repo"` delivery gives the agent each built-in skill twice — set
`"plugin"` there, or leave the plugin out. Cursor, Gemini CLI and GitHub Copilot have no modsys
plugin: they get the built-in skills only with `"repo"` delivery (`packs sync` says so).

## Other agents

```bash
modsys packs sync --agent cursor                   # Cursor
modsys packs sync --agent gemini --agent copilot   # Gemini CLI and GitHub Copilot: one write
modsys packs sync --agent cursor --remove          # take the copies out again
```

`modsys packs sync --agent cursor`, `--agent gemini` and `--agent copilot` write the skills into
`.agents/skills/` — the directory Codex reads too, written once however many of these agents
sync. GitHub Copilot also reads `.claude/skills/`: a repository that syncs for `claude` and for
an agent of `.agents/skills` gives Copilot every skill twice (`packs sync` prints a note) — where
Copilot works, keep one of the two directories. `modsys packs sync --agent cursor --remove`
takes the copies out again: every copy `packs sync` made in that directory is removed, an edited
copy stays (a conflict), and nothing else there is touched; it refuses while `[packs] agents`
lists another agent that reads the same directory, and a note says when `[packs] agents` still
lists the agent (the next `packs sync` copies its skills again).

## The core skills

| Skill | Use it when | Scope | Main commands |
|---|---|---|---|
| `module-scout` | a task is still being discussed: a short context brief for the modules it names, or the candidates found by meaning | read-only | `catalog`, `choose`, `show`, `related`, `context` |
| `module-discover` | a task is confirmed, or a branch needs review: its modules, docs to read and update, code files | read-only | `catalog`, `choose`, `discover`, `code-map files` |
| `module-research` | one question about a module needs a deep answer with file:line evidence and doc/code gaps | read-only | `catalog`, `choose`, `show --all-roles`, `related`, `code-map files`, `lint` |
| `module-sync` | work is done: bring the touched modules' docs, keywords and links in line, run the sync hooks, check `ci` | writes docs and registry fields | `sync-instructions`, `catalog`, `choose`, `registry`, `propose`, `sync`, `ci` |
| `module-create` | a new module or child: gathers the answers, shows a dry run, waits for a yes, fills the docs | writes the new module | `create --dry-run`, `create`, `code-map add`, `lint` |
| `module-split` | a module doc is over budget (MS030 / MS031): proposes children, stops for confirmation, moves sections verbatim | writes the children and the parent index | `show`, `create --parent`, `code-map add`, `lint` |
| `module-lint` | the gate fails: explains each finding, fixes the safe ones, leaves decisions to you | writes safe fixes | `ci`, `lint`, `registry` |
| `module-init` | a codebase without modules: maps the code, stops for you to confirm the candidates (gate 3), has one writer per module document it (subagents, or one at a time), reconciles, measures routing, stops again before anything lands (gate 7) | writes through `init`, after your yes | `init status`, `init map`, `init confirm`, `init fanout`, `init next`, `init done`, `init reconcile`, `eval routing --prompt`, `init verify`, `init finish` |
| `module-adopt` | a registry and docs another tool wrote: infers the config, explains each inference, writes it, shows lint by code, then asks what it cannot guess, fixes nothing (hands that to `module-lint`) | writes the config `adopt` infers | `adopt --dry-run`, `adopt`, `lint` |

A typical task: `module-scout` while it is discussed, `module-discover` once it is agreed,
the work, then `module-sync`; `module-create`, `module-split` and `module-lint` when the
registry itself needs work; `module-init` or `module-adopt` once, to start. The writers never edit a frozen `*.legacy.md` file. `module-sync`
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
modsys sync-instructions --from-diff "$BASE..HEAD" --json
```

## Choosing modules by meaning

Four skills (`module-scout`, `module-discover`, `module-research`, `module-sync`) share one
module-choice step. The skill runs `modsys catalog --json`, reads `match` (the configured mode and
whether an agent command exists) and `search` (the models and the depth), then:

- **By meaning** (`semantic` or `hybrid`): `modsys choose --task "<the text, verbatim, in any
  language>" --json` prints the work order; the skill hands it to YOUR agent — in Claude Code a
  subagent on `search.claude_model`, in Codex `codex exec -m <search.codex_model>` with the
  reasoning level of the depth (`quick` low, `standard` medium, `deep` high) — or answers it in
  its own session; the answer goes to `modsys choose --apply - --json`, which prints the picks with
  the docs to read. The depth sets how much the agent reads: `quick` the cards only, `standard`
  also the INDEX of up to 3 candidates, `deep` also the candidates' docs and code.
- **By keyword** (`lexical`, `hybrid`): the keyword half — short English queries (the registry's
  keywords are English whole words) through `discover` or `context`. In `hybrid` the skill merges
  both lists; a module found both ways ranks first.

**Hybrid is the default**: the mode is what you say ("only lexical", "only by meaning"), else
`match.mode` when it is `semantic` or `hybrid`, else `hybrid` — the engine's own default
`[match] mode = "lexical"` does not switch the skills to keywords only (the mode a plain
`modsys match` uses and the mode of the skills are separate: a skill always has your agent). Say
"search deep" for the depth, "use opus" for the model. Set the models and the depth once in the
team or personal config (`[search] claude_model`, `codex_model`, `effort`; `[match] mode =
"semantic"` makes meaning-only the default; see
[configuration.md](configuration.md#the-agent-command-and-search)). The skills never pass
`--match`; they call `modsys choose` themselves, so they need no agent command in the
environment (`match.semantic` only says whether `--match semantic` / `hybrid` would work for a
plain `modsys` call). The engine holds no model, key or network code and ships no model: the
agent that chooses is the one you already run, under your own credentials.

Also in these skills: `module-discover` goes from the candidates to the code
(`code-map files`, then `discover --files … --task-file …`) and reads the `children` list of a
split parent to pick the child the change is in; `module-sync` updates that child's doc (which
clears the parent's MS050) and adds a keyword only for a new public name a future task would
search by.

## The ui and qa packs

- **`ui`** adds the role `designer` (`standard = false`, `applies_when = "ui"`): `modsys create
  NAME … --tag ui` (or `--role designer`) scaffolds `roles/designer.md` with the sections UX
  invariants, interaction states, layout and accessibility, visual patterns and an optional
  design checker. `designer-review` checks a UI change against the designer docs of the modules
  it touches and ends with `Result: PASS` or `Result: FAIL` — a UI task is not done while a
  Must-fix is open. It runs a design checker only when a designer doc names one.
- **`qa`** adds the role `qa_acceptance` (`applies_when = "qa"`): the module's acceptance
  baseline, P0 / P1 / P2 criteria with stable ids `AC-NNN` in Given / When / Then form.
  `qa-acceptance` writes one task's criteria (`PRE-NNN`, `AC-NNN`) before code, reusing
  baseline ids; `qa-acceptance-baseline` creates or refreshes a module's baseline, continuing
  the highest id and never renumbering.

```bash
modsys create reviews --non-interactive --tag ui --tag qa \
  --description "Customer reviews of books: ratings, comments and moderation." \
  --keywords "review, rating, stars, comment, moderation"
modsys templates list   # roles/designer.md  role-template:ui  …/defaults/packs/ui/roles/designer.md
```

## Keeping them current

A built-in pack has no version of its own: its version is the engine's (`modsys --version`).
The managed marker records the version, so after an upgrade of modsys `modsys packs sync`
reports every copy as `updated` — a skill whose files did not change gets a new marker — and
`packs sync --check` is stale until it has run. That is intended: each agent copy names the
engine it came from. A copy edited in an agent's directory stays a conflict, and an ejected
skill is left alone.

## Owning one skill: eject

```bash
modsys eject module-sync         # copies it to .modsys/overrides/skills/module-sync/
modsys packs sync --agent claude --agent codex
modsys eject module-sync --diff  # later: what the engine changed since
modsys eject module-sync --rebase   # after taking that change by hand: MS063 clears
```

Edit the ejected copy: the agents get it and the engine never overwrites it. When a later
engine changes the skill's files, plain `modsys lint` reports MS063 (`ejected skill
'module-sync' is behind pack 'core' (the pack's files changed since the eject) …`); an engine
upgrade alone, with the skill's files unchanged, does not. Review the change with
`modsys eject module-sync --diff`, take what the team wants into the ejected copy by hand, then
run `modsys eject module-sync --rebase`: it records the engine's current version and file hashes
in the copy's `.modsys-ejected` (never touching the copy's files), so `--diff` says up to date
and MS063 clears. Or delete the copy and run `packs sync` — the agents get the engine's version
again. An ejected copy stays the skill's source even when its pack is disabled. The rules are the same as for any pack skill ([writing-a-pack.md](writing-a-pack.md)).

## Owning a whole pack: copy it

A repository pack with a built-in id replaces that built-in pack — enabled or not — and ranks
like any repository pack. Copy the directory its `packs list` row names:

```bash
modsys packs list --json                  # the built-in row's "dir"
cp -R <that dir> .modsys/packs/ui         # then edit .modsys/packs/ui/
```

The ids `core`, `qa` and `ui` are reserved: `modsys packs new ui` is refused and says how to
enable the built-in pack instead. A team pack that declares a skill with a core skill's name
shadows it (plain `lint` reports MS065 for the built-in one); a hand-written
`.claude/skills/module-scout/` is a `packs sync` conflict and is never overwritten.

## Evals

Whether the skills fire on the requests they are written for is measured with `claude plugin
eval`: `evals/skills/` in the modsys repository holds a trigger case per skill, an outcome case
per writer (`module-sync`, `module-create`, `module-split`) and a negative case, and
`evals/skills/run.py` runs them against a plugin assembled from the built-in packs — see
`evals/skills/README.md` there. Every run is a billed model call, so that suite is run by hand,
never by the unit suite or CI; before a stable release the outcome cases and a trigger check run
as subagents of a Claude Code session ([releasing.md](releasing.md)).
