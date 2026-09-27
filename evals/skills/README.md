# Skill evals

Do the built-in skills (`core`, `ui`, `qa` — [docs/skills.md](../../docs/skills.md)) fire on the
requests they are written for, and do the writers produce their result? These cases answer it
with `claude plugin eval`, the Claude Code eval runner: each case is a realistic request in a
prepared repository, scored by graders on what the agent did.

The unit suite checks the skills' STRUCTURE (`tests/test_builtin_skills.py`) and these cases'
shape (`tests/test_skill_evals.py`); it never runs `claude`. The evals measure BEHAVIOUR and cost
money: every run is a real, billed model call.

## Cases

| Case | Kind | Passes when |
|---|---|---|
| `<skill>/trigger` — one per skill (10) | trigger | the agent invoked that skill (`Skill` tool, grader `skill-fired`) and ran its primary modsys verb (`Bash`, grader `ran-modsys`) |
| `module-sync/outcome` | outcome | the catalog's module doc names the new `BarcodeScanner`; `sync-instructions` ran |
| `module-create/outcome` | outcome | `modules/wishlist/MODULE.md` was created and the registry lists `wishlist`; `create wishlist` ran |
| `module-split/outcome` | outcome | `MODULE.legacy.md` and the `search` child's doc were created; `create … --parent` ran |
| `negative/unrelated` | negative | an ISBN coding question fires no skill (`Skill` called 0 times, scored in both arms) and gets code |

Every case starts from `scaffold.sh`: a git copy of `tests/fixtures/bookshop` with
`[packs] builtin = ["core", "ui", "qa"]` and one routing rule, committed; a case's own `seed.sh`
adds its starting change (a new component, a long doc, a broken registry entry, a UI edit).

## Running them

```bash
python3 evals/skills/run.py --dry-run                 # assemble the plugin, print the command
python3 evals/skills/run.py                           # the gate: every case, the flags below
python3 evals/skills/run.py --case module-scout-trigger --runs 1 --ablation none \
  --threshold 0.5 --max-cost-usd 5 --allow-tools Bash Write Edit --trust-plugin --no-publish
```

`run.py` assembles a plugin in a work directory (`--out DIR`, else a new temporary one) — the
built-in skills under `skills/`, these cases under `evals/` with their scaffold, and a runtime
with this engine, the fixture and a `modsys` launcher — and runs `claude plugin eval` on it with
the launcher first on `PATH`, so the agent's sandboxed shell runs this checkout's modsys. Without
flags it uses the gate flags: `--ablation none --runs 2 --threshold 0.5 --max-cost-usd 20
--allow-tools Bash Write Edit --trust-plugin --no-publish`, plus `--scaffold` and `--json
<out>/result.json` always. It prints one line per case (score, cost, how many runs fired the
skill, the first run error) and the overall score.

The gate passes with exit `0` and an overall score of at least 0.8. Exit `2` (a cost ceiling hit,
a rejected credential) or a run error such as an unavailable service is "not run", never a pass.

Requirements: Claude Code 2.1.269 or later, logged in; git 2.31 or later; a Python outside your
home directory (the sandbox cannot read your home, so neither the runtime nor the interpreter
may live there). The Bash sandbox refuses to start — every Bash-granting case then ends with a
run error — when a credential store under your home holds a symbolic link, e.g. Docker Desktop's
`~/.docker/cli-plugins/`; run the evals where that is not the case (a CI runner, another
account).
