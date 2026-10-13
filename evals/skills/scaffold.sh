#!/usr/bin/env bash
# The workspace of every skill eval case: a git copy of the bookshop fixture with the engine's
# built-in packs core, ui and qa enabled and one routing rule (src/<module>/ belongs to the
# module), committed. run.py writes this file into each case as scaffold.sh,
# with @RUNTIME@ replaced by the directory that holds the fixture and the engine, and appends the
# case's own seed.sh (the change or state the case starts from).
set -euo pipefail
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
export GIT_AUTHOR_NAME=eval GIT_AUTHOR_EMAIL=eval@example.invalid
export GIT_COMMITTER_NAME=eval GIT_COMMITTER_EMAIL=eval@example.invalid
cp -R "@RUNTIME@/fixture/." .
printf '[packs]\nbuiltin = ["core", "ui", "qa"]\n\n[[code_map]]\nid = "src"\npattern = "src/{module}/**"\n' \
  > .segmently-modules/config.toml
git init -q -b main
git add -- .segmently-modules modules src
git commit -q -m "bookshop"
