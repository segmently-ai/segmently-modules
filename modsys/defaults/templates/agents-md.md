## Module docs (modsys)

This repository keeps a module registry (`${registry}`) with docs per module under
`${modules_dir}/`. Read them before a task and keep them current after it:

- Before a task, run `modsys context --task "<the task>" --role <role>` and read every file it
  lists.
- Roles in this repository: ${roles}.
- After a change, `modsys discover --from-diff <base>..HEAD` names the module docs to update;
  propose the updates with `modsys propose` instead of editing module docs mid-run.
- The gate: `modsys ci --base <base>` (lint, drift since the base, coverage).

Skills from packs (`modsys packs sync` copies them into the agents' skill directories):
${skills}
