"""Search modes of `match`, `context` and `discover --task` (P8.1 S1): `lexical` (keyword routing,
the default), `semantic` (an embedder's ranking) and `hybrid` (both). This module resolves the
mode (the `--match` flag wins over `[match] mode`, which wins over `lexical`), refuses or
degrades when no embedder is configured (S4), and holds the one seam an embedder plugs into —
`semantic_rows`. A lexical run never reaches this module's seam and changes no byte."""
from modsys.config import MATCH_MODES, validate_semantic
from modsys.output import UsageError

NO_EMBEDDER = ("semantic matching needs an embedder ([match.semantic] in .modsys/config.toml); "
               "in an agent, the skills choose modules from `modsys catalog`")
NO_EMBEDDER_NOTE = "semantic part skipped: no embedder configured"


def add_match_flag(parser) -> None:
    parser.add_argument("--match", choices=MATCH_MODES, metavar="{lexical,semantic,hybrid}",
                        help="how modules are found for the task text (default: [match] mode, "
                             "else lexical)")


def configured_mode(config: dict) -> str:
    """`[match] mode` of the loaded config (validated at load), `lexical` when unset."""
    return (config.get("match") or {}).get("mode", "lexical")


def semantic_config(config: dict) -> dict | None:
    """The `[match.semantic]` table of the merged config, or None without an embedder."""
    table = (config.get("match") or {}).get("semantic")
    if table is None:
        return None
    validate_semantic(table, "merged config")  # a merge of two valid layers can break the shape
    return table


def effective_mode(flag: str | None, config: dict) -> str:
    return flag or configured_mode(config)


def resolve(ws, flag: str | None) -> tuple[str, list[str]]:
    """(mode, notes) for one run. `semantic` without an embedder is refused (exit 2); `hybrid`
    without one runs lexically and says so in `notes`."""
    mode = effective_mode(flag, ws.config)
    if mode == "lexical" or semantic_config(ws.config) is not None:
        return mode, []
    if mode == "semantic":
        raise UsageError(NO_EMBEDDER)
    return mode, [NO_EMBEDDER_NOTE]


def semantic_rows(ws, text: str, top: int) -> list[dict]:
    """The embedder's ranking of the task text: rows `{module, similarity}`, best first. The
    seam of the embedder support (P8.1 task 3b replaces this function); it is reached only
    with `[match.semantic]` configured and the effective mode `semantic` or `hybrid`."""
    raise NotImplementedError("embedder support is not built yet")
