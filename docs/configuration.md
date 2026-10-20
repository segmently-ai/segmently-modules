# Segmently Modules configuration

Start with `segmently-modules init`: it writes a commented starter `.segmently-modules/config.toml` with a worked
example for the most-used sections below (it has none for `[budgets]`, `[match]`, `[lint]` or
`[roles.<name>]`). This page is the reference for every section and key.

## Layers

The effective config is merged from, lowest precedence first:

1. **engine defaults** — `segmently_modules/defaults/config.toml` (shipped with the engine);
2. **built-in packs** — the engine's packs that `[packs] builtin` enables (`core`, `qa`, `ui`),
   by id, below every repository pack;
3. **packs** — `.segmently-modules/packs/<id>/pack.toml`, lower `priority` wins (see [Packs](#packs));
4. **team config** — `.segmently-modules/config.toml` (commit it);
5. **user config** — `.segmently-modules/config.user.toml` (personal; git-ignore it).

Every file layer is optional: with no `.segmently-modules/config.toml` on disk (and no user config), the
engine defaults apply, packs under `.segmently-modules/packs/<id>/` load as usual and every verb works —
only what a missing file would set is absent (e.g. `[packs] builtin`, so no built-in pack is
enabled).

Merge rules: scalars — the higher layer wins; tables — merged key by key; arrays of tables that
all carry an `id` (`[[code_map]]`, `[[hooks.post_sync]]`) — merged by `id` (the same id
deep-merges, a new id appends); every other array — the higher layer's items are ADDED to the
lower layer's (duplicates dropped). An override never removes a lower-layer item: disable it
(`enabled = false`) instead. Unknown top-level sections are accepted (forward compatibility).
Known keys are type-checked, and a wrong type is an error naming the file — but an unknown key
*inside* a known section, a `[[code_map]]` rule, a `[[hooks.post_sync]]` entry or a
`[roles.<name>]` table is silently accepted and does nothing (e.g. an `exclude = [...]` key on a
`[[code_map]]` rule has no effect; there is no warning). The one exception is a
`[fields.<name>]` declaration, where an unknown key is refused (exit 2, `unknown key '…'`) — see
the `[fields.<name>]` section below.

`--config-dir DIR` points every verb at another config directory (default `<root>/.segmently-modules`).

## `[paths]`

| Key | Default | Meaning |
|---|---|---|
| `modules_dir` | `"modules"` | where module directories live: `<modules_dir>/<name>/MODULE.md`, children under `<name>/submodules/<child>/` |
| `registry` | `"modules/registry.json"` | the registry file (the generated index in the per-module layout) |
| `registry_layout` | `"single"` | `"single"`: one registry file · `"per-module"`: `<modules_dir>/<name>/<module_entry>` per module plus a generated index (`segmently-modules index split` converts, `segmently-modules index build` regenerates) |
| `module_doc` | `"MODULE.md"` | a module's main doc |
| `module_entry` | `"module.json"` | a module's entry file in the per-module layout |
| `proposals_dir` | `".segmently-modules/proposals"` | the proposals queue; `done/` keeps processed files |

## `[registry]`

| Key | Default | Meaning |
|---|---|---|
| `statuses` | `["active", "draft", "planned", "temporary"]` | allowed module `status` values (lint MS003; the writers refuse others) |
| `relations` | `["depends-on", "complements", "implemented-in", "shares-contract", "superseded-by"]` | allowed `related_modules[].relation` values (MS006) |
| `stub_pattern` | see note below | a regular expression; a module dir whose `MODULE.md` head matches is a pointer stub of a retired module |
| `dir_whitelist` | `[]` | directories under `modules_dir` that are not modules (no MS014; a dot-directory never needs it) |
| `updated_at_path` | `""` | e.g. `"metadata.last_updated"`: stamped with the UTC time on every registry write; empty = off |

The default `stub_pattern`, exactly as it must be written in TOML:

```toml
stub_pattern = 'status:?\**\s*\**(retired|merged|migrated|superseded)'
```

## `[budgets]`

| Key | Default | Meaning |
|---|---|---|
| `module_doc_split_signal` | `600` | `MODULE.md` lines above this: MS030 (consider splitting) |
| `module_doc_hard_stop` | `1000` | above this: MS031 (split into children) |
| `role_doc_max` | `600` | role doc lines above this: MS032 |
| `keywords_soft` | `40` | keywords above this on a module without children: MS020 |
| `keyword_shared_warn` | `4` | a keyword shared by this many modules or more: MS021 |
| `skill_split_signal` | `9000` | characters of a pack's `SKILL.md` or of one `references/*.md` file above this: MS068 (route its scenarios or split the skill; a signal, not a cap). An integer >= 1; any layer (a pack, `config.toml`, `config.user.toml`) |
| `pack_split_signal` | `64000` | characters of a pack's `SKILL.md` files together above this: MS069 (route, split a skill out, or split the pack). An integer >= 1; any layer. Both apply to every pack (built-in, repository, user) |
| `rules_text_max` | `8000` | characters of critical-rule text `show` returns for one target, the rules in order; a rule past it keeps its title, its `text` is `null` |
| `rules_index_entries` | `25` | lint MS071 (warning) when an indexed doc's critical-rules section (an `Indexed:` line) has more entries: a warning, never a cap — the entries are checked again against what a rule is (§ `[rules]`) |

## `[match]`

Module routing used by `match`, `context` and `discover --task`: keyword routing by default, by meaning when `mode` says so (see [the agent command](#the-agent-command-and-search)).

| Key | Default | Meaning |
|---|---|---|
| `keyword_weight` | `3` | score per matched keyword |
| `combination_weight` | `2` | bonus per `required_combinations` group fully present in the text |
| `negative_weight` | `-5` | score per matched `negative_keywords` phrase |
| `min_score` | `3` | rows below this are dropped |
| `top` | `8` | at most this many rows (`--top` overrides) |
| `normalize` | `"suffix"` | `"suffix"`: a keyword and a task word match when one is a form of the other — the endings `-s`, `-es`, `-ies`, `-ed` and `-ing` are ignored on both sides (below); `"none"`: exact words, the matching of 0.2.1; any other value is exit 2 naming the key |
| `mode` | `"lexical"` | `"lexical"`, `"semantic"` or `"hybrid"` (`--match` overrides); `semantic` and `hybrid` ask the user's own agent command (`SEGMENTLY_MODULES_AGENT_COMMAND`, below): `semantic` without one is refused (exit 2), `hybrid` without one runs lexically with a note; any other value is exit 2 naming the key. A mode from a config file (team, personal or pack) takes effect for `match`, `context` and `discover --task` only when the user opts in with `SEGMENTLY_MODULES_AGENT_ALLOW_REPO_MODE=1` (below); without it the run is lexical, its stdout byte-identical to `--match lexical`, with one stderr note. `--match` is the user's own choice and needs no opt-in. Every keyword call of the shipped skills, of the `agents-md` block and of a skill `packs new` scaffolds passes `--match lexical` (the skills still read the key to pick their own mode) |

`lexical` (the default) is the keyword routing described below and changes nothing in any output.
`semantic` takes the rows from the user's own agent alone; `hybrid` fuses the keyword rows and the
agent's picks by reciprocal rank fusion (k = 60) and every fused row carries `sources` (`keyword`,
`semantic`) and, when the agent listed it, its `confidence`. The wording of the refusals and
notes and the JSON shapes: [cli-contract.md](cli-contract.md#semantic-module-choice---match).
There is no `[match.semantic]` table and no endpoint key: the engine has no network code.

Matching is by whole words: a keyword or `negative_keywords` phrase must occur as a whole word (or
a run of whole words) in the task text, case-insensitive. Under `normalize = "suffix"` (the
default) the forms of one word match each other: `save` matches "saves", "saved" and "saving",
`entry` matches "entries", `stop` matches "stopped", so one form of a word is enough. The rule is
a light one, by suffix: only an ASCII word of 4 letters or more is cut, a stem keeps 3 letters,
and a word with no ending is never cut — `theme` never matches "them", `note` never "not", and
`news`, `setting` and `evening` are words of their own (never `new`, `set`, `even`). A module
that lists several forms of one word scores that word once. A keyword with a character that is
not a letter, digit or `_` (`.epub`, `c++`, `modules/xyz`) matches exactly. Under
`normalize = "none"` every keyword matches exactly (`todo` does not match `todos`). Precisely: a
boundary is enforced only
on an edge of the keyword that is itself a word character (letter, digit, `_`); a keyword that
starts or ends with a non-word character has NO boundary on that side and can still match inside
a longer token there — `.epub` matches inside `notebook.epub`, `c++` matches inside `c++17`. A
module with no matched keyword never gets a row, no matter what `negative_weight` alone would
score; a row below `min_score` is dropped even with matched keywords. When nothing reaches
`min_score`, `match` prints `no keyword matches (try rephrasing with domain terms, or use: list)` and
`context` prints `no module matched (try domain terms, or: segmently-modules list)`; `discover --task` with
no match simply omits the module (no message). Register the words tasks use (synonyms, not
forms) rather than relying on this to generalize.

Near misses: when nothing reaches `min_score`, `context` (JSON key `near_misses`, and its text)
and `match` (text only; `match --json` stays the plain row list) list the modules and children
that almost matched — a keyword that is not an exact hit but has a word sharing its first
letters with a word of the task (`reminder` ~ `remind`, `auth` ~ `authentication`: the first
5 letters, or all of the shorter word; both words at least 4 letters, so `api` and `tag` match
exactly only), or exact hits whose score a negative keyword pulled below `min_score`. The text
ends with `re-run with the module's own keyword in the task text, or read it directly: segmently-modules
show <module>`; `segmently-modules show <module>` prints the module's keywords on its `keys` line.

## The agent command and `[search]`

The engine holds no model, no API key and no network code. `semantic` / `hybrid` matching and
`segmently-modules choose --run` run a command the user configured, with the work order of `segmently-modules choose`
on its stdin (compact JSON; also as the files `SEGMENTLY_MODULES_WORK_ORDER` and `SEGMENTLY_MODULES_SCHEMA`), and read
its answer from stdout. A registry without modules, or `--top 0`, asks nothing.

Why an environment variable and not a config file: a command in a file the repository commits
(a team config, or a pack someone installs) would let a commit put an agent command on every
contributor's machine. So the command is read ONLY from the process environment of the user who
runs Segmently Modules; an `[agent]` table in any config file is refused (exit 2 naming the file), whatever
file it is in. A repository cannot choose or change the command, and it cannot make `match`,
`context` or `discover --task` run it: a `[match] mode` from any config file (team, personal or
pack) runs the agent command only with your opt-in,
`SEGMENTLY_MODULES_AGENT_ALLOW_REPO_MODE=1` in your environment (card text the repository wrote would reach
your agent: prompt injection, and one agent call per run). Without it the run is lexical and says
so in one stderr line (`segmently-modules: note: [match] mode "hybrid" is set in a config file; it runs your
agent command only with SEGMENTLY_MODULES_AGENT_ALLOW_REPO_MODE=1 (or pass --match hybrid) — ran lexical`);
`--match` and `choose --run` are your own requests and need no opt-in. A repository can still
run commands of its own: a `[[hooks.post_sync]]` hook (in the team config or a pack) runs on
`segmently-modules sync` with your environment, the agent variables included, so it can start your agent
command too; `sync --dry-run` runs no hook. So set the opt-in per CI job or per shell session in
repositories you trust, not in your shell profile, and keep the command's own permissions
read-only. The agent uses the user's own credentials (the
engine reads none), and the engine ships, installs and suggests no model.

| Key | Default | Meaning |
|---|---|---|
| `SEGMENTLY_MODULES_AGENT_COMMAND` | unset | the argv list of the agent command, a JSON array of strings, read ONLY from this environment variable (`catalog` reports `match.semantic` true only for a valid one outside an agent run; with a malformed value, or a bad `SEGMENTLY_MODULES_AGENT_TIMEOUT`, `catalog` exits 0 with `match.semantic` false and one stderr note, while the verbs that run the agent refuse it with exit 2); items may use `{claude_model}`, `{codex_model}`, `{effort}` and `{reasoning}` (`quick` → `low`, `standard` → `medium`, `deep` → `high`), `{{` / `}}` are literal braces; run without a shell. An `[agent]` table in any config file (team, personal or a pack) is refused (exit 2 naming the file): a repository could commit it. Inside an agent run (`SEGMENTLY_MODULES_WORK_ORDER` set) the command is unavailable: `semantic` and `choose --run` are refused, `hybrid` runs lexically with a note |
| `SEGMENTLY_MODULES_AGENT_ALLOW_REPO_MODE` | unset | environment only (never a config file): `1` lets a `[match] mode` from a config file run your agent command; unset, empty or `0` = off (the run is lexical, with one stderr note, and `SEGMENTLY_MODULES_AGENT_COMMAND` / `SEGMENTLY_MODULES_AGENT_TIMEOUT` are not read); anything else (`true`, `" 1 "`) is exit 2 `SEGMENTLY_MODULES_AGENT_ALLOW_REPO_MODE: expected 1 or 0, got '<value>'` (at most 40 characters shown). Validated only when a config file sets a non-lexical mode and no `--match` is given; `catalog` and `choose` never read it |
| `SEGMENTLY_MODULES_ALLOW_INDEX_WRITER` | unset | environment only (never a config file): `1` lets the engine start a writer that indexes the rules of a doc (`rules --build`, run by module-discover on the user's yes under `[rules] index = "discover"`); unset, empty or `0` = no writer is started; anything else is exit 2. A committed `[rules] index = "discover"` alone never starts an agent |
| `SEGMENTLY_MODULES_INDEX_COMMAND` | unset | the writer's argv, a JSON array of strings, environment only; items may use `{doc}` (its absolute path), `{doc_rule}` (`//` + that path, for a Claude Code permission rule), `{root}`, `{claude_model}`, `{codex_model}` (`{{` / `}}`: literal braces); run without a shell, the prompt on stdin. Unset inside Claude Code (`CLAUDECODE=1`): `claude -p --model {claude_model} --output-format json --permission-mode dontAsk --allowedTools Read Grep Glob Edit({doc_rule}) "Bash(segmently-modules rules:*)" "Bash(segmently-modules lint:*)"`. Elsewhere set it, e.g. `["codex", "exec", "-m", "{codex_model}", "--sandbox", "workspace-write", "-"]` (a sandboxed Codex session cannot give its child write access, and Codex has no marker the engine could read) |
| `SEGMENTLY_MODULES_INDEX_TIMEOUT` | `900` | seconds per writer, 1 to 3600 |
| `SEGMENTLY_MODULES_AGENT_TIMEOUT` | `300` | seconds: an integer from 1 to 3600 written with at most 4 digits (`0300` is accepted, `00300` is not; spaces around it are ignored); anything else is exit 2 naming the variable |
| `[search] claude_model` | `"sonnet"` | the model the Claude Code skill's subagent uses: a Claude Code subagent model alias (`sonnet`, `opus`, `haiku`) — the subagent takes no full model id; a full model id works only where your agent command passes the value to `claude -p --model`; 1–100 characters of letters, digits and `. _ : / @ + -`, starting with a letter or digit (the value becomes an item of your agent command) |
| `[search] codex_model` | `"gpt-5.6-luna"` | the model `codex exec -m` uses; same rule |
| `[search] effort` | `"standard"` | `quick` (choose from the cards only), `standard` (also open the INDEX of up to 3 candidates), `deep` (also read the candidates' docs and the code). Team or user config; the user's wins per key; any other value is exit 2; `segmently-modules choose --effort quick\|standard\|deep` overrides it for one run |
| `[search] card_keywords` | `10` | an integer >= 0: a work-order card carries the first N keywords of its module, in registry order (`0` = none, a card with fewer keeps them all). Team, personal or pack config; the personal value wins per key; `true`, `false`, a string, a fraction or a negative number is exit 2 naming the file. It caps the work order only (`choose`, `choose --apply` / `--run`, `--match semantic` / `hybrid`); `catalog` keeps every keyword; the `search` object of `catalog` and of the work order keeps its three keys. `catalog_digest` is computed over the capped cards, so a change of the cap changes the digest (`choose --apply` then notes `catalog changed since the work order`); `--effort` and the task do not change it |
| `[search] chooser` | `"always"` | when module-discover runs the chooser, the search by meaning: `always` (every run, as before this key), `when_unsure` (the keyword command first; the chooser only when its `lexical_confidence` is `unsure`, the lists then merged as in `hybrid`), `never` (keywords only). The user's words for one run ("by meaning", "only lexical") win over it; `[match] mode` stays the command line's default only, except that under `always` a `semantic` one keeps module-discover meaning-only. Team, personal or pack config; the personal value wins per key; any other value is exit 2 naming the file, the key, the allowed values and the value given |
| `[search] sure_min_score` | `2` | an integer >= 1: `discover --json`'s `lexical_confidence` is `unsure` (`low_score`) when the top keyword score is below it (a keyword hit scores `[match] keyword_weight`, 3 by default). With the default weights every keyword row scores at least 3, so the default 2 never yields `low_score`; raise it above one hit's score (4 or more) to make a single hit unsure. `true`, a string, a fraction, `0` or a negative number is exit 2 |
| `[search] cards` | `"full"` | the cards of every work order (`choose`, `choose --apply` / `--run`, `--match semantic` / `hybrid`): `full` (name, description, the first `card_keywords` keywords; a child card names its parent) or `brief` (one card per module and per child: name and description, a parent's card naming its children, a child's its parent, no keyword — a smaller order). `choose --cards full\|brief` overrides it for one run; any other value is exit 2 |
| `[search] generic` | `[]` | the modules that match almost any task (a shared UI kit, a shared data layer), by id, e.g. `["ui-kit", "data-core"]`; a listed module covers its family — the module and its children (`<id>/…`). `discover --json`'s `lexical_confidence` leaves their keyword rows out of its verdict: when every keyword row is theirs it is `unsure` with the reason `generic` (`top`: those at the top score); otherwise `tie`, `low_score` and `sure` are decided over the other modules' rows. So under `chooser = "when_unsure"` hits on these modules alone no longer skip the chooser. They stay in `discover`'s `modules` and in every other output. An id that names no module is ignored. Team, personal or pack config; the ids of every layer add up (arrays add); anything but a list of module ids (non-empty strings) is exit 2 naming the file |

`segmently-modules catalog --settings` prints every `[match]`, `[search]`, `[rules]` and `[discover]` key with its merged value,
defaults filled in (`--json`: `{match, search, rules, discover}`); `catalog` without it keeps its three `search` keys.

## `[rules]`

The rules index is optional. Every doc of a module — its module doc and each role doc, a child's
and its parent's — may hold a critical-rules section (`[lint] critical_rules_heading`) with the
rules that doc states; a section whose first line reads `Indexed: every rule of this doc,
YYYY-MM-DD.` is that doc's complete index (only a reader of the whole doc writes the line). Every
flow reads whatever sections exist; this key says who writes them.

| Key | Default | Meaning |
|---|---|---|
| `index` | `"sync"` | `sync`: the flows that write docs anyway write and keep the index — module-create and module-init index the docs they write, module-roles and module-split the docs they fill or split, module-sync keeps the entries of the rules a session changes and indexes the docs of a module the session changed that have none; module-discover only reads it (a module without a complete index: its docs read to the end). `discover`: the same, and module-discover, which writes nothing while it works, names the docs without an index of the modules it chose (`discover --files`, `rules`, `show`) and asks the user after its report whether to index them; on a yes `rules --build <module>… --background` gives each doc a writer, and each of the module doc's other docs in its own folder a writer that lists their rules for the engine to add — only with `SEGMENTLY_MODULES_ALLOW_INDEX_WRITER=1` in the user's environment (never in a branch review or a pipeline). `off`: nothing writes an index or a new section. `show --json` returns it as `rules_setting` and each target's state as `rules_index`; `rules --missing` lists the docs without one. Team, personal or pack config; any other value is exit 2 |

A rule, for every writer of an index, passes three tests: important (breaking it silently breaks money, data,
security, a UX invariant or another module's contract), not evident from the code it is about (not what that code
plainly does, not what a type, a test or a linter already enforces), and in force now (not history, a plan step or a
status). Feature descriptions and how-to steps are not rules.

## `[discover]`

What module-discover's step 5 reads (`show <module> --discover`), and whether its step 9 saves the result.

| Key | Default | Meaning |
|---|---|---|
| `docs` | `"all"` | the docs it reads: `"all"`, or a list of `"module"` (the module doc), `"extras"` (its other `context_files` docs) and role names, e.g. `["module", "developer"]`; a doc left out is a `skip` line (`not_read`, `why: "docs"`); an unknown name is exit 2 |
| `read` | `"whole"` | `"whole"`: every listed doc is read to the end; `"index"`: a doc whose rules index is complete, and an other doc its module doc's index cites, is an `index` line (`why: "index"`): not read, its rules are the `rules` output; a doc without an index is still read whole |
| `save` | `"always"` | module-discover's step 9 saves its result as a task context file (`task-context save`, `docs/cli-contract.md`): `"always"`; `"ask"`: it asks after the report; `"off"`: only when the user or a caller asks. A path the user or a caller gives always wins. `catalog --settings` prints it; any other value is exit 2 |
| `save_dir` | `".segmently-modules/tasks"` | where `task-context save` writes a file when no `--out` is given, relative to the root: `<YYYY-MM-DD>-<slug of the task>.json`; on first use the directory gets a `.gitignore` holding `*`. An empty value is exit 2 |

## `[lint]`

| Key | Default | Meaning |
|---|---|---|
| `fail_on` | `"error"` | `error` · `warning` · `never`: the lowest severity that makes `lint` exit 1 (`--fail-on` overrides) |
| `component_table_heading` | `"EXISTING Components"` | the `MODULE.md` section whose table rows lint checks for backticked paths (MS040) |
| `critical_rules_heading` | `"Critical Rules"` | the section of every module doc — the module doc and each role doc — whose rule headings (or top-level list items) `show`, `rules` and `discover` return as `rules`, each with its doc's role; a heading whose words, after any leading emoji or symbols, start with it, in any case, at any level ("🔴 Critical Rules (Read First)" is one, "Test cases from the Critical Rules" is not) |
| `drift_severity` | `"warning"` | severity of MS050 (`info`, `warning` or `error`) |
| `overlap_severity` | `"warning"` | severity of MS053 (`info`, `warning` or `error`) |
| `link_severity` | `"warning"` | severity of MS041, a link in a registered doc whose target is missing (`info`, `warning` or `error`) — `info` keeps a gate green while the links are fixed |

## `[create]`

| Key | Default | Meaning |
|---|---|---|
| `min_keywords` | `5` | distinct keywords a top-level module needs (a child needs 1) |
| `max_keywords` | `40` | the most distinct words a module's keywords may hold (forms of one word count once under `[match] normalize`): `init done` refuses more, `init verify` fails a new module with more, `create` warns; lint keeps MS020 (`[budgets] keywords_soft`) for existing modules; less than 1 is exit 2 |
| `generic_keywords` | `[]` | words added to the built-in generic list (below): `create` and `init done` warn about them, `init verify` fails a new module that holds one, lint reports them as MS023 (info) |
| `description_min` | `20` | shortest description, in characters |
| `description_max` | `200` | longest description |
| `default_status` | `"planned"` | status of a new module when none is given |

`create` also checks the keywords it is given and warns — it never refuses and never changes
what it writes (`--non-interactive` included; `segmently-modules: warning: …` lines on stderr — one per
short or generic keyword, one when there are too many, and ONE line for all the form (or plural)
hints of the run, naming their count and the first three pairs —, with `--json` the list
`data.warnings`, one entry per keyword, then the one for too many). It warns about a keyword of 3
characters or fewer (`api`, `ui`); a generic word — `common`, `data`, `helper`, `info`, `item`,
`list`, `misc`, `stuff`, `util`, `create`, `edit`, `add`, `delete`, `remove`, `update`, `save`,
`load`, `get`, `set`, `search`, `select`, `copy`, `open`, `close`, `show`, `user`, `screen`, `app`,
`module`, `test`, plus `generic_keywords`; any case and, under `[match]
normalize`, any form (`deletes`) — unless it is a word of the module's own name (`module-tools`
may keep `module`); and more distinct words than `max_keywords`. Under `normalize = "suffix"` (the
default) it says when a keyword is a form of an earlier one (`loans` after `loan`: one form is
enough). Under `normalize = "none"` it says instead when a single lowercase word of 4 letters or
more has no plain singular or plural keyword (matching is exact: `book` does not match "books").
That plural rule is a hint by suffix, not linguistics: `ies` ↔ a consonant + `y` (`categories` ↔
`category`), `sses` / `xes` / `zes` / `ches` / `shes` ↔ the word without `es`, otherwise `s`; a
word ending in `ss`, `us` or `is` counts as singular (`class` → `classes`). The hint never
suggests a generic word (one of the first nine: `utils` gets no "add `util`").

## `[coverage]`

`segmently-modules coverage` counts every git-tracked file plus every new file git does not ignore,
relative to the root. The modules dir, the config dir, the registry file and its `.lock`, the
proposals dir (`[paths]`) and dotfiles or dot-directories at any level never count. `share` is mapped / total rounded down to 3 decimals, so it never overstates;
`--fail-under PCT` compares the reported percent (`share` × 100, one decimal).

| Key | Default | Meaning |
|---|---|---|
| `include` | `["**"]` (built in) | globs a file must match to count; a team `include` replaces the built-in `**`; `include = []` is refused (it would count no file — omit `include` to count every file) |
| `exclude` | `[]` | globs that never count (generated code, vendored files, docs) |
| `doc_only` | `[]` | modules that own no code on purpose (a theory or registry module): lint MS054 leaves them alone; a name that is no registry module is MS056 |

## `[ci]`

`segmently-modules ci` — one gate: `lint` (plain), `drift` (`lint --changed` against `base`) and
`coverage`; every step always runs and the command exits 1 when any step failed. A flag
overrides each key (`--fail-on`, `--base`, `--fail-under`).

| Key | Default | Meaning |
|---|---|---|
| `fail_on` | `"warning"` | `error` · `warning` · `never`: the lowest severity that fails the lint and drift steps |
| `base` | `"HEAD"` | the ref drift is measured against — in CI the target branch; against `HEAD` a clean checkout has nothing to compare (`ci` says so in `notes`) |
| `coverage_fail_under` | unset | a number `0`–`100`: the coverage step fails below this percent (compared like `coverage --fail-under`); unset = the step only reports |

## `[packs]`

| Key | Default | Meaning |
|---|---|---|
| `agents` | unset | the agents `segmently-modules packs sync` writes pack skills for when no `--agent` flag is given: `claude` (`.claude/skills/`), `codex`, `cursor`, `gemini`, `copilot` (all four read `.agents/skills/`, written once however many of them are listed); `codex` also gets the agents of `module-discover`, `module-scout` and `module-research` in `.codex/agents/` (`<name>.toml`, managed files — [skills.md](skills.md)); any other name is refused (exit 2 naming the file). With no agent named, under `builtin_delivery = "plugin"`, a `.codex/agents/` holding a marked agent file means codex (a regular file directly in it whose first line is a valid `# segmently-modules-managed:` marker; a symlinked `.codex/agents` holding one infers too, so `next` shows its conflict rows; a symlinked file, a subdirectory or a non-directory does not; `setup`'s choice is unchanged). Only there do a bare `packs sync` and `next` read `.codex/agents/` to infer codex; a run that names its agents without `codex` never opens `.codex/`. Like every array, a higher layer ADDS to a lower one's list; `--agent` flags replace it. `packs sync --remove --agent A` refuses while another agent listed here reads A's directory |
| `builtin` | `[]` | the engine's built-in packs to enable: `core` (the core agent skills), `ui` (a `designer` role and the `designer` skill), `qa` (a `qa_acceptance` role and acceptance-criteria skills). Set it in `config.toml` or `config.user.toml` (the two lists add up; a repeated id counts once; a pack cannot set it); an unknown id is refused (exit 2 naming the file and the known ids). An enabled built-in pack is a pack layer below every repository pack; its version is the engine version. A repository pack with the same id (`.segmently-modules/packs/ui/`) replaces it, enabled or not |
| `builtin_delivery` | `"repo"` | where the agents get the enabled built-in packs' skills: `"repo"` — `segmently-modules packs sync` copies them into the agents' skill directories — or `"plugin"` — the Segmently Modules plugins provide them (`core` → `segmently-modules`, `ui` → `segmently-modules-ui`, `qa` → `segmently-modules-qa`): `packs sync` copies none of them (it still writes `codex`'s agent files in `.codex/agents/`, which no plugin can place) and removes the copies it made earlier (an edited copy is a conflict and stays), `segmently-modules eject` of a built-in skill is refused (`eject needs "repo"`), an ejected built-in skill is a `packs sync` conflict, and plain `lint` reports each copy still there (MS067, info). A table gives each agent its own value — `builtin_delivery = { claude = "plugin", codex = "repo" }`: Claude Code from the plugin, Codex as copies (Codex enables a plugin only for the user, in every repository). An agent the table leaves out takes the value of an agent that reads the same directory, else `"repo"`; agents that share `.agents/skills` need the same value. `packs sync` copies the built-in skills only for the `"repo"` agents and a repository pack's skills for every agent; MS067 looks only where a plugin delivers; `eject` of a built-in skill needs `"repo"` for every agent. The built-in packs' roles and templates and a repository pack's skills (any id) are the same under both; the `agents-md` block words the skill list's lead-in by delivery. Set it in `config.toml` or `config.user.toml` (a scalar: the user's wins); a pack cannot set it (exit 2 naming its `pack.toml`); any other value is exit 2 naming the file and `repo, plugin` |

## `[ui]`

Read by the `ui` pack's `designer` skill, not by the engine: the engine accepts the table (an
unknown top-level section) and checks none of its keys. The skill reads it from `config.toml`
and `config.user.toml` (a list in both adds up; for any other key the user file wins).

| Key | Default | What it holds |
|---|---|---|
| `rules` | unset | the docs every run reads: the team's design rules, token tables, surface kinds (each with its tokens, sizes and colour schemes) |
| `tokens` | unset | the files holding the token values the mocks use |
| `capture` | unset | how to screenshot the running app: a command, or the browser tool to use; unset — the skill asks the user for the screenshots |
| `sizes` | unset | the viewports to capture, such as `"1280x800"` |
| `schemes` | unset | the colour schemes to capture, such as `"light"`, `"dark"` |
| `checker` | unset | the design checker command; a designer doc's "Design checker" section replaces it for its module; unset and unnamed — no checker runs |
| `artifacts` | `.design` | the directory of the feature folders (`<artifacts>/<feature>/`: the brief, the mocks, the audit, the review, the screenshots) |

## `[init]`

`segmently-modules init` — start from existing code: preflight, map, the fan-out, reconcile, verify,
finish (every phase: [init.md](init.md)).

| Key | Default | Meaning |
|---|---|---|
| `exclude` | `[]` | globs (the `[[code_map]]` grammar) of files the init file set leaves out — preflight counts, candidates, `unassigned` and the file claims `init confirm` checks; a list of strings (anything else is exit 2 naming the file and the key); like every array, the user config's list adds to the team's |
| `co_change_commits` | `500` | how many recent commits `init map` reads for the co-change signal (`git log`); an integer `>= 0` (`0` turns the signal off: no `git log` runs); `true` / `false`, text or a fraction is exit 2 naming the file and the key |
| `split_hint_lines` | `10000` | `init map` gives a candidate with more lines of code than this a `split` hint whose `children` are its code-holding subdirectories (`{dir, lines}`; one over the limit replaced by its own, at most 3 levels down); `0` turns it off; below `0` is exit 2 |
| `routing_min_hit_rate` | `0.8` | the lowest routing hit rate `init verify` and `segmently-modules eval routing` pass (`--min-hit-rate` overrides it for `eval routing`): a number from `0` to `1` (anything else is exit 2 naming the file and the key); a run passes when hits ≥ this × tasks, unrounded |
| `max_parallel` | `4` | how many work items `init run --executor` (and the `module-init` skill's subagents) write at a time; an integer `>= 1`, no upper bound (never more than the pending items); `0`, a negative number, `true` / `false`, a fraction or text is exit 2 `[init] max_parallel must be an integer >= 1` naming the file |

Preflight (`<config_dir>/init/preflight.json`) lists the file set — `git ls-files --cached
--others --exclude-standard` in a git repository, else every file below the root except in
dot-directories and in `node_modules`, `.venv`, `venv`, `__pycache__`, `dist`, `build`,
`target`, `vendor` — minus `[init] exclude` and any path whose name is not valid UTF-8 (possible
on Linux; left out, as no output could name it), and counts it: every file toward `files`, its size
toward `bytes` (a file that cannot be read counts toward `files` only; a symlink is never
followed and adds 0 bytes). A text file — at most 1,048,576 bytes, no NUL byte in its first
8,192 — adds `len(text.splitlines())` to `lines` and its size to `token_estimate` (text bytes
// 4); a code file adds to its `languages` row, by extension:

| Extension | Language |
|---|---|
| `.c` | C |
| `.cc` | C++ |
| `.cjs` | JavaScript |
| `.cpp` | C++ |
| `.cs` | C# |
| `.cts` | TypeScript |
| `.dart` | Dart |
| `.ex` | Elixir |
| `.exs` | Elixir |
| `.go` | Go |
| `.h` | C |
| `.hpp` | C++ |
| `.java` | Java |
| `.js` | JavaScript |
| `.jsx` | JavaScript |
| `.kt` | Kotlin |
| `.lua` | Lua |
| `.m` | Objective-C |
| `.mjs` | JavaScript |
| `.mts` | TypeScript |
| `.php` | PHP |
| `.py` | Python |
| `.r` | R |
| `.rb` | Ruby |
| `.rs` | Rust |
| `.scala` | Scala |
| `.sh` | Shell |
| `.sql` | SQL |
| `.svelte` | Svelte |
| `.swift` | Swift |
| `.ts` | TypeScript |
| `.tsx` | TypeScript |
| `.vue` | Vue |

It also lists the package manifests (`package.json`, `pyproject.toml`, `setup.cfg`, `go.mod`,
`Cargo.toml`, `composer.json`, `*.csproj`: `{path, kind, name, workspaces}`, `name: null` when
one does not parse), the agents' instruction files that exist (`AGENTS.md`, `CLAUDE.md`,
`GEMINI.md`, `.cursorrules`, `.windsurfrules`, `.github/copilot-instructions.md`), the ADR
directories that hold files (`adr/`, `adrs/`, `doc/adr/`, `docs/adr/`, `docs/adrs/`,
`docs/decisions/`, `docs/architecture/decisions/`, `architecture/decisions/`), the top-level
directories and `git: {head, commits}` (`null` outside git).

## Adopting an existing registry

`segmently-modules adopt` reads a registry written by other tooling as it is and infers the config the
engine needs to read it (the README walks through it; every verb's JSON: `cli-contract.md`).
Every key it writes is followed by `# adopt:` lines with the evidence; the rules, all computed
in integers:

| Inferred | When | Written |
|---|---|---|
| `[paths]` | the registry is not at the configured path (`--registry PATH`, root-relative), or every module it lists has a `<modules_dir>/<name>/module.json` that is its registry entry (an object with `description`, `keywords`, `context_files` or `status`, and no other module's `name`); another tool's file there, or entries for only some modules, keep the single layout with an `# adopt:` note; `--layout single\|per-module` decides instead | `registry` and `modules_dir` (the registry file's directory); `registry_layout = "per-module"` |
| `[roles.<r>]` | a `context_files.roles` key of a module or child that no layer configures | `order` = the highest configured order + 10 per new role (most-used first, then by name); `standard = true` when at least 80 % of the top-level modules carry the role (`count * 5 >= total * 4`), else `false`; `applies_when` and `description` are never guessed |
| `[fields.<k>]` | an entry key that is neither a core field nor declared by a layer | `type` from the observed values (several types: a list, the most frequent first); `scope` = where the key was seen (`module`, `submodule` or both); `kind = "code_pointer"` when at least 80 % of its string values name paths of the repository (`path:line` and `path#L3` allowed; absolute paths, `~`, `..` and globs never count). A key holding a float, a `null` or a list of mixed types cannot be declared: it is listed in `inferred.skipped` (lint keeps MS012 for it); `deprecated` is never guessed |
| `[registry] dir_whitelist` | a directory under the modules dir that is neither a registry module nor a pointer stub (dot-directories never count) | the directories, active |
| `[registry] updated_at_path` | a registry-level key at most 2 levels deep (outside `modules`) named `…updated…` or `…modified…` holding an ISO-8601 date or timestamp | the shallowest, then by name |
| `[registry] statuses` / `relations` | a module's `status`, or a `related_modules` edge's `relation` (modules and children), that no team layer allows (MS003 / MS006 otherwise) | only the new values (arrays add to the defaults), most used first, each with the entries that use it — reported as `inferred.statuses` / `inferred.relations` (`[{value, count}]`); a null, non-string or empty value is never declared: `inferred.skipped` names it (lint keeps its finding) |
| `[[code_map]]` | at least 50 % of the top-level modules (`count * 2 >= total`) have `<prefix>/<module>` — a directory that holds a code file (an extension of the `[init]` language table; `docs/<module>/` of Markdown files does not count), or a `code_pointer` value under it; prefixes up to 3 segments, never the modules dir, the config dir, a dot-directory or `node_modules`, `.venv`, `venv`, `__pycache__`, `dist`, `build`, `target`, `vendor`; none when a layer already has rules | one rule `<prefix>/{module}/**`, `id` = the prefix with `/` → `-`; the widest coverage wins, then fewer segments, then a source container name (`src`, `lib`, `app`, `packages`, `services`, `apps`), then the name; the others are named as alternatives. When no prefix reaches 50 %: the best one (same order) COMMENTED OUT, with its `covered` of `total` evidence — reported as `inferred.code_map_suggestion` (`{pattern, covered, total}`; `null` when a rule was inferred or no prefix covers a module); the threshold stays 50 %, so a second `adopt` reports the same suggestion and never makes it a rule |
| `[budgets]` | the doc budgets would flag docs (MS030, MS031, MS032) | COMMENTED OUT: the observed maximum and how many findings it would clear — a team decision |

`adopt` never writes `[packs]` (its next steps name `[packs] builtin = ["core"]`) and never
edits an existing config: with a `config.toml` present it writes what is still missing to
`adopt.proposed.toml` for the team to merge by hand. It infers from the team layers only: a
declaration that lives only in `config.user.toml` (personal) is written to the team file too,
with the evidence line `also declared in config.user.toml (personal)`, so a teammate without
that file reads the registry the same way. Then lint runs in report mode against every layer
and the result (exit 0 whatever it finds).

## `[roles.<name>]`

Roles are the audiences of per-module docs (`roles/<role>.md`). Defaults: `developer` (10),
`qa` (20), `po` (30), `architect` (40), all standard.

| Key | Default | Meaning |
|---|---|---|
| `order` | `1000` | sort order in `show` / `context` |
| `enabled` | `true` | `false` hides the role everywhere |
| `standard` | `false` | `create` scaffolds its doc for every module |
| `applies_when` | — | a tag: `create --tag <tag>` scaffolds the doc (e.g. `"ui"` for a designer role) |
| `description` | — | one line, shown in the scaffolded doc |
| `template` | — | pack roles: the template path inside the pack |
| `rules_index` | `true` | `false`: another skill writes this role's docs (the qa pack's `qa_acceptance`), so they are never indexed by hand — a rules section they have is still read, and they never count as missing an index |

A role the team declares — here, a security review that every module gets:

```toml
[roles.security]
order = 50
standard = true
description = "Threats, secrets and permissions the module touches"
```

`create` resolves a template (first hit wins): `<config_dir>/overrides/templates/<path>` →
the role's own pack `template` → `<pack>/templates/<path>` in pack precedence order → the
engine's defaults: `MODULE.md`, one template per standard role (`roles/developer.md`,
`roles/qa.md`, `roles/po.md`, `roles/architect.md` — each with a few headed sections for that
audience) and the generic `roles/_role.md` for any other role. `agents-md.md` — the text of the
managed block `segmently-modules agents-md` keeps in agent instruction files (`${modules_dir}`,
`${registry}`, `${roles}`, `${skills}`, `${version}`) — resolves the same way. A candidate that
does not exist falls through to the next layer; one that exists but cannot be read stops the verb
with exit 2 and `cannot read <path>: <reason>`, writing nothing — and so does a template that is
not UTF-8 where a verb renders it ([cli-contract.md](cli-contract.md)). Templates use `${name}`,
`${title}`, `${description}`, `${status}`, `${keywords}`, `${parent}`, `${role}`,
`${role_description}`, `${article}` (`a` or `an`, for the role name that follows it).

**A role added after modules exist.** `create` only scaffolds docs for new modules. Once a role
is declared (here, in a pack, or by a newer engine), give the EXISTING modules its doc with
`segmently-modules roles add ROLE --all` — run it with `--dry-run` first (for the role above:
`segmently-modules roles add security --all --dry-run`, then `segmently-modules roles add security --all`); it renders
the doc as `create` would, registers it, never overwrites a file that is already there, and
writes nothing when nothing is missing. `--recreate` writes the doc of a registered role whose file is gone.
`segmently-modules roles list` shows, per role, the modules that have its doc and those that do not;
`segmently-modules next` names a standard role with missing docs (for instance after an upgrade) together
with the command. Fill each new doc with what that role needs for that module.

**Children and the parent's role docs.** A child (`parent/child`) without a doc of its own for a
role is covered by its parent's doc — `show` reads it that way — so `segmently-modules roles list` reports
it as `inherited` (a status of its own, neither `docs` nor `missing`), `segmently-modules next` does not ask
for it and `roles add ROLE --all` does not create it. Naming the child (`roles add ROLE
parent/child`) creates its own doc.

**A module that does not need a role.** Some modules need no doc for a standard role — a
backend module and a designer role, a build tool and a product-owner role. Say so once:
`segmently-modules roles skip ROLE MODULE… [--note "why"]` writes the mark into the registry,
`context_files.roles.<role>` = `false`, or `{"skip": "why"}` with a note. `roles list` counts
such a module as `skipped` (the text: `not needed N`), not `missing`; `segmently-modules next` stops asking
for it; `roles add ROLE --all` leaves it alone; `show --role ROLE` names the role as not needed,
with the note. A module that has the role's doc on disk is refused (delete the doc first). To
lift the mark, give the module its doc: `segmently-modules roles add ROLE MODULE`. A role that no module
needs is turned off instead: `[roles.<role>] enabled = false`.

`segmently-modules templates list` prints every template with the layer that wins (`override`,
`role-template:<pack>`, `pack:<pack>`, `engine`, or `engine-fallback` for a role rendered from
`roles/_role.md`) and its file. `segmently-modules templates override roles/qa.md` copies the winning
template to `.segmently-modules/overrides/templates/roles/qa.md` once; edit that copy — it wins from then
on (the engine never rewrites it, and a later upstream change to the template does not reach it).

**The rules of `segmently-modules choose`.** The instruction of the choose work order is the template
`choose/rules.md` (`segmently-modules templates list` shows it last, after the init prompts). It resolves
through the same chain (override → a pack's `templates/choose/rules.md` → the engine's), but a
missing engine file is never replaced by a role template. Format: every line that starts with
`- ` (at column 0) is one rule, sent as written without the `- ` and without trailing
whitespace, in file order; every other line is a note for the person editing and is not sent.
Placeholders (as in every template): `$max_picks` (the most picks the order allows), `$depth`
(the fixed sentence of `[search] effort`, or of `choose --effort` when given), `$$` for a literal `$`; any other `$name` stays as
written. An override without a `- $depth` rule drops the depth: `[search] effort` and
`choose --effort` then no longer reach the chooser of the text form, which has no `search` line
(only the JSON order's `search.effort` and `--run`'s `{effort}` / `{reasoning}` still carry it)
— keep `$depth` in your copy. To change the rules: `segmently-modules templates override choose/rules.md`,
then edit `.segmently-modules/overrides/templates/choose/rules.md`. A template without a rule is exit 2
(`<path>: no rule in choose/rules.md (a rule is a line starting with "- ")`), an unreadable or
non-UTF-8 one is exit 2 (`cannot read <path>: <reason>`). Only a run that builds a work order
reads it (`choose`, including `--apply` and `--run`, and `match` / `context` / `discover --task`
in semantic or hybrid mode); lexical runs, `catalog` and the other verbs never do.

## `[fields.<name>]`

Every registry field beyond the core ones is declared once; the declaration drives validation
(lint, writers), the JSON Schema (`segmently-modules schema`), `show` output and `create` prompts. Core
fields (always present, never redeclared): `name`, `description`, `status`, `keywords`,
`context_files`, `related_modules`, `submodules`, `negative_keywords`, `required_combinations`.

| Key | Default | Meaning |
|---|---|---|
| `type` | required | a type expression or a list of them: `string`, `bool`, `int`, `object`, `T[]`, `map<string,T>` |
| `scope` | `"module"` | `"module"`, `"submodule"` or both (a list) |
| `kind` | `"data"` | `"code_pointer"`: the values are code paths (a file or a directory; `path:line` allowed) that map files to the module and show up as `code` in `show` / `context` |
| `required` | `[]` | scopes where the field is mandatory (MS001) |
| `description` | `""` | shown in the schema and `create` prompts |
| `ask_on_create` | `false` | `create` asks for it (answers key = field name) |
| `deprecated` | `""` | non-empty = deprecated; the text is the migration hint (MS011; writers refuse it) |
| `used_by` | `[]` | informational: which features read it |
| `sync_hint` | `""` | when to update the field after a change, in plain words — `segmently-modules sync-instructions` lists it for every module a change touches |

The core fields carry these `sync_hint`s (`name` has none: the engine keeps it equal to the
registry key). A layer may set a core field's `sync_hint` and nothing else —
`[fields.keywords]` with only `sync_hint = "…"` replaces the hint; any other key is refused
(exit 2, `is a core field; it cannot be redeclared`):

| Core field | `sync_hint` |
|---|---|
| `description` | Rewrite it when the module's purpose or scope changes: one sentence on what it does, why, and when a task belongs here. |
| `status` | Change it when the module's lifecycle moves on, e.g. from planned to active when its code ships. |
| `keywords` | Add the words a task about this module would use when the change brings new ones; a split parent keeps all its keywords. |
| `context_files` | Update it when a doc of the module is added, moved or removed: universal names the module doc, roles names each role doc. |
| `related_modules` | Add an edge when the change makes this module depend on, complement or share a contract with another module. |
| `submodules` | Add a child when a functional area grows out of the module (a split); remove one when its area is retired. |
| `negative_keywords` | Add a phrase when tasks that use this module's words but belong elsewhere keep matching it. |
| `required_combinations` | Add a group when two words point to this module only together, not alone. |

After a change, one command lists per touched module the docs to update, the drift and these
hints:

```bash
segmently-modules sync-instructions --from-diff "$BASE..HEAD"   # or --files PATH …, or --module M …
```

An undeclared field in the registry is MS012; writing one is refused with
`unknown field 'X' (declare [fields.X] in config or a pack)`. Example:

```toml
[fields.code_paths]
type = "string[]"
kind = "code_pointer"
scope = ["module", "submodule"]
description = "Source files or directories of the module"
```

## `[[code_map]]`

Rules that map code files to modules. `sync`, `discover`, `lint --changed` (MS050), `coverage`
and the `code_globs` of `show` / `context` all use them (together with module docs, which map
to their own module, and `code_pointer` fields).

Add rules with `segmently-modules code-map add` (the preferred way): it APPENDS one rule to the team
config `.segmently-modules/config.toml` — one write, never a rewrite, so comments, the file mode, a
symlink and the file's `\n` / `\r\n` style stay — after re-parsing and validating the
combined text; `--dry-run` shows the block. It refuses (exit `2`, nothing written) when
`config.toml` does not exist (run `segmently-modules init`), when the id already exists in any layer (a
repeated id would deep-merge into that rule), when `--module` names no registry module or
child, and a `--pattern` without `{module}`. Editing or removing a rule is done by hand.

```bash
segmently-modules code-map add src --pattern "src/{module}/**"
segmently-modules code-map add catalog-search --glob "src/catalog/search/**" --module catalog/search --exclusive
```

| Key | Meaning |
|---|---|
| `id` | required, unique; a higher layer with the same id deep-merges into the rule |
| `pattern` | a glob with a `{module}` segment: `{module}` captures ONE path segment and must name a top-level module (`src/{module}/**`, `app/repositories/{module}.py`) |
| `globs` | a list of globs routed to `module` |
| `module` | required with `globs`: a top-level module or a child (`parent/child`), never empty; with a `pattern` it overrides the capture |
| `exclusive` | `true`: a file this rule matches is mapped ONLY by the exclusive rules that match it — other rules skip the file (docs and `code_pointer` mapping are unaffected). An exclusive rule wins only over non-exclusive rules: two exclusive rules that route one file to different modules are still an MS053 overlap |
| `shared` | `true`: the files this rule routes belong to its module AND to the modules other rules route them to, on purpose — a feature module and the service that ships it; both keep the file (drift fires for both) and MS053 does not report the overlaps of this rule — with any other rule, so keep a shared rule's globs narrow. `exclusive` and `shared` in one rule are refused (`code-map add --shared` writes it) |

A `pattern` MUST contain a literal `{module}` segment — even when `module` is also set (which
then overrides the value the segment would have captured, per the row above). `pattern =
"docs/**"` with `module = "tasks"` is refused (exit `2`) with the fix spelled out:
`code_map.<id>: pattern "docs/**" has no {module} segment — for a fixed module use globs =
["docs/**"] and module = "tasks"` (`module = "NAME"` when the rule has none). An empty
`module = ""` is refused too (`module must be a non-empty module or parent/child name`).

`segmently-modules code-map list` prints the effective rules (every layer merged; `--module TARGET` keeps
the ones that route files to TARGET) and `segmently-modules code-map files TARGET` every repository file
that maps to TARGET with how it maps (`docs`, `code_pointer:<field>`, `code_map:<id>`) — the
resolved file list that `code_globs` is not. `--source-only` keeps the TARGET's source files: those
that map to it by more than `docs` and match no test glob ([`[tests]`](#tests)); `--paths` prints
one repository-relative path per line, sorted, without `via` (no file: no output, exit `0`;
with `--json` it is refused, exit `2`). Without the two flags the output is unchanged.

```bash
segmently-modules code-map files catalog --source-only --paths
```

The `id` deep-merge is checked per layer, not after merging: each layer is validated on its own,
so an override that repeats only `id` (or `id` + `exclusive`) is refused with "needs a pattern or
globs" — a higher layer overriding an existing rule must repeat `pattern` or `globs` (and
`module`) too, not just the key it changes.

A rule needs `pattern` or `globs`. Glob syntax: `**` any path (also across `/`), `*` any
characters within one segment, `?` one character. `**/` needs at least one directory to match:
`**/*.md` does not match a root-level `README.md` (there is no `/` before it) — to include root
files too, list both (`*.md` and `**/*.md`). A rule whose `module` names no registry module or
child maps nothing and is reported as MS052 — a config-level finding (module `*`, like MS021)
that only plain `segmently-modules lint` shows; `lint --changed` narrows to the changed modules and drops
it — run `segmently-modules ci` (or plain `segmently-modules lint --fail-on warning`) to catch it: `segmently-modules ci`
already runs plain lint at `[ci] fail_on` (default `warning`), unlike plain `lint`'s own
default `fail_on = "error"`, which exits 0 on a warning-level finding like MS052. `show` /
`context` list each target's rules as `code_globs` (a
pattern's `{module}` filled in) — routing rules, not a file list; for the files a real change
touches, use `discover --files` / `sync --dry-run --files` instead.

A `{module}` capture that names no registry module (`app/repositories/base.py` under
`pattern = "app/repositories/{module}.py"`) routes nothing for that file: the file stays
unmapped unless another rule, a `code_pointer` field or its docs location maps it — it is not
"claimed" by the rule, even an `exclusive` one. `coverage` lists it as unmapped and
`discover --files` prints it as `file      <path> -> (no module)`.

## `[tests]`

Which files are tests. Only `code-map files TARGET --source-only` reads it: it leaves these files
out, as it leaves out the docs, so an agent gets the module's source files alone.

| Key | Default | Meaning |
|---|---|---|
| `globs` | the built-in list below | globs of test files (the `[[code_map]]` glob syntax). A layer's list is ADDED to the built-in list and to the lower layers' lists — it never removes a built-in glob. Anything but a list of non-empty strings is refused (exit `2`, naming the file and `[tests] globs`) |

The built-in globs list each form at the root and below a directory, because `**/` needs at least
one directory before it: `__tests__/**`, `**/__tests__/**`, `tests/**`, `**/tests/**`, `test/**`,
`**/test/**`, `*.test.*`, `**/*.test.*`, `*.spec.*`, `**/*.spec.*`, `test_*.py`, `**/test_*.py`,
`*_test.*`, `**/*_test.*`. A glob of yours follows the same rule: `**/fixtures/**` leaves out
`src/fixtures/x` but not a root-level `fixtures/x`; add `fixtures/**` as well.

```toml
[tests]
globs = ["fixtures/**", "**/fixtures/**"]   # added to the built-in globs: at the root and below
```

## `[[hooks.post_sync]]`

Commands `segmently-modules sync` runs after it maps a change (skipped with `--dry-run`).

| Key | Default | Meaning |
|---|---|---|
| `id` | required | letters, digits, `.`, `_`, `-` |
| `run` | required | argv list; items starting with `./` or `../` resolve against the declaring pack's directory (team and user hooks: the root) |
| `enabled` | `true` | `false` disables a hook declared by a lower layer |
| `required` | `false` | a failing required hook makes `sync` exit 1 |
| `timeout_s` | `60` | seconds |

A hook runs in the root with the event as JSON on stdin
(`{changed_modules, changed_files, diff_range}`) and `SEGMENTLY_MODULES_ROOT`, `SEGMENTLY_MODULES_EVENT`,
`SEGMENTLY_MODULES_HOOK_ID`, `SEGMENTLY_MODULES_RUN_ID` in its environment. It may print
`{"proposals": [{op, module, field|doc, value, reason}], "messages": ["…"]}`; the proposals are
validated like `segmently-modules propose` and queued under agent `hook-<id>`. A crash, a timeout or
garbage output fails that hook alone. A hook reads a changed module's docs and its declared
fields with `segmently-modules show <module> --json` (`read`, `fields`) instead of parsing the registry.

A hook is a command the repository or a pack commits: it runs with your environment, the agent
variables included — in a repository you do not trust, `sync --dry-run` runs none.

## Packs

A pack is a directory `.segmently-modules/packs/<id>/` with a `pack.toml`: a reusable bundle of config for
a stack or a team. Meta keys: `id` (default: the directory name), `version`, `priority`
(default `50`; a LOWER number takes precedence over other packs), `requires`, `description`,
`skills`, `agents`. Every other key is a config layer, like `config.toml`: a pack may declare
`[roles.*]`, `[fields.*]`, `[[code_map]]`, `[[hooks.post_sync]]`, `[registry]`, `[paths]` and
the rest. A pack's roles, fields and hooks record the pack as their `owner`; a pack may ship
templates under `templates/` (`MODULE.md`, `roles/<role>.md`) and hook scripts next to its
`pack.toml`. The team config overrides every pack.

A pack's agent skills are `[skills.<id>]` tables (the `skills` meta key — never merged into the
config): `path` (required, the skill directory relative to the pack: a `SKILL.md` in the Agent
Skills format plus any other files) and `reads_roles` (optional, a list of role names). A
malformed table is a config error naming the `pack.toml`; when two packs declare one skill id,
the higher-precedence pack's skill wins. `segmently-modules packs new ID --role NAME --skill NAME`
scaffolds a pack, `segmently-modules packs list` lists the installed ones and `segmently-modules packs sync --agent
claude --agent codex` copies every skill to `.claude/skills/<skill>/` and
`.agents/skills/<skill>/` (the `[packs] agents` list when no `--agent` is given). `segmently-modules eject
SKILL` copies a skill to `.segmently-modules/overrides/skills/SKILL/` for the team to own: `packs sync`
then materializes it from that copy and the pack never overwrites it — the whole workflow is in
[writing-a-pack.md](writing-a-pack.md).

## Lint codes

`lint` checks the registry, fields, docs and config; `lint --changed` narrows the report to the
modules a change touches and adds the drift checks. Config-level findings carry module `*`
(MS021, MS052, MS053, MS056 and the pack checks MS06x) — `lint --changed` drops them along with every other finding outside the
touched modules, so they show up ONLY in plain `segmently-modules lint` (and `segmently-modules ci`). A CI gate built only on `lint --changed`
never sees a shared-keyword note (MS021, severity `info` — report-only, it never fails a gate at
any `--fail-on` setting) or a typo'd `[[code_map]]` rule (MS052, severity `warning`); `segmently-modules ci`
catches both without a separate plain `lint` call, since its default `[ci] fail_on` is
`warning` — a gate that runs plain `segmently-modules lint` with no `--fail-on` override never actually
fails on it, because plain `lint`'s own default is `fail_on = "error"`.

| Code | Severity | Finding |
|---|---|---|
| MS001 | error | a required field is missing |
| MS002 | error | an entry's `name` differs from its registry key |
| MS003 | error | `status` not in `[registry] statuses` |
| MS004 | error | a `context_files` path is missing on disk (or not a string) |
| MS005 | error | a registered `*.md` doc holds NUL bytes or is not valid UTF-8 (damaged); path = the doc. The doc checks (MS005, MS041–MS043) read only `*.md` / `*.markdown` paths inside the root — an image or a source file listed in `context_files` is never read as a doc, and a path outside the root never at all |
| MS006 | error | `related_modules[].relation` not in `[registry] relations` |
| MS007 | error | a relation without a `description` |
| MS008 | error | a relation without a `module` target |
| MS009 | error | a relation's target module is not in the registry |
| MS010 | error | a relation's target child is not a child of that module |
| MS011 | error | a deprecated field is present |
| MS012 | warning | an undeclared field is present |
| MS013 | error | a value does not match its field type (or an entry is not an object, or a `context_files.roles` value is neither a doc path, a list of doc paths nor a not-needed mark: `false` or `{"skip": "<note>"}`) |
| MS014 | error | a directory under `modules_dir` is neither registered nor a pointer stub (dot-directories are never modules and are skipped) |
| MS015 | warning | `context_files.roles` names a role that is not configured |
| MS018 | warning | a module's (or child's) `context_files` has no `universal` doc — another doc key in its place (`module_md`) is read as an extra doc, so `show` lists no module doc and the size checks (MS030/MS031), the components table (MS040) and the critical rules never see it; the message names the other doc keys |
| MS016 | warning | a `*.md` in a module's (or child's) `roles/` directory that no registry entry names — agents never load it; the message names the role its file name reads as (the same name, or one starting with it: `ARCHITECTURE.md` → `architect`) and how to register it; `*.legacy.md` never counts |
| MS017 | info | the `*.md` files directly in a module's (or child's) directory that no registry entry names, one finding per module (path = the directory; nested directories such as `plans/` are not looked at; `*.legacy.md` never counts) |
| MS020 | info | more keywords than `[budgets] keywords_soft` |
| MS021 | info | a keyword shared by `[budgets] keyword_shared_warn` modules or more (plain `lint` only) |
| MS022 | warning | an empty keyword (matches every task) |
| MS023 | info | a keyword is a generic word (`[create] generic_keywords` and the built-in list, any form under `[match] normalize`; never a word of the module's own name) |
| MS030 | warning | `MODULE.md` longer than `module_doc_split_signal` |
| MS031 | error | `MODULE.md` longer than `module_doc_hard_stop` |
| MS032 | warning | a role doc longer than `role_doc_max` |
| MS040 | warning | a backticked path in the components table is missing on disk |
| MS041 | `link_severity` | a Markdown link (inline, image or reference definition — never a footnote `[^1]:`, never inside code or an HTML comment) in a registered doc whose target is missing on disk — relative to the doc, a leading `/` from the root, and a path that does not start with `./` or `../` also counts when it exists from the root (agents read `src/x.ts` so); a URL, a placeholder (`{`, `<`, `*`, `…`) and a path outside the repository are not checked — unless the path without its leading `../` exists from the root, which the message names ("fix the ../ depth", for one `../` too few or too many); path = the doc |
| MS042 | info | a link's `#anchor` names no heading of its target `.md` (GitHub's heading anchors — headings in block quotes and list items too, entities decoded, emphasis underscores dropped —, `-1`, `-2` for repeats, `{#id}` and HTML `id` / `name`; case-insensitive; a `#L12` line anchor is not checked) |
| MS043 | info | backticked repository paths outside fenced code and outside the components table that are missing on disk, one finding per module: a path whose first segment is a top-level directory holding files git does not ignore, found neither from the root, nor next to the doc, nor under the module's code directories (its `[[code_map]]` globs and code pointers); build output (`dist/`, `build/`, `node_modules/`, `coverage/`, …) is never checked; plain `lint` only (it needs the repository's file list) |
| MS050 | `drift_severity` | `--changed`: a module's code changed but none of its docs; a changed doc of the target, of its parent or of one of its children counts (so an update of a child's doc clears its parent), never a sibling's; a doc whose change sits inside its critical-rules section (a rules index written or kept) does not count |
| MS051 | error | `--changed`: a frozen `*.legacy.md` snapshot was modified or deleted |
| MS052 | warning | a `[[code_map]]` rule's `module` is not a registry module or child (plain `lint` only) |
| MS053 | `overlap_severity` | two `[[code_map]]` rules route the same file to two different modules, neither rule `shared = true` (plain `lint` only; see below) |
| MS054 | info | an `active` module that maps no code file — none of its files or its children's comes through a `[[code_map]]` rule or a code pointer (docs never count), so drift never fires for it — unless `[coverage] doc_only` names it; only with a `[[code_map]]` rule, inside git, plain `lint` only; `next` lists these modules in one `no-code` item |
| MS056 | warning | `[coverage] doc_only` names a module that is not in the registry, or a child (it takes top-level modules: a module counts its children's code) |
| MS060 | warning | an unknown key in a pack's `pack.toml` — at the top level (neither a meta key nor a config section), in a `[roles.<name>]` or in a `[skills.<id>]` table (plain `lint` only) |
| MS061 | error | a pack role's `template` file does not exist in the pack, or resolves outside the pack directory (plain `lint` only) |
| MS062 | error | a pack skill, or an ejected copy in `<config_dir>/overrides/skills/<skill>/` (the one `packs sync` then copies), agents cannot load: its `path` does not exist, is not a directory or is outside the pack; it contains a symlink; it has no `SKILL.md`; the front matter is missing, has no `name` or one that differs from the skill id, has an unquoted `name` / `description` value that agents' strict YAML loaders reject (a `: ` inside, a trailing `:`, or a leading `@`, `%`, `*`, `&`, `!`, `[`, `{` or backtick), or has no `description` of 1–1024 characters; or a file it names — each `references/<file>` written in its `SKILL.md` or in one of its `references/*.md` files (one level of chaining) — does not exist or lies outside the skill directory (a name holding `*`, `?` or `[` is a pattern and is not checked — `references/route-*`, `references/[ab].md`; the message names the naming file, whose path is the finding's; `packs sync` and `eject` do not look at names; `argument-hint` and `arguments` are accepted in any form) (plain `lint` only) |
| MS063 | warning / info | an ejected skill (`segmently-modules eject`) is behind its pack — the pack's files, or a repository pack's version, changed since the eject (a built-in pack's version is the engine's: an upgrade alone does not count) (warning; `segmently-modules eject <skill> --diff` shows the change); a pack file it cannot read (warning, naming the file); a symlink at the ejected path (warning: it is in the way, never an ejected copy — remove it) — or no pack declares it any more (info: the ejected copy is its only source) (plain `lint` only) |
| MS064 | warning | a skill's `reads_roles` names a role no layer configures, or a disabled one (plain `lint` only) |
| MS065 | warning | two packs declare the same skill id: the lower-precedence one is shadowed (plain `lint` only) |
| MS066 | info | a repository pack takes a built-in pack's id (`core`, `qa`, `ui`) and replaces that built-in pack, enabled or not; info never fails a gate (plain `lint` only) |
| MS067 | info | `[packs] builtin_delivery = "plugin"` and an agent directory still holds a copy `packs sync` made of a built-in skill (its `.segmently-modules-managed` marker): the plugin provides the skill, so the agent sees it twice — `segmently-modules packs sync` removes an unedited copy (the message says `--agent <agent>` when `[packs] agents` leaves that directory out; an edited copy or an ejected skill's copy stays a conflict); path = the copy's directory; info never fails a gate (plain `lint` only) |
| MS068 | warning | a pack skill's `SKILL.md`, or one `*.md` file directly in its `references/` (an ejected copy's too), is longer than `[budgets] skill_split_signal` characters: `<skill>[/<file>]: N characters > skill split signal S — route its scenarios or split the skill`; path = the file (plain `lint` only) |
| MS069 | warning | a pack's `SKILL.md` files together (never `references/`, never ejected copies) are longer than `[budgets] pack_split_signal` characters: `pack '<pack>': N characters of skills > pack split signal P — route, split a skill out, or split the pack`; path = its `pack.toml` (plain `lint` only) |
| MS070 | — (info) | an entry of a doc's critical-rules section cites `doc:line` that names no doc, or a line past that doc's end: a citation its writer did not re-derive, or text that moved since; a path from the repository root (`modules/…`), else from the citing doc's module directory (`roles/qa.md:12`) |
| MS071 | — (warning) | an indexed doc (an `Indexed:` line) whose critical-rules section has more entries than `[budgets] rules_index_entries` (25); a hand-written section is never flagged |

MS053 compares every pair of `[[code_map]]` rules over the repository's files (git-tracked +
new, not ignored; `[coverage]` filters do not apply) after `exclusive` precedence: a pair is
reported once when it routes at least one file to two different targets where neither is the
other's parent (`catalog` + `catalog/search` is fine; `catalog/search` + `catalog/admin`, or
`orders` + `db`, is an overlap; two rules routing to the same module are not). The message
names both rules, the target each gives the first such file, the file count and that first
file (`[[code_map]] 'db' (-> db) and 'repositories' (-> orders) both map 4 file(s), e.g.
app/repositories/orders.py — mark the more specific rule exclusive = true or narrow its
globs`). The check runs only with two rules or more and inside a git work tree (otherwise it is
skipped silently). Lint asks git at most once per run whether the root is a work tree and once
for the file list, shared by MS043, MS053 and MS054; without a `[[code_map]]` rule and without
a backticked repository path in the docs it runs no git command at all. Only the rules are compared:
a file's docs location and `code_pointer` fields never make a pair. Plain `lint` and the lint
step of `segmently-modules ci` compute it; `lint --changed` does not (it would drop the finding anyway).
