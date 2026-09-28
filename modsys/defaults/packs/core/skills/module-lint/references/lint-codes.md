# Lint codes: meaning and fix

Every code the `lint` and `ci` verbs report. **Safe** = a mechanical fix the skill may make;
**Ask** = a decision for the user (offer the options). Module `*` = a config-level finding.

| Code | Meaning | Fix |
|---|---|---|
| MS001 | a required field is missing from an entry | Safe when the value is known (the module's own name, a description from its doc); else Ask |
| MS002 | an entry's `name` differs from its registry key | Safe: set `name` to the key |
| MS003 | `status` is not one of the configured statuses | Ask which status; the error lists the allowed ones |
| MS004 | a `context_files` path is missing on disk | Safe when the file moved (fix the path); Ask when it was deleted |
| MS006 | a relation name is not one of the configured relations | Ask which relation; the writer's error lists them |
| MS007 | a relation has no `description` | Safe when the docs say why the modules are linked; else Ask |
| MS008 | a relation has no `module` target | Ask which module it points at |
| MS009 | a relation points at a module that is not in the registry | Ask: the module was renamed, merged or removed |
| MS010 | a relation points at a child that does not exist | Ask: the child was renamed or removed |
| MS011 | a deprecated field is present | Ask: the message names the replacement; moving the value is a decision |
| MS012 | a field nobody declared is present | Ask: declare it in the team config or a pack, or remove it |
| MS013 | a value does not match its field type | Safe when the intended value is obvious (a string that should be a list); else Ask |
| MS014 | a directory under the modules directory is not registered | Ask: register it (`module-create`) or remove it |
| MS015 | a role doc is listed for a role that is not configured | Ask: configure the role or drop the doc from `context_files` |
| MS020 | more keywords than the soft budget (info) | Ask: keep, trim or split |
| MS021 | a keyword shared by many modules (info, `*`) | Ask which module the word really routes to |
| MS022 | an empty keyword, which matches every task | Safe: remove it |
| MS030 | the module doc is past the split signal | Ask: `module-split`, or move detail into role docs |
| MS031 | the module doc is past the hard stop | Ask: `module-split` |
| MS032 | a role doc is past its budget | Ask: trim, or split the module |
| MS040 | a path in the components table is missing on disk | Safe when the file moved (fix the path); else Ask |
| MS050 | code changed but none of the module's docs did (drift) | `module-sync`: the docs need a real update |
| MS051 | a frozen `*.legacy.md` snapshot was modified or deleted | Safe: restore it from git; never edit it |
| MS052 | a routing rule names a module that does not exist (`*`) | Ask: fix the rule in the team config |
| MS053 | two routing rules send one file to two modules (`*`) | Ask which rule wins (`exclusive = true`) or narrow a glob |
| MS060 | an unknown key in a pack's `pack.toml` (`*`) | Ask the pack's owner (usually a typo) |
| MS061 | a pack role's template is missing or outside the pack (`*`) | Ask the pack's owner |
| MS062 | a pack skill agents cannot load (`*`) | Ask the pack's owner; the message says what is wrong |
| MS063 | an ejected skill is behind its pack (its files changed since the eject, or a repository pack's version did), a pack file it cannot read, or no pack declares it (`*`) | Ask: review `modsys eject <skill> --diff --json`, take what the team wants into the copy by hand, then `modsys eject <skill> --rebase --json` records the pack's current state and clears it (the copy's files stay as they are). Or delete the copy and run `packs sync` (the pack's version returns) |
| MS064 | a skill reads a role that is not configured or disabled (`*`) | Ask the pack's owner |
| MS065 | two packs declare one skill id; one is shadowed (`*`) | Ask: rename one of the skills |
| MS066 | a repository pack takes a built-in pack's id and replaces that pack (`*`, info) | Nothing to fix when the team owns that pack on purpose; otherwise ask to rename the repository pack |
