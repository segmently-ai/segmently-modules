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

Copy the skills where the agents read them — Claude Code from `.claude/skills/<skill>/`, Codex
from `.agents/skills/<skill>/` — and commit the copies:

```bash
modsys packs sync --agent claude --agent codex   # created  claude  .claude/skills/api-review  (team 0.1.0) …
git add .claude/skills .agents/skills && git commit -m "skills: api-review"
modsys packs sync --check --agent claude --agent codex   # in CI: exit 1 when a copy is stale
```

Put the agents in the team config once (`[packs] agents = ["claude", "codex"]`) and a bare
`modsys packs sync` does the same. Each copy holds a `.modsys-managed` marker (the pack, its
version, the source and a hash per file). Edit the skill in the pack and run `packs sync` again:
the copies are `updated`; a file the pack no longer has is deleted; a skill the pack no longer
declares is `removed` from the agents' directories.

## Conflicts

`packs sync` never overwrites what it does not manage. A skill is a `conflict` — reported, left
untouched, exit 1 — when its directory has no marker (a skill written by hand), the marker names
another pack, a managed file was edited or deleted in the agent's directory, or a new pack file
would replace a file that is not managed. The other skills still sync. Resolve it by hand: revert
the local edit (`git checkout -- .claude/skills/api-review`) and sync again, or move a
hand-written skill away, or eject the skill (next section) when the team wants to own its
changes. A source agents cannot load (MS062) is `invalid` and never copied.

## Owning a skill: eject

When the team needs its own version of a pack skill (a skill from someone else's pack, or one
it wants to freeze), eject it:

```bash
modsys eject api-review                  # copies it to .modsys/overrides/skills/api-review/
modsys packs sync                        # the agents' copies now come from the ejected copy
modsys eject api-review --diff           # later: what the pack changed since the eject
```

Edit the ejected copy and run `packs sync`: both agents get it (`updated`, `source` `ejected`).
The pack never overwrites an ejected skill, even at a new version; plain `modsys lint` then
reports MS063 — `ejected skill 'api-review' is behind pack 'team' (ejected from 0.1.0, pack is
now 0.2.0)` — and `eject api-review --diff` shows the upstream change as a unified diff, so the
team can take what it wants by hand. If the pack drops the skill, the ejected copy stays the
skill's only source (MS063 info). To go back to the pack's version, delete
`.modsys/overrides/skills/api-review/` and run `modsys packs sync`.

## Tell the agents: the managed block

Agents read `CLAUDE.md` (Claude Code) and `AGENTS.md` (Codex). One command keeps a block there
that says how to use modsys in this repository, which roles exist and which skills the packs
add:

```bash
modsys agents-md --target CLAUDE.md --target AGENTS.md          # added / created
modsys agents-md --target CLAUDE.md --target AGENTS.md --check  # in CI: exit 1 when stale
```

The block sits between `<!-- modsys:begin v1 -->` and `<!-- modsys:end -->`; every byte outside
it is the team's and is never touched (a file without the markers gets the block appended after
one blank line). Run it again after adding a skill or a role: only the block changes. The text
comes from the `agents-md.md` template — `modsys templates override agents-md.md` gives the team
its own copy to edit. When `AGENTS.md` is a symlink to `CLAUDE.md`, the block is written once.

## Lint

Plain `modsys lint` (and the lint step of `modsys ci`) checks every installed pack; the findings
carry module `*`, so `lint --changed` never shows them:

| Code | Severity | Finding |
|---|---|---|
| MS060 | warning | an unknown key in `pack.toml` (top level, `[roles.<name>]`, `[skills.<id>]`) — e.g. a typo like `standrad`, or `budget` / `consumed_by`, which are not role keys |
| MS061 | error | a role's `template` does not exist in the pack, or points outside it |
| MS062 | error | a skill agents cannot load (path, symlink, `SKILL.md` front matter) |
| MS063 | warning / info | an ejected skill is behind its pack, or no pack declares it any more |
| MS064 | warning | `reads_roles` names a role no layer configures, or a disabled one |
| MS065 | warning | another pack with a higher precedence declares the same skill id |
