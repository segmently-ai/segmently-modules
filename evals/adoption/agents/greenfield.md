# E-B blind agent — greenfield

Placeholders, filled by whoever runs the eval: `{WORKDIR}` an empty directory for this run,
`{VENV}` a virtualenv with modsys installed (`{VENV}/bin/modsys`), `{DOCS}` a directory with
copies of the engine's `README.md` and `docs/`. Everything below the line is the prompt.

---

You are a developer starting a NEW project, and you want to use **modsys** — a module registry
and context layer for AI coding agents — from day one.

**Project:** a small todo API with three features: tasks, lists and reminders. Plain Python
stubs are enough (a file or two per feature); no framework, no tests needed.

**Tools and rules**

- Work only in `{WORKDIR}`; make it a git repository first. modsys is installed:
  `{VENV}/bin/modsys` (activate `{VENV}` or call it by that path).
- The documentation is every file under `{DOCS}` plus the output of `modsys --help` and
  `modsys <verb> --help`. Nothing else.
- Do NOT read modsys's source code (the installed package, site-packages or any checkout). If
  you are truly blocked, you may look at the source ONCE: log it as a **source peek** (the file
  and what you needed from it), then continue.
- Time box: about 40 commands (every shell command counts).

**Goal steps**

1. Bootstrap modsys in the repository and register the three features as modules, with their
   docs.
2. Connect the modules to their code, so that a change to a code file is recognised as a change
   to its module. Verify it with a command.
3. Record typed relations between the modules (for example: reminders depend on tasks).
   `modsys lint` must report no errors.
4. Split a child module off one module (for example `tasks/search`) with its own code, and
   verify that its code maps to the child — not to the parent.
5. Run the agent loop on a small task, "add a priority field to tasks": read the context an
   agent would read before planning, make the code change and commit it, let the drift gate
   catch the docs that did not change, update the docs through the proposals flow (agents never
   edit docs directly), and show the gate passing.

**Friction log** — keep `{WORKDIR}/FRICTION.md` up to date as you go:

- `## Log` — numbered entries: the command(s), what you expected, what happened, and the
  severity of any friction: **blocker** (you could not continue without a source peek or
  outside help), **major** (it cost several commands or a wrong turn), **minor** (wording,
  cosmetics).
- `## Summary` — goal steps completed (by number), total commands, source peeks (each with the
  file and why, or "0"), blockers / majors / minors one line each, the top 3 improvements for
  the tool's authors, and any docs that were wrong or misleading.
