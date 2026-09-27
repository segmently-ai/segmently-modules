# Writing a pack

> Start here: [README](../README.md). Every config key: [configuration.md](configuration.md).
> Every verb's JSON: [cli-contract.md](cli-contract.md).

A pack bundles what a team (or a stack) adds to modsys: roles with their doc templates, agent
skills that read those role docs, and any config layer — fields, `[[code_map]]` rules, hooks. A
pack lives in the repository at `.modsys/packs/<id>/` and is committed with it.

## Layout

```text
.modsys/packs/team/
├── pack.toml                  # meta keys, [roles.*], [skills.*], any config section
├── roles/reviewer.md          # the template of a role's per-module doc
├── templates/                 # optional: MODULE.md or roles/<role>.md for every module
└── skills/api-review/         # an agent skill (the Agent Skills format)
    ├── SKILL.md               # front matter: name (= the directory name) and description
    └── references/…           # anything else the skill needs (scripts, references)
```

## `pack.toml`

```toml
id = "team"                      # default: the directory name
version = "0.1.0"
priority = 50                    # a LOWER number wins over other packs (default 50)
description = "Team review conventions"

[roles.reviewer]
order = 100                      # sort order in show / context
standard = false                 # true: `modsys create` writes roles/reviewer.md for every module
description = "What a reviewer checks in a module"
template = "roles/reviewer.md"   # relative to the pack directory

[skills.api-review]
path = "skills/api-review"       # the skill directory, relative to the pack directory
reads_roles = ["reviewer"]       # the roles whose module docs the skill reads
```

- **Meta keys:** `id`, `version`, `priority`, `requires`, `description`, `skills`, `agents`.
  Every other top-level key is a config layer, exactly like `.modsys/config.toml`
  ([configuration.md](configuration.md)); the team config overrides every pack.
- **`[roles.<name>]`:** `order`, `enabled`, `standard`, `description`, `applies_when`,
  `template`. A role name is lowercase letters, digits and `_`, words joined by `-`.
- **`[skills.<id>]`:** `path` (required) and `reads_roles` (a list of role names, default
  `[]`). The id follows the Agent Skills name rule — 1–64 characters, lowercase letters and
  digits, words joined by single hyphens — and equals the `name` in the skill's `SKILL.md`. A
  malformed `[skills.<id>]` table (not a table, `path` missing or not a string, `reads_roles` not
  a list of strings, an id that breaks the rule) is a config error: every verb exits 2 naming
  the `pack.toml`. When two packs declare the same skill id, the higher-precedence pack's
  skill is the one every verb uses.

## Role templates

A role's template is rendered by `modsys create` into `modules/<module>/roles/<role>.md` (or a
child's `…/submodules/<child>/roles/<role>.md`). Placeholders: `${title}`, `${role}`,
`${role_description}`, `${name}`, `${description}`, `${status}`, `${keywords}`, `${parent}`.
`modsys templates list` shows which file wins for each role; the team can still override any
template with `modsys templates override roles/<role>.md`.

## Walkthrough

Scaffold a pack with one role and one skill that reads it:

```bash
modsys packs new team --role reviewer --skill api-review --description "Team review conventions"
```

It writes `.modsys/packs/team/pack.toml`, `roles/reviewer.md` and
`skills/api-review/SKILL.md`, and the pack is part of the config at once. Edit the role
template (what a reviewer checks) and the skill (its description and steps), then create a
module that has the role:

```bash
modsys create reviews --non-interactive --role reviewer \
  --description "Customer reviews of books: ratings, comments and moderation." \
  --keywords "review, rating, stars, comment, moderation"
modsys show reviews --role reviewer   # the reviewer doc of the module: what the skill reads
modsys templates list                 # roles/reviewer.md  role-template:team  .modsys/packs/team/roles/reviewer.md
modsys packs list                     # the pack, its role and its skill
```

## Lint

Plain `modsys lint` (and the lint step of `modsys ci`) checks every installed pack; the findings
carry module `*`, so `lint --changed` never shows them:

| Code | Severity | Finding |
|---|---|---|
| MS060 | warning | an unknown key in `pack.toml` (top level, `[roles.<name>]`, `[skills.<id>]`) — e.g. a typo like `standrad`, or `budget` / `consumed_by`, which are not role keys |
| MS061 | error | a role's `template` does not exist in the pack, or points outside it |
| MS062 | error | a skill agents cannot load (path, symlink, `SKILL.md` front matter) |
| MS064 | warning | `reads_roles` names a role no layer configures, or a disabled one |
| MS065 | warning | another pack with a higher precedence declares the same skill id |
