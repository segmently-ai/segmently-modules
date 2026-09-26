import copy
import re
import tomllib
from importlib import resources
from pathlib import Path

from modsys.merge import merge_layers
from modsys.output import UsageError

PACK_META_KEYS = {"id", "version", "priority", "requires", "description", "skills", "agents"}
DEFAULT_PACK_PRIORITY = 50
REGISTRY_LAYOUTS = ("single", "per-module")


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


# value type name -> (check, wording used in error messages)
_TYPES = {
    "str": (lambda v: isinstance(v, str), "a string"),
    "int": (_is_int, "an integer"),
    "bool": (lambda v: isinstance(v, bool), "a boolean"),
    "list[str]": (lambda v: isinstance(v, list) and all(isinstance(i, str) for i in v),
                  "a list of strings"),
}
# Only KNOWN keys are checked; unknown keys and sections pass (forward compatibility).
LAYER_SCHEMA = {
    "paths": {k: "str" for k in ("modules_dir", "registry", "registry_layout", "module_doc",
                                 "module_entry", "proposals_dir")},
    "registry": {"statuses": "list[str]", "relations": "list[str]", "dir_whitelist": "list[str]",
                 "stub_pattern": "str", "updated_at_path": "str"},
    "budgets": {k: "int" for k in ("module_doc_split_signal", "module_doc_hard_stop",
                                   "role_doc_max", "keywords_soft", "keyword_shared_warn")},
    "match": {k: "int" for k in ("keyword_weight", "combination_weight", "negative_weight",
                                 "min_score", "top")},
    "lint": {"fail_on": "str", "component_table_heading": "str", "drift_severity": "str"},
    "create": {"min_keywords": "int", "description_min": "int", "description_max": "int",
               "default_status": "str"},
    "coverage": {"include": "list[str]", "exclude": "list[str]"},
}
ROLE_SCHEMA = {"order": "int", "enabled": "bool", "standard": "bool", "description": "str",
               "applies_when": "str", "template": "str"}


def _require_table(value, section: str, source) -> dict:
    if not isinstance(value, dict):
        raise UsageError(f"{source}: [{section}] must be a table, got {value!r}")
    return value


def _check_table(table: dict, schema: dict, section: str, source) -> None:
    for key, type_name in schema.items():
        if key in table:
            check, expected = _TYPES[type_name]
            if not check(table[key]):
                raise UsageError(f"{source}: [{section}] {key}: expected {expected}, "
                                 f"got {table[key]!r}")


def validate_layer(layer: dict, source) -> None:
    """Type-check the known keys of one config layer (a pack, config.toml or
    config.user.toml) before it is merged; `source` names the file in errors."""
    for section, schema in LAYER_SCHEMA.items():
        if section in layer:
            _check_table(_require_table(layer[section], section, source), schema, section, source)
    pattern = layer.get("registry", {}).get("stub_pattern")
    if pattern is not None:
        try:
            re.compile(pattern)
        except re.error as e:
            raise UsageError(f"{source}: [registry] stub_pattern: invalid regular expression: "
                             f"{e}") from None
    drift = layer.get("lint", {}).get("drift_severity")
    if drift is not None and drift not in ("info", "warning", "error"):
        raise UsageError(f"{source}: [lint] drift_severity: expected info, warning or error, "
                         f"got {drift!r}")
    layout = layer.get("paths", {}).get("registry_layout")
    if layout is not None and layout not in REGISTRY_LAYOUTS:
        raise UsageError(f"{source}: [paths] registry_layout: expected one of "
                         f"{list(REGISTRY_LAYOUTS)}, got {layout!r}")
    top = layer.get("match", {}).get("top")
    if top is not None and top < 0:
        raise UsageError(f"{source}: [match] top: expected an integer >= 0, got {top!r}")
    from modsys.changes import validate_code_map  # lazy: keeps config import-light
    from modsys.hooks import validate_hooks  # hooks imports proposals -> store; keep lazy
    validate_hooks(layer, source, _check_table)
    validate_code_map(layer, source, _check_table)
    for section in ("roles", "fields"):
        for name, spec in _require_table(layer.get(section, {}), section, source).items():
            _require_table(spec, f"{section}.{name}", source)
            if section == "roles":
                _check_table(spec, ROLE_SCHEMA, f"roles.{name}", source)


def read_toml(path: Path) -> dict:
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise UsageError(f"{path}: invalid TOML: {e}") from e
    except OSError as e:
        raise UsageError(f"{path}: cannot read: {e}") from e


def core_defaults() -> dict:
    text = resources.files("modsys").joinpath("defaults/config.toml").read_text(encoding="utf-8")
    return tomllib.loads(text)


def discover_packs(config_dir: Path) -> list[dict]:
    """Installed packs, highest precedence first (lowest priority number, then id)."""
    packs = []
    for pack_toml in sorted((config_dir / "packs").glob("*/pack.toml")):
        data = read_toml(pack_toml)
        priority = data.get("priority", DEFAULT_PACK_PRIORITY)
        if not _is_int(priority):
            raise UsageError(f"{pack_toml}: priority must be an integer, got {priority!r}")
        pack_id = data.get("id", pack_toml.parent.name)
        if not isinstance(pack_id, str) or not pack_id:
            raise UsageError(f"{pack_toml}: id must be a non-empty string, got {pack_id!r}")
        packs.append({"id": pack_id, "priority": priority, "path": pack_toml, "data": data})
    return sorted(packs, key=lambda p: (p["priority"], p["id"]))


def _pack_layer(pack: dict) -> dict:
    """The pack's config layer. A deep copy, so the parsed pack data stays untouched; every
    field, role and hook the pack declares records the pack as its `owner` (provenance for
    error messages, pack-relative templates and hook paths)."""
    layer = {k: copy.deepcopy(v) for k, v in pack["data"].items() if k not in PACK_META_KEYS}
    validate_layer(layer, pack["path"])
    for section in ("fields", "roles"):
        for spec in (layer.get(section) or {}).values():
            spec.setdefault("owner", pack["id"])
    for hooks in (layer.get("hooks") or {}).values():
        for hook in hooks if isinstance(hooks, list) else []:
            if isinstance(hook, dict):
                hook.setdefault("owner", pack["id"])
    return layer


def load_config(config_dir: Path) -> dict:
    packs = discover_packs(config_dir)
    layers = [core_defaults()] + [_pack_layer(p) for p in reversed(packs)]
    for name in ("config.toml", "config.user.toml"):
        path = config_dir / name
        if path.exists():
            layer = read_toml(path)
            validate_layer(layer, path)
            layers.append(layer)
    config = merge_layers(layers)
    config["_packs"] = [p["id"] for p in packs]
    config["_pack_dirs"] = {p["id"]: str(p["path"].parent) for p in packs}
    return config


def enabled_roles(config: dict) -> list[str]:
    roles = config.get("roles") or {}
    active = [(spec.get("order", 1000), name) for name, spec in roles.items()
              if spec.get("enabled", True)]
    return [name for _, name in sorted(active)]
