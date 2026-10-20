"""`segmently-modules catalog [--settings] [--json]`: one card per module and per child — name,
status, description, keywords (a child also names its parent) — the input an agent reads to
choose modules by meaning (P8.1 S2). Read-only: no lock, no write, never runs the agent. JSON
carries `match: {mode, semantic}` (`semantic` = a valid `SEGMENTLY_MODULES_AGENT_COMMAND` is set)
and the `search` settings. `catalog --settings` prints only the settings: every `[match]` and
`[search]` key, `[rules] index` and `[discover]`, defaults filled in, and no card (the registry is not read). `catalog --plain` prints
only each card's id, description and keywords, one wrapped block each, for an agent to read whole
and judge by meaning (2026-10-19: discover's step 1 reads every card itself)."""
import json
import textwrap

from segmently_modules.output import EXIT_OK, UsageError, defer_note, emit
from segmently_modules.registry import as_dict
from segmently_modules.config import (LAYER_SCHEMA, core_defaults, discover_settings, rules_index_setting, search_all,
                                      search_settings)
from segmently_modules.semantic import agent_configured, configured_mode
from segmently_modules.workspace import Workspace


def _keywords(entry: dict) -> list[str]:
    kw = entry.get("keywords")
    return [k for k in kw if isinstance(k, str)] if isinstance(kw, list) else []


def _text(value) -> str:
    return value if isinstance(value, str) else ""


def cards(modules: dict) -> list[dict]:
    """Registry order, each child right after its parent. A child's description and status are
    its own, falling back to the parent's (as `show` does)."""
    out = []
    for name, entry in modules.items():
        if not isinstance(entry, dict):
            continue
        out.append({"name": name, "status": _text(entry.get("status")),
                    "description": _text(entry.get("description")),
                    "keywords": _keywords(entry)})
        for child, sub in as_dict(entry.get("submodules")).items():
            sub = as_dict(sub)
            out.append({"name": f"{name}/{child}",
                        "status": _text(sub.get("status")) or _text(entry.get("status")),
                        "description": _text(sub.get("description")) or
                        _text(entry.get("description")),
                        "keywords": _keywords(sub), "parent": name})
    return out


def register(sub, common) -> None:
    p = sub.add_parser("catalog", parents=[common],
                       help="one card per module and child, for choosing modules by meaning")
    p.add_argument("--settings", action="store_true",
                   help="print only the settings: every [match] and [search] key, defaults "
                        "filled in")
    p.add_argument("--plain", action="store_true",
                   help="print only each module's and child's id, description and keywords, one "
                        "block each, to read whole")
    p.set_defaults(func=run)


def _semantic(config: dict) -> bool:
    """`match.semantic`. A malformed `SEGMENTLY_MODULES_AGENT_COMMAND` / `SEGMENTLY_MODULES_AGENT_TIMEOUT` (the timeout
    is checked first) makes it false with one deferred stderr note — the refusal the verbs that
    run the agent give with exit 2: `catalog` itself reports, it never runs the agent."""
    try:
        return agent_configured(config)
    except UsageError as e:
        defer_note(f"{e} — match.semantic is false")
        return False


def match_settings(config: dict) -> dict:
    """`catalog --settings`' `match`: what `catalog` shows (`mode`, `semantic`), then every other
    key `[match]` knows, the merged value or the engine default."""
    merged, defaults = config.get("match") or {}, core_defaults().get("match") or {}
    out = {"mode": configured_mode(config), "semantic": _semantic(config)}
    for key in LAYER_SCHEMA["match"]:
        if key not in out:
            out[key] = merged.get(key, defaults.get(key))
    return out


def run(args) -> int:
    ws = Workspace.from_args(args)
    if args.settings and args.plain:
        raise UsageError("--settings and --plain are two different prints: give one")
    if args.settings:
        data = {"match": match_settings(ws.config), "search": search_all(ws.config),
                "rules": {"index": rules_index_setting(ws.config)},
                # 2026-10-20: module-discover reads `[discover] save` here (step 1's settings) for its step 9
                "discover": discover_settings(ws.config)}
        emit("catalog", data, args.json, _render_settings)
        return EXIT_OK
    if args.plain:
        data = {"modules": [{"module": c["name"], "description": c["description"], "keywords": c["keywords"]}
                            for c in cards(ws.registry.modules)]}
        emit("catalog", data, args.json, _render_cards)
        return EXIT_OK
    data = {"match": {"mode": configured_mode(ws.config), "semantic": _semantic(ws.config)},
            "search": search_settings(ws.config),
            "modules": cards(ws.registry.modules)}
    emit("catalog", data, args.json, _render)
    return EXIT_OK


def _render_settings(data) -> None:
    """One `key = value` line per key under a `[match]`, a `[search]`, a `[rules]` and a `[discover]`
    heading; each value as TOML writes it."""
    for i, group in enumerate(("match", "search", "rules", "discover")):
        if i:
            print()
        print(f"[{group}]")
        for key, value in data[group].items():
            print(f"{key} = {json.dumps(value, ensure_ascii=False)}")


def _render_cards(data) -> None:
    """One block per card: the id, then the description and the keywords wrapped at 100 characters, so
    a reader that cuts long lines still gets every word."""
    for c in data["modules"]:
        print(c["module"])
        print(textwrap.fill(c["description"] or "(no description)", 100, initial_indent="  ",
                            subsequent_indent="  ", break_long_words=False, break_on_hyphens=False))
        if c["keywords"]:
            print(textwrap.fill("keywords: " + ", ".join(c["keywords"]), 100, initial_indent="  ",
                                subsequent_indent="    ", break_long_words=False, break_on_hyphens=False))
        print()
    print(f"{len(data['modules'])} modules and children")


def _render(data) -> None:
    if not data["modules"]:
        print("no modules in the registry")
    for c in data["modules"]:
        parent = f"  (child of {c['parent']})" if "parent" in c else ""
        print(f"{c['name']}  {c['status']}  {c['description']}{parent}  "
              f"[{', '.join(c['keywords'])}]")
