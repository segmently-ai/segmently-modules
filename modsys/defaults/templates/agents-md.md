## Module docs (modsys)

This repository keeps a module registry (`${registry}`) with docs per module under
`${modules_dir}/`. Read them before a task and keep them current after it:

- Before a task, write it to a file and run
  `modsys context --task-file <file> --role <role> --match lexical`; read every file it lists.
- Roles in this repository: ${roles}.
- After a change, `modsys sync-instructions --from-diff <base>..HEAD` says what to bring up to
  date per module: the docs, the drift, the field hints (the `module-sync` skill of the `core`
  pack does the whole job). `<base>` is where the work branched off:
  `git merge-base <target> HEAD`.
- Pipelines whose agents must not edit docs mid-run queue changes with `modsys propose`
  instead; `modsys sync --apply-proposals` applies them.
- The gate: `modsys ci --base <base>` (lint, drift since the base, coverage).

Skills from packs (${skills_delivery}):
${skills}
