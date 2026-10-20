# The report (step 8) and the saved result (step 9)

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

Saved: `<path>`
```

- `Rules:` only for a `modify` module (`references/rules.md`): each rule `rules <module>` gives
  that applies to the task (`references/rules.md`), verbatim, in its order, then the `index:` line.
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
- Whatever is written from this report — a brief, a plan — keeps every `Rules:` line verbatim with
  its `doc:line`: a rule stays a rule (never / must), never a question to check or a risk.
- An empty section says "none"; it is never left out.

## Saved result

Step 9 saves the report as a task context file, the source the phases after discovery read and add to.
`[discover] save` (step 1's settings): `"always"` — save; `"ask"` — ask after the report; `"off"` — only when the
user or a caller asks. A path the user or a caller names always wins: it goes to `--out <path>`, and the file is
saved whatever the setting. Write the input below to a temp file outside the repository, then:

```bash
segmently-modules task-context save --from <temp file> --json
```

Its `path` is the saved file; the report's last line is `Saved: <path>` (none when nothing was saved). Exit 2:
read stderr, fix the input, run it again.

The input holds your judgements; the engine fills the rest — each doc's role and hash, every rule of the docs
whole, the docs to update, the files outside every module and the missing ones, the commit:

```json
{
  "task": "<the task, verbatim>",
  "search": {"mode": "lexical | semantic | hybrid", "lexical": "sure | unsure | not run", "reason": null},
  "modules": [{"module": "<module>[/<child>]", "usage": "modify | consume | reference", "score": 8,
               "why": "<the Why: line>", "named_by_user": false,
               "files": [{"path": "<file>", "line": 42, "tag": "edit | read", "symbol": "<symbol>",
                          "why": "<what changes there, or why it was read>"}],
               "tests": "<the Tests: line>", "risks": ["<a risk or unknown>"],
               "consequences": [{"text": "<a likely consequence>", "file": "<the existing file, or null>"}],
               "one_way": {"kind": "<what cannot be undone>", "reason": "<why>"}}],
  "docs": [{"path": "<doc>", "nothing": false, "extracts": [{"text": "<the extract>", "ref": "<doc>:<line>"}]}],
  "rules": [{"ref": "<doc>:<line>", "applies": "<why it applies to this task>"}],
  "rejected": [{"module": "<module>", "score": 3, "why": "<the reason>"}],
  "summary": "<two or three sentences: the modules, the main risks>"
}
```

- Everything the report holds is in the input: each module with its `Code:` lines as `files`, each `Docs:` line
  (a doc read with nothing for the task: `"nothing": true`), each rejected candidate.
- A rule is named by its `doc:line` as `rules` prints it, never retyped: the engine copies its text from the
  doc. A rule quoted from a doc's body, outside its critical-rules section, also carries `"text"`, its words; the
  engine keeps the doc's own line next to them.
- A pipeline that still reads the former `discovery-results.json` (`version` `1.1`) gets it from the saved file:
  `task-context export <file> --format discovery-1.1`.
