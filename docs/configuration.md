# modsys configuration

Start with `modsys init`: it writes a commented starter `.modsys/config.toml` with a worked
example for every section below. This page is the reference for every section and key.

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
(`enabled = false`) instead. Unknown keys and sections are accepted (forward compatibility);
known keys are type-checked, and a wrong type is an error naming the file.

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
| `stub_pattern` | `'status:?\**\s*\**(retired\|merged\|migrated\|superseded)'` | a regular expression; a module dir whose `MODULE.md` head matches is a pointer stub of a retired module |
| `dir_whitelist` | `[]` | directories under `modules_dir` that are not modules (no MS014) |
| `updated_at_path` | `""` | e.g. `"metadata.last_updated"`: stamped with the UTC time on every registry write; empty = off |

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

## `[lint]`

| Key | Default | Meaning |
|---|---|---|
| `fail_on` | `"error"` | `error` · `warning` · `never`: the lowest severity that makes `lint` exit 1 (`--fail-on` overrides) |
| `component_table_heading` | `"EXISTING Components"` | the `MODULE.md` section whose table rows lint checks for backticked paths (MS040) |
| `drift_severity` | `"warning"` | severity of MS050 (`info`, `warning` or `error`) |

## `[create]`

| Key | Default | Meaning |
|---|---|---|
| `min_keywords` | `5` | distinct keywords a top-level module needs (a child needs 1) |
| `description_min` | `20` | shortest description, in characters |
| `description_max` | `200` | longest description |
| `default_status` | `"planned"` | status of a new module when none is given |

## `[coverage]`

`modsys coverage` counts every git-tracked file plus every new file git does not ignore,
relative to the root. The modules dir, the config dir and dotfiles or dot-directories at any
level never count. `share` is mapped / total rounded down to 3 decimals, so it never overstates;
`--fail-under PCT` compares the reported percent (`share` × 100, one decimal).

| Key | Default | Meaning |
|---|---|---|
| `include` | `["**"]` (built in) | globs a file must match to count; a team `include` replaces the built-in `**` |
| `exclude` | `[]` | globs that never count (generated code, vendored files, docs) |

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
engine's defaults (`MODULE.md`, `roles/_role.md`). Templates use `${name}`, `${title}`,
`${description}`, `${status}`, `${keywords}`, `${parent}`, `${role}`, `${role_description}`.

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

| Key | Meaning |
|---|---|
| `id` | required, unique; a higher layer with the same id deep-merges into the rule |
| `pattern` | a glob with a `{module}` segment: `{module}` captures ONE path segment and must name a top-level module (`src/{module}/**`, `app/repositories/{module}.py`) |
| `globs` | a list of globs routed to `module` |
| `module` | required with `globs`: a top-level module or a child (`parent/child`); with a `pattern` it overrides the capture |
| `exclusive` | `true`: a file this rule matches is mapped ONLY by the exclusive rules that match it — other rules skip the file (docs and `code_pointer` mapping are unaffected) |

A rule needs `pattern` or `globs`. Glob syntax: `**` any path (also across `/`), `*` any
characters within one segment, `?` one character. A rule whose `module` names no registry
module or child maps nothing and is reported as MS052. `show` / `context` list each target's
rules as `code_globs` (a pattern's `{module}` filled in) — routing rules, not a file list.

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

## Lint codes

`lint` checks the registry, fields, docs and config; `lint --changed` narrows the report to the
modules a change touches and adds the drift checks.

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
| MS021 | info | a keyword shared by `[budgets] keyword_shared_warn` modules or more |
| MS022 | warning | an empty keyword (matches every task) |
| MS030 | warning | `MODULE.md` longer than `module_doc_split_signal` |
| MS031 | error | `MODULE.md` longer than `module_doc_hard_stop` |
| MS032 | warning | a role doc longer than `role_doc_max` |
| MS040 | warning | a backticked path in the components table is missing on disk |
| MS050 | `drift_severity` | `--changed`: a module's code changed but none of its docs |
| MS051 | error | `--changed`: a frozen `*.legacy.md` snapshot was modified or deleted |
| MS052 | warning | a `[[code_map]]` rule's `module` is not a registry module or child |
