"""The work order of `modsys choose` (P8.1 S3, layer 1) and the validation of an answer to it.
The work order is everything an agent needs to pick modules by meaning: the task verbatim, the
rules, one card per module and child, the answer's JSON Schema and a digest of the cards. It is
deterministic (no time, path, host or random value), so two runs on one tree are byte-identical.
`validate_answer` is the one validator behind `choose --apply`, `choose --run` and
`--match semantic|hybrid`."""
import hashlib
import json
import string
from pathlib import Path

from modsys.catalog_cmd import cards as catalog_cards
from modsys.config import card_keywords, search_settings
from modsys.create import resolve_template_source
from modsys.output import UsageError

DEFAULT_MAX_PICKS = 5
# Shaped for strict structured outputs (`codex exec --output-schema` sends it in strict mode):
# every object closed and listing every property as required, only keywords strict mode takes
# (no `$schema`, no `minimum` / `maximum`). `validate_answer` stays lenient: `none`, `reason`
# and `catalog_digest` may be missing, extra keys are ignored, and it checks 0..1 itself.
ANSWER_SCHEMA = {
    "title": "modsys choose answer",
    "type": "object",
    "properties": {
        "picks": {"type": "array", "items": {
            "type": "object",
            "properties": {"module": {"type": "string"},
                           "confidence": {"type": "number", "description": "from 0 to 1"},
                           "reason": {"type": "string"}},
            "required": ["module", "confidence", "reason"],
            "additionalProperties": False}},
        "none": {"type": "boolean"},
        "catalog_digest": {"type": ["string", "null"],
                           "description": "the work order's catalog_digest, or null"}},
    "required": ["picks", "none", "catalog_digest"],
    "additionalProperties": False,
}
RULES_TEMPLATE = "choose/rules.md"  # the instruction of the work order, a template (D3)
DEPTH = {  # fixed English texts: the work order must not vary from run to run
    "quick": "Choose from the cards only; do not open any file.",
    "standard": "Choose from the cards, and also open the INDEX or the head of MODULE.md of up "
                "to 3 candidates before you answer.",
    "deep": "Choose from the cards, and also read the candidates' docs and confirm the choice "
            "in their code before you answer.",
}


def work_card(card: dict, keywords: int | None = None) -> dict:
    """A card of the work order: the first `keywords` registry keywords (all when None)."""
    kw = card["keywords"] if keywords is None else card["keywords"][:keywords]
    out = {"module": card["name"], "description": card["description"], "keywords": kw}
    if "parent" in card:
        out["parent"] = card["parent"]
    return out


def digest_of(cards: list[dict]) -> str:
    canonical = json.dumps(cards, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def choose_rules_source(ws) -> tuple[str, Path]:
    """(source, path) of `choose/rules.md`: the template chain without the role fallback."""
    return resolve_template_source(ws, RULES_TEMPLATE, None, fallback=False)


def template_rules(ws, max_picks: int, depth: str) -> list[str]:
    """The rules of the work order: every line of the winning `choose/rules.md` that starts
    with `- ` (the text after it, trailing whitespace removed, an empty one is a note), in file
    order, with `$max_picks` / `$depth` / `$$` substituted per rule. A template that cannot be
    read, or holds no rule, is a usage error naming its root-relative path."""
    path = choose_rules_source(ws)[1]
    try:
        text = path.read_bytes().decode("utf-8")
    except OSError as e:
        raise UsageError(f"cannot read {ws.rel(path)}: {e.strerror or e}") from None
    except UnicodeDecodeError:
        raise UsageError(f"cannot read {ws.rel(path)}: not valid UTF-8") from None
    text = text.removeprefix("\ufeff")
    rules = [line[2:].rstrip() for line in text.split("\n") if line.startswith("- ")]
    rules = [r for r in rules if r]
    if not rules:
        raise UsageError(f'{ws.rel(path)}: no rule in choose/rules.md (a rule is a line '
                         f'starting with "- ")')
    return [string.Template(r).safe_substitute(max_picks=max_picks, depth=depth) for r in rules]


def build(ws, task: str, max_picks: int = DEFAULT_MAX_PICKS, effort: str | None = None) -> dict:
    """The work order. `effort` (`choose --effort`) overrides `[search] effort` for this order;
    the cards carry the first `[search] card_keywords` keywords, and the digest covers them."""
    search = search_settings(ws.config)
    if effort is not None:
        search["effort"] = effort
    limit = card_keywords(ws.config)
    cards = [work_card(c, limit) for c in catalog_cards(ws.registry.modules)]
    rules = template_rules(ws, max_picks, DEPTH[search["effort"]])
    return {"task": task, "rules": rules, "cards": cards, "answer_schema": ANSWER_SCHEMA,
            "catalog_digest": digest_of(cards), "max_picks": max_picks, "search": search}


def render(order: dict) -> None:
    """The work order as a prompt any agent can take."""
    print("Task:")
    print(order["task"])
    print()
    print("Rules:")
    for r in order["rules"]:
        print(f"- {r}")
    print()
    print("Candidates (one per line: module, description, keywords):")
    for c in order["cards"]:
        parent = f"  (child of {c['parent']})" if "parent" in c else ""
        print(f"{c['module']}  {c['description']}  [{', '.join(c['keywords'])}]{parent}")
    print()
    print("Answer schema:")
    print(json.dumps(order["answer_schema"], indent=2))
    print()
    print(f"catalog_digest: {order['catalog_digest']}")


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate_answer(answer, order: dict, max_picks: int | None = None):
    """(picks, none, notes) of an answer object against the cards of `order`. Picks: dicts
    `{module, confidence, reason?}` sorted by confidence (ties by card order), unknown ids
    dropped, duplicates merged, cut to `max_picks`. A schema violation is a usage error naming
    the path; an unknown id, a duplicate, a digest mismatch or a cut is a note."""
    if not isinstance(answer, dict):
        raise UsageError("answer: expected a JSON object")
    raw = answer.get("picks")
    if not isinstance(raw, list):
        raise UsageError("answer: picks: required, an array (may be empty)")
    none = answer.get("none", False)
    if not isinstance(none, bool):
        raise UsageError("answer: none: expected a boolean")
    digest = answer.get("catalog_digest")
    if digest is not None and not isinstance(digest, str):
        raise UsageError("answer: catalog_digest: expected a string")
    known = [c["module"] for c in order["cards"]]
    best: dict[str, dict] = {}
    notes: list[str] = []
    for i, pick in enumerate(raw):
        where = f"answer: picks[{i}]"
        if not isinstance(pick, dict):
            raise UsageError(f"{where}: expected an object")
        if not isinstance(pick.get("module"), str):
            raise UsageError(f"{where}.module: required, a string")
        conf = pick.get("confidence")
        if not _num(conf):
            raise UsageError(f"{where}.confidence: required, a number from 0 to 1")
        if not 0 <= conf <= 1:
            raise UsageError(f"{where}.confidence: expected a number from 0 to 1, got {conf!r}")
        reason = pick.get("reason")
        if reason is not None and not isinstance(reason, str):
            raise UsageError(f"{where}.reason: expected a string")
        row = {"module": pick["module"], "confidence": conf}
        if reason is not None:
            row["reason"] = reason
        if row["module"] not in known:
            notes.append(f"unknown module dropped: {row['module']}")
        elif row["module"] in best:
            notes.append(f"duplicate pick {row['module']}: kept the highest confidence")
            if conf > best[row["module"]]["confidence"]:
                best[row["module"]] = row
        else:
            best[row["module"]] = row
    if digest is not None and digest != order["catalog_digest"]:
        notes.append("catalog changed since the work order")
    if none:
        if raw:
            notes = [n for n in notes if n == "catalog changed since the work order"]
            notes.append("none is true; picks ignored")
        return [], True, notes
    picks = sorted(best.values(), key=lambda p: (-p["confidence"], known.index(p["module"])))
    if max_picks is not None and len(picks) > max_picks:
        notes.append(f"the agent returned {len(picks)} picks; kept the top {max_picks}")
        picks = picks[:max_picks]
    return picks, False, notes
