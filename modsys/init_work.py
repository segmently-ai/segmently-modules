"""`init fanout|next|done` — phase 4 (fan-out): one work item per confirmed module, claimed and
checked one at a time, whoever writes the docs (an agent session, a skill's subagents, a CI
executor: `init run`).

  <config_dir>/init/work/<module>.json   the work item: {module, parent, paths, files (the first
                                         200 of the module's files, in path order), files_total,
                                         neighbours (the proposal's import edges to other
                                         included modules), roles (the roles `create`
                                         scaffolds), staging_dir, prompt} — `existing: true`
                                         (and `prompt: null`) for a module that is already in
                                         the registry: done from the start, never rewritten
  <config_dir>/init/staging/<module>/    what the writer writes: MODULE.md, roles/<role>.md
                                         per role, entry.json {description, keywords,
                                         related_modules?}

The prompt is rendered from the template `init/module_prompt.md` (the template chain: team
override, packs, engine), the doc templates it embeds from `create`'s chain; no `${…}`
placeholder is left in it. A module's status in `state.json`: pending -> running (a claim:
`init next`, `init run`) -> done | failed; `init done` checks the staging output. Every state
change is a read-modify-write under `state.json.lock`."""
import json
import re
import shutil
import string

from modsys.changes import glob_to_regex
from modsys.config import enabled_roles
from modsys.create import article, ask_fields, resolve_template
from modsys.fields import value_matches
from modsys.output import UsageError
from modsys.store import serialize

FILES_CAP = 200
DOC_PLACEHOLDERS = {"description": "<one sentence: what the module does, why, when to use it>",
                    "keywords": "<the keywords>", "status": "active", "parent": ""}
_LEFT = re.compile(r"\$\{(\w*)\}?")
_FIRST_PLACEHOLDER = re.compile(r"\$\{[^}\s]*\}?")


def fence(text: str) -> str:
    """A code fence longer than every backtick run of `text`."""
    runs = [len(m) for m in re.findall(r"`{3,}", text)]
    return "`" * max(3, max(runs, default=0) + 1)


def fill(template: str, values: dict) -> str:
    """`template` with `values` substituted; any placeholder left becomes `<name>`."""
    text = string.Template(template).safe_substitute(values)
    return _LEFT.sub(lambda m: f"<{m.group(1) or 'value'}>", text)


def counts(state: dict) -> dict:
    statuses = [m["status"] for m in state["modules"].values()]
    return {s: statuses.count(s) for s in ("pending", "running", "done", "failed")}


class Work:
    """Phase 4 over an `InitFlow` (`flow`): work items, claims, checks."""

    def __init__(self, flow, ws):
        self.flow, self.ws, self.root = flow, ws, flow.root
        self.dir = flow.work / "work"
        self.staging = flow.work / "staging"

    # --- inputs ---------------------------------------------------------------------------

    def confirmed(self) -> list[dict]:
        """The included candidates of confirmed.json, in its order."""
        doc = self.flow.read_json(self.flow.output("gate-map"))
        return [c for c in (doc or {}).get("candidates", []) if c.get("include") is True]

    def registry_raw(self) -> dict:
        """The registry as the engine reads it (`{"modules": {}}` when there is none yet)."""
        path = self.root / self.ws.config["paths"]["registry"]
        if self.ws.config["paths"]["registry_layout"] == "single" and not path.is_file():
            return {"modules": {}}
        return self.ws.registry.raw

    def registry_modules(self) -> dict:
        return self.registry_raw()["modules"]

    def roles(self) -> list[str]:
        """The roles `create` scaffolds for a module without tags: the standard ones."""
        roles = self.ws.config.get("roles") or {}
        return [r for r in enabled_roles(self.ws.config) if roles[r].get("standard")]

    def targets(self) -> set[str]:
        """The modules an entry's edge may name: the included confirmed ones and the registry."""
        return {c["name"] for c in self.confirmed()} | set(self.registry_modules())

    def item_path(self, module: str):
        return self.dir / f"{module}.json"

    def staging_dir(self, module: str):
        return self.staging / module

    def item(self, module: str) -> dict:
        return self.flow.read_json(self.item_path(module))

    # --- the work items -------------------------------------------------------------------

    def build_item(self, candidate: dict, included: set[str], files: list[str],
                   existing: bool) -> dict:
        name = candidate["name"]
        rx = [glob_to_regex(g) for g in candidate["paths"]]
        own = [f for f in files if any(r.match(f) for r in rx)]
        item = {"module": name, "parent": None, "paths": list(candidate["paths"]),
                "files": own[:FILES_CAP], "files_total": len(own),
                "neighbours": [{"to": e["to"], "imports": e["imports"]}
                               for e in candidate.get("edges") or []
                               if isinstance(e, dict) and e.get("to") in included],
                "roles": self.roles(),
                "staging_dir": self.flow.rel(self.staging_dir(name)), "prompt": None}
        if existing:
            item["existing"] = True
        else:
            item["prompt"] = self.prompt(item)
        return item

    def doc_block(self, rel: str, text: str) -> str:
        f = fence(text)
        return f"### `{rel}`\n\n{f}markdown\n{text.rstrip(chr(10))}\n{f}\n"

    def prompt(self, item: dict) -> str:
        """The writer's prompt for one work item (template `init/module_prompt.md`)."""
        name, cfg = item["module"], self.ws.config
        values = {"name": name, "title": name.replace("-", " ").title(), **DOC_PLACEHOLDERS}
        docs = [self.doc_block("MODULE.md", fill(resolve_template(self.ws, "MODULE.md"),
                                                 values))]
        for role in item["roles"]:
            spec = cfg["roles"][role]
            text = fill(resolve_template(self.ws, f"roles/{role}.md", role),
                        {**values, "role": role, "article": article(role),
                         "role_description": spec.get("description", "")})
            docs.append(self.doc_block(f"roles/{role}.md", text))
        extra = ask_fields(self.ws, "module")
        asked = "".join(f"\n  - `{n}`: {d.description or 'a field this repository asks for'} "
                        f"(type {' | '.join(d.type)}; required)" for n, d in extra.items())
        total = item["files_total"]
        note = (f"(the first {len(item['files'])} of {total} files, in path order)"
                if total > len(item["files"]) else f"({total} file{'s' * (total != 1)})")
        values = {"module": name, "staging_dir": item["staging_dir"],
                  "paths": ", ".join(f"`{p}`" for p in item["paths"]), "files_note": note,
                  "files": "\n".join(f"- `{f}`" for f in item["files"]) or "- (no file)",
                  "neighbours": "\n".join(f"- `{n['to']}` ({n['imports']} import(s))"
                                          for n in item["neighbours"]) or "- none found",
                  "docs": "\n".join(docs), "roles": ", ".join(item["roles"]) or "none",
                  "description_min": cfg["create"]["description_min"],
                  "description_max": cfg["create"]["description_max"],
                  "min_keywords": cfg["create"]["min_keywords"],
                  "relations": ", ".join(cfg["registry"]["relations"]), "ask_fields": asked}
        text = fill(resolve_template(self.ws, "init/module_prompt.md"), values)
        return text if text.endswith("\n") else text + "\n"

    def fanout(self) -> dict:
        """Write one work item per included confirmed module and every module's state entry.
        Re-run while every item is pending: the same bytes. Refused after gate 3 is open, when
        an item left pending (run `init resume` / `init run`), or when a module directory exists
        without a registry entry (nothing written)."""
        flow = self.flow
        state = flow.load_state()
        if state is None or state["phases"]["gate-map"]["status"] != "done" \
                or not flow.output("gate-map").is_file():
            raise UsageError("gate 3 has not passed — edit the proposal, then run "
                             "modsys init confirm")
        started = [m for m, e in state["modules"].items()
                   if e["status"] != "pending" and not e.get("existing")]
        if started:
            raise UsageError(f"the fan-out has started ({len(started)} module(s) not pending: "
                             f"{', '.join(sorted(started))}) — continue with modsys init resume "
                             f"or modsys init run")
        registry = self.registry_modules()
        mdir = self.ws.config["paths"]["modules_dir"]
        candidates = self.confirmed()
        conflicts = [c["name"] for c in candidates if c["name"] not in registry
                     and (self.root / mdir / c["name"]).exists()]
        if conflicts:
            raise UsageError(f"{', '.join(f'{mdir}/{n}/' for n in conflicts)} exist(s) without a "
                             f"registry entry — register it with modsys create, or move it "
                             f"away, then run modsys init fanout; nothing written")
        included = {c["name"] for c in candidates}
        files = flow.files()
        items = {c["name"]: self.build_item(c, included, files, c["name"] in registry)
                 for c in sorted(candidates, key=lambda c: c["name"])}
        flow.mark(state, "fanout", "running")
        texts = {name: serialize(item) for name, item in items.items()}
        before = {p.name: p.read_bytes() for p in self.dir.glob("*.json")} \
            if self.dir.is_dir() else {}
        for name, text in texts.items():
            flow.write(self.item_path(name), text)
        for stale in set(before) - {f"{n}.json" for n in items}:
            (self.dir / stale).unlink()
        state["modules"] = {name: ({"status": "done", "attempts": 0, "error": None,
                                    "existing": True} if item.get("existing") else
                                   {"status": "pending", "attempts": 0, "error": None})
                            for name, item in items.items()}
        digest = "".join(f"{n}\0{flow.sha(t)}\n" for n, t in texts.items())
        flow.mark(state, "fanout", "done", flow.sha(digest))
        unchanged = before == {f"{n}.json": t.encode("utf-8") for n, t in texts.items()}
        return {"items": list(items), "existing": [n for n, i in items.items()
                                                   if i.get("existing")],
                "status": "unchanged" if unchanged else "written", "state": state}

    # --- claims and checks ----------------------------------------------------------------

    def require_fanout(self, state: dict | None) -> dict:
        if state is None or state["phases"]["gate-map"]["status"] != "done":
            raise UsageError("gate 3 has not passed — run modsys init confirm first")
        if state["phases"]["fanout"]["status"] != "done":
            raise UsageError("the fan-out has not run — run modsys init fanout first")
        return state

    def clear(self, module: str, make: bool = False) -> None:
        """Remove a module's staging dir (`make`: then create it empty); a symlinked one — or a
        symlinked staging root — is refused, its target left alone."""
        target = self.staging_dir(module)
        for path in (self.staging, target):
            if path.is_symlink():
                raise UsageError(f"{self.flow.rel(path)} is a symlink — remove it (its target "
                                 f"is left alone)")
        try:
            if target.exists():
                shutil.rmtree(target)
            if make:
                target.mkdir(parents=True)
        except OSError as e:
            raise UsageError(f"cannot write {self.flow.rel(target)}/: {e.strerror or e}") \
                from None

    def reset(self) -> list[str]:
        """Every running or failed module back to pending, its staging dir removed (`attempts`
        and the last error kept until the next claim); a done module is never touched."""
        state = self.require_fanout(self.flow.load_state())
        if not any(e["status"] in ("running", "failed") for e in state["modules"].values()):
            return []
        with self.flow.locked():
            state = self.flow.load_state()
            stale = sorted(m for m, e in state["modules"].items()
                           if e["status"] in ("running", "failed"))
            for module in stale:
                self.clear(module)
                state["modules"][module]["status"] = "pending"
            self.flow.save_state(state)
        return stale

    def claim(self, module: str | None = None) -> tuple[dict | None, dict]:
        """The first pending module in name order (or `module`, when it is pending), now
        running (attempts + 1, its staging dir cleared and created, its last error dropped):
        (work item or None, counts)."""
        self.require_fanout(self.flow.load_state())  # a refusal writes nothing, not even the lock
        with self.flow.locked():
            state = self.require_fanout(self.flow.load_state())
            pending = sorted(m for m, e in state["modules"].items() if e["status"] == "pending")
            if module is not None:
                pending = [module] if module in pending else []
            if not pending:
                return None, counts(state)
            module = pending[0]
            self.clear(module, make=True)
            entry = state["modules"][module]
            entry.update(status="running", attempts=entry["attempts"] + 1, error=None)
            self.flow.save_state(state)
        return self.item(module), counts(state)

    def problems(self, module: str) -> list[str]:
        """What keeps a module's staging output from `done` (SI-8), one line each."""
        item = self.item(module)
        base = self.staging_dir(module)
        expected = ["MODULE.md", *(f"roles/{r}.md" for r in item["roles"]), "entry.json"]
        found = sorted(p.relative_to(base).as_posix() for p in base.rglob("*")
                       if p.is_file() or p.is_symlink()) if base.is_dir() else []
        out = [f"missing {rel}" for rel in expected if rel not in found]
        out += [f"unexpected file {rel}" for rel in found if rel not in expected]
        for rel in expected[:-1]:
            path = base / rel
            if rel not in found:
                continue
            if path.is_symlink():
                out.append(f"{rel} is a symlink (write the file itself)")
                continue
            try:
                text = path.read_bytes().decode("utf-8")
            except (OSError, UnicodeDecodeError) as e:
                out.append(f"{rel}: cannot read it as UTF-8 text ({e})")
                continue
            if not text.strip():
                out.append(f"{rel} is empty")
            elif "${" in text:
                out.append(f"{rel}: unfilled placeholder {_FIRST_PLACEHOLDER.search(text).group(0)}")
        if "entry.json" in found and not (base / "entry.json").is_symlink():
            out += self.entry_problems(base / "entry.json")
        elif "entry.json" in found:
            out.append("entry.json is a symlink (write the file itself)")
        return out

    def entry_problems(self, path) -> list[str]:
        try:
            entry = json.loads(path.read_bytes().decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return ["entry.json: invalid JSON"]
        if not isinstance(entry, dict):
            return ["entry.json: not an object"]
        cfg = self.ws.config
        extra = ask_fields(self.ws, "module")
        allowed = {"description", "keywords", "related_modules", *extra}
        out = [f"entry.json: unknown key '{k}'" for k in sorted(entry) if k not in allowed]
        low, high = cfg["create"]["description_min"], cfg["create"]["description_max"]
        desc = entry.get("description")
        if not isinstance(desc, str) or not low <= len(desc.strip()) <= high:
            out.append(f"description must be {low}–{high} characters")
        kws = entry.get("keywords")
        need = cfg["create"]["min_keywords"]
        if not (isinstance(kws, list) and all(isinstance(k, str) and k.strip() for k in kws)
                and len(set(kws)) >= need):
            out.append(f"at least {need} distinct keywords (a list of non-empty strings)")
        for name, fdef in extra.items():
            if name not in entry:
                out.append(f"entry.json: missing '{name}' (a field this repository asks for)")
            elif not value_matches(fdef, entry[name]):
                out.append(f"entry.json: '{name}' does not match type {' | '.join(fdef.type)}")
        edges = entry.get("related_modules", [])
        if not isinstance(edges, list):
            return out + ["related_modules must be a list of edges"]
        targets, relations = self.targets(), cfg["registry"]["relations"]
        for i, edge in enumerate(edges):
            if not isinstance(edge, dict):
                out.append(f"related_modules[{i}]: not an object")
                continue
            if edge.get("module") not in targets:
                out.append(f"related_modules[{i}]: '{edge.get('module')}' is not a confirmed "
                           f"module")
            if edge.get("relation") not in relations:
                out.append(f"related_modules[{i}]: relation '{edge.get('relation')}' is not in "
                           f"the relations ({', '.join(relations)})")
            if not isinstance(edge.get("description"), str) or not edge["description"].strip():
                out.append(f"related_modules[{i}]: missing description")
            unknown = sorted(set(edge) - {"module", "relation", "description"})
            if unknown:
                out.append(f"related_modules[{i}]: unknown key '{unknown[0]}'")
        return out

    def done(self, module: str) -> tuple[str, list[str]]:
        """`init done <module>`: (status, problems) — `done` when the staging output is
        complete; a pending or unknown module is exit 2; an item already done stays done."""
        state = self.require_fanout(self.flow.load_state())
        modules = state["modules"]
        if module not in modules:
            raise UsageError(f"unknown module '{module}' (modules: {', '.join(sorted(modules))})")
        status = modules[module]["status"]
        if status == "done":
            return "already done", []
        if status == "pending":
            raise UsageError(f"'{module}' is pending — claim it first: modsys init next")
        problems = self.problems(module)
        if problems:
            return status, problems
        with self.flow.locked():
            state = self.flow.load_state()
            entry = state["modules"][module]
            if entry["status"] in ("running", "failed"):
                entry.update(status="done", error=None)
                self.flow.save_state(state)
        return "done", []
