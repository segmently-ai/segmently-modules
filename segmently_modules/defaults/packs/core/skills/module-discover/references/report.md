# The report (step 8) and the JSON (step 9)

## Report

Shown in the conversation, in this shape. Modules in usage order — `modify`, `consume`,
`reference` — and by score within each.

```markdown
## Discovery: <task, one line>

Search: <lexical | by meaning | hybrid> — <the setting or the user's words> — lexical <sure | unsure: reason | not run>

### <module>[/<child>] — usage: modify | consume | reference (score <0–10>)
Why: <what the task needs from it; "named by the user" when it was>
Rules:
- `<doc>:<line>` (<role>) — <the rule's first line, verbatim>
- index: <complete (<date>) | building in the background — <doc>, … | not indexed — <doc>, … | incomplete — <doc>, …>
Docs:
- `<path>` (<role>): <a rule, constraint, contract or pitfall that bears on the task>
- `<path>` (<role>): read, nothing for this task
Docs to update: `<path>`, …
Code:
- `edit` — `<file>:<line>` — `<symbol>` — <what changes there, one clause>
- `read` — `<file>:<line>` — `<symbol>` — <why it was read: called as is / alternative / pattern to follow>
Tests: add new — <what to cover>
Risks / unknowns: <open questions, a doc the code contradicts, an assumption the plan must check>
Likely consequence: <what the implementation will probably also need> — <the existing file it would touch, or "a new file: the plan decides where">

### Rejected
- <module> — <reason> (score <0–10>, or "off-topic by its description")

### Files outside every module
- `<file>` — needs `module-create` or a `[[code_map]]` rule

### Missing files
- `<file>`

Index the rules of <doc>, … now? A writer per doc, in the background, edits only their critical-rules sections; the next reader gets the index instead of reading them again.
```

- `Rules:` only for a `modify` module (`references/rules.md`): each rule
  `rules <module>` gives (`references/rules.md`), verbatim, in its order, then the `index:` line.
  A `consume` or `reference` module: no `Rules:` lines.
- Every doc step 5 lists is read to the end — the whole file with your file-read tool, never a
  search in it, a line range or a cut — and is on a `Docs:` line: an extract, or "read, nothing
  for this task". An
  extract is short and says what it means for this task. A rule — a never / must / do not / always
  statement, a ❌ line — is quoted in the doc's own words with its `doc:line`, never softened into an
  option or a question.
- A `reference` module has its main doc's lines and no `Code:` line.
- `Code:` holds existing code only. A file the work will create is never listed: where new code
  goes is the plan's decision.
- Every `Code:` line starts with its tag. `edit`: an existing file the change edits; its why
  says what changes there, in one clause, never "relevant" or "related". `read`: a file called
  or consulted as it is, a consumer, a pattern to follow, or an alternative — a file offered
  with "or", "either" or "could also" is never `edit`, and its why says "alternative". Only
  the `edit` lines are the files to change; the `read` lines are evidence.
- `Tests:` one line per module with an `edit` line. An existing test file is `edit` only when
  its assertion names the symbol or value the task changes, and this line then reads
  `Tests: edit the lines above`; otherwise `Tests: add new — <what to cover>`, with no path.
- `Likely consequence:` lines, none or more, under `Risks / unknowns`: what the implementation
  will probably also need (an environment variable to read, an export to add, an import path a
  test runner resolves) and the existing file it would touch, or "a new file: the plan decides
  where". A consequence never enters `Code:` and never names a new path.
- `Search:` is the first line under the title, in the form `references/choose.md` gives.
- The closing question only when an `index:` line says `not indexed` (`references/rules.md`):
  every such doc, once; on a yes run `rules_build`'s `build`, never without it.
- An empty section says "none"; it is never left out.

## JSON (`discovery-results.json`)

Only when the user asks, at the path the user names — the shape a planning pipeline reads:

```json
{
  "version": "1.1",
  "task": "<the task, verbatim>",
  "modules": [
    {
      "name": "<module>[/<child>]",
      "score": 7.5,
      "confidence": "high | medium | user_specified",
      "usage_type": "MODIFY | EXTEND | READ-ONLY",
      "documentation": {"module_md": "<main doc>", "<role>_md": "<role doc>"},
      "files": [{"path": "<file>", "offset": 42, "limit": 30, "reason": "edit — <symbol> — <what changes there>"},
                {"path": "<file>", "offset": 7, "limit": 30, "reason": "read — <symbol> — <why it was read>"}]
    }
  ],
  "files_outside_modules": [{"path": "<file>", "offset": 1, "limit": 30, "reason": "<why>"}],
  "summary": "<two or three sentences: the modules, the main risks>"
}
```

`usage_type`: `modify` → `MODIFY` (`EXTEND` when the task adds new code on the module's patterns),
`consume` and `reference` → `READ-ONLY`. `confidence`: `user_specified` for a module the user
named, else `high` when the score is ≥ 7, otherwise `medium`. `documentation` holds every doc step 5 read for the
module, one key per role (`developer_md`, `qa_md`, …). `files[].offset` is the touch point's line.
`files[].reason` starts with the tag of its `Code:` line: `edit — ` or `read — `.
