"""`init finish` — gate 7 (D4): the staging tree becomes the registry and the module docs.

Interactive: a person has read `init status` and `verify.json`; `init finish` moves every new
module's staging docs to `<modules_dir>/<module>/` (the configured layout), adds its entry to
the registry through the registry writer (lock, the house serializer; in the per-module layout
its `module.json` and the rebuilt index), appends one `[[code_map]]` rule `init-<module>` (its
confirmed paths) per new module to `<config_dir>/config.toml` through the `code-map add` writer
(when that file exists), writes the managed block into `CLAUDE.md` / `AGENTS.md` (those that
exist; `--agents-md FILE` names others) and marks the state finished — all or nothing: a failed
or interrupted write puts back every file it touched. It never commits: it prints the `git add`
line. A module already in the registry is never moved or rewritten.

Refusals (exit 2, nothing written): already finished; reconcile never ran; verify not passed or
the staging tree changed since it (both overridden by `--force`, recorded in the state); a module
directory or registry entry that appeared since, a registry changed since reconcile, a
`[[code_map]]` id already taken (never overridden).

`--open-pr [--base B] [--branch modsys/init]`: needs `gh` on PATH, a git remote `origin` and a
tree with no change outside what the commit takes (the files above plus the starter files `init`
created); creates the branch from the current commit, commits every written file in ONE commit,
pushes it and runs `gh pr create` with the verify summary, the routing table and the judgement
items as the body. A failed push or `gh` keeps the commit on the branch, records `pr: "pending"`
and exits 1; `init resume --open-pr` retries only what is left."""
import contextlib
import json
import shutil
import subprocess
from pathlib import Path

from modsys.agents_md_cmd import _target, agents_md
from modsys.changes import git_env, work_tree_error
from modsys.code_map_cmd import _defined_in, add_rule
from modsys.config import load_config
from modsys.fields import load_field_defs
from modsys.init_overlay import code_map_rules
from modsys.init_verify import tree_sha
from modsys.layout import build_index
from modsys.output import UsageError
from modsys.store import atomic_write, open_store, serialize, utc_now
from modsys.workspace import Workspace

INSTRUCTION_FILES = ("CLAUDE.md", "AGENTS.md")


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                          errors="replace", env=git_env())


class Finish:
    def __init__(self, work):
        self.work, self.flow, self.root = work, work.flow, work.flow.root

    def workspace(self) -> Workspace:
        config = load_config(self.flow.config_dir, self.root)
        return Workspace(self.root, self.flow.config_dir, config, load_field_defs(config))

    # --- checks ---------------------------------------------------------------------------

    def check(self, state: dict | None, force: bool) -> tuple[dict, dict, list[str]]:
        """(state, the staging registry, the reasons a forced finish overrides)."""
        if state is None:
            raise UsageError("no init state — run modsys init map")
        if state["phases"]["finish"]["status"] == "done":
            raise UsageError("already finished — see modsys init status")
        staged = self.work.staging / "registry.json"
        if state["phases"]["reconcile"]["status"] != "done" or not staged.is_file():
            raise UsageError("reconcile has not run — run modsys init reconcile, then modsys init "
                             "verify")
        forced = []
        verify = None
        with contextlib.suppress(OSError, ValueError):
            verify = json.loads((self.flow.work / "verify.json").read_text(encoding="utf-8"))
        if state["phases"]["verify"]["status"] != "done" or not isinstance(verify, dict) \
                or verify.get("passed") is not True:
            forced.append("verify not passed")
        elif verify.get("staging_sha256") != tree_sha(self.work.staging):
            forced.append("staging changed since verify")
        if forced and not force:
            raise UsageError("verify has not passed — run modsys init verify"
                             if forced[0] == "verify not passed" else
                             "staging changed since verify — run modsys init verify")
        return state, json.loads(staged.read_text(encoding="utf-8")), forced

    def conflicts(self, ws, staged: dict, state: dict) -> list[str]:
        """Everything `finish` would overwrite: it never does."""
        mdir = ws.config["paths"]["modules_dir"]
        real = self.work.registry_modules()
        new = [m for m, e in sorted(state["modules"].items()) if not e.get("existing")]
        out = [f"{mdir}/{m}/ exists" for m in new if (self.root / mdir / m).exists()]
        out += [f"the registry already has '{m}'" for m in new if m in real]
        kept = {m: e for m, e in staged["modules"].items() if m not in new}
        changed = sorted(m for m in set(kept) | set(real)
                         if m not in new and serialize(kept.get(m, {})) != serialize(
                             real.get(m, {})))
        if changed:
            out.append(f"the registry changed since init reconcile ({', '.join(changed)}) — "
                       f"rerun modsys init reconcile")
        if (self.flow.config_dir / "config.toml").is_file():
            for rule in code_map_rules(self.work, state):
                owner = _defined_in(ws, rule["id"])
                if owner:
                    out.append(f"[[code_map]] '{rule['id']}' is already defined in {owner}")
        return out

    def targets(self, ws, agents_md_args: list[str]) -> list[str]:
        if agents_md_args:
            for target in agents_md_args:
                _target(ws, target)  # outside the root or a directory: exit 2
            return list(agents_md_args)
        return [t for t in INSTRUCTION_FILES if (self.root / t).is_file()]

    # --- the writes -----------------------------------------------------------------------

    def apply(self, state: dict, staged: dict, targets: list[str]) -> dict:
        """Move, register, map and tell the agents — or put everything back."""
        ws = self.workspace()
        paths = ws.config["paths"]
        new = [m for m, e in sorted(state["modules"].items()) if not e.get("existing")]
        registry = self.root / paths["registry"]
        touched = [registry, self.flow.config_dir / "config.toml",
                   *(self.root / t for t in targets)]
        if paths["registry_layout"] == "per-module":
            touched += [self.root / paths["modules_dir"] / m / paths["module_entry"] for m in new]
        saved = {p: p.read_bytes() if p.is_file() else None for p in touched}
        moved, created = [], []
        try:
            for m in new:
                base, final = self.work.staging_dir(m), f"{paths['modules_dir']}/{m}"
                docs = [(base / "MODULE.md", f"{final}/{paths['module_doc']}")]
                docs += [(d, f"{final}/roles/{d.name}") for d in sorted((base / "roles")
                                                                         .glob("*.md"))]
                for source, rel in docs:
                    created.append(self.root / rel)
                    atomic_write(self.root / rel, source.read_text(encoding="utf-8"))
                    moved.append(rel)
            with open_store(ws).edit() as reg:
                for m in new:
                    if m in reg.raw["modules"]:
                        raise UsageError(f"the registry already has '{m}' — nothing written")
                    reg.raw["modules"][m] = staged["modules"][m]
            if paths["registry_layout"] == "per-module":
                text, stale = build_index(self.root, ws.config)
                if stale:
                    atomic_write(registry, text)
            ws = self.workspace()
            ids = []
            if (self.flow.config_dir / "config.toml").is_file():
                for rule in code_map_rules(self.work, state):
                    add_rule(ws, rule["id"], None, rule["globs"], rule["module"], False, False)
                    ids.append(rule["id"])
                ws = self.workspace()
            rows = agents_md(ws, targets, False, False)["targets"] if targets else []
        except BaseException:
            for path, data in saved.items():
                with contextlib.suppress(OSError):
                    if data is None:
                        path.unlink(missing_ok=True)
                    else:
                        atomic_write(path, data.decode("utf-8"))
            for path in created:
                with contextlib.suppress(OSError):
                    path.unlink(missing_ok=True)
            stop = self.root / paths["modules_dir"]
            for d in sorted({d for p in created for d in p.parents if stop in d.parents},
                            key=lambda d: -len(d.parts)):
                with contextlib.suppress(OSError):
                    d.rmdir()
            raise
        written = moved + [self.flow.rel(p) for p, data in saved.items()
                           if p.is_file() and p.read_bytes() != data]
        return {"moved": moved, "agents_md": [{"path": r["path"], "status": r["status"]}
                                              for r in rows], "code_map": ids,
                "written": sorted(set(written))}

    def git_add(self, written: list[str]) -> list[str]:
        """What the commit takes: every file finish wrote, and the starter files `init` created
        that git still reports as changed or new."""
        paths = set(written)
        if work_tree_error(self.root) is None:
            status = git(self.root, "status", "--porcelain=v1", "--untracked-files=all")
            starters = {".gitignore", self.flow.rel(self.flow.config_dir / "config.toml"),
                        self.workspace().config["paths"]["registry"]}
            paths |= {line[3:] for line in status.stdout.splitlines() if line[3:] in starters}
        return sorted(paths)

    # --- the pull request -----------------------------------------------------------------

    def pr_checks(self, base: str | None, branch: str, expected: set[str]) -> str:
        """Everything `--open-pr` needs, before anything is written; the base branch."""
        for flag, value in (("--base", base), ("--branch", branch)):
            if value is not None and value.startswith("-"):
                raise UsageError(f"{flag} {value!r} may not start with '-'")
        if shutil.which("gh") is None:
            raise UsageError("gh is not installed (needed for --open-pr)")
        error = work_tree_error(self.root)
        if error:
            raise UsageError(f"--open-pr needs a git repository ({error})")
        dirty = [line[3:] for line in git(self.root, "status", "--porcelain=v1",
                                          "--untracked-files=all").stdout.splitlines()
                 if line[3:] not in expected]
        if dirty:
            raise UsageError(f"working tree not clean ({', '.join(dirty[:5])}) — commit or stash "
                             f"it first")
        if git(self.root, "remote", "get-url", "origin").returncode != 0:
            raise UsageError("no git remote 'origin' (needed for --open-pr)")
        if git(self.root, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").returncode \
                == 0:
            raise UsageError(f"branch {branch} exists — name another with --branch")
        if base is None:
            current = git(self.root, "symbolic-ref", "--short", "HEAD")
            if current.returncode != 0:
                raise UsageError("HEAD is detached — name the base with --base")
            base = current.stdout.strip()
        return base

    def pr_body(self, state: dict, forced: list[str]) -> str:
        verify, report = {}, {}
        with contextlib.suppress(OSError, ValueError):
            verify = json.loads((self.flow.work / "verify.json").read_text(encoding="utf-8"))
        with contextlib.suppress(OSError, ValueError):
            report = json.loads((self.flow.work / "reconcile.json").read_text(encoding="utf-8"))
        new = [m for m, e in sorted(state["modules"].items()) if not e.get("existing")]
        lines = [f"Module docs for {len(new)} module(s), written by `modsys init`: "
                 f"{', '.join(new)}.", "", "## Verify", ""]
        s = (verify.get("lint") or {}).get("summary") or {}
        lines.append(f"- lint: {s.get('error', '?')} error(s), {s.get('warning', '?')} "
                     f"warning(s), {s.get('info', '?')} info")
        lines.append(f"- invented components: {len(verify.get('invented') or [])}")
        routing = verify.get("routing")
        if not routing:
            lines.append("- routing: not measured")
        else:
            lines += [f"- routing: hit rate {routing['hit_rate']} ({routing['hits']}/"
                      f"{routing['tasks']}, top {routing['top']}; threshold "
                      f"{routing['min_hit_rate']})", "", "| Module | Hits | Tasks |",
                      "|---|---|---|"]
            lines += [f"| {r['module']} | {r['hits']} | {r['tasks']} |"
                      for r in routing["per_module"]]
            misses = [f"- {r['module']}: \"{m['task']}\" → {', '.join(m['got']) or 'none'}"
                      for r in routing["per_module"] for m in r["misses"]]
            if misses:
                lines += ["", "Misses:", *misses]
        lines += ["", "## Judgement items (init reconcile)", ""]
        items = report.get("judgement") or []
        for j in items:
            if j["kind"] == "duplicate":
                where = ", ".join(f"{d['file']}:{d['line']}" for d in j["definitions"])
                lines.append(f"- duplicate `{j['name']}`: {where}")
            elif j["kind"] == "keyword-tie":
                lines.append(f"- keyword `{j['keyword']}` ties: {', '.join(j['modules'])}")
            else:
                lines.append(f"- keyword `{j['keyword']}` stays in {j['module']} (it would drop "
                             f"below the keyword minimum)")
        if not items:
            lines.append("- none")
        if forced:
            lines += ["", f"Finished with --force: {'; '.join(forced)}."]
        return "\n".join(lines) + "\n"

    def publish(self, state: dict) -> tuple[str, str | None]:
        """The steps of the pull request not done yet (commit, push, `gh pr create`); (pr, the
        error that left it pending)."""
        pr = state["open_pr"]
        body = self.flow.work / "pr-body.md"
        if not pr["committed"]:
            steps = [("checkout", "-q", "-b", pr["branch"]), ("add", "--", *pr["paths"]),
                     ("commit", "-q", "-m", f"modsys: module docs from init "
                                            f"({len(pr['paths'])} files)")]
            for args in steps:
                proc = git(self.root, *args)
                if proc.returncode != 0:
                    return "pending", f"git {args[0]} failed: {proc.stderr.strip()[:300]}"
                if args[0] == "checkout":
                    pr["branch_created"] = True
            pr["committed"] = True
            self.flow.save_state(state)
        if not pr["pushed"]:
            proc = git(self.root, "push", "-q", "origin", pr["branch"])
            if proc.returncode != 0:
                return "pending", f"git push failed: {proc.stderr.strip()[:300]}"
            pr["pushed"] = True
            self.flow.save_state(state)
        try:
            proc = subprocess.run(["gh", "pr", "create", "--base", pr["base"], "--head",
                                   pr["branch"], "--title", pr["title"], "--body-file", str(body)],
                                  cwd=self.root, capture_output=True, text=True, errors="replace")
        except OSError as e:
            return "pending", f"gh cannot run: {e.strerror or e}"
        if proc.returncode != 0:
            return "pending", f"gh pr create failed: {(proc.stderr or proc.stdout).strip()[:300]}"
        url = next((l.strip() for l in reversed(proc.stdout.splitlines()) if l.strip()), "created")
        state["pr"] = url
        self.flow.save_state(state)
        return url, None

    # --- the action -----------------------------------------------------------------------

    def run(self, force: bool, agents_md_args: list[str], open_pr: bool, base: str | None,
            branch: str) -> dict:
        state, staged, forced = self.check(self.flow.load_state(), force)
        ws = self.workspace()
        problems = self.conflicts(ws, staged, state)
        if problems:
            raise UsageError("init finish would overwrite: " + "; ".join(problems) +
                             " — nothing written")
        targets = self.targets(ws, agents_md_args)
        new = [m for m, e in state["modules"].items() if not e.get("existing")]
        if open_pr:  # the starter files init created may still be uncommitted: the PR takes them
            expected = {".gitignore", self.flow.rel(self.flow.config_dir / "config.toml"),
                        ws.config["paths"]["registry"]}
            base = self.pr_checks(base, branch, expected)
        self.flow.mark(state, "finish", "running")
        result = self.apply(state, staged, targets)
        state["phases"]["finish"].update(status="done", finished_at=utc_now())
        state["phase"] = "finished"
        if forced:
            state["forced"] = {"at": utc_now(), "reason": "; ".join(forced)}
        add = self.git_add(result.pop("written"))
        error = None
        if open_pr:
            state["pr"] = "pending"
            state["open_pr"] = {"branch": branch, "base": base, "paths": add, "committed": False,
                                "pushed": False,
                                "title": f"modsys: module docs for {len(new)} module(s) (init)"}
            self.flow.write(self.flow.work / "pr-body.md", self.pr_body(state, forced))
        self.flow.save_state(state)
        if open_pr:
            _, error = self.publish(state)
        registry = self.workspace().config["paths"]["registry"]
        return {**result, "registry": registry, "git_add": add, "forced": bool(forced),
                "pr": state.get("pr"), "error": error, "state": state}
