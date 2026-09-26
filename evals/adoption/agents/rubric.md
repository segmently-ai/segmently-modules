# E-B rubric

Score each run (one friction log of `greenfield.md` or `brownfield.md`) on its own, then
compare runs of the same persona across phases.

| Metric | How to count |
|---|---|
| Goal steps done | goal steps the log shows as done AND verified by a command (greenfield: 5, brownfield: 4) |
| Commands | every shell command the agent ran — modsys, git, edits through the shell, `ls` / `cat` |
| Source peeks | reads of modsys's source (package, site-packages, a checkout); the target is 0 |
| Blockers / majors / minors | the log's own severities, re-checked by the scorer: a blocker is anything the agent could not get past without a source peek or outside help |
| Coverage (brownfield) | the mapped share the agent reported, re-checked with `modsys coverage --json` in the final repository |

**PASS** = all goal steps done, 0 source peeks, 0 blockers, commands ≤ 40 (greenfield) or
≤ 45 (brownfield), and — brownfield — the coverage reported and ≥ 0.8.

Scorecard (one row per run):

| Run | Persona | Goal steps | Commands | Source peeks | Blockers | Majors | Minors | Coverage | PASS |
|---|---|---|---|---|---|---|---|---|---|
| 1 | greenfield | 5/5 | … | 0 | 0 | … | … | — | yes/no |

Run each persona 2–3 times per phase. For every major or blocker, note the doc, help text or
error message that would have prevented it; those notes feed the next fix round.
