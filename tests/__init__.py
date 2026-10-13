"""The test package. Every test process starts with sentinel `claude` and `codex` executables
first on PATH (P8.1 AC-072): a real agent CLI can never run from a test — a sentinel that is
executed exits 97 and records the call in `SENTINEL_LOG`. `REAL_PATH` is the PATH before the
sentinels; tests that look for the real Claude Code CLI (the packaging tests, which never run it
as an agent command) resolve it with `shutil.which("claude", path=REAL_PATH)`. The agent variables
of the developer's shell (`SEGMENTLY_MODULES_AGENT_COMMAND`, `SEGMENTLY_MODULES_AGENT_TIMEOUT`, `SEGMENTLY_MODULES_WORK_ORDER`) are
cleared first."""
import atexit
import os
import shutil
import stat
import tempfile
from pathlib import Path

REAL_PATH = os.environ.get("PATH", "")
for _var in ("SEGMENTLY_MODULES_AGENT_COMMAND", "SEGMENTLY_MODULES_AGENT_TIMEOUT", "SEGMENTLY_MODULES_WORK_ORDER"):
    os.environ.pop(_var, None)  # a developer's own agent settings never reach a test
_SENTINELS = Path(tempfile.mkdtemp(prefix="segmently-modules-sentinel-"))
SENTINEL_LOG = _SENTINELS / "executed.log"
for _name in ("claude", "codex"):
    _exe = _SENTINELS / _name
    _exe.write_text('#!/bin/sh\necho "sentinel: a real agent CLI was executed ($0)" >&2\n'
                    f'echo "$0 $*" >> "{SENTINEL_LOG}"\nexit 97\n', encoding="utf-8")
    _exe.chmod(_exe.stat().st_mode | stat.S_IXUSR)
os.environ["PATH"] = f"{_SENTINELS}{os.pathsep}{REAL_PATH}"
atexit.register(shutil.rmtree, _SENTINELS, ignore_errors=True)
