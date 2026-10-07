# Finding the modules for a task

## How modules are found
`modsys context --task-file <file> --role <role> --match lexical --json` (the read set for a
task) and `modsys match "<task>" --match lexical --json` rank modules by their keywords —
lexical, the default.
`--match semantic` or `hybrid` asks the user's own agent command (`MODSYS_AGENT_COMMAND`, a JSON
argv list in the environment; a config file can never set it). A `[match] mode` committed to the
repository runs that command only with `MODSYS_AGENT_ALLOW_REPO_MODE=1` in the user's
environment.

## Choosing modules by meaning
`modsys choose --task-file <file> --effort standard --json` (the task written to a file) prints a
work order for an agent to pick modules from the cards (`modsys catalog --json`); `--apply <file>` checks the answer,
`--run` asks the agent command. Effort: `quick`, `standard` or `deep`; default `[search]
effort`.

## A task keeps reaching the wrong module
Tune the target's keywords: `modsys registry append <module> keywords '"<word>"' --dry-run`. A
generic word that belongs elsewhere: `negative_keywords` on the module that wrongly matches; two
words that point here only together: `required_combinations`. Check with
`modsys match "<task>" --match lexical --json`.

## Measure the routing
`modsys eval routing --prompt --json` returns a prompt that asks for tasks per module; save the
answer (`[{task, module}]`) to a file and run `modsys eval routing --tasks <file> --json` — the
hit rate per module, exit 1 below `--min-hit-rate` (default `[init] routing_min_hit_rate`, 0.8).
