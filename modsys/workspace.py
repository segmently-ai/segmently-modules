from dataclasses import dataclass, field
from pathlib import Path

from modsys.config import load_config
from modsys.fields import FieldDef, load_field_defs
from modsys.output import UsageError
from modsys.registry import Registry, load_registry

ROOT_MARKERS = (".modsys", "modules/registry.json")


def find_root(start: Path) -> Path:
    """Nearest directory holding a root marker; the nearest `.git` ends the search."""
    start = start.resolve()
    for d in (start, *start.parents):
        if any((d / marker).exists() for marker in ROOT_MARKERS):
            return d
        if (d / ".git").exists():
            return d
    raise UsageError(f"cannot find a repository root above {start}; pass --root")


@dataclass
class Workspace:
    root: Path
    config_dir: Path
    config: dict
    fields: dict[str, FieldDef]
    _registry: Registry | None = field(default=None, repr=False)

    @classmethod
    def load(cls, root: Path, config_dir: Path | None = None) -> "Workspace":
        """A workspace for programmatic callers (pipelines, hooks, tests) — no argparse needed."""
        root = Path(root).resolve()
        config_dir = Path(config_dir or root / ".modsys").resolve()
        config = load_config(config_dir)
        return cls(root, config_dir, config, load_field_defs(config))

    @classmethod
    def from_args(cls, args) -> "Workspace":
        return cls.load(args.root or find_root(Path.cwd()), args.config_dir)

    @property
    def registry(self) -> Registry:
        if self._registry is None:
            if self.config["paths"]["registry_layout"] == "per-module":
                from modsys.layout import load_per_module
                self._registry = load_per_module(self.root, self.config)
            else:
                self._registry = load_registry(self.root / self.config["paths"]["registry"])
        return self._registry
