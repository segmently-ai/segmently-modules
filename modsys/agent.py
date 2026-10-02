"""The user's own agent command (P8.1 S3, layer 3): `[agent] command` runs a program the USER
chose — never a model of the engine's — with the work order on stdin and reads its answer from
stdout. The command comes only from the `MODSYS_AGENT_COMMAND` environment variable (a JSON
array) or from a `.modsys/config.user.toml` that git does not track (outside a git work tree
only the variable counts); a committed config, a tracked personal config or a pack that sets
`[agent]` is refused, so a commit cannot make the engine run an agent command. The engine holds no model, no key
and no network code: whatever the command does, it does with the user's own credentials."""
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
from pathlib import Path

from modsys.output import UsageError

ENV_COMMAND = "MODSYS_AGENT_COMMAND"
DEFAULT_TIMEOUT_S = 300
MAX_TIMEOUT_S = 3600
REASONING = {"quick": "low", "standard": "medium", "deep": "high"}
PLACEHOLDERS = ("claude_model", "codex_model", "effort", "reasoning")
STDERR_CHARS = 500
MAX_STDOUT = 4 * 1024 * 1024  # an agent that prints more is stopped and refused
KEEP_STDERR = 64 * 1024
NESTED = ("already inside an agent run (MODSYS_WORK_ORDER is set): a nested agent call is "
          "refused; use lexical matching or modsys choose --task")
NESTED_NOTE = "semantic part skipped: nested agent call"
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


def nested() -> bool:
    """This process runs inside an agent run (the engine sets MODSYS_WORK_ORDER for its child):
    an agent that runs modsys must not start the agent again."""
    return bool(os.environ.get("MODSYS_WORK_ORDER"))


def require_untracked(path: Path, root) -> None:
    """The personal config `path` may set `[agent]` only when git does NOT track it (a tracked
    file is a committed one: anyone who clones would run its command) and it lies in a git work
    tree (outside one the engine cannot tell). A tracked symlink counts as tracked."""
    from modsys.changes import git_env
    from modsys.config import shown
    here = shown(path, root)
    run_git = lambda *a: subprocess.run(["git", "-C", str(path.parent), *a], env=git_env(),  # noqa: E731
                                        capture_output=True, text=True)
    try:
        inside = run_git("rev-parse", "--is-inside-work-tree")
        tracked = run_git("ls-files", "--error-unmatch", "--", path.name)
    except OSError:  # git is not installed
        inside = None
    if inside is None or inside.returncode != 0 or inside.stdout.strip() != "true":
        raise UsageError(f"{here}: [agent] is read only from MODSYS_AGENT_COMMAND outside a git "
                         f"work tree (the engine cannot tell whether this file is committed)")
    if tracked.returncode == 0:
        raise UsageError(f"{here} is tracked by git — [agent] is read only from an untracked "
                         f"personal config or {ENV_COMMAND}")


def settings(config: dict) -> dict | None:
    """`{command, timeout_s, source}` of the agent command in force, or None when there is
    none: the environment variable beats `config.user.toml`; an empty variable is unset; an
    invalid one is refused (never a silent fallback to the user config)."""
    if nested():
        return None
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


def _drain(stream, keep: int, limit: int | None, box: dict, key: str, proc) -> None:
    """Read `stream` to its end on a thread: keep the first `keep` bytes; past `limit` bytes
    stop the agent (its group) and flag it."""
    total = 0
    try:
        for chunk in iter(lambda: stream.read(65536), b""):
            total += len(chunk)
            if len(box[key]) < keep:
                box[key] += chunk[:keep - len(box[key])]
            if limit is not None and total > limit:
                box["over"] = True
                _kill_group(proc)
                return
    except (OSError, ValueError):
        pass


def _write_files(tmp: Path, work_order: dict, schema: dict) -> tuple[Path, Path, str]:
    order_text = json.dumps(work_order, indent=2, ensure_ascii=False)
    order_file, schema_file = tmp / "work-order.json", tmp / "answer-schema.json"
    for path, text in ((order_file, order_text), (schema_file, json.dumps(schema, indent=2))):
        try:
            path.write_text(text, encoding="utf-8")
        except OSError as e:
            raise UsageError(f"cannot write {path}: {e.strerror or e}") from None
    return order_file, schema_file, order_text


def run(config: dict, work_order: dict, schema: dict, check=lambda answer: answer, cwd=None):
    """Run the agent command on `work_order` (the dict of `modsys choose --json`) and return
    `check(answer)`, the answer object it printed validated by the caller (a usage error of
    `check` is reported naming the agent). The work order goes to the child's stdin and, with the
    answer schema, to two files in a private temp directory (`MODSYS_WORK_ORDER`,
    `MODSYS_SCHEMA`) removed afterwards, whatever happens. The child runs in `cwd`, in its own
    process group; Ctrl-C, SIGTERM and SIGHUP stop it and its group; its output is capped."""
    from modsys.config import search_settings
    cfg = settings(config)
    search = search_settings(config)
    values = {**search, "reasoning": REASONING[search["effort"]]}
    argv = substitute(cfg["command"], values)
    name, timeout_s = argv[0], cfg["timeout_s"]
    try:
        tmp = Path(tempfile.mkdtemp(prefix="modsys-agent-"))
    except OSError as e:
        raise UsageError(f"cannot write a temp directory: {e.strerror or e}") from None
    before = _set_signals()
    proc = None
    try:
        order_file, schema_file, _ = _write_files(tmp, work_order, schema)
        env = {**os.environ, "MODSYS_WORK_ORDER": str(order_file),
               "MODSYS_SCHEMA": str(schema_file)}
        box = {"out": b"", "err": b"", "over": False}
        with open(order_file, "rb") as stdin:
            try:
                proc = subprocess.Popen(argv, stdin=stdin, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, env=env, cwd=cwd,
                                        start_new_session=True)
            except OSError as e:
                raise UsageError(f"agent {name}: cannot run it ({e.strerror or e}) — "
                                 f"check [agent] command in {cfg['source']}") from None
        readers = [threading.Thread(target=_drain, daemon=True,
                                    args=(proc.stdout, MAX_STDOUT, MAX_STDOUT, box, "out", proc)),
                   threading.Thread(target=_drain, daemon=True,
                                    args=(proc.stderr, KEEP_STDERR, None, box, "err", proc))]
        for t in readers:
            t.start()
        try:
            proc.wait(timeout=timeout_s * TIMEOUT_UNIT)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
            raise UsageError(f"agent timed out after {timeout_s} s ({name})") from None
        finally:
            _kill_group(proc)  # never a child (or a background grandchild) left behind
            for t in readers:
                t.join(KILL_GRACE_S)
        if box["over"]:
            raise UsageError(f"agent {name} printed more than {MAX_STDOUT} bytes")
        stdout = box["out"].decode("utf-8", "replace")
        stderr = box["err"].decode("utf-8", "replace")
        if proc.returncode != 0:
            tail = f": {stderr.strip()[:STDERR_CHARS]}" if stderr.strip() else ""
            raise UsageError(f"agent {name} exited {proc.returncode}{tail}")
        answer = parse_output(stdout, name)
        try:
            return check(answer)
        except UsageError as e:
            raise UsageError(f"agent {name}: {e}") from None
    finally:
        if proc is not None:
            _kill_group(proc)
            _close(proc)
        _restore_signals(before)
        shutil.rmtree(tmp, ignore_errors=True)


def _as_interrupt(signum, frame) -> None:
    raise KeyboardInterrupt  # SIGTERM, SIGHUP: the same road as Ctrl-C (exit 130)


def _set_signals() -> dict:
    before = {}
    for sig in (signal.SIGTERM, getattr(signal, "SIGHUP", None)):
        if sig is None:
            continue
        try:
            if signal.getsignal(sig) is signal.SIG_IGN:  # `nohup` keeps a signal ignored
                continue
            before[sig] = signal.signal(sig, _as_interrupt)
        except ValueError:  # not the main thread
            pass
    return before


def _restore_signals(before: dict) -> None:
    for sig, handler in before.items():
        try:
            signal.signal(sig, handler)
        except ValueError:
            pass
