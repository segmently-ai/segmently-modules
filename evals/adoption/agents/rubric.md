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
the documented paths it took. For brownfield, record in the run's notes whether it used
`modsys init map` (the docs offer it for an existing codebase); it does not change the score.

Scorecard (one row per run):

| Run | Persona | Goal steps | Commands | Source peeks | Blockers | Majors | Minors | Coverage | PASS |
|---|---|---|---|---|---|---|---|---|---|
| 1 | greenfield | 5/5 | … | 0 | 0 | … | … | — | yes/no |

Run each persona 2–3 times per phase. For every major or blocker, note the doc, help text or
error message that would have prevented it; those notes feed the next fix round.

## pack-author

Five goal steps, each verified by the scorer in the final repository (`{WORKDIR}`), not taken
from the log:

1. a pack under `.modsys/packs/` declares a new role and a skill whose `reads_roles` names it;
   `modsys lint` exits 0 and reports no MS060–MS065 error;
2. a new module's doc for that role exists (`modsys show <module> --role <role> --json` lists
   it with `exists: true`);
3. `modsys packs sync --check --agent claude --agent codex` exits 0, and the skill's `SKILL.md`
   in `.claude/skills/<skill>/` calls `modsys show … --role <role>`;
4. `.modsys/overrides/skills/<skill>/` exists, its `SKILL.md` differs from the pack's, and the
   agents' copies equal the ejected copy;
5. `CLAUDE.md` and `AGENTS.md` each hold exactly one `<!-- modsys:begin` line, `CLAUDE.md`
   still holds the team's notes, and `modsys agents-md --check --target CLAUDE.md --target
   AGENTS.md` exits 0.

Commands and source peeks are counted as above; source peeks are verified by scanning every
Bash (heredoc bodies stripped), Read, Grep and Glob input of the transcript, not only the
self-report.

**PASS (pack-author)** = all 5 goal steps verified, 0 source peeks, 0 blockers, commands ≤ 35.

## adopter

Four goal steps, each verified by the scorer in the final repository (`{WORKDIR}`, built by
`agents/adopter_repo.py`), not taken from the log:

1. `modules/registry.json` and every module doc under `modules/` are byte-identical to the
   repository as built (`git diff --quiet <the first commit> -- modules` exits 0);
2. `.modsys/config.toml` exists and is committed (`git ls-files --error-unmatch
   .modsys/config.toml` exits 0, and `git status --porcelain -- .modsys/config.toml` is empty);
3. `modsys lint --fail-on warning` exits 0;
4. `modsys show inventory --json` lists `src/inventory/` under `code` (the registry's
   `stock_paths` field), and `modsys list --json` lists `inventory`, `orders`, `shipping` and
   `loyalty`.

Commands and source peeks are counted as above (the transcript scan, not the self-report).

**PASS (adopter)** = all 4 goal steps verified, 0 source peeks, 0 blockers, commands ≤ 35.
