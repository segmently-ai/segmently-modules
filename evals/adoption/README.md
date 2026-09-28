# Adoption evals

Two ways to measure whether a team (or an agent) can put modsys into a repository — and extend
it with a pack — using only what ships: a deterministic script (E-A) and blind-agent runs (E-B).

## E-A — deterministic (`run_eval.py`)

```bash
python3 evals/adoption/run_eval.py      # from the engine checkout; exit 0 = every step passed
```

It builds six repositories in temp dirs and drives this checkout's CLI (`python -m modsys`)
through adoption, a team pack, the built-in skills, adopting an existing registry and starting
from existing code. No network: the brownfield app is generated.

| Scenario | Steps |
|---|---|
| greenfield | `git init` → a missing registry names `modsys init` → `init` (and again: nothing changes) → 3 modules → `code-map add` (no hand edit) → a relation via `registry append` (a bad edge is refused) → lint clean → coverage 100 % → `context` returns `code_globs` → commit → code-only change: `lint --changed --fail-on warning` exits 1 with MS050 → `propose` a `doc_append` → `sync --from-diff --apply-proposals` → commit: gate exits 0 → `ci --base <first commit>` exits 0 → a code-only change: `ci` exits 1 (drift step failed) → a docs follow-up: `ci` exits 0 → a child module mapped by its own exclusive rule (`code-map add --exclusive`) |
| brownfield | a generated layered app (`app/routes/<f>/`, `app/repositories/<f>.py`, `app/models/<f>.py`, `app/sql/<f>.sql`, `tests/test_<f>.py`, an `app/db/` layer) → `init` keeps `.gitignore` → baseline coverage → a module per feature + `db` → layered rules: lint reports MS053 until the per-feature `repositories` / `sql` rules are `exclusive` (a hand edit), then lint is clean → coverage ≥ 80 % → `code-map files orders` lists `app/repositories/orders.py` → a feature repository maps only to its feature → a feature change drifts only the feature (MS050, `discover`) → `index split` + per-module layout keep `list` / `match` |
| packs | a git copy of `tests/fixtures/bookshop` → `packs new team --role reviewer --skill api-review` → plain `lint` without MS06x → `create reviews … --role reviewer` renders the pack's template → `show reviews --role reviewer` lists it → `packs sync --agent claude --agent codex`: 2 × `created` → `packs sync --check` exits 0 → a local edit in `.claude/skills/api-review/SKILL.md`: `packs sync` exits 1 (`conflict`), the edit stays → revert → `eject api-review` → edit the ejected copy: `packs sync` 2 × `updated` from it → the pack moves to `0.2.0` with a changed skill: plain `lint` reports MS063 → `eject api-review --diff` shows the change → a `CLAUDE.md` with team text: `agents-md --target CLAUDE.md --target AGENTS.md` → `added` + `created`, and again → 2 × `unchanged`, the team text kept → `templates list`: `roles/reviewer.md` from `role-template:team` |
| skills | a git copy of `tests/fixtures/bookshop` → `[packs] builtin = ["core", "ui", "qa"]`: `packs list` shows the three built-in packs → plain `lint` without MS06x → `packs sync --agent claude --agent codex`: 10 skills × 2 agents `created` → `packs sync --check` exits 0 → `agents-md --target AGENTS.md` lists the 10 skills → `create reviews … --tag ui --tag qa` renders `roles/designer.md` and `roles/qa_acceptance.md` from the packs' templates (`templates list`: `role-template:ui` / `role-template:qa`) → a code change in `catalog`: `sync-instructions --from-diff` names `catalog` with an MS050 drift row and the `keywords` hint → `eject module-sync` → the edited ejected copy: `packs sync` 2 × `updated` (`source: ejected`) → `packs new core` is refused (a reserved id) |
| adopt | a git copy of `tests/fixtures/bookshop` without `.modsys/` (+ `src/checkout/`, `src/payments/` files) and a reference copy with its declarations and a `src/{module}/**` rule → `adopt --dry-run` writes nothing and names the role `designer`, the field `file_paths` and the rule `src/{module}/**` → `adopt` writes `.modsys/config.toml` → `list` and `show catalog --all-roles` equal the reference copy's → a second `adopt` writes `.modsys/adopt.proposed.toml`, `config.toml` unchanged → every file outside `.modsys/` is byte-identical to the start |
| init-map | `tests/fixtures/bookshop_monorepo` with its history (`tests/fixtures/build_monorepo.py`) → `init` → `init map`: the seven candidates → exclude one and rename one in `.modsys/init/proposal.json` → `init confirm` → `init status`: gate 3 passed → `init resume` runs the fan-out (the work items) → a fresh copy: `init map` stopped by the test seam, then `init resume` → `preflight.json` / `proposal.json` equal an uninterrupted run's |

Every step checks an exit code and the data. The scorecard on stdout:

```json
{"greenfield": {"steps": [{"name": "init", "ok": true, "detail": "…"}], "commands": 26, "ok": true},
 "brownfield": {"steps": ["…"], "commands": 20, "ok": true},
 "packs": {"steps": ["…"], "commands": 15, "ok": true},
 "skills": {"steps": ["…"], "commands": 11, "ok": true},
 "adopt": {"steps": ["…"], "commands": 7, "ok": true},
 "init-map": {"steps": ["…"], "commands": 7, "ok": true}}
```

`commands` counts modsys invocations. A scenario stops at its first failed step; the other
scenarios still run, and the script exits 1. `tests/test_adoption_eval.py` runs it with the
unit tests; its failure-path test sets `MODSYS_EVAL_FAIL_STEP=<scenario>:<step name>`, a test
seam that forces that one step to fail.

## E-B — blind agents (`agents/`)

`agents/greenfield.md`, `agents/brownfield.md`, `agents/pack-author.md` and `agents/adopter.md`
(its repository: `python3 evals/adoption/agents/adopter_repo.py <dir>`) are prompts for an
LLM agent that gets only this repository's `README.md` and `docs/` plus `--help` — no source
reading. Fill the placeholders (`{WORKDIR}` an empty work directory — for `pack-author` and
`adopter` a prepared repository, described at the top of the prompt — `{VENV}` a venv with
modsys installed, `{DOCS}` a directory with copies of `README.md` and `docs/`), run each prompt
2–3 times per phase, and score the friction logs with `agents/rubric.md` (its `pack-author` and
`adopter` sections list the checks the scorer runs in the final repository).
