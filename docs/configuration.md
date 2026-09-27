# modsys configuration

Start with `modsys init`: it writes a commented starter `.modsys/config.toml` with a worked
example for the most-used sections below (it has none for `[budgets]`, `[match]`, `[lint]` or
`[roles.<name>]`). This page is the reference for every section and key.

## Layers

The effective config is merged from, lowest precedence first:

1. **engine defaults** — `modsys/defaults/config.toml` (shipped with the engine);
2. **packs** — `.modsys/packs/<id>/pack.toml`, lower `priority` wins (see [Packs](#packs));
3. **team config** — `.modsys/config.toml` (commit it);
4. **user config** — `.modsys/config.user.toml` (personal; git-ignore it).

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

`--config-dir DIR` points every verb at another config directory (default `<root>/.modsys`).

## `[paths]`

| Key | Default | Meaning |
|---|---|---|
| `modules_dir` | `"modules"` | where module directories live: `<modules_dir>/<name>/MODULE.md`, children under `<name>/submodules/<child>/` |
| `registry` | `"modules/registry.json"` | the registry file (the generated index in the per-module layout) |
| `registry_layout` | `"single"` | `"single"`: one registry file · `"per-module"`: `<modules_dir>/<name>/<module_entry>` per module plus a generated index (`modsys index split` converts, `modsys index build` regenerates) |
| `module_doc` | `"MODULE.md"` | a module's main doc |
| `module_entry` | `"module.json"` | a module's entry file in the per-module layout |
| `proposals_dir` | `".modsys/proposals"` | the proposals queue; `done/` keeps processed files |

## `[registry]`

| Key | Default | Meaning |
|---|---|---|
| `statuses` | `["active", "draft", "planned", "temporary"]` | allowed module `status` values (lint MS003; the writers refuse others) |
| `relations` | `["depends-on", "complements", "implemented-in", "shares-contract", "superseded-by"]` | allowed `related_modules[].relation` values (MS006) |
| `stub_pattern` | see note below | a regular expression; a module dir whose `MODULE.md` head matches is a pointer stub of a retired module |
| `dir_whitelist` | `[]` | directories under `modules_dir` that are not modules (no MS014) |
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

## `[match]`

Keyword routing used by `match`, `context` and `discover`.

| Key | Default | Meaning |
|---|---|---|
| `keyword_weight` | `3` | score per matched keyword |
| `combination_weight` | `2` | bonus per `required_combinations` group fully present in the text |
| `negative_weight` | `-5` | score per matched `negative_keywords` phrase |
| `min_score` | `3` | rows below this are dropped |
| `top` | `8` | at most this many rows (`--top` overrides) |

Matching is exact-token: a keyword or `negative_keywords` phrase must occur as a whole word (or
whole phrase) in the task text — case-insensitive, with no stemming and no plural/singular
normalization (`todo` does not match `todos` or `to-do`). Precisely: a boundary is enforced only
on an edge of the keyword that is itself a word character (letter, digit, `_`); a keyword that
starts or ends with a non-word character has NO boundary on that side and can still match inside
a longer token there — `.epub` matches inside `notebook.epub`, `c++` matches inside `c++17`. A
module with no matched keyword never gets a row, no matter what `negative_weight` alone would
score; a row below `min_score` is dropped even with matched keywords. When nothing reaches
`min_score`, `match` prints `no keyword matches (try rephrasing with domain terms, or use: list)` and
`context` prints `no module matched (try domain terms, or: modsys list)`; `discover --task` with
no match simply omits the module (no message). Register every form a task is likely to use
(singular AND plural, synonyms) rather than relying on this to generalize.

Near misses: when nothing reaches `min_score`, `context` (JSON key `near_misses`, and its text)
and `match` (text only; `match --json` stays the plain row list) list the modules and children
that almost matched — a keyword that is not an exact hit but has a word sharing its first
letters with a word of the task (`reminder` ~ `reminders`, `schedule` ~ `scheduling`: the first
5 letters, or all of the shorter word; both words at least 4 letters, so `api` and `tag` match
exactly only), or exact hits whose score a negative keyword pulled below `min_score`. The text
ends with `re-run with the module's own keyword in the task text, or read it directly: modsys
show <module>`; `modsys show <module>` prints the module's keywords on its `keys` line.

## `[lint]`

| Key | Default | Meaning |
|---|---|---|
| `fail_on` | `"error"` | `error` · `warning` · `never`: the lowest severity that makes `lint` exit 1 (`--fail-on` overrides) |
| `component_table_heading` | `"EXISTING Components"` | the `MODULE.md` section whose table rows lint checks for backticked paths (MS040) |
| `drift_severity` | `"warning"` | severity of MS050 (`info`, `warning` or `error`) |
| `overlap_severity` | `"warning"` | severity of MS053 (`info`, `warning` or `error`) |

## `[create]`

| Key | Default | Meaning |
|---|---|---|
| `min_keywords` | `5` | distinct keywords a top-level module needs (a child needs 1) |
| `description_min` | `20` | shortest description, in characters |
| `description_max` | `200` | longest description |
| `default_status` | `"planned"` | status of a new module when none is given |

## `[coverage]`

`modsys coverage` counts every git-tracked file plus every new file git does not ignore,
relative to the root. The modules dir, the config dir, the registry file and its `.lock`, the
proposals dir (`[paths]`) and dotfiles or dot-directories at any level never count. `share` is mapped / total rounded down to 3 decimals, so it never overstates;
`--fail-under PCT` compares the reported percent (`share` × 100, one decimal).

| Key | Default | Meaning |
|---|---|---|
| `include` | `["**"]` (built in) | globs a file must match to count; a team `include` replaces the built-in `**`; `include = []` is refused (it would count no file — omit `include` to count every file) |
| `exclude` | `[]` | globs that never count (generated code, vendored files, docs) |

## `[ci]`

`modsys ci` — one gate: `lint` (plain), `drift` (`lint --changed` against `base`) and
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
| `agents` | unset | the agents `modsys packs sync` writes pack skills for when no `--agent` flag is given: `claude` (`.claude/skills/`) and / or `codex` (`.agents/skills/`); any other name is refused (exit 2 naming the file). Like every array, a higher layer ADDS to a lower one's list; `--agent` flags replace it |

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

`create` resolves a template (first hit wins): `<config_dir>/overrides/templates/<path>` →
the role's own pack `template` → `<pack>/templates/<path>` in pack precedence order → the
engine's defaults: `MODULE.md`, one template per standard role (`roles/developer.md`,
`roles/qa.md`, `roles/po.md`, `roles/architect.md` — each with a few headed sections for that
audience) and the generic `roles/_role.md` for any other role. `agents-md.md` — the text of the
managed block for agent instruction files — resolves the same way. Templates use `${name}`,
`${title}`, `${description}`, `${status}`, `${keywords}`, `${parent}`, `${role}`,
`${role_description}`.

`modsys templates list` prints every template with the layer that wins (`override`,
`role-template:<pack>`, `pack:<pack>`, `engine`, or `engine-fallback` for a role rendered from
`roles/_role.md`) and its file. `modsys templates override roles/qa.md` copies the winning
template to `.modsys/overrides/templates/roles/qa.md` once; edit that copy — it wins from then
on (the engine never rewrites it, and a later upstream change to the template does not reach it).

## `[fields.<name>]`

Every registry field beyond the core ones is declared once; the declaration drives validation
(lint, writers), the JSON Schema (`modsys schema`), `show` output and `create` prompts. Core
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
| `sync_hint` | `""` | informational: how the field follows code changes |

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

Add rules with `modsys code-map add` (the preferred way): it APPENDS one rule to the team
config `.modsys/config.toml` — one write, never a rewrite, so comments, the file mode, a
symlink and the file's `\n` / `\r\n` style stay — after re-parsing and validating the
combined text; `--dry-run` shows the block. It refuses (exit `2`, nothing written) when
`config.toml` does not exist (run `modsys init`), when the id already exists in any layer (a
repeated id would deep-merge into that rule), when `--module` names no registry module or
child, and a `--pattern` without `{module}`. Editing or removing a rule is done by hand.

```bash
modsys code-map add src --pattern "src/{module}/**"
modsys code-map add catalog-search --glob "src/catalog/search/**" --module catalog/search --exclusive
```

| Key | Meaning |
|---|---|
| `id` | required, unique; a higher layer with the same id deep-merges into the rule |
| `pattern` | a glob with a `{module}` segment: `{module}` captures ONE path segment and must name a top-level module (`src/{module}/**`, `app/repositories/{module}.py`) |
| `globs` | a list of globs routed to `module` |
| `module` | required with `globs`: a top-level module or a child (`parent/child`), never empty; with a `pattern` it overrides the capture |
| `exclusive` | `true`: a file this rule matches is mapped ONLY by the exclusive rules that match it — other rules skip the file (docs and `code_pointer` mapping are unaffected) |

A `pattern` MUST contain a literal `{module}` segment — even when `module` is also set (which
then overrides the value the segment would have captured, per the row above). `pattern =
"docs/**"` with `module = "tasks"` is refused (exit `2`) with the fix spelled out:
`code_map.<id>: pattern "docs/**" has no {module} segment — for a fixed module use globs =
["docs/**"] and module = "tasks"` (`module = "NAME"` when the rule has none). An empty
`module = ""` is refused too (`module must be a non-empty module or parent/child name`).

`modsys code-map list` prints the effective rules (every layer merged; `--module TARGET` keeps
the ones that route files to TARGET) and `modsys code-map files TARGET` every repository file
that maps to TARGET with how it maps (`docs`, `code_pointer:<field>`, `code_map:<id>`) — the
resolved file list that `code_globs` is not.

The `id` deep-merge is checked per layer, not after merging: each layer is validated on its own,
so an override that repeats only `id` (or `id` + `exclusive`) is refused with "needs a pattern or
globs" — a higher layer overriding an existing rule must repeat `pattern` or `globs` (and
`module`) too, not just the key it changes.

A rule needs `pattern` or `globs`. Glob syntax: `**` any path (also across `/`), `*` any
characters within one segment, `?` one character. `**/` needs at least one directory to match:
`**/*.md` does not match a root-level `README.md` (there is no `/` before it) — to include root
files too, list both (`*.md` and `**/*.md`). A rule whose `module` names no registry module or
child maps nothing and is reported as MS052 — a config-level finding (module `*`, like MS021)
that only plain `modsys lint` shows; `lint --changed` narrows to the changed modules and drops
it — run `modsys ci` (or plain `modsys lint --fail-on warning`) to catch it: `modsys ci`
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

## `[[hooks.post_sync]]`

Commands `modsys sync` runs after it maps a change (skipped with `--dry-run`).

| Key | Default | Meaning |
|---|---|---|
| `id` | required | letters, digits, `.`, `_`, `-` |
| `run` | required | argv list; items starting with `./` or `../` resolve against the declaring pack's directory (team and user hooks: the root) |
| `enabled` | `true` | `false` disables a hook declared by a lower layer |
| `required` | `false` | a failing required hook makes `sync` exit 1 |
| `timeout_s` | `60` | seconds |

A hook runs in the root with the event as JSON on stdin
(`{changed_modules, changed_files, diff_range}`) and `MODSYS_ROOT`, `MODSYS_EVENT`,
`MODSYS_HOOK_ID`, `MODSYS_RUN_ID` in its environment. It may print
`{"proposals": [{op, module, field|doc, value, reason}], "messages": ["…"]}`; the proposals are
validated like `modsys propose` and queued under agent `hook-<id>`. A crash, a timeout or
garbage output fails that hook alone.

## Packs

A pack is a directory `.modsys/packs/<id>/` with a `pack.toml`: a reusable bundle of config for
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
the higher-precedence pack's skill wins. `modsys packs new ID --role NAME --skill NAME`
scaffolds a pack, `modsys packs list` lists the installed ones and `modsys packs sync --agent
claude --agent codex` copies every skill to `.claude/skills/<skill>/` and
`.agents/skills/<skill>/` (the `[packs] agents` list when no `--agent` is given) — the whole
workflow is in [writing-a-pack.md](writing-a-pack.md).

## Lint codes

`lint` checks the registry, fields, docs and config; `lint --changed` narrows the report to the
modules a change touches and adds the drift checks. Config-level findings carry module `*`
(MS021, MS052, MS053 and the pack checks MS06x) — `lint --changed` drops them along with every other finding outside the
touched modules, so they show up ONLY in plain `modsys lint` (and `modsys ci`). A CI gate built only on `lint --changed`
never sees a shared-keyword note (MS021, severity `info` — report-only, it never fails a gate at
any `--fail-on` setting) or a typo'd `[[code_map]]` rule (MS052, severity `warning`); `modsys ci`
catches both without a separate plain `lint` call, since its default `[ci] fail_on` is
`warning` — a gate that runs plain `modsys lint` with no `--fail-on` override never actually
fails on it, because plain `lint`'s own default is `fail_on = "error"`.

| Code | Severity | Finding |
|---|---|---|
| MS001 | error | a required field is missing |
| MS002 | error | an entry's `name` differs from its registry key |
| MS003 | error | `status` not in `[registry] statuses` |
| MS004 | error | a `context_files` path is missing on disk (or not a string) |
| MS006 | error | `related_modules[].relation` not in `[registry] relations` |
| MS007 | error | a relation without a `description` |
| MS008 | error | a relation without a `module` target |
| MS009 | error | a relation's target module is not in the registry |
| MS010 | error | a relation's target child is not a child of that module |
| MS011 | error | a deprecated field is present |
| MS012 | warning | an undeclared field is present |
| MS013 | error | a value does not match its field type (or an entry is not an object) |
| MS014 | error | a directory under `modules_dir` is neither registered nor a pointer stub |
| MS015 | warning | `context_files.roles` names a role that is not configured |
| MS020 | info | more keywords than `[budgets] keywords_soft` |
| MS021 | info | a keyword shared by `[budgets] keyword_shared_warn` modules or more (plain `lint` only) |
| MS022 | warning | an empty keyword (matches every task) |
| MS030 | warning | `MODULE.md` longer than `module_doc_split_signal` |
| MS031 | error | `MODULE.md` longer than `module_doc_hard_stop` |
| MS032 | warning | a role doc longer than `role_doc_max` |
| MS040 | warning | a backticked path in the components table is missing on disk |
| MS050 | `drift_severity` | `--changed`: a module's code changed but none of its docs |
| MS051 | error | `--changed`: a frozen `*.legacy.md` snapshot was modified or deleted |
| MS052 | warning | a `[[code_map]]` rule's `module` is not a registry module or child (plain `lint` only) |
| MS053 | `overlap_severity` | two `[[code_map]]` rules route the same file to two different modules (plain `lint` only; see below) |
| MS060 | warning | an unknown key in a pack's `pack.toml` — at the top level (neither a meta key nor a config section), in a `[roles.<name>]` or in a `[skills.<id>]` table (plain `lint` only) |
| MS061 | error | a pack role's `template` file does not exist in the pack, or resolves outside the pack directory (plain `lint` only) |
| MS062 | error | a pack skill agents cannot load: its `path` does not exist, is not a directory or is outside the pack; it contains a symlink; it has no `SKILL.md`; the front matter is missing, has no `name` or one that differs from the skill id, or no `description` of 1–1024 characters (plain `lint` only) |
| MS064 | warning | a skill's `reads_roles` names a role no layer configures, or a disabled one (plain `lint` only) |
| MS065 | warning | two packs declare the same skill id: the lower-precedence one is shadowed (plain `lint` only) |

MS053 compares every pair of `[[code_map]]` rules over the repository's files (git-tracked +
new, not ignored; `[coverage]` filters do not apply) after `exclusive` precedence: a pair is
reported once when it routes at least one file to two different targets where neither is the
other's parent (`catalog` + `catalog/search` is fine; `catalog/search` + `catalog/admin`, or
`orders` + `db`, is an overlap; two rules routing to the same module are not). The message
names both rules, the target each gives the first such file, the file count and that first
file (`[[code_map]] 'db' (-> db) and 'repositories' (-> orders) both map 4 file(s), e.g.
app/repositories/orders.py — mark the more specific rule exclusive = true or narrow its
globs`). The check runs only with two rules or more and inside a git work tree (otherwise it is
skipped silently; without rules `lint` runs no git command at all). Only the rules are compared:
a file's docs location and `code_pointer` fields never make a pair. Plain `lint` and the lint
step of `modsys ci` compute it; `lint --changed` does not (it would drop the finding anyway).
