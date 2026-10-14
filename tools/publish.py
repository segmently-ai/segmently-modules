"""The publish tree of the segmently-modules plugins (P6 D4): channel versions, the two marketplace files
and their merge, the structural check of the Codex one — stdlib only.

    python3 tools/publish.py --channel dev|stable --out DIR

builds the three plugins (tools/build_plugins.py) with the channel's version into
`DIR/plugins/` and writes `DIR/.claude-plugin/marketplace.json` (Claude Code) and
`DIR/.agents/plugins/marketplace.json` (Codex) — the tree `claude plugin validate` and `codex
plugin marketplace add` read; `tools/release.py` writes the same into the publish repository.

Channels are branches of the publish repository; each has its own marketplace name:
`stable` → `segmently-modules`, `dev` → `segmently-modules-dev` (two marketplaces can be added side by side).
Versions (one source: the engine's `__version__`, X.Y.Z or X.Y.Z.devN): `stable` = X.Y.Z;
`dev` = X.Y.Z-dev.h<8 hex> — the content hash of the three plugin trees, their manifests
read with the `version` blanked (the one value made from the hash), so a rebuild of the same
tree is the same version and any other change — a manifest key too — is a new one; the `h`
keeps an all-digit hash a valid SemVer identifier. A version lives only in each plugin's
manifests, never in a marketplace entry.
Exit 0 laid out · 2 a refusal or a write failure (stdout empty, stderr `publish.py: error: …`;
--out and every directory the run created are removed) · 130 Ctrl-C (the same clean-up)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True  # running a tool never leaves tools/__pycache__ in the engine
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_plugins  # noqa: E402  (a sibling script)

MARKETPLACES = {"stable": "segmently-modules", "dev": "segmently-modules-dev"}  # channel (branch) -> marketplace
CLAUDE_MARKETPLACE = ".claude-plugin/marketplace.json"
CODEX_MARKETPLACE = ".agents/plugins/marketplace.json"
OWNER = {"name": "Segmently Modules maintainers"}
DESCRIPTION = {"stable": "The Segmently Modules plugins: module-registry skills and the "
                         "segmently-modules CLI",
               "dev": "The Segmently Modules plugins, dev channel: every change before a release"}
README_PIN = re.compile(rb"segmently-modules\.git@v\d+\.\d+\.\d+")  # a stable build's pin
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


def blank_version(data: bytes) -> bytes:
    """A manifest's bytes with its `version` blanked — what the content hash reads."""
    try:
        doc = json.loads(data)
    except ValueError:
        return data
    return dump({**doc, "version": ""}).encode() if isinstance(doc, dict) else data


def content_hash(plugins: Path) -> str:
    """sha256 over (path, mode, bytes) of every file of the three plugin directories in
    `plugins`, in path order — a manifest with its `version` blanked and a README with its
    install pins (`segmently-modules.git@vX.Y.Z`) unpinned (the version is made from this hash;
    any other change moves it)."""
    h = hashlib.sha256()
    for name in sorted(build_plugins.PLUGINS):
        root = plugins / name
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            rel = path.relative_to(root).as_posix()
            data = path.read_bytes()
            if rel in build_plugins.MANIFESTS:
                data = blank_version(data)
            elif rel == "README.md":
                data = README_PIN.sub(b"segmently-modules.git", data)
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


def merge_plugins(existing, ours: list[dict], where: str = "the marketplace file") -> list[dict]:
    """The `plugins` list: every entry we do not own kept as it is and where it is (whatever
    its shape: an entry whose `name` is not a string is not ours), ours replaced in place
    (merged by name; a second entry with one of our names is dropped — the list never holds a
    name of ours twice), the missing ones of ours appended in name order. A `plugins` value
    that is not a list is a BuildError naming `where`: its entries could not be kept."""
    if existing is None:
        existing = []
    if not isinstance(existing, list):
        raise build_plugins.BuildError(f"{where}: plugins is not a list — fix it: the release "
                                       f"merges its entries into it")
    mine = {e["name"]: e for e in ours}
    out, seen = [], set()
    for entry in existing:
        name = entry.get("name") if isinstance(entry, dict) else None
        if not isinstance(name, str) or name not in mine:
            out.append(entry)
        elif name not in seen:
            out.append(mine[name])
            seen.add(name)
    return out + [e for name, e in sorted(mine.items()) if name not in seen]


def marketplaces(channel: str, claude_old=None, codex_old=None) -> tuple[dict, dict]:
    """The two marketplace files of a channel, merged into the ones on the branch (None: new).
    Ours: `name`, and `owner` / `description` of the Claude one; other keys are kept. An old
    file that is not a JSON object is a BuildError naming it."""
    ours = entries(channel)
    for rel, old in ((CLAUDE_MARKETPLACE, claude_old), (CODEX_MARKETPLACE, codex_old)):
        if old is not None and not isinstance(old, dict):
            raise build_plugins.BuildError(f"{rel} is not a JSON object — fix it: the release "
                                           f"merges its entries into it")
    claude, codex = claude_old or {}, codex_old or {}
    name = MARKETPLACES[channel]
    claude = {"name": name, "owner": dict(OWNER), "description": DESCRIPTION[channel],
              **{k: v for k, v in claude.items() if k not in ("name", "owner", "description",
                                                             "plugins")},
              "plugins": merge_plugins(claude.get("plugins"), [c for c, _ in ours.values()],
                                       CLAUDE_MARKETPLACE)}
    codex = {"name": name, **{k: v for k, v in codex.items() if k not in ("name", "plugins")},
             "plugins": merge_plugins(codex.get("plugins"), [x for _, x in ours.values()],
                                      CODEX_MARKETPLACE)}
    return claude, codex


def dump(value) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def codex_problems(root: Path) -> list[str]:
    """The structural check of `.agents/plugins/marketplace.json` under `root` (Codex documents
    no validator): a JSON object with a `name` and a `plugins` list; every entry an object with
    a unique `name` (a string) and a `source` object; a `local` source's `path` starts with
    `./`, stays inside `root` (real paths: a symlink out of it leaves it) and is a directory."""
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
    seen, real_root = set(), Path(os.path.realpath(root))
    for i, entry in enumerate(plugins):
        name = entry.get("name") if isinstance(entry, dict) else None
        named = isinstance(name, str) and bool(name)
        label = f"plugin '{name}'" if named else f"plugins[{i}]"
        if named:
            if name in seen:
                problems.append(f"{label}: the name is used twice")
            seen.add(name)
        elif name is None or name == "":
            problems.append(f"{label}: name is missing")
        else:
            problems.append(f"{label}: name is not a string")
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
        target = Path(os.path.realpath(root / rel))
        if target != real_root and real_root not in target.parents:
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
    `plugins` and the channel's two marketplace files — directories 0755 and the two files 0644
    whatever the umask (the plugins keep the builder's modes)."""
    for name in build_plugins.PLUGINS:
        shutil.copytree(plugins / name, dest / "plugins" / name)
    claude, codex = marketplaces(channel)
    for rel, value in ((CLAUDE_MARKETPLACE, claude), (CODEX_MARKETPLACE, codex)):
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        (dest / rel).write_text(dump(value), encoding="utf-8")
        os.chmod(dest / rel, 0o644)
    for d in (dest, dest / "plugins", *(p for rel in (CLAUDE_MARKETPLACE, CODEX_MARKETPLACE)
                                        for p in (dest / rel).parents if dest in p.parents)):
        os.chmod(d, 0o755)


def write_error(e: OSError, fallback: Path) -> str:
    """`cannot write <path>: <reason>` for a failed write (shutil's list of failed copies:
    the first one)."""
    if isinstance(e, shutil.Error) and e.args and isinstance(e.args[0], list) and e.args[0]:
        _, dst, why = e.args[0][0]
        return f"cannot write {dst}: {why}"
    return f"cannot write {e.filename or fallback}: {e.strerror or e}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=PROG, description="Lay out the segmently-modules publish tree "
                                     "of a channel: the plugins and both marketplace files.")
    parser.add_argument("--channel", required=True, choices=sorted(MARKETPLACES))
    parser.add_argument("--out", required=True, type=Path,
                        help="a directory that does not exist yet")
    args = parser.parse_args(argv)
    out = args.out.absolute()
    if os.path.lexists(out):
        print(f"{PROG}: error: {out} exists — give a new directory", file=sys.stderr)
        return 2
    created: list[Path] = []  # the parents of --out this run made: gone again on a failure

    def clean_up() -> None:
        shutil.rmtree(out, ignore_errors=True)
        build_plugins.remove_dirs(created)

    try:
        with tempfile.TemporaryDirectory() as tmp:
            version = build_channel(build_plugins.ENGINE, Path(tmp), args.channel)
            created += build_plugins.make_dirs(out.parent)
            layout(Path(tmp), out, args.channel)
    except build_plugins.BuildError as e:
        clean_up()
        print(f"{PROG}: error: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        clean_up()
        print(f"{PROG}: error: {write_error(e, out)}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        clean_up()
        print(f"{PROG}: interrupted", file=sys.stderr)
        return 130
    print(f"{args.channel}: marketplace {MARKETPLACES[args.channel]}, version {version}, "
          f"in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
