# Choosing the candidates (step 1)

**Every card, read and judged by you.** `segmently-modules catalog --plain > <cards file>` gives each
module and child of the registry: its id, description and keywords, nothing else. Read the file to
the end (in parts when it is long) and judge every card against the task by meaning:
- its description says the task needs the module → a candidate;
- its description is close, or its keywords name what the task implies → a candidate to verify;
- otherwise → not a candidate.

Never narrow the cards with grep, a regex, a script or a keyword score before reading them: the
verdict is yours, from what each card says. The keyword list and the chooser below only add
candidates; they never remove one the cards gave you. Step 2 then reads each candidate's main doc.

Run `segmently-modules catalog --settings > <temp file>`; read `[match] mode` and `[search]`. The text: the task as
given. For the keyword half write 1–3 short English queries to a temporary `<file>` (steps 6 and 7
use it too): the domain terms and code identifiers the task implies (registry keywords are English
and match whole words). The user may set the model ("use opus") and the depth ("search deep":
`choose --effort deep`; `<reasoning>` follows it). These words set the chooser's model and depth
when it runs; they never make it run.

**The mode.** One table decides whether the chooser (the search by meaning) runs. Read it top
down; the first row that fits decides, so the user's words for this run win over
`search.chooser`. The user's words count in any language. `match.mode` decides nothing here,
except that the `always` row keeps `semantic` for a `semantic` one. The keyword commands always
pass `--match lexical`.

| The user's words, this run | `search.chooser` | Keyword result | Mode |
|---|---|---|---|
| "by meaning" | any | any | `semantic`: the chooser runs |
| "only lexical" | any | any | `lexical`: no chooser |
| none | `always` | any | `hybrid` (`semantic` when `match.mode` is `semantic`): the chooser runs, as it always did |
| none | `when_unsure` | `sure` | `lexical`: no chooser |
| none | `when_unsure` | `unsure` | `hybrid`: the chooser runs after the keyword command |
| none | `never` | any | `lexical`: no chooser |

`when_unsure`: run the keyword command first, on its own; its first line, `lexical: sure` or
`lexical: unsure: <reason>`, is the keyword result. On `sure` the keyword list (every row, not only
the `top`) is the candidates: no `choose` command and no chooser agent. On `unsure` run the by-meaning half too,
then merge the lists as `hybrid` does.

- By meaning (`semantic`, `hybrid`): write the text, verbatim, to `<task file>`. **Claude Code:**
  `segmently-modules choose --task-file <task file> > <order file>`; give `<order file>`'s path to the
  `segmently-modules:module-chooser` agent with `model: <search.claude_model>` (without that agent: a
  subagent told "this file is your whole task; answer with its JSON only; change nothing"); its
  reply is the answer. **Codex:** the same with `--json`, its `answer_schema` written to
  `<schema file>`, then
  `codex exec -m <search.codex_model> -c model_reasoning_effort=<reasoning> --sandbox read-only --output-schema <schema file> - < <order file>`
  (`low`, `medium`, `high` for `quick`, `standard`, `deep`). **Elsewhere** (no subagent, no
  `codex exec`, or it fails, as inside a sandbox): answer the order yourself, every card read, by its rules. Pipe the answer to
  `segmently-modules choose --apply - --json`.
- By keyword (`lexical`, `hybrid`): `segmently-modules discover --task-file <file> --match lexical > <temp file>`,
  read to the end.
- `hybrid`: merge the lists; a module found both ways ranks first.

**A failing chooser** — no agent to hand the order to, an answer that is not JSON, or
`choose --apply` exits 2 — never ends the run: answer the order yourself, every card read, by its
rules (the **Elsewhere** path), and say so on the search line. If your own answer fails
`choose --apply` too, use the keyword list (run the keyword command when it has not run) and say
so on the search line.

**The search line.** The first line under the report's title says how the candidates were
chosen: `Search: <lexical | by meaning | hybrid> — <the setting or the user's words> — lexical <sure | unsure: reason | not run>`
(the mode `semantic` is written `by meaning`), e.g. `Search: lexical — when_unsure, chooser skipped — lexical sure`,
`Search: hybrid — when_unsure — lexical unsure: tie`,
or, after a failing chooser, `Search: hybrid — always, chooser failed (no agent): answered in the session — lexical sure`.
No keyword command ran: `Search: by meaning — "by meaning" — lexical not run`.

If a temporary file cannot be written (a read-only sandbox), pass the task through a quoted
heredoc and read the order from stdout instead of a file:

```bash
segmently-modules choose --task-file - <<'EOF'
<the task text, verbatim>
EOF
```
