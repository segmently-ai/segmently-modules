import os
from dataclasses import dataclass, field
from pathlib import Path

from modsys.config import load_config
from modsys.fields import FieldDef, load_field_defs
from modsys.output import UsageError
from modsys.registry import Registry, load_registry

ROOT_MARKERS = (".modsys", "modules/registry.json")


def find_root(start: Path) -> Path:
    """Nearest directory holding a root marker; the nearest `.git` ends the search, and so does
    a directory listed in GIT_CEILING_DIRECTORIES — never entered, as git's own search does."""
    start = start.resolve()
    ceilings = {Path(p).resolve() for p in
                os.environ.get("GIT_CEILING_DIRECTORIES", "").split(os.pathsep) if p}
    for d in (start, *start.parents):
        if d != start and d in ceilings:
            break
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
        config = load_config(config_dir, root)
        return cls(root, config_dir, config, load_field_defs(config))

    @classmethod
    def from_args(cls, args) -> "Workspace":
        return cls.load(args.root or find_root(Path.cwd()), args.config_dir)

    def rel(self, path) -> str:
        """`path` as users see it: root-relative (posix) when it lies inside the root, else
        absolute."""
        path = Path(os.path.normpath(Path(path).absolute()))
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return str(path)

    @property
    def registry(self) -> Registry:
        if self._registry is None:
            if self.config["paths"]["registry_layout"] == "per-module":
                from modsys.layout import load_per_module
                self._registry = load_per_module(self.root, self.config)
            else:
                self._registry = load_registry(self.root / self.config["paths"]["registry"])
        return self._registry
