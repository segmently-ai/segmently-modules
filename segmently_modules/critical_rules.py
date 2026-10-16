"""The rules of a module doc's critical-rules section (`[lint] critical_rules_heading`).

`show`, `discover` and `rules` return them so an agent sees every rule of a module it is about to
change without reading the whole doc: the section is found by its heading (any level, any case,
any decoration around the words), and each rule is a deeper heading inside it, or, in a section
that has none, a top-level list item.
"""
from __future__ import annotations

import re
from pathlib import Path

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_ITEM = re.compile(r"^(?:[-*+]|\d+[.)])\s+(.*)$")
TITLE_MAX = 160


def _clean(text: str) -> str:
    text = re.sub(r"\*\*|__", "", text).strip()
    return text if len(text) <= TITLE_MAX else text[:TITLE_MAX - 1].rstrip() + "…"


def critical_rules(path: Path, heading: str) -> list[dict]:
    """[{line (1-based), title, text}] of the rules under the first heading that contains
    `heading` (case-insensitive), up to the next heading of the same or a higher level; [] when
    the file is missing, unreadable or has no such section. Fenced code is skipped when looking
    for headings and items. `title` = the heading's or the item's words, cut to TITLE_MAX;
    `text` = the whole rule as written, so it reads on its own: the words in full, then a heading
    rule's lines up to the next heading of the section, or a list rule's indented continuation
    lines (stripped)."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").split("\n")
    except OSError:
        return []
    want = heading.strip().lower()
    if not want:
        return []
    level, heads, items, fence, end = None, [], [], False, len(lines) + 1
    for n, line in enumerate(lines, 1):
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
            continue
        if fence:
            continue
        m = _HEADING.match(line)
        if level is None:
            if m and want in m.group(2).lower():
                level = len(m.group(1))
            continue
        if m:
            if len(m.group(1)) <= level:
                end = n
                break
            heads.append({"line": n, "title": _clean(m.group(2)), "first": m.group(2)})
            continue
        if not line.startswith((" ", "\t")):
            mi = _ITEM.match(line)
            if mi:
                items.append({"line": n, "title": _clean(mi.group(1)), "first": mi.group(1)})
    rules = heads or items
    for k, r in enumerate(rules):
        stop = rules[k + 1]["line"] if k + 1 < len(rules) else end
        body = lines[r["line"]:stop - 1]
        if not heads:  # a list rule: its indented continuation only
            cont = []
            for ln in body:
                if ln.strip() and not ln.startswith((" ", "\t")):
                    break
                cont.append(ln)
            body = cont
        r["text"] = "\n".join([r.pop("first").strip()] + body).strip()
    return rules
