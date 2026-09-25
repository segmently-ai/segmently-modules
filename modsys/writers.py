"""Field-level registry edits, validated by field definitions. Pure functions over the raw
registry document; persistence is the store's job (modsys.store)."""
import difflib
import hashlib
import json

from modsys.fields import FieldDef, value_matches
from modsys.output import UsageError

OPS = ("set", "append", "remove", "unset")
STRUCTURAL = {"name", "submodules"}  # renames and children go through create/split, not field ops


def entry_for(raw: dict, target: str) -> tuple[dict, str]:
    """The registry entry for `module` or `module/child`, and its scope."""
    parent, _, child = target.partition("/")
    entry = raw["modules"].get(parent)
    if not isinstance(entry, dict):
        raise UsageError(f"unknown module '{parent}'")
    if not child:
        return entry, "module"
    sub = (entry.get("submodules") or {}).get(child) if isinstance(entry.get("submodules"),
                                                                    dict) else None
    if not isinstance(sub, dict):
        raise UsageError(f"'{child}' is not a submodule of '{parent}'")
    return sub, "submodule"


def entry_sha256(raw: dict, target: str) -> str:
    """Content hash of one entry (proposals use it as their optimistic-concurrency base)."""
    entry, _ = entry_for(raw, target)
    return hashlib.sha256(json.dumps(entry, ensure_ascii=False).encode("utf-8")).hexdigest()


def _field_def(fields: dict[str, FieldDef], field: str, scope: str) -> FieldDef:
    if field in STRUCTURAL:
        raise UsageError(f"'{field}' is structural and cannot be edited as a field")
    fdef = fields.get(field)
    if fdef is None:
        raise UsageError(f"unknown field '{field}' (declare [fields.{field}] in config or a pack)")
    if fdef.deprecated:
        raise UsageError(f"field '{field}' is deprecated: {fdef.deprecated}")
    if scope not in fdef.scope:
        raise UsageError(f"field '{field}' is not allowed on {scope} entries "
                         f"(scope: {', '.join(fdef.scope)})")
    return fdef


def _check(fdef: FieldDef, value) -> None:
    if not value_matches(fdef, value):
        raise UsageError(f"value {value!r} does not match field '{fdef.name}' type "
                         f"{' | '.join(fdef.type)}")


def apply_field_op(raw: dict, fields: dict[str, FieldDef], op: str, target: str,
                   field: str, value=None) -> bool:
    """Apply one operation in place. Returns True when the document changed.
    set: replace the value · append: add one item to an array (no-op if present) ·
    remove: drop every equal item from an array · unset: delete the field."""
    if op not in OPS:
        raise UsageError(f"unknown op '{op}' (ops: {', '.join(OPS)})")
    entry, scope = entry_for(raw, target)
    fdef = _field_def(fields, field, scope)
    if op == "set":
        _check(fdef, value)
        if entry.get(field, object()) == value:
            return False
        entry[field] = value
        return True
    if op == "unset":
        if scope in fdef.required:
            raise UsageError(f"'{field}' is required on {scope} entries and cannot be unset")
        if field not in entry:
            return False
        del entry[field]
        return True
    current = entry.get(field, [])
    if not isinstance(current, list):
        raise UsageError(f"field '{field}' on '{target}' is not an array; use set")
    if op == "append":
        if value in current:
            return False
        new = current + [value]
    else:  # remove
        new = [item for item in current if item != value]
        if new == current:
            return False
    _check(fdef, new)
    entry[field] = new
    return True


def unified_diff(before: str, after: str, label: str) -> str:
    return "".join(difflib.unified_diff(before.splitlines(keepends=True),
                                        after.splitlines(keepends=True),
                                        fromfile=f"a/{label}", tofile=f"b/{label}"))
