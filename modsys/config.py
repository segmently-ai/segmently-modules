import tomllib
from importlib import resources
from pathlib import Path

from modsys.merge import merge_layers
from modsys.output import UsageError

PACK_META_KEYS = {"id", "version", "priority", "requires", "description", "skills", "agents"}
DEFAULT_PACK_PRIORITY = 50


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
        packs.append({"id": data.get("id", pack_toml.parent.name),
                      "priority": int(data.get("priority", DEFAULT_PACK_PRIORITY)),
                      "path": pack_toml, "data": data})
    return sorted(packs, key=lambda p: (p["priority"], p["id"]))


def _pack_layer(pack: dict) -> dict:
    layer = {k: v for k, v in pack["data"].items() if k not in PACK_META_KEYS}
    for spec in (layer.get("fields") or {}).values():
        spec.setdefault("owner", pack["id"])
    return layer


def load_config(config_dir: Path) -> dict:
    packs = discover_packs(config_dir)
    layers = [core_defaults()] + [_pack_layer(p) for p in reversed(packs)]
    for name in ("config.toml", "config.user.toml"):
        path = config_dir / name
        if path.exists():
            layers.append(read_toml(path))
    config = merge_layers(layers)
    config["_packs"] = [p["id"] for p in packs]
    return config


def enabled_roles(config: dict) -> list[str]:
    roles = config.get("roles") or {}
    active = [(spec.get("order", 1000), name) for name, spec in roles.items()
              if spec.get("enabled", True)]
    return [name for _, name in sorted(active)]
