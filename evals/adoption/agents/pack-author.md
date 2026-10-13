# E-B blind agent — pack author

Placeholders, filled by whoever runs the eval: `{WORKDIR}` a git repository prepared for this
run — a copy of the engine's `tests/fixtures/bookshop` (a bookshop registry with the modules
`catalog`, `checkout`, `payments` and the pack `bookshop`) plus a `CLAUDE.md` holding
`# Bookshop` and the line `Team notes: run the tests before every push.`, committed once;
`{VENV}` a virtualenv with Segmently Modules installed (`{VENV}/bin/segmently-modules`); `{DOCS}` a directory with
copies of the engine's `README.md` and `docs/`. Everything below the line is the prompt.

---

You maintain a repository that already uses **Segmently Modules** — a module registry and context layer
for AI coding agents. Your team wants its own conventions in it: a module-doc audience for API
reviewers, and an agent skill that reviews API changes by reading those docs.

**Tools and rules**

- Work only in `{WORKDIR}` (a git repository; Segmently Modules is already set up there). Segmently Modules is
  installed: `{VENV}/bin/segmently-modules` (activate `{VENV}` or call it by that path).
- The documentation is every file under `{DOCS}` plus the output of `segmently-modules --help` and
  `segmently-modules <verb> --help`. Nothing else.
- Do NOT read Segmently Modules' source code (the installed package, site-packages or any checkout). If
  you are truly blocked, you may look at the source ONCE: log it as a **source peek** (the file
  and what you needed from it), then continue.
- Time box: about 35 commands — one shell invocation is one command, even chained with `&&`,
  `;` or a pipe; a read through a dedicated read tool is not a command (log it separately).

**Goal steps**

1. Add your team's own pack with a custom role for API reviewers and an agent skill that reads
   that role's module docs. `segmently-modules lint` must report no problem with the pack.
2. Add a new module (for example, book reviews) that has a doc for the new role, and show with
   a command that an agent can find and read that doc through Segmently Modules.
3. Put the skill where Claude Code and where Codex read skills, and run the check a CI job
   would run to prove those copies are current.
4. The team wants its own wording of the skill, which later versions of the pack must never
   overwrite: take the skill over, change its steps, and get both agents' copies updated.
5. Tell the agents about Segmently Modules in `CLAUDE.md` and `AGENTS.md` without losing the team's notes
   already in `CLAUDE.md`, and show that running it again changes nothing.

**Friction log** — keep `{WORKDIR}/FRICTION.md` up to date as you go:

- `## Log` — numbered entries: the command(s), what you expected, what happened, and the
  severity of any friction: **blocker** (you could not continue without a source peek or
  outside help), **major** (it cost several commands or a wrong turn), **minor** (wording,
  cosmetics).
- `## Summary` — goal steps completed (by number), total commands, source peeks (each with the
  file and why, or "0"), blockers / majors / minors one line each, the top 3 improvements for
  the tool's authors, and any docs that were wrong or misleading.
