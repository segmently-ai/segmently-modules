# E-B blind agent — adopter

Placeholders, filled by whoever runs the eval: `{WORKDIR}` a git repository built by
`python3 evals/adoption/agents/adopter_repo.py {WORKDIR}` from the engine checkout — a bookshop
warehouse app (modules `inventory`, `orders`, `shipping`, `loyalty` with the child
`loyalty/rewards`) whose `modules/registry.json` and module docs another tool wrote: extra
fields, a role of its own, a timestamp key, no `.segmently-modules/`, committed once; `{VENV}` a
virtualenv with Segmently Modules installed (`{VENV}/bin/segmently-modules`); `{DOCS}` a directory with copies of the
engine's `README.md` and `docs/`. Everything below the line is the prompt.

---

You maintain a repository whose module registry (`modules/registry.json`) and module docs were
written by another tool your team used before. Now the team wants to use **Segmently Modules** — a module
registry and context layer for AI coding agents — on the same registry, without rewriting it.

**Tools and rules**

- Work only in `{WORKDIR}` (a git repository). Segmently Modules is installed: `{VENV}/bin/segmently-modules`
  (activate `{VENV}` or call it by that path).
- The documentation is every file under `{DOCS}` plus the output of `segmently-modules --help` and
  `segmently-modules <verb> --help`. Nothing else.
- Do NOT read Segmently Modules' source code (the installed package, site-packages or any checkout). If
  you are truly blocked, you may look at the source ONCE: log it as a **source peek** (the file
  and what you needed from it), then continue.
- Time box: about 35 commands — one shell invocation is one command, even chained with `&&`,
  `;` or a pipe; a read through a dedicated read tool is not a command (log it separately).

**Goal steps**

1. Make Segmently Modules read this registry as it is: the registry file and the module docs must stay
   exactly as they are (other tooling still writes them).
2. Keep whatever configuration that takes in the repository, committed.
3. Get `segmently-modules lint` clean — no error and no warning — without editing the registry or a doc.
4. Show with commands that an agent asking Segmently Modules about a module gets that module's code
   locations, and that every module of the registry is listed.

**Friction log** — keep `{WORKDIR}/FRICTION.md` up to date as you go:

- `## Log` — numbered entries: the command(s), what you expected, what happened, and the
  severity of any friction: **blocker** (you could not continue without a source peek or
  outside help), **major** (it cost several commands or a wrong turn), **minor** (wording,
  cosmetics).
- `## Summary` — goal steps completed (by number), total commands, source peeks (each with the
  file and why, or "0"), blockers / majors / minors one line each, the top 3 improvements for
  the tool's authors, and any docs that were wrong or misleading.
