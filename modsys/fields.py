"""Registry field definitions. Core fields are built in; everything else is declared
in config/packs under [fields.<name>] — one declaration drives validation, JSON Schema,
show output, create prompts and sync hints."""
import re
from dataclasses import dataclass

from modsys.output import UsageError

_MAP = re.compile(r"map<string,(.+)>")
SCALARS = {"string": str, "bool": bool, "int": int, "object": dict}
JSON_TYPES = {"string": "string", "bool": "boolean", "int": "integer", "object": "object"}
BOTH = ("module", "submodule")


@dataclass(frozen=True)
class FieldDef:
    name: str
    type: tuple[str, ...]
    scope: tuple[str, ...] = ("module",)
    description: str = ""
    kind: str = "data"                # "data" | "code_pointer"
    used_by: tuple[str, ...] = ()
    ask_on_create: bool = False
    sync_hint: str = ""
    deprecated: str = ""              # non-empty = deprecated; value is the migration hint
    required: tuple[str, ...] = ()    # scopes where the field is mandatory
    owner: str = "core"


def _core(name, type_, scope, description, required=(), used_by=()):
    return FieldDef(name=name, type=type_, scope=scope, description=description,
                    required=required, used_by=used_by)


CORE_FIELDS: dict[str, FieldDef] = {f.name: f for f in [
    _core("name", ("string",), ("module",), "Registry key, repeated", ("module",)),
    _core("description", ("string",), BOTH, "Main relevance indicator: WHAT / WHY / WHEN",
          ("module",)),
    _core("status", ("string",), ("module",), "Lifecycle status (registry.statuses)",
          ("module",)),
    _core("keywords", ("string[]",), BOTH, "Routing discriminators", ("module",), ("match",)),
    _core("context_files", ("object",), BOTH, "Docs to load: universal, roles, extras", BOTH),
    _core("related_modules", ("object[]",), ("module",), "Typed edges to other modules"),
    _core("submodules", ("object",), ("module",), "Child functional areas"),
    _core("negative_keywords", ("map<string,string[]>", "string[]"), ("module",),
          "Phrases that mean NOT this module", used_by=("match",)),
    # both shapes exist in real registries: [["a", "b"]] and a flat ["a", "b"] (each item = one term)
    _core("required_combinations", ("string[][]", "string[]"), ("module",),
          "Term groups that together add a match bonus", used_by=("match",)),
]}


def validate_type_expr(expr: str) -> None:
    if expr in SCALARS:
        return
    if expr.endswith("[]"):
        return validate_type_expr(expr[:-2])
    m = _MAP.fullmatch(expr)
    if m:
        return validate_type_expr(m.group(1))
    raise ValueError(f"unknown type expression {expr!r}")


def check_type(expr: str, value) -> bool:
    if expr == "bool":
        return isinstance(value, bool)
    if expr == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if expr in SCALARS:
        return isinstance(value, SCALARS[expr])
    if expr.endswith("[]"):
        return isinstance(value, list) and all(check_type(expr[:-2], v) for v in value)
    m = _MAP.fullmatch(expr)
    return (m is not None and isinstance(value, dict)
            and all(isinstance(k, str) and check_type(m.group(1), v)
                    for k, v in value.items()))


def value_matches(fdef: FieldDef, value) -> bool:
    return any(check_type(t, value) for t in fdef.type)


def _tuple(v) -> tuple:
    return tuple(v) if isinstance(v, list) else (v,)


def load_field_defs(config: dict) -> dict[str, FieldDef]:
    defs = dict(CORE_FIELDS)
    for name, spec in (config.get("fields") or {}).items():
        owner = spec.get("owner", "config")
        if name in CORE_FIELDS:
            raise UsageError(f"field {name!r} (owner {owner}) is a core field; "
                             f"it cannot be redeclared")
        types = _tuple(spec.get("type", "object"))
        for t in types:
            try:
                validate_type_expr(t)
            except ValueError as e:
                raise UsageError(f"field {name!r} (owner {owner}): {e}") from e
        defs[name] = FieldDef(
            name=name, type=types, scope=_tuple(spec.get("scope", "module")),
            description=spec.get("description", ""), kind=spec.get("kind", "data"),
            used_by=_tuple(spec.get("used_by", [])),
            ask_on_create=bool(spec.get("ask_on_create", False)),
            sync_hint=spec.get("sync_hint", ""), deprecated=spec.get("deprecated", ""),
            required=_tuple(spec.get("required", [])), owner=owner)
    return defs


def _schema_for(expr: str) -> dict:
    if expr in JSON_TYPES:
        return {"type": JSON_TYPES[expr]}
    if expr.endswith("[]"):
        return {"type": "array", "items": _schema_for(expr[:-2])}
    return {"type": "object", "additionalProperties": _schema_for(_MAP.fullmatch(expr).group(1))}


def _field_schema(fdef: FieldDef) -> dict:
    options = [_schema_for(t) for t in fdef.type]
    schema = options[0] if len(options) == 1 else {"anyOf": options}
    return {**schema, "description": fdef.description} if fdef.description else schema


def to_json_schema(defs: dict[str, FieldDef], statuses: list[str]) -> dict:
    def entry(scope: str) -> dict:
        return {"type": "object",
                "properties": {n: _field_schema(d) for n, d in defs.items() if scope in d.scope},
                "required": [n for n, d in defs.items() if scope in d.required],
                "additionalProperties": True}

    module = entry("module")
    module["properties"]["status"] = {**module["properties"]["status"], "enum": statuses}
    module["properties"]["submodules"] = {"type": "object",
                                          "additionalProperties": entry("submodule")}
    return {"$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "modsys registry", "type": "object", "required": ["modules"],
            "properties": {"modules": {"type": "object", "additionalProperties": module}}}
