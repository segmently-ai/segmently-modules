"""A stand-in for Claude Code's `claude` in the release tests (never a model): it logs every
call — argv, `CLAUDE_CONFIG_DIR`, which credential variables were set — as a JSON line to
`$FAKE_CLAUDE_LOG`, and answers only the calls a release may make: `--version`, `plugin
validate`, `plugin marketplace add <dir>`, `plugin install <p>@<m> --scope user` (a
directory marketplace; a plugin's `dependencies` are installed with it, as Claude Code 2.1.284
does), `plugin list --json`, `plugin details <p>`. Any other call exits 99 and is logged as
forbidden. `FAKE_CLAUDE_FAIL=validate|install` makes that call exit 1. State lives in
`$CLAUDE_CONFIG_DIR/fake-state.json`; installs are copies under `$CLAUDE_CONFIG_DIR/cache/`."""
import json
import os
import shutil
import sys
from pathlib import Path

SECRETS = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")


def main(argv: list[str]) -> int:
    config = os.environ.get("CLAUDE_CONFIG_DIR")
    record = {"argv": argv, "config": config,
              "secrets": sorted(k for k in SECRETS if k in os.environ)}
    fail = os.environ.get("FAKE_CLAUDE_FAIL", "")
    if argv == ["--version"]:
        log(record)
        print("2.1.284 (Claude Code)")
        return 0
    known = (argv[:2] in (["plugin", "validate"], ["plugin", "install"], ["plugin", "details"])
             or argv[:3] == ["plugin", "marketplace", "add"] or argv == ["plugin", "list",
                                                                        "--json"])
    if not known or not config:
        log({**record, "forbidden": True})
        print(f"fake claude: forbidden call {argv}", file=sys.stderr)
        return 99
    log(record)
    state_path = Path(config) / "fake-state.json"
    state = (json.loads(state_path.read_text()) if state_path.is_file()
             else {"markets": {}, "installed": {}})
    if argv[:2] == ["plugin", "validate"]:
        ok = fail != "validate"
        print(json.dumps({"success": ok, "manifest": {"errors": [] if ok else ["planted"],
                                                      "warnings": []}}))
        return 0 if ok else 1
    if argv[:3] == ["plugin", "marketplace", "add"]:
        root = Path(argv[3])
        name = json.loads((root / ".claude-plugin/marketplace.json").read_text())["name"]
        state["markets"][name] = str(root)
        print(f"added {name}")
    elif argv[:2] == ["plugin", "install"]:
        if fail == "install":
            print("fake claude: planted install failure", file=sys.stderr)
            return 1
        name, market = argv[2].split("@")
        install(state, Path(config), name, market)
        print(f"installed {argv[2]}")
    elif argv[:2] == ["plugin", "list"]:
        print(json.dumps([{"id": pid, "version": v["version"], "scope": "user",
                           "enabled": True, "installPath": v["path"]}
                          for pid, v in state["installed"].items()]))
    else:
        pid = next(p for p in state["installed"] if p == argv[2] or p.split("@")[0] == argv[2])
        skills = sorted(p.parent.name for p in
                        Path(state["installed"][pid]["path"]).glob("skills/*/SKILL.md"))
        print(f"{pid}\n  Skills ({len(skills)})  {', '.join(skills)}")
    state_path.write_text(json.dumps(state))
    return 0


def install(state: dict, config: Path, name: str, market: str) -> None:
    root = Path(state["markets"][market])
    entry = next(e for e in json.loads((root / ".claude-plugin/marketplace.json").read_text())
                 ["plugins"] if e["name"] == name)
    source = root / entry["source"]
    manifest = json.loads((source / ".claude-plugin/plugin.json").read_text())
    dest = config / "cache" / market / name / manifest["version"]
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(source, dest)
    state["installed"][f"{name}@{market}"] = {"version": manifest["version"], "path": str(dest)}
    for dep in manifest.get("dependencies", []):
        if f"{dep}@{market}" not in state["installed"]:
            install(state, config, dep, market)


def log(record: dict) -> None:
    path = os.environ.get("FAKE_CLAUDE_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
