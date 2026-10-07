## Module docs (modsys)

This repository keeps a module registry (`${registry}`) with docs per module under
`${modules_dir}/`. Read them before a task and keep them current after it:

- Before a task, write it to a temporary file outside the repository and run
  `modsys context --task-file <file> --role <role> --match lexical`; read every file it lists.
- Roles in this repository: ${roles}.
- After a change, `modsys sync-instructions --from-diff <base>..HEAD` says what to bring up to
  date per module: the docs, the drift, the field hints (the `module-sync` skill of the `core`
  pack does the whole job). `<base>` is where the work branched off:
  `git merge-base <target> HEAD`.
- Pipelines whose agents must not edit docs mid-run queue changes with `modsys propose`
  instead; `modsys sync --apply-proposals` applies them.
- The gate: `modsys ci --base <base>` (lint, drift since the base, coverage).
- At the start of module work, `modsys next` lists what the repository needs now; when it lists
  items, tell the user. The `module-assistant` skill of the `core` pack plans and carries them
  out, sets modsys up, and answers how to do something with modsys.

Skills from packs (${skills_delivery}):
${skills}
