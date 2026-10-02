"""The user's own agent command (P8.1 S3, layer 3): `[agent] command` runs a program the USER
chose — never a model of the engine's — with the work order on stdin and reads its answer from
stdout. The command comes only from `.modsys/config.user.toml` or the `MODSYS_AGENT_COMMAND`
environment variable (a JSON array); a committed config or a pack that sets `[agent]` is
refused, so a commit cannot make the engine run anything. The engine holds no model, no key
and no network code: whatever the command does, it does with the user's own credentials."""
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path

from modsys.output import UsageError

ENV_COMMAND = "MODSYS_AGENT_COMMAND"
DEFAULT_TIMEOUT_S = 300
MAX_TIMEOUT_S = 3600
REASONING = {"quick": "low", "standard": "medium", "deep": "high"}
PLACEHOLDERS = ("claude_model", "codex_model", "effort", "reasoning")
STDERR_CHARS = 500
TIMEOUT_UNIT = 1.0  # seconds per `timeout_s` unit — the seam the timeout tests shrink
KILL_GRACE_S = 2.0
_TOKEN = re.compile(r"\{\{|\}\}|\{(\w+)\}|[{}]")


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _scan(item: str, source: str):
    """Yield `("text", str)` and `("name", placeholder)` parts of one argv item (`{{` / `}}` are
    literal braces); any other brace use is a usage error naming the item."""
    pos = 0
    for m in _TOKEN.finditer(item):
        if m.start() > pos:
            yield "text", item[pos:m.start()]
        pos = m.end()
        token = m.group(0)
        if token in ("{{", "}}"):
            yield "text", token[0]
        elif m.group(1):
            if m.group(1) not in PLACEHOLDERS:
                raise UsageError(f"{source}: [agent] command: item {item!r}: unknown placeholder "
                                 f"{{{m.group(1)}}} (placeholders: "
                                 f"{', '.join('{' + p + '}' for p in PLACEHOLDERS)})")
            yield "name", m.group(1)
        else:
            raise UsageError(f"{source}: [agent] command: item {item!r}: unmatched brace "
                             f"{token!r} (write {token * 2} for a literal one)")
    if pos < len(item):
        yield "text", item[pos:]


def validate_command(command, source: str) -> list[str]:
    """The argv of an `[agent] command` value: a non-empty list of strings whose braces are
    placeholders or escapes, argv[0] without a placeholder."""
    if not (isinstance(command, list) and command and all(isinstance(i, str) for i in command)):
        raise UsageError(f"{source}: [agent] command: expected a non-empty list of strings, "
                         f"got {command!r}")
    for n, item in enumerate(command):
        parts = list(_scan(item, source))
        if n == 0 and any(kind == "name" for kind, _ in parts):
            raise UsageError(f"{source}: [agent] command: argv[0] {item!r} must not contain a "
                             f"placeholder")
    return command


def substitute(command: list[str], values: dict) -> list[str]:
    """Each item with its placeholders replaced, one item at a time and never through a shell;
    a substituted value is not scanned again."""
    out = []
    for item in command:
        out.append("".join(values[v] if kind == "name" else v for kind, v in _scan(item, "")))
    return out


def validate_agent_table(table, source, user: bool) -> None:
    """The `[agent]` table of one config layer. Refused outside the user config."""
    if not isinstance(table, dict):
        raise UsageError(f"{source}: [agent] must be a table, got {table!r}")
    if not user:
        key = next((k for k in ("command", "timeout_s") if k in table), "command")
        raise UsageError(f"{source}: [agent] {key}: not allowed here — the agent command is "
                         f"yours alone: set it in .modsys/config.user.toml or in "
                         f"{ENV_COMMAND} (a repository's config cannot run a command)")
    if "command" in table:
        validate_command(table["command"], source)
    if "timeout_s" in table:
        t = table["timeout_s"]
        if not (_is_int(t) and 1 <= t <= MAX_TIMEOUT_S):
            raise UsageError(f"{source}: [agent] timeout_s: expected an integer from 1 to "
                             f"{MAX_TIMEOUT_S}, got {t!r}")


def settings(config: dict) -> dict | None:
    """`{command, timeout_s, source}` of the agent command in force, or None when there is
    none: the environment variable beats `config.user.toml`; an empty variable is unset; an
    invalid one is refused (never a silent fallback to the user config)."""
    table = config.get("agent") or {}
    timeout_s = table.get("timeout_s", DEFAULT_TIMEOUT_S)
    raw = os.environ.get(ENV_COMMAND, "")
    if raw.strip():
        try:
            command = json.loads(raw)
        except ValueError:
            raise UsageError(f"{ENV_COMMAND}: expected a JSON array of strings, got "
                             f"{raw[:80]!r}") from None
        if not (isinstance(command, list) and command and
                all(isinstance(i, str) for i in command)):
            raise UsageError(f"{ENV_COMMAND}: expected a non-empty JSON array of strings, "
                             f"got {raw[:80]!r}")
        return {"command": validate_command(command, ENV_COMMAND), "timeout_s": timeout_s,
                "source": ENV_COMMAND}
    if "command" in table:
        return {"command": table["command"], "timeout_s": timeout_s,
                "source": ".modsys/config.user.toml"}
    return None


# ---- the answer of the agent (SI-P81-12) -------------------------------------------------

_FENCE = re.compile(r"\A```(?:json)?[ \t]*\n(.*?)\n?```\Z", re.S)


def _json(text: str, name: str, what: str):
    try:
        return json.loads(text)
    except ValueError:
        raise UsageError(f"agent {name}: {what} is not JSON: {text[:120]!r}") from None


def parse_output(stdout: str, name: str):
    """The answer object inside an agent's stdout: the answer itself, or a `claude -p
    --output-format json` envelope's `structured_output` / `result`. The first matching step
    decides; no free-text scraping."""
    text = stdout.strip()
    if not text:
        raise UsageError(f"agent {name} printed nothing")
    doc = _json(text, name, "its output")
    if not isinstance(doc, dict):
        raise UsageError(f"agent {name}: its output is not a JSON object")
    if "picks" in doc or "none" in doc:
        return doc
    if doc.get("is_error") is True:
        detail = doc.get("result") if isinstance(doc.get("result"), str) else ""
        raise UsageError(f"agent {name} reported an error" + (f": {detail[:200]}" if detail
                                                              else ""))
    if isinstance(doc.get("structured_output"), dict):
        return doc["structured_output"]
    result = doc.get("result")
    if isinstance(result, str):
        body = result.strip()
        m = _FENCE.match(body)
        inner = _json(m.group(1) if m else body, name, "its `result`")
        if not isinstance(inner, dict):
            raise UsageError(f"agent {name}: its `result` is not a JSON object")
        return inner
    if isinstance(result, dict):
        return result
    raise UsageError(f"agent {name}: no answer in its output (expected `picks`/`none`, "
                     f"`structured_output` or `result`)")


# ---- running it ---------------------------------------------------------------------------

def _kill_group(proc: subprocess.Popen) -> None:
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass
        if sig == signal.SIGTERM:
            try:
                proc.wait(timeout=KILL_GRACE_S)
            except subprocess.TimeoutExpired:
                pass
    try:
        proc.wait(timeout=KILL_GRACE_S)
    except subprocess.TimeoutExpired:
        pass


def _close(proc: subprocess.Popen) -> None:
    for f in (proc.stdin, proc.stdout, proc.stderr):
        try:
            f and f.close()
        except OSError:
            pass


def run(config: dict, work_order: dict, schema: dict, check=lambda answer: answer):
    """Run the agent command on `work_order` (the dict of `modsys choose --json`) and return
    `check(answer)`, the answer object it printed validated by the caller (a usage error of
    `check` is reported naming the agent). The work order goes to the child's stdin and, with the
    answer schema, to two files in a private temp directory (`MODSYS_WORK_ORDER`,
    `MODSYS_SCHEMA`) removed afterwards, whatever happens."""
    from modsys.config import search_settings
    cfg = settings(config)
    search = search_settings(config)
    values = {**search, "reasoning": REASONING[search["effort"]]}
    argv = substitute(cfg["command"], values)
    name, timeout_s = argv[0], cfg["timeout_s"]
    order_text = json.dumps(work_order, indent=2, ensure_ascii=False)
    tmp = Path(tempfile.mkdtemp(prefix="modsys-agent-"))
    try:
        order_file, schema_file = tmp / "work-order.json", tmp / "answer-schema.json"
        order_file.write_text(order_text, encoding="utf-8")
        schema_file.write_text(json.dumps(schema, indent=2), encoding="utf-8")
        env = {**os.environ, "MODSYS_WORK_ORDER": str(order_file),
               "MODSYS_SCHEMA": str(schema_file)}
        try:
            proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, env=env, text=True,
                                    encoding="utf-8", errors="replace",
                                    start_new_session=True)
        except OSError as e:
            raise UsageError(f"agent {name}: cannot run it ({e.strerror or e}) — "
                             f"check [agent] command in {cfg['source']}") from None
        try:
            stdout, stderr = proc.communicate(order_text, timeout=timeout_s * TIMEOUT_UNIT)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
            raise UsageError(f"agent timed out after {timeout_s} s ({name})") from None
        except BaseException:  # Ctrl-C and anything else: no child left behind
            _kill_group(proc)
            raise
        finally:
            if proc.poll() is None:
                _kill_group(proc)
            _close(proc)
        if proc.returncode != 0:
            tail = f": {stderr.strip()[:STDERR_CHARS]}" if stderr.strip() else ""
            raise UsageError(f"agent {name} exited {proc.returncode}{tail}")
        answer = parse_output(stdout, name)
        try:
            return check(answer)
        except UsageError as e:
            raise UsageError(f"agent {name}: {e}") from None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
