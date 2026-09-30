"""The publish tree of the modsys plugins (P6 D4): channel versions, the two marketplace files
and their merge, the structural check of the Codex one — stdlib only.

    python3 tools/publish.py --channel dev|stable --out DIR

builds the three plugins (tools/build_plugins.py) with the channel's version into
`DIR/plugins/` and writes `DIR/.claude-plugin/marketplace.json` (Claude Code) and
`DIR/.agents/plugins/marketplace.json` (Codex) — the tree `claude plugin validate` and `codex
plugin marketplace add` read; `tools/release.py` writes the same into the publish repository.

Channels are branches of the publish repository; each has its own marketplace name:
`stable` → `modsys`, `dev` → `modsys-dev` (two marketplaces can be added side by side).
Versions (one source: the engine's `__version__`, X.Y.Z or X.Y.Z.devN): `stable` = X.Y.Z;
`dev` = X.Y.Z-dev.h<8 hex> — the content hash of the three plugin trees without their
manifests (the files that carry the version), so a rebuild of the same tree is the same
version, and the `h` keeps an all-digit hash a valid SemVer identifier. A version lives only in
each plugin's manifests, never in a marketplace entry."""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_plugins  # noqa: E402  (a sibling script)

MARKETPLACES = {"stable": "modsys", "dev": "modsys-dev"}  # channel (branch) -> marketplace
CLAUDE_MARKETPLACE = ".claude-plugin/marketplace.json"
CODEX_MARKETPLACE = ".agents/plugins/marketplace.json"
OWNER = {"name": "modsys maintainers"}
DESCRIPTION = {"stable": "The modsys plugins: module-registry skills and the modsys CLI",
               "dev": "The modsys plugins, dev channel: every change before a release"}
ENGINE_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:\.dev\d+)?$")
PROG = "publish.py"


def base_version(engine_version: str) -> str:
    """X.Y.Z of `__version__` (a `.devN` suffix dropped)."""
    m = ENGINE_VERSION.fullmatch(engine_version)
    if not m:
        raise build_plugins.BuildError(f"__version__ {engine_version!r} is not X.Y.Z or "
                                       f"X.Y.Z.devN")
    return ".".join(m.groups())


def channel_version(channel: str, engine_version: str, content: str) -> str:
    """The version the channel stamps: X.Y.Z (stable) or X.Y.Z-dev.h<content[:8]> (dev)."""
    base = base_version(engine_version)
    return base if channel == "stable" else f"{base}-dev.h{content[:8]}"


def content_hash(plugins: Path) -> str:
    """sha256 over (path, mode, bytes) of every file of the three plugin directories in
    `plugins`, in path order — the manifests excluded (they carry the version)."""
    h = hashlib.sha256()
    for name in sorted(build_plugins.PLUGINS):
        root = plugins / name
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            rel = path.relative_to(root).as_posix()
            if rel in build_plugins.MANIFESTS:
                continue
            data = path.read_bytes()
            h.update(f"{name}/{rel}\0{path.stat().st_mode & 0o777:o}\0{len(data)}\0".encode())
            h.update(data)
    return h.hexdigest()


def build_channel(engine: Path, out: Path, channel: str) -> str:
    """Build the plugins into `out` with the channel's version; the version."""
    engine_version = build_plugins.engine_version(engine)
    base_version(engine_version)  # refuse an unusable __version__ before anything is built
    with tempfile.TemporaryDirectory() as tmp:
        build_plugins.build(engine, Path(tmp), None)
        version = channel_version(channel, engine_version, content_hash(Path(tmp)))
    build_plugins.build(engine, out, version)
    return version


def entries(channel: str) -> dict[str, tuple[dict, dict]]:
    """{plugin: (its Claude Code entry, its Codex entry)} — relative sources, no version."""
    return {name: ({"name": name, "source": f"./plugins/{name}",
                    "description": build_plugins.PLUGINS[name]["description"]},
                   {"name": name, "source": {"source": "local", "path": f"./plugins/{name}"}})
            for name in sorted(build_plugins.PLUGINS)}


def merge_plugins(existing, ours: list[dict]) -> list[dict]:
    """The `plugins` list: every entry we do not own kept as it is and where it is, ours
    replaced in place (merged by name), the missing ones of ours appended in name order."""
    mine = {e["name"]: e for e in ours}
    out, seen = [], set()
    for entry in existing if isinstance(existing, list) else []:
        name = entry.get("name") if isinstance(entry, dict) else None
        if name in mine:
            out.append(mine[name])
            seen.add(name)
        else:
            out.append(entry)
    return out + [e for name, e in sorted(mine.items()) if name not in seen]


def marketplaces(channel: str, claude_old=None, codex_old=None) -> tuple[dict, dict]:
    """The two marketplace files of a channel, merged into the ones on the branch (None: new).
    Ours: `name`, and `owner` / `description` of the Claude one; other keys are kept."""
    ours = entries(channel)
    claude = claude_old if isinstance(claude_old, dict) else {}
    codex = codex_old if isinstance(codex_old, dict) else {}
    name = MARKETPLACES[channel]
    claude = {"name": name, "owner": dict(OWNER), "description": DESCRIPTION[channel],
              **{k: v for k, v in claude.items() if k not in ("name", "owner", "description",
                                                             "plugins")},
              "plugins": merge_plugins(claude.get("plugins"), [c for c, _ in ours.values()])}
    codex = {"name": name, **{k: v for k, v in codex.items() if k not in ("name", "plugins")},
             "plugins": merge_plugins(codex.get("plugins"), [x for _, x in ours.values()])}
    return claude, codex


def dump(value) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def codex_problems(root: Path) -> list[str]:
    """The structural check of `.agents/plugins/marketplace.json` under `root` (Codex documents
    no validator): a JSON object with a `name` and a `plugins` list; every entry an object with
    a unique `name` and a `source` object; a `local` source's `path` starts with `./`, stays
    inside `root` and is a directory."""
    path = root / CODEX_MARKETPLACE
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        return [f"{CODEX_MARKETPLACE}: cannot be read as JSON: {e}"]
    if not isinstance(doc, dict):
        return [f"{CODEX_MARKETPLACE}: not a JSON object"]
    problems = []
    if not isinstance(doc.get("name"), str) or not doc["name"]:
        problems.append(f"{CODEX_MARKETPLACE}: name is missing")
    plugins = doc.get("plugins")
    if not isinstance(plugins, list):
        return problems + [f"{CODEX_MARKETPLACE}: plugins is not a list"]
    seen = set()
    for i, entry in enumerate(plugins):
        name = entry.get("name") if isinstance(entry, dict) else None
        label = f"plugin '{name}'" if isinstance(name, str) and name else f"plugins[{i}]"
        if not isinstance(name, str) or not name:
            problems.append(f"{label}: name is missing")
        elif name in seen:
            problems.append(f"{label}: the name is used twice")
        seen.add(name)
        source = entry.get("source") if isinstance(entry, dict) else None
        if not isinstance(source, dict) or not isinstance(source.get("source"), str):
            problems.append(f"{label}: source is not an object with a source type")
            continue
        if source["source"] != "local":
            continue
        rel = source.get("path")
        if not isinstance(rel, str) or not rel.startswith("./"):
            problems.append(f"{label}: source.path {rel!r} does not start with ./")
            continue
        target = Path(os.path.normpath(root / rel))
        if target != root and root not in target.parents:
            problems.append(f"{label}: source.path {rel!r} leaves the marketplace root")
        elif not target.is_dir():
            problems.append(f"{label}: source.path {rel!r} is not a directory")
    return problems


def plugin_problems(root: Path, version: str) -> list[str]:
    """Our entries of the Claude Code marketplace under `root`: each one's plugin exists and its
    manifests carry `version` (Claude's own validator does not check that a relative source
    exists)."""
    try:
        doc = json.loads((root / CLAUDE_MARKETPLACE).read_text(encoding="utf-8"))
        listed = {e.get("name"): e.get("source") for e in doc["plugins"] if isinstance(e, dict)}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as e:
        return [f"{CLAUDE_MARKETPLACE}: cannot be read: {e}"]
    problems = []
    for name in sorted(build_plugins.PLUGINS):
        if listed.get(name) != f"./plugins/{name}":
            problems.append(f"plugin '{name}': no entry with the source ./plugins/{name}")
            continue
        for rel in build_plugins.MANIFESTS:
            try:
                found = json.loads((root / "plugins" / name / rel).read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
                problems.append(f"plugin '{name}': {rel} cannot be read: {e}")
                continue
            if not isinstance(found, dict) or found.get("version") != version:
                problems.append(f"plugin '{name}': {rel} does not carry version {version}")
    return problems


def layout(plugins: Path, dest: Path, channel: str) -> None:
    """A publish tree in `dest` (a new directory): `plugins/<name>/` copied from the build in
    `plugins` and the channel's two marketplace files."""
    for name in build_plugins.PLUGINS:
        shutil.copytree(plugins / name, dest / "plugins" / name)
    claude, codex = marketplaces(channel)
    for rel, value in ((CLAUDE_MARKETPLACE, claude), (CODEX_MARKETPLACE, codex)):
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        (dest / rel).write_text(dump(value), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=PROG, description="Lay out the modsys publish tree "
                                     "of a channel: the plugins and both marketplace files.")
    parser.add_argument("--channel", required=True, choices=sorted(MARKETPLACES))
    parser.add_argument("--out", required=True, type=Path,
                        help="a directory that does not exist yet")
    args = parser.parse_args(argv)
    out = args.out.absolute()
    if os.path.lexists(out):
        print(f"{PROG}: error: {out} exists — give a new directory", file=sys.stderr)
        return 2
    try:
        with tempfile.TemporaryDirectory() as tmp:
            version = build_channel(build_plugins.ENGINE, Path(tmp), args.channel)
            layout(Path(tmp), out, args.channel)
    except build_plugins.BuildError as e:
        shutil.rmtree(out, ignore_errors=True)
        print(f"{PROG}: error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        shutil.rmtree(out, ignore_errors=True)
        print(f"{PROG}: interrupted", file=sys.stderr)
        return 130
    print(f"{args.channel}: marketplace {MARKETPLACES[args.channel]}, version {version}, "
          f"in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
