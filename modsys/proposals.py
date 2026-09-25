"""Proposals queue. During a pipeline run agents never edit the registry or module docs;
they queue proposals (`<proposals_dir>/<run_id>-<agent>.json`, schema `modsys.proposal/1`).
One step applies them under the registry lock:

- `set` / `unset` / `doc_write` carry `base_sha256` (the entry or file as the agent saw it);
  a different current state rejects the item with a reason — others still apply.
- `append` / `remove` / `doc_append` merge safely, so they skip the base check.
- Processed files move to `<proposals_dir>/done/` with per-item results; re-running apply
  finds nothing pending (idempotent).
"""
import copy
import json
import os
import re
from pathlib import Path

from modsys.output import UsageError
from modsys.store import (atomic_write, file_lock, file_sha256, open_store, sha256_bytes,
                          utc_now)
from modsys.writers import OPS as FIELD_OPS, apply_field_op, entry_for, entry_sha256

SCHEMA = "modsys.proposal/1"
DOC_OPS = ("doc_write", "doc_append")
CHECKED_OPS = {"set", "unset", "doc_write"}
_SAFE = re.compile(r"^[A-Za-z0-9._-]+$")


def proposals_dir(ws) -> Path:
    return ws.root / ws.config["paths"]["proposals_dir"]


def module_dir(ws, module: str) -> Path:
    parent, _, child = module.partition("/")
    base = ws.root / ws.config["paths"]["modules_dir"] / parent
    return base / "submodules" / child if child else base


def check_doc_path(ws, module: str, doc: str) -> Path:
    """A doc proposal may only touch files inside its own module directory, never a frozen
    `*.legacy.md` snapshot."""
    path = (ws.root / doc).resolve()
    home = module_dir(ws, module).resolve()
    if home != path and home not in path.parents:
        raise UsageError(f"doc '{doc}' is outside module '{module}' ({home.relative_to(ws.root)})")
    if path.name.endswith(".legacy.md"):
        raise UsageError(f"doc '{doc}' is a frozen legacy snapshot and is never edited")
    return path


def make_item(ws, op: str, module: str, reason: str, field: str | None = None,
              doc: str | None = None, value=None) -> dict:
    """Validate one proposal item against the CURRENT state and stamp its base hash."""
    if not reason:
        raise UsageError("a proposal needs --reason")
    raw = ws.registry.raw
    entry_for(raw, module)  # unknown module / child -> UsageError
    if op in FIELD_OPS:
        if not field:
            raise UsageError(f"{op} proposals need --field")
        apply_field_op(copy.deepcopy(raw), ws.fields, op, module, field, value)  # validates
        return {"op": op, "module": module, "field": field, "value": value, "reason": reason,
                "base_sha256": entry_sha256(raw, module)}
    if op in DOC_OPS:
        if not doc:
            raise UsageError(f"{op} proposals need --doc")
        if not isinstance(value, str):
            raise UsageError(f"{op} proposals need text (--value or --value-file)")
        path = check_doc_path(ws, module, doc)
        return {"op": op, "module": module, "doc": doc, "value": value, "reason": reason,
                "base_sha256": file_sha256(path)}
    raise UsageError(f"unknown op '{op}' (ops: {', '.join(FIELD_OPS + DOC_OPS)})")


def add_proposal(ws, run_id: str, agent: str, item: dict) -> Path:
    for label, value in (("run id", run_id), ("agent", agent)):
        if not _SAFE.match(value):
            raise UsageError(f"{label} {value!r} may only contain letters, digits, '.', '_', '-'")
    path = proposals_dir(ws) / f"{run_id}-{agent}.json"
    with file_lock(path):
        doc = (json.loads(path.read_text(encoding="utf-8")) if path.exists() else
               {"schema": SCHEMA, "run_id": run_id, "agent": agent, "created_at": utc_now(),
                "items": []})
        doc["items"].append({"id": str(len(doc["items"]) + 1), **item})
        atomic_write(path, json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    return path


def pending(ws, run_id: str | None = None) -> list[tuple[Path, dict]]:
    d = proposals_dir(ws)
    out = []
    for path in sorted(d.glob("*.json")) if d.is_dir() else []:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise UsageError(f"{path}: not a valid proposal file: {e}") from None
        if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
            raise UsageError(f"{path}: not a {SCHEMA} file")
        if run_id is None or doc.get("run_id") == run_id:
            out.append((path, doc))
    return out


class _Snapshot:
    """The state before one proposal file's items: every item of a run was made against it,
    so base hashes compare with this, not with the run's own earlier (applied) items."""

    def __init__(self, raw: dict, docs: dict):
        self.raw, self.docs = copy.deepcopy(raw), dict(docs)

    def entry_sha(self, module: str) -> str:
        return entry_sha256(self.raw, module)

    def doc_sha(self, path: Path) -> str | None:
        if path in self.docs:
            return sha256_bytes(self.docs[path].encode("utf-8"))
        return file_sha256(path)


def _apply_item(ws, raw: dict, snap: _Snapshot, item: dict, docs: dict) -> dict:
    """Apply one item to the in-memory registry / pending doc writes; return its result."""
    result = {"id": item.get("id"), "op": item.get("op"), "module": item.get("module")}
    try:
        op, module = item["op"], item["module"]
        if op in FIELD_OPS:
            entry_for(raw, module)
            if op in CHECKED_OPS and snap.entry_sha(module) != item.get("base_sha256"):
                return {**result, "status": "rejected",
                        "reason": f"'{module}' changed since the proposal was made"}
            changed = apply_field_op(raw, ws.fields, op, module, item["field"], item.get("value"))
            return {**result, "status": "applied" if changed else "noop"}
        path = check_doc_path(ws, module, item["doc"])
        current = docs.get(path)
        if current is None:
            current = path.read_text(encoding="utf-8") if path.exists() else None
        if op == "doc_write":
            if snap.doc_sha(path) != item.get("base_sha256"):
                return {**result, "status": "rejected",
                        "reason": f"'{item['doc']}' changed since the proposal was made"}
            new = item["value"]
        elif op == "doc_append":
            text = item["value"]
            if current is not None and text.strip() and text.strip() in current:
                return {**result, "status": "noop"}
            base = current or ""
            new = base + ("" if not base or base.endswith("\n") else "\n") + text
        else:
            raise UsageError(f"unknown op '{op}'")
        if not new.endswith("\n"):
            new += "\n"
        if new == current:
            return {**result, "status": "noop"}
        docs[path] = new
        return {**result, "status": "applied"}
    except (UsageError, KeyError, TypeError) as e:
        return {**result, "status": "rejected", "reason": f"invalid item: {e}"}


def apply_proposals(ws, run_id: str | None = None, dry_run: bool = False) -> dict:
    """Apply every pending proposal file (optionally one run) in file-name order."""
    files = pending(ws, run_id)
    report = {"files": [], "summary": {"applied": 0, "noop": 0, "rejected": 0},
              "dry_run": dry_run}
    if not files:
        return report
    store = open_store(ws)
    docs: dict[Path, str] = {}
    with store.locked():
        registry = store.load()
        raw = copy.deepcopy(registry.raw)
        for path, doc in files:
            snap = _Snapshot(raw, docs)
            results = [_apply_item(ws, raw, snap, item, docs) for item in doc.get("items", [])]
            for r in results:
                report["summary"][r["status"]] += 1
            report["files"].append({"file": path.name, "run_id": doc.get("run_id"),
                                    "agent": doc.get("agent"), "results": results})
        if dry_run:
            return report
        store.commit(registry, raw)
        for path, text in docs.items():
            atomic_write(path, text)
        for (path, doc), entry in zip(files, report["files"]):
            _archive(path, doc, entry["results"])
    return report


def _archive(path: Path, doc: dict, results: list, reason: str | None = None) -> None:
    done = path.parent / "done"
    done.mkdir(exist_ok=True)
    record = {**doc, "processed_at": utc_now(), "results": results}
    if reason:
        record["rejected_reason"] = reason
    atomic_write(done / path.name, json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    os.unlink(path)


def reject_run(ws, run_id: str, reason: str) -> list[str]:
    if not reason:
        raise UsageError("rejecting proposals needs --reason")
    files = pending(ws, run_id)
    if not files:
        raise UsageError(f"no pending proposals for run '{run_id}'")
    for path, doc in files:
        results = [{"id": i.get("id"), "op": i.get("op"), "module": i.get("module"),
                    "status": "rejected", "reason": reason} for i in doc.get("items", [])]
        _archive(path, doc, results, reason)
    return [p.name for p, _ in files]
