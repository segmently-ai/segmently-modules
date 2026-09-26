# E-B rubric

Score each run (one friction log of `greenfield.md` or `brownfield.md`) on its own, then
compare runs of the same persona across phases.

| Metric | How to count |
|---|---|
| Goal steps done | goal steps the log shows as done AND verified by a command (greenfield: 5, brownfield: 4) |
| Commands | ONE shell invocation the agent issued (one tool call / one prompt line) counts as one command — even when it chains several statements with `&&`, `;` or a pipe. A read through a dedicated read tool (not the shell) is a source peek or a doc read, not a command: count and report it separately, do not add it to this total. |
| Source peeks | reads of modsys's source (package, site-packages, a checkout); the target is 0 |
| Blockers / majors / minors | the log's own severities, re-checked by the scorer: a blocker is anything the agent could not get past without a source peek or outside help |
| Coverage (brownfield) | the mapped share the agent reported, re-checked with `modsys coverage --json` in the final repository; also record that command's per-module counts and flag in the run's notes any module — especially a shared/catch-all one — holding a large share of the total (e.g. more than 30 %). Coverage met through a catch-all module is reported in the notes, not hidden; it does not change the PASS rule below. |

**PASS** = all goal steps done, 0 source peeks, 0 blockers, commands ≤ 40 (greenfield) or
≤ 45 (brownfield), and — brownfield — the coverage reported and ≥ 0.8.

A run that wires code with `modsys code-map add` instead of editing `.modsys/config.toml` by
hand, or gates with `modsys ci` instead of separate `lint` / `lint --changed` / `coverage`
calls, is scored exactly the same: every metric above counts what the run did, not which of
the documented paths it took.

Scorecard (one row per run):

| Run | Persona | Goal steps | Commands | Source peeks | Blockers | Majors | Minors | Coverage | PASS |
|---|---|---|---|---|---|---|---|---|---|
| 1 | greenfield | 5/5 | … | 0 | 0 | … | … | — | yes/no |

Run each persona 2–3 times per phase. For every major or blocker, note the doc, help text or
error message that would have prevented it; those notes feed the next fix round.
