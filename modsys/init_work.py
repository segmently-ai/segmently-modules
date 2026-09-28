"""`init fanout` — phase 4 (fan-out): one work item per confirmed module, whoever writes the docs
(an agent session, a skill's subagents, a CI executor).

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
placeholder is left in it. Every module starts `pending` in `state.json` (a module created by
hand: `done`, `existing`)."""
import re
import string

from modsys.changes import glob_to_regex
from modsys.config import enabled_roles
from modsys.create import article, ask_fields, resolve_template
from modsys.output import UsageError
from modsys.store import serialize

FILES_CAP = 200
DOC_PLACEHOLDERS = {"description": "<one sentence: what the module does, why, when to use it>",
                    "keywords": "<the keywords>", "status": "active", "parent": ""}
_LEFT = re.compile(r"\$\{(\w*)\}?")


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

    def registry_modules(self) -> dict:
        path = self.root / self.ws.config["paths"]["registry"]
        if self.ws.config["paths"]["registry_layout"] == "single" and not path.is_file():
            return {}
        return self.ws.registry.modules

    def roles(self) -> list[str]:
        """The roles `create` scaffolds for a module without tags: the standard ones."""
        roles = self.ws.config.get("roles") or {}
        return [r for r in enabled_roles(self.ws.config) if roles[r].get("standard")]

    def item_path(self, module: str):
        return self.dir / f"{module}.json"

    def staging_dir(self, module: str):
        return self.staging / module

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
