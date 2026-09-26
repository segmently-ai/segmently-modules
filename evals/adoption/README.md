# Adoption evals

Two ways to measure whether a team (or an agent) can put modsys into a repository using only
what ships: a deterministic script (E-A) and blind-agent runs (E-B).

## E-A — deterministic (`run_eval.py`)

```bash
python3 evals/adoption/run_eval.py      # from the engine checkout; exit 0 = every step passed
```

It builds two repositories from nothing in temp dirs and drives this checkout's CLI
(`python -m modsys`) through adoption. No network: the brownfield app is generated.

| Scenario | Steps |
|---|---|
| greenfield | `git init` → a missing registry names `modsys init` → `init` (and again: nothing changes) → 3 modules → `[[code_map]]` → a relation via `registry append` (a bad edge is refused) → lint clean → coverage 100 % → `context` returns `code_globs` → commit → code-only change: `lint --changed --fail-on warning` exits 1 with MS050 → `propose` a `doc_append` → `sync --from-diff --apply-proposals` → commit: gate exits 0 → a child module mapped by its own exclusive rule |
| brownfield | a generated layered app (`app/routes/<f>/`, `app/repositories/<f>.py`, `app/models/<f>.py`, `app/sql/<f>.sql`, `tests/test_<f>.py`, an `app/db/` layer) → `init` keeps `.gitignore` → baseline coverage → a module per feature + `db` → layered rules with `exclusive` → coverage ≥ 80 % → a feature repository maps only to its feature → a feature change drifts only the feature (MS050, `discover`) → `index split` + per-module layout keep `list` / `match` |

Every step checks an exit code and the data. The scorecard on stdout:

```json
{"greenfield": {"steps": [{"name": "init", "ok": true, "detail": "…"}], "commands": 21, "ok": true},
 "brownfield": {"steps": ["…"], "commands": 18, "ok": true}}
```

`commands` counts modsys invocations. A scenario stops at its first failed step; the script
exits 1. `tests/test_adoption_eval.py` runs it with the unit tests.

## E-B — blind agents (`agents/`)

`agents/greenfield.md` and `agents/brownfield.md` are prompts for an LLM agent that gets only
this repository's `README.md` and `docs/` plus `--help` — no source reading. Fill the
placeholders (`{WORKDIR}` an empty work directory, `{VENV}` a venv with modsys installed,
`{DOCS}` a directory with copies of `README.md` and `docs/`), run each prompt 2–3 times per
phase, and score the friction logs with `agents/rubric.md`.
