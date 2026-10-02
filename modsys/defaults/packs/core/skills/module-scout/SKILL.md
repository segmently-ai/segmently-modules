---
name: module-scout
description: Quick, read-only context on the modules a task is about, while the task is still being discussed. Asks the modsys CLI what each named module is, which docs to read and which modules it is linked to, reads those docs and reports a short brief. No plan, no edits. Use when the user says "look at module X", "load the context for", "what do we know about", or describes a change and names modules before a plan exists.
---

# module-scout

## When to use

- A change is being discussed, or the user names modules (`parent/child`, a module doc's path) and
  wants their context before deciding anything: a short brief, no plan, no edits.

## When not to use

- The task is confirmed and you need its touch-set: use `module-discover`.
- One question needs a deep answer from the docs and the code: use `module-research`.
- Work is finished and the docs must catch up: use `module-sync`.

## Scope

Read-only: modsys read verbs and reading files; it writes only temporary files outside the
repository, never edits a file, never runs a writer verb, never commits. The registry, layout and
roles come from `modsys`, never from an assumed path.

If `modsys` is not found, tell the user how to install it — the `modsys` plugin for Claude Code, `uv tool install git+ssh://git@github.com/<owner>/<repo>.git`, or `pipx install git+ssh://git@github.com/<owner>/<repo>.git` — and stop until it runs.

## Steps

1. No module named? Choose the candidates.

   Run `modsys catalog --json`; read `match` and `search`. The text: the user's topic or question.
   The mode: the user's words ("only lexical", "only by meaning"), else `match.mode` unless
   `lexical`, else `hybrid`; the user may also set the depth ("search deep") or the model ("use
   opus").

   - By meaning (`semantic`, `hybrid`):
     `modsys choose --task "<the text, verbatim, any language>" --json` prints a work order. Answer
     it in Claude Code by a subagent (`model: <search.claude_model>`), in Codex by
     `codex exec -m <search.codex_model> -c model_reasoning_effort=<reasoning> --output-schema <schema file> -`
     (the order on stdin, `answer_schema` in the file; `low`, `medium`, `high` for `quick`,
     `standard`, `deep`), else answer it in this session, at the depth its rules set: `quick` the
     cards only, `standard` also the INDEX or the main doc's head of up to 3 candidates, `deep`
     also their docs and code. Pipe the answer to `modsys choose --apply - --json`: `picks` with
     their `read` docs.
   - By keyword (`lexical`, `hybrid`):
     `modsys context --task "<the domain terms and code identifiers, in English>" --json`: its
     `modules`; none but `near_misses`: list them and ask which module is meant.
   - `hybrid`: merge the lists; a module found both ways ranks first. Pass `--match semantic` or
     `--match hybrid` only when `match.semantic` is true: else modsys has no agent to ask.

   Never widen the list on your own.

2. For each module, named or chosen: `modsys show <module> --json`.

   - `read[]`: the docs to open, in order; `exists: false` = a missing doc: say so.
   - A split module (`submodules`; its first doc is the parent INDEX): read the index, then only
     the children the topic touches (`modsys show <module>/<child> --json`) — never all of them.
   - A pointer stub (exit 1, `stub`): retired or merged; report the stub, never guess.
   - Talk about one audience (testing, design, product): add
     `modsys show <module> --role <role> --json`; the roles are the `roles/<role>.md` rows of
     `modsys templates list --json` — never guess one.

3. Its neighbours: `modsys related <module> --json` (`edges` out of it, `reverse` into it). Read a
   forward edge's main doc only when its relation says this module needs the other (e.g.
   `depends-on`); name the rest with their relation, unread.

4. Read the docs for what the topic needs: purpose, components, rules ("never", "always", "must"),
   pitfalls. No code — that is `module-research`.

5. Report the brief, per module: what it owns (a line or two); the rules bearing on the topic,
   quoted short with their doc; the neighbours read and why, and those only named; missing docs or
   stubs; next: `module-discover` once the task is confirmed, `module-research` for a question that
   needs the code. Readable in a minute: no plan, no file list.

## Gates

No gates — read-only: it never stops for a confirmation. It asks only when no module is found and
the near misses leave the choice open.

## Exit codes

`0` ok · `1` from `show` or `related` = a pointer stub · `2` = a usage or config error (no
registry: "run modsys init"): read stderr, fix the command or report it.
