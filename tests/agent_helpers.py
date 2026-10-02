"""Helpers of the P8.1 agent tests: a configurable fake agent command (`tests/fake_agent.py`),
the user config that names it, and a PATH whose `claude` / `codex` are sentinels that fail the
test when executed — no real agent CLI is ever reachable from these tests."""
import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from unittest import mock

from tests.helpers import SPLIT_FIXTURE, copy_fixture

FAKE = Path(__file__).with_name("fake_agent.py")
SENTINEL_BODY = '#!/bin/sh\necho "sentinel: a real agent CLI was executed ($0)" >&2\n' \
                'echo "$0 $*" >> "$SENTINEL_LOG"\nexit 97\n'


def picks(*items):
    """A valid answer: items are (module, confidence[, reason])."""
    return {"picks": [{"module": m, "confidence": c, **({"reason": r[0]} if r else {})}
                      for m, c, *r in items], "none": False}


class AgentRepo:
    """Mixin for unittest.TestCase: a copy of the split fixture, sentinel claude/codex first on
    PATH, no inherited agent environment."""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.root = copy_fixture(self.tmp, SPLIT_FIXTURE)
        self.R = ("--root", str(self.root))
        self.bin = self.tmp / "sentinel-bin"
        self.bin.mkdir()
        self.sentinel_log = self.tmp / "sentinel.log"
        for name in ("claude", "codex"):
            exe = self.bin / name
            exe.write_text(SENTINEL_BODY, encoding="utf-8")
            exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
        patcher = mock.patch.dict(os.environ, {"PATH": f"{self.bin}{os.pathsep}"
                                               f"{os.environ.get('PATH', '')}",
                                               "SENTINEL_LOG": str(self.sentinel_log)})
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("MODSYS_AGENT_COMMAND", None)
        self.calls_log = self.tmp / "calls.json"
        self.behaviour_n = 0

    def tearDown(self):
        self.assertFalse(self.sentinel_log.exists(), "a sentinel claude/codex was executed")
        super().tearDown()

    def config(self, text: str, name: str = "config.toml") -> None:
        (self.root / ".modsys").mkdir(exist_ok=True)
        (self.root / ".modsys" / name).write_text(text, encoding="utf-8")

    def behaviour(self, **cfg) -> list[str]:
        """The argv of a fake agent with this behaviour (answer: a dict is dumped as JSON)."""
        self.behaviour_n += 1
        if isinstance(cfg.get("answer"), (dict, list)):
            cfg["answer"] = json.dumps(cfg["answer"])
        cfg.setdefault("log", str(self.calls_log))
        path = self.tmp / f"behaviour-{self.behaviour_n}.json"
        path.write_text(json.dumps(cfg), encoding="utf-8")
        return [sys.executable, str(FAKE), str(path)]

    def agent(self, extra_argv=(), timeout_s=None, search: str = "", **cfg) -> list[str]:
        """Configure the fake agent as `[agent] command` in config.user.toml."""
        argv = self.behaviour(**cfg) + list(extra_argv)
        text = f"[agent]\ncommand = {json.dumps(argv)}\n"
        if timeout_s is not None:
            text += f"timeout_s = {timeout_s}\n"
        self.config(text + search, "config.user.toml")
        return argv

    def calls(self) -> list[dict]:
        return json.loads(self.calls_log.read_text(encoding="utf-8")) \
            if self.calls_log.exists() else []
