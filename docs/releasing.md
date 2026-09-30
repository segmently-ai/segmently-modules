# Releasing the plugins

> For maintainers of modsys itself. Using modsys: [README](../README.md).

modsys reaches agents as three plugins — `modsys` (the `core` skills and the command line),
`modsys-ui` and `modsys-qa` — built from this repository and published in a separate **publish
repository** that holds the marketplaces. Nothing here pushes unless you pass `--push`, and the
publish repository on GitHub is created by its owner, never by these tools.

## Build

```bash
python3 tools/build_plugins.py                    # dist/plugins/{modsys,modsys-ui,modsys-qa}
python3 tools/build_plugins.py --out /tmp/plugins --version 0.2.0
```

| Plugin | Holds |
|---|---|
| `modsys` | `skills/` = the `core` pack's skills; `bin/modsys` (the launcher, mode 0755); `runtime/modsys/` = the files git tracks under `modsys/`, byte for byte |
| `modsys-ui` | `skills/` = the `ui` pack's skill; depends on `modsys` (Claude Code installs it too) |
| `modsys-qa` | `skills/` = the `qa` pack's skills; depends on `modsys` |

Each plugin has three manifests — `.claude-plugin/plugin.json` (Claude Code), `plugin.json` (the
Agent Plugins manifest Codex reads) and `.codex-plugin/plugin.json` — and a `README.md`, all
rendered from one table in the builder. The build reads git's index and the work tree, never an
installed copy: an untracked file never ships, a file's mode comes from the index, and nothing
carries a timestamp — two builds of one tree are byte-identical. A refusal (not a git work
tree, a tracked file missing, a symlink in a skill, a `--version` that is not SemVer 2.0) is
exit 2 and leaves `--out` as it was.

`bin/modsys` (source: `tools/launcher.sh`, POSIX `sh`) runs the plugin's own engine with the
first Python 3.11 or newer it finds: `MODSYS_PYTHON`; `python3.14` … `python3.11`, `python3` on
`PATH`; the same names in `/opt/homebrew/bin`, `/usr/local/bin`, `/usr/bin` (one directory at a
time — they work where a sandbox denies the home directory); then `uv run`. Nothing found is
exit 127 naming the three ways out; an unusable `MODSYS_PYTHON` is exit 127 too — never a
silent fall-through.

## Channels, versions, tags

| Channel | Branch of the publish repository | Marketplace | Version |
|---|---|---|---|
| `stable` | `stable` | `modsys` | `X.Y.Z` |
| `dev` | `dev` | `modsys-dev` | `X.Y.Z-dev.h<8 hex>` |

One version source: `__version__` in `modsys/__init__.py` (`pyproject.toml` holds the same
string; a test keeps them equal). `stable` stamps it without its `.devN` suffix; `dev` adds the
content hash of the three plugin trees without their manifests, so rebuilding the same tree is
the same version. A version lives only in the plugins' manifests, never in a marketplace entry.
A stable release tags the publish repository `v<version>` and, per plugin,
`<plugin>--v<version>` (the format `claude plugin tag` makes, annotated), and this repository
`v<version>` on its release commit. The plugin's command line reports the engine's own version:
`modsys 0.1.0` on `stable`, the `.devN` form on `dev`.

```bash
python3 tools/publish.py --channel dev --out /tmp/publish   # a publish tree to look at
```

lays out `plugins/` with both marketplace files — `.claude-plugin/marketplace.json` and
`.agents/plugins/marketplace.json` (Codex) — without touching any repository.

## Release

```bash
MODSYS_GUARD=/path/to/the/private/guard.py python3 tools/release.py \
    --publish-repo ../publish-repo --channel dev --publish-slug <owner>/<publish repo>
```

| Step | What it does |
|---|---|
| 1 leak guard | the private guard `MODSYS_GUARD` names reports this repository clean (files and history), and the organisation of `--publish-slug` appears nowhere in it |
| 2 clean trees | this repository and the publish repository have no uncommitted change; for `stable` the version is not tagged yet in either |
| 3 tests | the unit suite and the adoption eval |
| 4 build | `stable`: the release commit here (`X.Y.Z.devN` → `X.Y.Z`); then the three plugins with the channel's version |
| 5 validate | the guard and the organisation scan over the build; our checks of the publish tree; `claude plugin validate --strict` of each plugin and the marketplace |
| 6 publish repo | on the channel's branch: exactly `plugins/modsys`, `plugins/modsys-ui`, `plugins/modsys-qa` replaced, both marketplace files merged by plugin name, its own sections of `README.md` and `CHANGELOG.md` |
| 7 commit | `release modsys <version> (<channel>)`; `stable` adds the tags |
| 8 smoke install | a throw-away `CLAUDE_CONFIG_DIR`: add the marketplace, install `modsys-ui` (its dependency `modsys` comes with it) and `modsys-qa`, check the nine core skills, run the installed `bin/modsys --version` and `lint` on the bookshop fixture — no model call |

Then, for `stable`, the commit that starts the next version here (`X.Y.(Z+1).dev0`). A build
the channel already holds is "nothing to release" (exit 0, nothing committed). **All or
nothing:** a failed step or Ctrl-C puts both repositories back — branches, tags, HEAD, work
tree — and removes every temp directory. Exit `0` done · `1` a step failed · `2` a refusal ·
`130` interrupted.

- **The guard.** `MODSYS_GUARD` names the private leak guard — a script the host project keeps
  outside this repository, run as `<python> <guard> --target DIR`; it must exit 0 and print a
  `… CLEAN` line. It is never copied here: a path inside this repository is refused.
- **No repository slug before the public release.** The organisation of `--publish-slug` must
  appear nowhere in this repository (files, history) or in the build; the slug is written only
  into the publish repository's own README section. Docs here use `<owner>/<repo>`.
- **The publish repository is shared ground.** Entries, plugins and text the release does not
  own are kept as they are; a marketplace file that is not valid JSON, or a `README.md` that is
  not a regular file, fails the step instead of being overwritten.
- **Without `claude` on `PATH`** steps 5 and 8 skip the Claude Code checks and say so; `--push`
  is then refused.
- **`--push`** pushes the channel branch (and the tags) of the publish repository, then this
  repository's branch and `v<version>` — an owner command, each time. Creating the publish
  repository on GitHub is the owner's as well.

## Before a stable release: the skill evals

Evals are model calls, so they run before a stable release, as subagents of a Claude Code
session — never in a pipeline:

- the outcome cases of every skill whose files changed since the last `v<version>` tag (the
  first stable release: all of them — `module-sync`, `module-create`, `module-split` from
  `evals/skills/<skill>/outcome/prompt.md`, their graders read as assertions; `module-adopt`
  and `module-init` from their `evals.json`): the with-skill pass rate is at least 0.8 per
  skill and not below the run without the skill;
- the trigger check over the twelve skill descriptions (a judge subagent, three shuffled runs):
  should-trigger at least 0.8 and false-trigger at most 0.1 on the held-out 40 %.

A description is never changed after its trigger check passed. `evals/skills/README.md` says how
to run the `claude plugin eval` suite by hand on a machine that allows it.

## CI

`.github/workflows/ci.yml` runs on every push to any branch (so on every commit of a pull
request from a branch of the repository), on Python 3.11 and 3.14: the unit suite, the adoption
eval, two plugin builds compared byte for byte, the launcher test under `dash`, and — with
Claude Code installed as it comes, without credentials — `claude plugin validate --strict` on
the three plugins and the dev marketplace plus a throw-away install (`CLAUDE_CONFIG_DIR` in the
runner's temp directory). It makes no model call and reads no secret; nothing runs on a
schedule. The private guard is not part of CI — the release and the `pre-push` hook run it —
and neither are the skill evals (above). The release repeats the validation and runs the full
smoke install, so a CI run without Claude Code would lose nothing the release does not check
again.
