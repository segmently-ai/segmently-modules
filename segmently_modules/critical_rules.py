"""The rules of a module doc's critical-rules section (`[lint] critical_rules_heading`).

`show`, `discover` and `rules` return them so an agent sees every rule of a module it is about to
change without reading the whole doc: the section is found by its heading (any level, any case,
any decoration around the words), and each rule is a deeper heading inside it, or, in a section
that has none, a top-level list item.

Every doc of a module (the module doc and each role doc, a submodule's too) can hold such a section
for its own rules. A section whose first line, before any rule, reads `Indexed: every rule of this
doc, YYYY-MM-DD.` is that doc's complete rules index (module-sync's rules-index procedure writes
it); a section without the line is hand-written and its rules count all the same.
"""
from __future__ import annotations

import re
from pathlib import Path

_HEADING_START = re.compile(r"(#{1,6})\s+")
_ITEM = re.compile(r"^(?:[-*+]|\d+[.)])\s+(.*)$")
_INDEXED = re.compile(r"^[*_]*indexed[*_]*:.*?(\d{4}-\d{2}-\d{2})", re.I)  # `**Indexed:**` too
_LEAD = re.compile(r"^[^\w]+")  # emoji, symbols and punctuation before a heading's words
TITLE_MAX = 160
INDEXED_LINE = "Indexed: every rule of this doc, {date}."


def parse_heading(line: str, min_level: int = 1) -> tuple[int, str] | None:
    """(level, words) of a Markdown heading line (`#` to `######`, then whitespace), None for any
    other line or one above `min_level`: the words without the trailing whitespace, the closing
    `#`s and the whitespace before them. The same as matching `^(#{1,6})\\s+(.*?)\\s*#*\\s*$`, in
    linear time: that pattern backtracked cubically on a long run of spaces, and lint took minutes
    on a doc with a 16,000-space heading."""
    m = _HEADING_START.match(line)
    if not m or len(m.group(1)) < min_level:
        return None
    return len(m.group(1)), line[m.end():].rstrip().rstrip("#").rstrip()


def _clean(text: str) -> str:
    text = re.sub(r"\*\*|__", "", text).strip()
    return text if len(text) <= TITLE_MAX else text[:TITLE_MAX - 1].rstrip() + "…"


def section_span(text: str, heading: str) -> tuple[int, int] | None:
    """(first, last) 1-based lines of the doc's critical-rules section, its heading included, up
    to the line before the next heading of the same or a higher level; None when the doc has no
    such section. Matched as `critical_section` matches it; fenced code is skipped."""
    want = heading.strip().lower()
    if not want:
        return None
    lines = text.split("\n")
    start, level, fence = None, None, False
    for n, line in enumerate(lines, 1):
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
            continue
        h = None if fence else parse_heading(line)
        if not h:
            continue
        if start is None:
            if _LEAD.sub("", h[1]).lower().startswith(want):
                start, level = n, h[0]
        elif h[0] <= level:
            return start, n - 1
    return (start, len(lines)) if start is not None else None


def critical_rules(path: Path, heading: str) -> list[dict]:
    """The rules of the doc's critical-rules section: `critical_section(...)["rules"]`."""
    return critical_section(path, heading)["rules"]


def critical_section(path: Path, heading: str) -> dict:
    """{present, indexed, rules} of a doc's critical-rules section — the first heading whose words,
    after any leading emoji or symbols, start with `heading` (any case, any level): "🔴 Critical Rules
    (Read First)" is one, "Test cases from the Critical Rules" is not. `present`: the doc has the
    section; `indexed`: the date of its `Indexed:` line (a line before the first rule, outside
    HTML comments), None when it has none; `rules`: [{line (1-based), title, text}] of the rules
    under that heading, up to the next heading of the same or a higher level; [] when the file is
    missing, unreadable or has no such section. Fenced code is skipped when looking
    for headings and items. `title` = the heading's or the item's words, cut to TITLE_MAX;
    `text` = the whole rule as written, so it reads on its own: the words in full, then a heading
    rule's lines up to the next heading of the section, or a list rule's indented continuation
    lines (stripped)."""
    none = {"present": False, "indexed": None, "rules": []}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").split("\n")
    except OSError:
        return none
    want = heading.strip().lower()
    if not want:
        return none
    level, heads, items, fence, end = None, [], [], False, len(lines) + 1
    indexed, comment = None, False
    for n, line in enumerate(lines, 1):
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
            continue
        if fence:
            continue
        if level is not None and not heads and not items:  # before the first rule: the mark
            stripped = line.strip()
            if comment or stripped.startswith("<!--"):
                comment = "-->" not in stripped
                continue
            mark = _INDEXED.match(stripped)
            if mark and indexed is None:
                indexed = mark.group(1)
                continue
        h = parse_heading(line)
        if level is None:
            if h and _LEAD.sub("", h[1]).lower().startswith(want):
                level = h[0]
            continue
        if h:
            if h[0] <= level:
                end = n
                break
            heads.append({"line": n, "title": _clean(h[1]), "first": h[1]})
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
        if heads:
            r["_body"] = (r["line"] + 1, body)
    if heads:
        rules = [x for r in rules for x in _group_items(r)]
    return {"present": level is not None, "indexed": indexed, "rules": rules}


GROUP_WORDS_MAX = 3  # "DO", "DON'T", "Common Mistakes", "✅ Do": a label, not a rule


def _group_items(rule: dict) -> list[dict]:
    """A heading rule that only labels a group — a title of at most GROUP_WORDS_MAX words over a
    list, not numbered — stands for its items: each top-level item becomes a rule, its title and
    text led by the group's label ("DON'T: call track() directly"), so a quoted item never loses the
    prohibition, and `group` naming the heading. Any other rule stays as it is."""
    first, body = rule.pop("_body")
    words = re.findall(r"[^\W\d_][\w'’-]*", rule["title"])
    if re.match(r"^\W*\d", rule["title"]):  # "1. Use integers": a numbered rule, never a label
        return [rule]
    items = []
    for k, ln in enumerate(body):
        mi = _ITEM.match(ln) if not ln.startswith((" ", "\t")) else None
        if mi:
            cont = []
            for nxt in body[k + 1:]:
                if nxt.strip() and not nxt.startswith((" ", "\t")):
                    break
                cont.append(nxt)
            lead = f"{rule['title']}: {mi.group(1).strip()}"
            items.append({"line": first + k, "title": _clean(lead),
                          "text": "\n".join([lead] + cont).strip(), "group": rule["title"]})
    if len(words) > GROUP_WORDS_MAX or not items:
        return [rule]
    return items
