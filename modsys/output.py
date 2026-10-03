import contextlib
import json
import os
import sys
from typing import Callable

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130  # SIGINT (Ctrl-C), the shell convention 128 + 2


class UsageError(Exception):
    """Bad input, config or registry. Reported on stderr with exit code 2."""


class _QuietStream:
    """A process stream that survives a closed reader (F19): on the first EPIPE it points the
    file descriptor at `os.devnull`, so every later write, and the interpreter's flush at exit,
    land there silently — the verb runs to its end and its exit code stays its own. Any other
    write error (a full disk, a file size limit) is remembered the same way and reported once by
    `quiet_streams` (`modsys: error: cannot write stdout: …`, exit 2). Only the stream's text
    methods are guarded: `.buffer` is forwarded as it is, so engine code writes through
    `print` / `write`."""

    def __init__(self, raw, fd: int):
        self._raw, self._fd = raw, fd
        self.error: OSError | None = None

    def _trip(self) -> None:
        try:
            null = os.open(os.devnull, os.O_WRONLY)
            try:
                os.dup2(null, self._fd)
            finally:
                os.close(null)
        except OSError:
            pass
        try:  # the bytes the failed write left in the buffer go to the null device too
            self._raw.flush()
        except (OSError, ValueError):
            pass

    def _failed(self, error: OSError) -> None:
        if not isinstance(error, BrokenPipeError) and self.error is None:
            self.error = error
        self._trip()

    def write(self, text):
        try:
            return self._raw.write(text)
        except OSError as e:
            self._failed(e)
            return len(text)

    def writelines(self, lines) -> None:
        for line in lines:
            self.write(line)

    def flush(self) -> None:
        try:
            self._raw.flush()
        except OSError as e:
            self._failed(e)

    def __getattr__(self, name):
        return getattr(self._raw, name)


@contextlib.contextmanager
def quiet_streams():
    """Wrap the process's own stdout and stderr in `_QuietStream` for one run (a stream a test
    or a caller swapped in is left alone) and flush them before the interpreter does. A write
    error other than a closed reader ends the run with one stderr line and exit 2."""
    wrapped = []
    for name, fd in (("stdout", 1), ("stderr", 2)):
        raw = getattr(sys, name)
        if raw is not None and raw is getattr(sys, f"__{name}__"):
            guard = _QuietStream(raw, fd)
            setattr(sys, name, guard)
            wrapped.append((name, raw, guard))
    try:
        yield
    finally:
        failed = False
        for name, raw, guard in wrapped:
            try:
                guard.flush()
            finally:
                setattr(sys, name, raw)
            if guard.error is not None:
                failed = True
                if name == "stdout":
                    reason = guard.error.strerror or guard.error
                    try:
                        print(f"modsys: error: cannot write stdout: {reason}", file=sys.stderr)
                        sys.stderr.flush()
                    except (OSError, ValueError):
                        pass
        if failed:
            raise SystemExit(2)


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
    if lines:
        try:  # stdout is block-buffered in a pipe or a file: the note must come after it
            sys.stdout.flush()
        except (OSError, ValueError):  # closed or broken stdout: not this function's contract
            pass
    for line in lines:
        print(f"modsys: note: {line}", file=sys.stderr)


def emit(verb: str, data, as_json: bool, render_text: Callable[[object], None]) -> None:
    if as_json:
        print(json.dumps({"schema": f"modsys.{verb}/1", "data": data},
                         indent=2, ensure_ascii=False))
    else:
        render_text(data)
