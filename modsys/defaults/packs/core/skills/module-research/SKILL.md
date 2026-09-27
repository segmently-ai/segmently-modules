---
name: module-research
description: Answers one question about one or more modules in depth, from their docs and their code, read-only. Reads every role doc, the module's links in both directions, the code files modsys maps to it and its lint findings, then writes a brief with file:line evidence that names every place where the docs and the code disagree. Use for "how does X really work", "is the doc of X still true", "explain module X in depth", or before a risky change to X.
---

# module-research

The deep, evidence-based answer to one question about a module: what the docs claim, what the
code does, and where the two part ways. `module-scout` is the quick version without code.

## When to use

- A question about a module needs proof from the code, not just its docs.
- The user suspects a module doc is out of date and wants to know where.
- Before a risky change: what exactly does the module do today, and who depends on it?

## When not to use

- You only need the gist of a module while a task is discussed: use `module-scout`.
- You need the touch-set of a confirmed task: use `module-discover`.
- The docs must be fixed, not just checked: report the gaps here, then use `module-sync` (after
  a change) or `module-lint` (for findings).

## Scope

Read-only: it runs modsys read verbs, reads docs and code, and searches the code. It never
edits a file — gaps are reported, not fixed — and never commits.

## Steps

1. Pin the question in one sentence, and the module(s) it is about. Unsure which modules?
   Ask `modsys context --task "<the question>" --json` and take the top rows.

2. Load every doc of the module.

   ```bash
   modsys show <module> --all-roles --json
   ```

   For a split module (`submodules` in the result), read the parent index and then the children
   the question touches: `modsys show <module>/<child> --all-roles --json` (a child's result
   also lists the parent's role docs as its baseline). Read the docs fully.

3. Load its links, both ways.

   ```bash
   modsys related <module> --json
   ```

   `edges` are the modules it relies on or complements; `reverse` are the ones that point at
   it — the ones a change would affect. Read a linked module's main doc only when the question
   crosses into it.

4. Find the code.

   ```bash
   modsys code-map files <module> --json
   ```

   These are the files routed to the module (`via` says by which rule or doc). The `show`
   result adds `code` (paths a field of the module points at) and `code_globs` (the routing
   patterns). Search these files for the names the docs and the question use; read the parts
   that answer the question. Nothing routed? Say so — the module may lack routing rules — and
   search by the component names its main doc lists.

5. Check the lint state of the module.

   ```bash
   modsys lint --json
   ```

   Keep the findings whose `module` is the module or one of its children; findings with module
   `*` concern the config and matter only when they name this module.

6. Compare. For every statement in the docs that bears on the question — a component, a rule, a
   flow, a limit — find the code that implements it. Record each disagreement as "the docs say
   X (doc:line), the code does Y (file:line)". Record doc statements you could not find in the
   code, and code behaviour the docs never mention.

7. Write the brief:

   - the answer, first, in a few sentences;
   - the evidence: file:line for every claim;
   - the gaps table — doc claim · code reality · file:line · how sure you are;
   - who is affected (the `reverse` links) when the answer is about a change;
   - the lint findings that matter;
   - next steps: `module-sync` to bring the docs in line after a change, `module-lint` for the
     findings. Do not edit the docs here.

## Gates

No gates — read-only: it reports and stops. It asks only when the question is too broad to
answer with evidence (then it proposes a narrower one).

## Exit codes

`0` ok · `1` from `lint` = findings at or above the fail level (still a valid result: read
them) · `1` from `show` = a pointer stub · `2` = a usage or config error: read stderr, fix the
command or report the message.
