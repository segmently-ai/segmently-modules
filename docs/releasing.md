# Releasing the plugins

> For maintainers of Segmently Modules itself. Using Segmently Modules: [README](../README.md).

Segmently Modules reaches agents as three plugins — `segmently-modules` (the `core` skills and the command line),
`segmently-modules-ui` and `segmently-modules-qa` — built from this repository and published in a separate **publish
repository** that holds the marketplaces: this repository is `segmently-ai/segmently-modules`,
the publish repository `segmently-ai/segmently-modules-plugins`. Nothing here pushes unless you
pass `--push`, and the publish repository on GitHub is created by its owner, never by these tools.

## Build

```bash
python3 tools/build_plugins.py                    # dist/plugins/{segmently-modules,segmently-modules-ui,segmently-modules-qa}
python3 tools/build_plugins.py --out /tmp/plugins --version 0.2.0
```

| Plugin | Holds |
|---|---|
| `segmently-modules` | `skills/` = the `core` pack's skills; `bin/segmently-modules` (the launcher, mode 0755); `runtime/segmently_modules/` = the files git tracks under `segmently_modules/`, byte for byte |
| `segmently-modules-ui` | `skills/` = the `ui` pack's skill; depends on `segmently-modules` (Claude Code installs it too) |
| `segmently-modules-qa` | `skills/` = the `qa` pack's skills; depends on `segmently-modules` |

Each plugin has three manifests — `.claude-plugin/plugin.json` (Claude Code), `plugin.json` (the
Agent Plugins manifest Codex reads) and `.codex-plugin/plugin.json` — and a `README.md`, all
rendered from one table in the builder. The build reads git's index and the work tree, never an
installed copy: an untracked file never ships, a file's mode comes from the index, and nothing
carries a timestamp — two builds of one tree are byte-identical. A tracked file with
uncommitted changes ships as it is on disk; one `warning:` line names such files. The builder
replaces only its own output: an `--out` whose `segmently-modules`, `segmently-modules-ui` or `segmently-modules-qa` is not an
earlier build of that plugin — or is this repository, or holds it (`--out ..` from the
checkout) — is refused. The three directories are renamed into place together at the end, so
a refusal (not a git work tree, a tracked file missing, a symlink in a skill, a `--version`
that is not SemVer 2.0, git missing), a failure or Ctrl-C is exit 2 (130) and leaves `--out`
as it was — a missing `--out` is not even created.

`bin/segmently-modules` (source: `tools/launcher.sh`, POSIX `sh`) runs the plugin's own engine with the
first Python 3.9 or newer it finds: `SEGMENTLY_MODULES_PYTHON`; `python3.14` … `python3.9`, `python3` on
`PATH`; the same names in `/opt/homebrew/bin`, `/usr/local/bin`, `/usr/bin` (one directory at a
time — they work where a sandbox denies the home directory); then `uv run`. Nothing found is
exit 127 naming the three ways out; an unusable `SEGMENTLY_MODULES_PYTHON` is exit 127 too — never a
silent fall-through — and so is a plugin without its `runtime/`. The engine runs through a
`python -c` line that drops the working directory from that process's `sys.path` (what `-P`
does from 3.11) and then runs the package: the working directory never shadows the plugin's
engine, while an executor or a hook the engine starts imports its own modules as it would
anywhere.

## Channels, versions, tags

| Channel | Branch of the publish repository | Marketplace | Version |
|---|---|---|---|
| `stable` | `stable` | `segmently-modules` | `X.Y.Z` |
| `dev` | `dev` | `segmently-modules-dev` | `X.Y.Z-dev.h<8 hex>` |

One version source: `__version__` in `segmently_modules/__init__.py` (`pyproject.toml` holds the same
string; a test keeps them equal). `stable` stamps it without its `.devN` suffix; `dev` adds the
content hash of the three plugin trees without their manifests, so rebuilding the same tree is
the same version. A version lives only in the plugins' manifests, never in a marketplace entry.
A stable release tags the publish repository `v<version>` and, per plugin,
`<plugin>--v<version>` (the format `claude plugin tag` makes, annotated), and this repository
`v<version>` on its release commit. The plugin's command line reports the engine's own version:
`segmently-modules 0.1.0` on `stable`, the `.devN` form on `dev`.

```bash
python3 tools/publish.py --channel dev --out /tmp/publish   # a publish tree to look at
```

lays out `plugins/` with both marketplace files — `.claude-plugin/marketplace.json` and
`.agents/plugins/marketplace.json` (Codex) — without touching any repository.

## Release notes

Before a stable release write its notes in `CHANGELOG.md`, as lines under the `## [Unreleased]`
heading (Keep a Changelog style); a note is a line starting with `- ` or `* `. A stable release
is refused without one (blank lines, comment lines and `### ` sub-headings alone hold no note),
when `CHANGELOG.md` is missing or git does not track it, and when `SEGMENTLY_MODULES_RELEASE_DATE` is set
but is not a date. The release commit dates the section: `## [Unreleased]` becomes
`## [X.Y.Z] - DATE` below a new, empty `## [Unreleased]`; set `SEGMENTLY_MODULES_RELEASE_DATE=YYYY-MM-DD`
for a fixed date, else the local date is used. The notes also go into the publish repository's
changelog entry. A dev release publishes the pending `[Unreleased]` lines, or `no notes yet`
when there are none.

The published notes are the lines under the heading up to the next `## ` heading, without blank
lines and without comment lines: a comment line — one whose text starts with `<!--`, through the
line that holds its `-->` — is dropped; a `<!--` inside a line of text is kept as written. On
either channel, dev as well as stable, the release is refused when `CHANGELOG.md` holds two
`## [Unreleased]` headings (the error names their lines: keep one), and when a note holds
`<!-- segmently-modules:changelog:` — the marker of the publish repository's changelog section, which the
entry would damage: reword that note.

## Release

```bash
SEGMENTLY_MODULES_GUARD=/path/to/the/private/guard.py python3 tools/release.py \
    --publish-repo ../segmently-modules-plugins --channel dev \
    --publish-slug segmently-ai/segmently-modules-plugins
```

| Step | What it does |
|---|---|
| 1 leak guard | first the notes check: the notes under `## [Unreleased]` in `CHANGELOG.md` — `stable` needs at least one note (a tracked file; `SEGMENTLY_MODULES_RELEASE_DATE`, when set, a date), `dev` publishes `no notes yet` without; two `## [Unreleased]` headings or a note holding the changelog marker are refused on both (see Release notes); then the private guard `SEGMENTLY_MODULES_GUARD` names reports this repository clean (files and history), and the organisation of `--publish-slug` appears in it only in the two public slugs |
| 2 clean trees | this repository and the publish repository have no uncommitted change; for `stable` the version is not tagged yet in either; with `--suite-passed TREE`, TREE is this repository's `HEAD^{tree}` |
| 3 tests | the unit suite — each `tests/test_*.py` module in its own process, `--jobs N` at a time — and the adoption eval (see Step 3 below) |
| 4 build | `stable`: the release commit here (`X.Y.Z.devN` → `X.Y.Z`, and in `CHANGELOG.md` the `## [Unreleased]` heading becomes `## [X.Y.Z] - DATE` below a new, empty `## [Unreleased]`; every `segmently-modules.git@vX.Y.Z` install pin in `README.md` → `X.Y.Z`); then the three plugins with the channel's version |
| 5 validate | the guard and the organisation scan (the same two slugs) over the build; our checks of the publish tree; `claude plugin validate --strict` of each plugin and the marketplace |
| 6 publish repo | on the channel's branch: exactly `plugins/segmently-modules`, `plugins/segmently-modules-ui`, `plugins/segmently-modules-qa` replaced, both marketplace files merged by plugin name, its own sections of `README.md` and `CHANGELOG.md` |
| 7 commit | `release segmently-modules <version> (<channel>)`; `stable` adds the tags |
| 8 smoke install | a throw-away `CLAUDE_CONFIG_DIR`: add the marketplace, install `segmently-modules-ui` (its dependency `segmently-modules` comes with it) and `segmently-modules-qa`, check the twelve core skills, run the installed `bin/segmently-modules --version` and `lint` on the bookshop fixture — no model call |

Then, for `stable`, the commit that starts the next version here (`X.Y.(Z+1).dev0`) — so
`stable` needs `__version__` = `X.Y.Z.devN` (step 2 says so otherwise). A build the channel
already holds is "nothing to release" (exit 0, nothing committed). The run leaves the publish
repository on the channel branch.

**Step 3.** The release runs each `tests/test_*.py` module in its own process (`<python> -m
unittest discover -s tests -p <module>.py` from this repository, `PYTHONDONTWRITEBYTECODE=1`, its
own process group), `--jobs N` at a time (1–32, default `min(4, CPU count)`) — any other value
is a usage error, exit 2 — the `test_release*` modules first (the longest), then the rest by name.
Every module runs to its end; the step says `Ran <N> tests in <M> modules (<J> jobs), OK` (with
`(skipped=<K>)` when tests were skipped), or fails naming each failing module with the last 600
characters of the first one's stderr. Ctrl-C, SIGTERM or a closed terminal during the suite kill
every running test process group before the put-back starts: SIGINT first, so a test runs its
clean-up (its temp directories go, a release it runs stops its own tests), then SIGKILL to the
groups after at most 2 s. A process a test moves to its own process group or session is reached
only through that test's clean-up: if the test ignores SIGINT, the SIGKILL of the test's group
does not reach it. Then the adoption eval.

`--suite-passed TREE` says the unit suite already passed on this tree — a gate ran it, so the
release need not run it again: TREE is the 40-hex tree id the gate printed (`git rev-parse
'HEAD^{tree}'` on the tree it tested). Step 2 checks it against this repository's `HEAD^{tree}`
and refuses anything else, writing nothing: `--suite-passed <TREE> is not this engine's tree
<tree> — leave the flag out and the suite runs`. With a matching TREE step 3 runs no unit test
and says `the unit suite passed on tree <first 12 hex> before (--suite-passed)`; the adoption
eval always runs, on both channels. A stable release's own commits come after step 3, so the
same TREE is accepted again after a put-back and refused after a finished stable release.

**The channel branch.** An existing local branch is used; a clone that has the branch only as
`origin/<channel>` gets a local branch made from it (tracking it); a local branch behind or
diverged from `origin/<channel>` is refused at step 2 — run `git pull` there first (the tool
never fetches: it compares with the refs the clone already has). A channel that exists nowhere
starts at the first commit behind the publish repository's HEAD that is not a release commit of
this tool (an empty branch when there is none): `dev` and `stable` start from the same commit
whatever is checked out, and neither holds the other's releases or changelog entries.

**All or nothing, up to the push:** a failed step, Ctrl-C, SIGTERM or a closed terminal (unless
the run was started ignoring it, as `nohup` does) puts back what the run wrote — the branches
and tags it made or moved, HEAD, the index and the files it writes — and removes every temp
directory. Nothing else is touched: a branch, a tag or an untracked file that appeared beside
the run stays. The put-back always finishes (a second Ctrl-C is ignored) and is checked: "both
repositories are as they were" is printed only when that is true; otherwise the message names
the repository, the command that failed and the refs to reset by hand (exit 1). Do not work in
either repository during a run: one that changed between step 2 and the run's first write to it
is a refusal that writes nothing there. Exit `0` done · `1` a step failed · `2` a refusal ·
`130` interrupted.

- **The guard.** `SEGMENTLY_MODULES_GUARD` names the private leak guard — a script the host project keeps
  outside this repository, run as `<python> <guard> --target DIR` from your working directory;
  it must exit 0 and print a `… CLEAN` line. Hits are its `<n> hit(s)` line; any other exit or
  a missing verdict is "the leak guard failed", with its last line. It is never copied here: a
  path inside this repository is refused.
- **Only the two public slugs.** The organisation of `--publish-slug` may appear in this
  repository (files, history) and in the build only as `<org>/segmently-modules` (this
  repository) and as the publish slug itself — whole slugs: a longer slug built on one
  (`<org>/segmently-modules-private`), any other slug of the organisation or the organisation
  alone is refused.
- **The README pin.** `README.md` pins the install lines to the latest stable release
  (`…/segmently-modules.git@vX.Y.Z`); the stable release commit moves every pin to its own
  version, so the README never names a release that is not out.
- **The publish repository is shared ground.** Entries, plugins and text the release does not
  own are kept as they are, with their line endings; a marketplace file that is not valid JSON,
  a `README.md` that is not a regular file, or section markers damaged by a hand edit fail the
  step instead of being overwritten, and a symlinked `plugins`, `.claude-plugin` or `.agents`
  is refused. The release commit must hold the build — every path, mode and byte — whatever
  the repository's ignore rules or `core.fileMode` say, or step 7 fails.
- **Without `claude` on `PATH`** steps 5 and 8 skip the Claude Code checks and say so; `--push`
  is then refused.
- **`--push`** pushes the channel branch (and the tags) of the publish repository, then this
  repository's branch and `v<version>` — an owner command, each time; it is refused before step 1
  when a repository it pushes has no `origin`. A failed or interrupted push is never put back:
  the release stays committed and tagged locally, and the tool prints what was pushed and the
  `git push` commands left to run. Without `--push` it prints the same commands at the end —
  that is how a finished release is pushed by hand (a second run does not push it: `dev` has
  nothing to release, `stable` would release the next version). Creating the publish
  repository on GitHub is the owner's as well.

## npm

`tools/build_npm.py [--out dist/npm] [--version V]` builds the package `@segmently/modules` from
this tree: `package.json`, `README.md`, `LICENSE`, `bin/segmently-modules` (the plugin's
launcher, `tools/launcher.sh`) and `runtime/segmently_modules/` (the tracked files, as the core
plugin carries them). Node runs nothing: npm puts the launcher on `PATH`, and the launcher runs
the engine with the first Python 3.9 or newer it finds (macOS and Linux). The engine's `X.Y.Z`
is npm's `X.Y.Z` on the dist-tag `latest`; `X.Y.Z.devN` is `X.Y.Z-dev.N` on `next`. Two builds of
one tree are byte-identical, and `--out` is replaced only when it holds an earlier build;
`tests/test_build_npm.py` packs the package, installs it with npm into a throw-away prefix and
runs it.

Publishing is a maintainer's step after a release, from a clone at the release tag:

```bash
git clone --branch vX.Y.Z https://github.com/segmently-ai/segmently-modules.git sm && cd sm
python3 tools/build_npm.py --out ../sm-npm       # prints the publish command with its dist-tag
npm publish ../sm-npm --tag latest               # --tag next for a dev version
```

Run the private leak guard over the built package first, as over the plugin build. npm asks
for the account's one-time password. A published version is never replaced: a wrong one is
deprecated (`npm deprecate @segmently/modules@X.Y.Z "<why>"`) and fixed by the next patch release.

## Before a stable release: the skill evals

Evals are model calls, so they run before a stable release, as subagents of a Claude Code
session — never in a pipeline:

- the outcome cases of every skill whose files changed since the last `v<version>` tag (the
  first stable release: all of them — `module-sync`, `module-create`, `module-split` from
  `evals/skills/<skill>/outcome/prompt.md`, their graders read as assertions; `module-adopt`
  and `module-init` from their `evals.json`): the with-skill pass rate is at least 0.8 per
  skill and not below the run without the skill;
- the trigger check over the fourteen skill descriptions (a judge subagent, three shuffled runs):
  should-trigger at least 0.8 and false-trigger at most 0.1 on the held-out 40 %.

A description is never changed after its trigger check passed. `evals/skills/README.md` says how
to run the `claude plugin eval` suite by hand on a machine that allows it.

## CI

`.github/workflows/ci.yml` runs on a push to `main`, on version tags (`v*`) and on pull requests
(a pull request's branch is not run twice). On macOS's own Python 3.9 (the floor, a virtual
environment of the Command Line Tools' `/usr/bin/python3`) it runs the unit suite and the
adoption eval, within 60 minutes. On Python 3.11 and 3.14, within 45 minutes: the unit
suite, the adoption eval, two plugin builds compared byte for byte, the launcher test under
`dash`, and — with Claude Code installed as it comes, without credentials — `claude plugin
validate --strict` on the three plugins and the dev marketplace plus a throw-away install
(`CLAUDE_CONFIG_DIR` in the runner's temp directory) that checks all three plugins are installed
and enabled and runs the installed `bin/segmently-modules --version`. It makes no model call and reads no
secret; nothing runs on a schedule. The private guard is not part of CI — the release and the
`pre-push` hook run it — and neither are the skill evals (above). The release repeats the
validation and runs the full smoke install, so a CI run without Claude Code would lose nothing
the release does not check again.
