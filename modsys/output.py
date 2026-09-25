import json
from typing import Callable

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130  # SIGINT (Ctrl-C), the shell convention 128 + 2


class UsageError(Exception):
    """Bad input, config or registry. Reported on stderr with exit code 2."""


def emit(verb: str, data, as_json: bool, render_text: Callable[[object], None]) -> None:
    if as_json:
        print(json.dumps({"schema": f"modsys.{verb}/1", "data": data},
                         indent=2, ensure_ascii=False))
    else:
        render_text(data)
