# Contributing to Segmently Modules

Thank you for helping. This file says how the code is kept and how a change gets in.

## Principles

- Python ≥ 3.11, stdlib only: Segmently Modules has no runtime dependency, and a change does not
  add one.
- The command line is a contract. [`docs/cli-contract.md`](docs/cli-contract.md) describes every
  verb's JSON output, exit codes and messages; pipelines and the skills parse them. A change to the
  contract is deliberate: the doc and a `CHANGELOG.md` line come in the same change.
- Docs, messages, code comments and commit messages are in English.

## Running it from a checkout

No install is needed:

```bash
python3 -m segmently_modules --help
python3 -m segmently_modules lint --root tests/fixtures/bookshop
```

## Tests

- Run the tests of what you touched: `python3 -m unittest tests.test_<area>`.
- The whole suite, `python3 -m unittest discover -s tests -t .`, takes about 35 minutes; CI runs it on
  Python 3.11 and 3.14 for every pull request.
- The adoption eval, `python3 evals/adoption/run_eval.py`, replays scripted adoption scenarios
  against the command line; CI runs it too.

The skill texts under `segmently_modules/defaults/packs/` follow rules the tests enforce:

- every command a skill names is parsed by the real parser;
- a command whose output a skill reads carries `--json`, and a write is shown first with `--dry-run`;
- a skill's `description` is at most 600 characters, and all of them together at most 7,000.

## Pull requests

1. Work on a branch and keep the change to one subject.
2. Add or update the tests that pin the behaviour; CI must be green.
3. Add one line under `## [Unreleased]` in `CHANGELOG.md` for every change a user can see.

Releases are maintainers' work: [`docs/releasing.md`](docs/releasing.md).

## License

By contributing you agree that your contribution is licensed under the MIT License of this
repository ([LICENSE](LICENSE)).
