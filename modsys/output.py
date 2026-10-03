import json
import sys
from typing import Callable

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130  # SIGINT (Ctrl-C), the shell convention 128 + 2


class UsageError(Exception):
    """Bad input, config or registry. Reported on stderr with exit code 2."""


_DEFERRED_NOTES: list[str] = []


def defer_note(line: str) -> None:
    """Queue one stderr line (without its `modsys: note: ` prefix) for `flush_notes`: a verb
    that decides early but must say it only when the run succeeds, after its stdout."""
    _DEFERRED_NOTES.append(line)


def clear_notes() -> None:
    _DEFERRED_NOTES.clear()


def flush_notes() -> None:
    """Print the queued notes to stderr (`modsys: note: …`, one line each) and empty the queue.
    `cli.main` calls it only after a verb returned exit 0."""
    lines = list(_DEFERRED_NOTES)
    _DEFERRED_NOTES.clear()
    for line in lines:
        print(f"modsys: note: {line}", file=sys.stderr)


def emit(verb: str, data, as_json: bool, render_text: Callable[[object], None]) -> None:
    if as_json:
        print(json.dumps({"schema": f"modsys.{verb}/1", "data": data},
                         indent=2, ensure_ascii=False))
    else:
        render_text(data)
