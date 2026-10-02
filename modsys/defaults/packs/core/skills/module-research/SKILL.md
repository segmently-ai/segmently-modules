---
name: module-research
description: Answers one question about one or more modules in depth, from their docs and their code, read-only. Reads every role doc, the module's links in both directions, the code files modsys maps to it and its lint findings, then writes a brief with file:line evidence that names every place where the docs and the code disagree. Use for "how does X really work", "is the doc of X still true", "explain module X in depth", or before a risky change to X.
---

# module-research

## When to use

- A question about a module needs proof from the code: is its doc still true, what does it do
  before a risky change.

## When not to use

- The gist of a module while a task is discussed: use `module-scout`.
- The touch-set of a confirmed task: use `module-discover`.
- The docs must be fixed, not just checked: report the gaps here, then `module-sync` (after a
  change) or `module-lint` (for findings).

## Scope

Read-only: modsys read verbs, docs, code; it writes only temporary files outside the repository,
never edits a file — gaps are reported, not fixed — and never commits.

If `modsys` is not found, tell the user how to install it — the `modsys` plugin for Claude Code, `uv tool install git+ssh://git@github.com/<owner>/<repo>.git`, or `pipx install git+ssh://git@github.com/<owner>/<repo>.git` — and stop until it runs.

## Steps

Pin the question in one sentence.

1. No module named? Choose the candidates.

   Run `modsys catalog --json`; read `match` and `search`. The text: the user's topic or question.
   The mode: the user's words ("only lexical"), else `match.mode` unless `lexical`, else `hybrid`;
   the user may set the depth ("search deep") or the model ("use opus").

   - By meaning (`semantic`, `hybrid`):
     `modsys choose --task-file <the text, verbatim, in a file> --json` prints a work order. Answer
     it whole (never a preview) in Claude Code by a subagent (`model: <search.claude_model>`), in Codex by
     `codex exec -m <search.codex_model> -c model_reasoning_effort=<reasoning> --output-schema <schema file> -`
     (the order on stdin, `answer_schema` in the file; `low`, `medium`, `high` for `quick`,
     `standard`, `deep`), else answer it in this session, at the depth its rules set (or the
     user's): `quick` the cards only, `standard` also the INDEX or the main doc's head of up to 3
     candidates, `deep` also their docs and code. Pipe the answer to
     `modsys choose --apply - --json`: `picks` with their `read` docs.
   - By keyword (`lexical`, `hybrid`):
     `modsys context --task-file <the domain terms and code identifiers, in English, in a file> --match lexical --json`:
     its `modules`; none but `near_misses`: list them, ask which is meant.
   - `hybrid`: merge the lists; a module found both ways ranks first. Pass `--match semantic` or
     `--match hybrid` only when `match.semantic` is true.

   Keep the top 3; never widen the list on your own.

2. Load every doc of each module: `modsys show <module> --all-roles --json`. A split module
   (`submodules`): read the parent index, then the children the question touches —
   `modsys show <module>/<child> --all-roles --json` (the parent's role docs are the child's
   baseline). Read the docs fully.

3. Its links, both ways: `modsys related <module> --json`. `edges`: the modules it relies on;
   `reverse`: those pointing at it, which a change would affect. Read a linked module's main doc
   only when the question crosses into it.

4. Its code: `modsys code-map files <module> --json` (`via`: the routing rule; `show` adds `code`
   and `code_globs`). Search it for the names the docs and the question use; read what answers it.
   Nothing routed? Say so and search by the component names its main doc lists.

5. Its lint state: `modsys lint --json`. Keep the findings of the module and its children; findings
   with module `*` only when they name it.

6. Compare. For each doc statement that bears on the question — a component, a rule, a flow, a
   limit — find the code that implements it. Record each disagreement as "the docs say X
   (doc:line), the code does Y (file:line)", the doc statements the code does not show, and code
   behaviour the docs never mention.

7. Write the brief: the answer first, in a few sentences; file:line evidence for every claim; the
   gaps table (doc claim · code reality · file:line · how sure); who is affected (`reverse`) when
   it is about a change; the lint findings that matter; next: `module-sync` after a change,
   `module-lint` for findings.

## Gates

No gates — read-only: it reports and stops. It asks only when the question is too broad to answer
with evidence (then it proposes a narrower one).

## Exit codes

`0` ok · `1` from `lint` = findings at or above the fail level (a valid result: read them) · `1`
from `show` = a pointer stub · `2` = a usage or config error: read stderr, fix the command or
report it.
