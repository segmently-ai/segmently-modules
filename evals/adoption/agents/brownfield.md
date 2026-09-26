# E-B blind agent — brownfield

Placeholders, filled by whoever runs the eval: `{WORKDIR}` an empty directory for this run,
`{VENV}` a virtualenv with modsys installed (`{VENV}/bin/modsys`), `{DOCS}` a directory with
copies of the engine's `README.md` and `docs/`. Everything below the line is the prompt.

---

You are a developer on an EXISTING Python web API, and you want to adopt **modsys** — a module
registry and context layer for AI coding agents — for it.

**Repository:** clone `https://github.com/nsidnev/fastapi-realworld-example-app` into
`{WORKDIR}/app` and check out commit `029eb77`:

```bash
git clone https://github.com/nsidnev/fastapi-realworld-example-app {WORKDIR}/app
git -C {WORKDIR}/app checkout -q 029eb77
```

The code is layered — routes, repositories, models, services, SQL queries and tests — and each
layer is split by feature.

**Tools and rules**

- Work only in `{WORKDIR}/app`. modsys is installed: `{VENV}/bin/modsys` (activate `{VENV}` or
  call it by that path).
- The documentation is every file under `{DOCS}` plus the output of `modsys --help` and
  `modsys <verb> --help`. Nothing else.
- Do NOT read modsys's source code (the installed package, site-packages or any checkout). If
  you are truly blocked, you may look at the source ONCE: log it as a **source peek** (the file
  and what you needed from it), then continue.
- Time box: about 45 commands (every shell command counts).

**Goal steps**

1. Put modsys into the repository and register one module per real feature of the app (find
   them in the code layout), plus a module for any shared layer that deserves its own docs.
2. Connect the modules to their code, so that a change to any file of a feature maps to that
   feature's module — and only to it: a feature's repository or query file must not also count
   as a change to a shared persistence module. Report the mapping coverage of the repository's
   files (the mapped share and what stays unmapped); aim for at least 80 %.
3. `modsys lint` reports no errors.
4. Run the agent loop on a real task, "add limit/offset pagination to the comments list
   endpoint": read the context an agent would read before planning, make the code change and
   commit it, let the drift gate catch the docs that did not change (for the module you changed
   only), update the docs through the proposals flow (agents never edit docs directly), and
   show the gate passing.

**Friction log** — keep `{WORKDIR}/FRICTION.md` up to date as you go:

- `## Log` — numbered entries: the command(s), what you expected, what happened, and the
  severity of any friction: **blocker** (you could not continue without a source peek or
  outside help), **major** (it cost several commands or a wrong turn), **minor** (wording,
  cosmetics).
- `## Summary` — goal steps completed (by number), total commands, source peeks (each with the
  file and why, or "0"), the final mapping coverage, blockers / majors / minors one line each,
  the top 3 improvements for the tool's authors, and any docs that were wrong or misleading.
