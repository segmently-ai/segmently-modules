# Security policy

## Supported versions

Security fixes go into the latest 0.x minor release.

## Reporting a vulnerability

Report it privately, never in a public issue:

- GitHub's **Report a vulnerability** button on the Security tab of this repository (private
  vulnerability reporting), or
- email `leonid@segmently.ai`.

You get an acknowledgement within 5 working days. Please include the version
(`segmently-modules --version`), what you ran and what happened.

## Trust model

- The command line runs locally, with the rights of the user who runs it. It makes no network
  call itself; the one exception is `init finish --open-pr` (and `init resume --open-pr`), which
  runs `git push origin` and `gh pr create` for the branch it made.
- A repository can run commands of its own: a `[[hooks.post_sync]]` hook in its team config or
  in a pack it installs runs on `segmently-modules sync` with your environment (`sync --dry-run`
  runs none), the way a build script of that repository runs. Review a repository's
  `.segmently-modules/` before you run `sync` in it, as you would review its build scripts.
- The agent command (`SEGMENTLY_MODULES_AGENT_COMMAND`) is read only from your environment, never
  from a config file. A `[match] mode` that a config file sets runs it only when you also set
  `SEGMENTLY_MODULES_AGENT_ALLOW_REPO_MODE=1`; `--match` and `choose --run` are your own requests.
  Details: [docs/configuration.md](docs/configuration.md).
