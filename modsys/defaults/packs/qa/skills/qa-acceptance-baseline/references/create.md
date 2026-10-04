# create: a module with no baseline yet

Step 5 of `qa-acceptance-baseline` — write the doc — when step 1 found no `role:qa_acceptance`
row with `exists: true` (when it found one, the doc exists: follow `references/refresh.md`
instead).

- It does not: start from the file of the `roles/qa_acceptance.md` row of
  `modsys templates list --json`, fill it, save it next to the module's other role docs,
  and add it to the module's `context_files`:

  ```bash
  modsys registry set <module> context_files '<the object with roles.qa_acceptance added>' --dry-run
  modsys registry set <module> context_files '<the object with roles.qa_acceptance added>' --json
  ```

  Build the object from `show --all-roles`: `universal` is the universal row, each
  `role:<role>` row is `roles.<role>`; add `roles.qa_acceptance`. Check the dry run's diff
  changes nothing else.
