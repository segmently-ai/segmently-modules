"""Helpers of the P8.1 agent tests: a configurable fake agent command (`tests/fake_agent.py`),
the user config that names it, and a PATH whose `claude` / `codex` are sentinels that fail the
test when executed — no real agent CLI is ever reachable from these tests."""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

from tests import SENTINEL_LOG
from tests.helpers import NO_AUTO_MAINTENANCE, SPLIT_FIXTURE, copy_fixture, git

FAKE = Path(__file__).with_name("fake_agent.py")
CLEAN_KEEP = ("PATH", "TMPDIR", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM",
              "GIT_CEILING_DIRECTORIES", *NO_AUTO_MAINTENANCE)


def picks(*items):
    """A valid answer: items are (module, confidence[, reason])."""
    return {"picks": [{"module": m, "confidence": c, **({"reason": r[0]} if r else {})}
                      for m, c, *r in items], "none": False}


class AgentRepo:
    """Mixin for unittest.TestCase: a copy of the split fixture that is a git work tree (the
    personal config stays untracked), the sentinel claude/codex first on PATH (tests/__init__),
    and a CLEAN environment — no developer variable, no credential — for the code under test
    and the fake agent it starts."""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.root = copy_fixture(self.tmp, SPLIT_FIXTURE)
        self.R = ("--root", str(self.root))
        clean = {k: v for k, v in os.environ.items() if k in CLEAN_KEEP}
        clean["HOME"] = str(self.tmp)
        patcher = mock.patch.dict(os.environ, clean, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        git(self.root, "init", "-q")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "fixture")
        self.sentinel_log = SENTINEL_LOG
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
        """Configure the fake agent: `MODSYS_AGENT_COMMAND` (and `MODSYS_AGENT_TIMEOUT`) in the
        environment, which the AgentRepo setUp restores; `search` goes to config.user.toml."""
        argv = self.behaviour(**cfg) + list(extra_argv)
        os.environ["MODSYS_AGENT_COMMAND"] = json.dumps(argv)
        if timeout_s is not None:
            os.environ["MODSYS_AGENT_TIMEOUT"] = str(timeout_s)
        if search:
            self.config(search, "config.user.toml")
        return argv

    def no_agent(self) -> None:
        os.environ.pop("MODSYS_AGENT_COMMAND", None)
        os.environ.pop("MODSYS_AGENT_TIMEOUT", None)

    def calls(self) -> list[dict]:
        return json.loads(self.calls_log.read_text(encoding="utf-8")) \
            if self.calls_log.exists() else []
