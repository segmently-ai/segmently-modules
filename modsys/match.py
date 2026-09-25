import re

from modsys.output import EXIT_OK, UsageError, emit
from modsys.registry import as_dict, as_list
from modsys.workspace import Workspace


_WORD = re.compile(r"\w")


def term_pattern(term: str) -> re.Pattern:
    # Boundary only on an edge that is a word char: identical to \b for word-edged
    # terms ("book" never hits "books"), and a superset for terms with a non-word
    # edge (".epub", "c++ code", "modules/xyz"), which \b matched only by accident.
    # Verified in the 2026-09-25 dry-run: 0 parity diffs on the real corpus.
    t = term.lower()
    left = r"(?<!\w)" if t and _WORD.match(t[0]) else ""
    right = r"(?!\w)" if t and _WORD.match(t[-1]) else ""
    return re.compile(left + re.escape(t) + right)


def matched_terms(text_lower: str, terms) -> list:
    # malformed registry values (non-list, non-str terms) are lint's job; ignore them here
    return [t for t in as_list(terms)
            if isinstance(t, str) and term_pattern(t).search(text_lower)]


def negative_phrases(entry: dict) -> list:
    """negative_keywords: {generic_word: [phrases]} or a legacy flat phrase list.
    Only phrase matches penalize."""
    nk = entry.get("negative_keywords")
    if isinstance(nk, dict):
        return [p for phrases in nk.values() for p in as_list(phrases)]
    if isinstance(nk, list):
        return nk
    return []


def score_entry(text_lower: str, entry: dict, weights: dict) -> tuple[int, list, list]:
    hits = matched_terms(text_lower, entry.get("keywords"))
    score = weights["keyword_weight"] * len(hits)
    for combo in as_list(entry.get("required_combinations")):
        terms = combo if isinstance(combo, list) else [combo]
        if terms and len(matched_terms(text_lower, terms)) == len(terms):
            score += weights["combination_weight"]
    neg = matched_terms(text_lower, negative_phrases(entry))
    score += weights["negative_weight"] * len(neg)
    return score, hits, neg


def match_modules(modules: dict, text: str, weights: dict, top: int,
                  min_score: int) -> list[dict]:
    text_lower = text.lower()
    rows = []
    for name, entry in modules.items():
        if not isinstance(entry, dict):
            continue
        score, hits, neg = score_entry(text_lower, entry, weights)
        if score >= min_score and hits:
            rows.append({"module": name, "score": score, "keywords": hits, "negative": neg})
        for child, sub in as_dict(entry.get("submodules")).items():
            if not isinstance(sub, dict):
                continue
            c_hits = matched_terms(text_lower, sub.get("keywords"))
            c_score = weights["keyword_weight"] * len(c_hits)
            if c_hits and c_score >= min_score:
                rows.append({"module": f"{name}/{child}", "score": c_score,
                             "keywords": c_hits, "negative": []})
    rows.sort(key=lambda r: (-r["score"], r["module"]))
    return rows[:top]


def register(sub, common) -> None:
    p = sub.add_parser("match", parents=[common],
                       help="rank modules by keyword match against task text")
    p.add_argument("text")
    p.add_argument("--top", type=int)
    p.add_argument("--min-score", type=int)
    p.set_defaults(func=run)


def run(args) -> int:
    if args.top is not None and args.top < 0:
        raise UsageError("--top must be >= 0")
    ws = Workspace.from_args(args)
    cfg = ws.config["match"]
    rows = match_modules(ws.registry.modules, args.text, cfg,
                         cfg["top"] if args.top is None else args.top,
                         cfg["min_score"] if args.min_score is None else args.min_score)
    emit("match", rows, args.json, _render)
    return EXIT_OK


def _render(rows) -> None:
    if not rows:
        print("no keyword matches (try rephrasing with domain terms, or use: list)")
        return
    for r in rows:
        neg = f"  NEGATIVE:{','.join(r['negative'])}" if r["negative"] else ""
        print(f"{r['score']:>4}  {r['module']:<42} {', '.join(r['keywords'])}{neg}")
