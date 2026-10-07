# Keeping the docs current

The base below is where the work branched off: `git merge-base <target> HEAD`.

## After a change: update the docs
The `module-sync` skill: it takes the session's decisions and the code change, asks
`modsys sync-instructions --from-diff <base>..HEAD --json` which docs to update per module (with
the drift and the fields' sync hints), edits them and runs the sync hooks. Uncommitted work:
`modsys sync-instructions --files <path> --json`.

## See the drift
`modsys lint --changed --base <base> --json`: MS050 = a module's code changed and none of its
docs did; MS051 = a frozen `*.legacy.md` was edited. `modsys next --base <base> --json` lists it
too.

## Pipelines that must not edit docs mid-run
Queue the change instead:
`modsys propose --module <module> --op doc_append --doc <path> --value-file <file> --reason "<why>" --json`
(or `--op set --field <field> --value '<json>'`). Review: `modsys proposals list --json`; apply:
`modsys proposals apply --dry-run`, then without `--dry-run`; reject:
`modsys proposals reject --run-id <id> --reason "<why>" --json`. A sync applies them at its end
with `--apply-proposals`.

## The CI gate
`modsys ci --base <base> --json` runs lint, the drift since the base and coverage; exit 1 when
a step fails. In a CI job the base is the target branch as CI fetched it (`origin/main`, with
enough history fetched for a merge base). Settings: `[ci] base`, `fail_on` (default `warning`),
`coverage_fail_under`. A registry with old findings: keep the `--json` output of one `ci` run as
a baseline file, then `modsys ci --base <base> --baseline <file> --json` fails only on new
findings (drift is never "known"). Add `modsys packs sync --check --json` and
`modsys agents-md --check --json --target CLAUDE.md` to keep the copies and the block current.
The `module-lint` skill explains and fixes findings.
