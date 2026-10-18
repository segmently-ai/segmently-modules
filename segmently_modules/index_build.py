"""The rules index, written by an agent the engine starts (`[rules] index = "discover"`, 2026-10-18).

Four trial runs on the benchmark stand showed that the agent running module-discover never writes
a doc the user did not ask for, whatever the setting and the skill say. So the command line does
it: `discover --files` (module-discover's step 7, which knows the modules a change modifies)
starts `rules --build` in the background for their docs without an index, and returns at once.
That run reads the docs in full; the next one finds the index.

Who may write, and with what:
- `SEGMENTLY_MODULES_ALLOW_INDEX_WRITER=1`, read ONLY from the environment (a personal setting: a
  shell profile, `~/.claude/settings.json`'s `env`). A committed config file never starts an
  agent: `[rules] index = "discover"` alone only names the docs.
- the writer command: `SEGMENTLY_MODULES_INDEX_COMMAND` (a JSON array of strings, environment
  only), else, inside Claude Code (`CLAUDECODE=1`), `claude -p` allowed to edit that one doc and
  to read. Codex exposes no such marker, and a sandboxed session cannot hand a child write
  access: there the user sets the command (`codex exec … --sandbox workspace-write -`).

Each doc gets one writer, several at once (`[init] max_parallel`). The prompt is module-sync's
rules-index procedure for that doc alone, on stdin and in `SEGMENTLY_MODULES_WORK_ORDER`. The
engine trusts no reply: after the writer exits it reads the doc again. The doc must carry an
`Indexed:` line, and every change must lie inside its critical-rules section; otherwise the doc
goes back to what it was. A backup file the writer left next to the doc (`<doc>-e` from BSD
`sed -i -e`, `.bak`, `.orig`, `~`) is removed. A change to any other file under the modules
directory is reported, never undone (it may be the user's). State lives outside the repository,
in the temp directory: a lock while a build runs, the last result after it."""
from __future__ import annotations

import concurrent.futures
import datetime
import difflib
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from segmently_modules.agent import nested
from segmently_modules.critical_rules import critical_section, section_span
from segmently_modules.output import UsageError

ENV_ALLOW = "SEGMENTLY_MODULES_ALLOW_INDEX_WRITER"
ENV_COMMAND = "SEGMENTLY_MODULES_INDEX_COMMAND"
ENV_TIMEOUT = "SEGMENTLY_MODULES_INDEX_TIMEOUT"
DEFAULT_TIMEOUT_S = 900
MAX_TIMEOUT_S = 3600
PLACEHOLDERS = ("claude_model", "codex_model", "doc", "doc_rule", "root")
# inside Claude Code: read anything, edit the one doc, run the read verbs the procedure names
CLAUDE_WRITER = ["claude", "-p", "--model", "{claude_model}", "--output-format", "json",
                 "--permission-mode", "dontAsk", "--allowedTools", "Read", "Grep", "Glob",
                 "Edit({doc_rule})", "Bash(segmently-modules rules:*)", "Bash(segmently-modules lint:*)"]
BACKUPS = ("-e", ".bak", ".orig", "~")
_TOKEN = re.compile(r"\{(\w+)\}")
RUN_ENGINE = ("import runpy, sys; sys.path[:1] == [''] and sys.path.pop(0); "
              "runpy.run_module('segmently_modules', run_name='__main__', alter_sys=True)")
NOT_ALLOWED = (f"set {ENV_ALLOW}=1 in your own environment (a shell profile, or the `env` of "
               f"~/.claude/settings.json) to let a writer index them; until then module-sync "
               f"indexes them after the change")
NO_WRITER = (f"no writer: outside Claude Code set {ENV_COMMAND} (a JSON array, e.g. [\"codex\", "
             f"\"exec\", \"-m\", \"{{codex_model}}\", \"--sandbox\", \"workspace-write\", \"-\"])")


def allowed() -> bool:
    """`SEGMENTLY_MODULES_ALLOW_INDEX_WRITER`: `1` = yes; unset, empty or `0` = no; anything else
    is refused."""
    raw = os.environ.get(ENV_ALLOW, "")
    if raw in ("", "0"):
        return False
    if raw == "1":
        return True
    raise UsageError(f"{ENV_ALLOW}: expected 1 or 0, got {raw[:40]!r}")


def timeout_s() -> int:
    raw = os.environ.get(ENV_TIMEOUT, "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_S
    if not (len(raw) <= 4 and raw.isascii() and raw.isdigit() and 1 <= int(raw) <= MAX_TIMEOUT_S):
        raise UsageError(f"{ENV_TIMEOUT}: expected an integer from 1 to {MAX_TIMEOUT_S}, got {raw[:40]!r}")
    return int(raw)


def writer_command() -> list[str] | None:
    """The writer's argv template: `SEGMENTLY_MODULES_INDEX_COMMAND`, else `claude -p` inside
    Claude Code, else None."""
    raw = os.environ.get(ENV_COMMAND, "")
    if raw.strip():
        try:
            command = json.loads(raw)
        except ValueError:
            raise UsageError(f"{ENV_COMMAND}: expected a JSON array of strings, got {raw[:80]!r}") from None
        if not (isinstance(command, list) and command and all(isinstance(i, str) for i in command)):
            raise UsageError(f"{ENV_COMMAND}: expected a non-empty JSON array of strings, got {raw[:80]!r}")
        for n, item in enumerate(command):
            names = _TOKEN.findall(item.replace("{{", "").replace("}}", ""))
            if any(t not in PLACEHOLDERS for t in names) or "{" in _TOKEN.sub("", item.replace("{{", "").replace("}}", "")) \
                    or "}" in _TOKEN.sub("", item.replace("{{", "").replace("}}", "")):
                raise UsageError(f"{ENV_COMMAND}: item {item!r}: the placeholders are "
                                 f"{', '.join('{' + p + '}' for p in PLACEHOLDERS)} ({{{{ and }}}} for a brace)")
            if n == 0 and names:
                raise UsageError(f"{ENV_COMMAND}: argv[0] {item!r} must not contain a placeholder")
        return command
    if os.environ.get("CLAUDECODE") == "1":
        return list(CLAUDE_WRITER)
    return None


def state_dir(root: Path) -> Path:
    """Outside the repository and the same for every process of the user (a session's own TMPDIR
    would hide a running build from the next one): `$XDG_CACHE_HOME` or `~/.cache`, then
    `segmently-modules/index-<hash of the root>`; the temp directory when that cannot be made."""
    key = f"index-{hashlib.sha1(str(root.resolve()).encode('utf-8')).hexdigest()[:12]}"
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "segmently-modules"
    try:
        (base / key).mkdir(parents=True, exist_ok=True)
        return base / key
    except OSError:
        return Path(tempfile.gettempdir()) / "segmently-modules" / key


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def running(root: Path) -> dict | None:
    """The build in progress (`build.lock`: {pid, docs, started}), or None."""
    lock = state_dir(root) / "build.lock"
    try:
        held = json.loads(lock.read_text("utf-8"))
    except (OSError, ValueError):
        return None
    return held if isinstance(held, dict) and _alive(int(held.get("pid", 0))) else None


def pending(ws, targets: list[str]) -> list[dict]:
    """The docs without an index of `targets` and of each child's parent, each once:
    [{doc, target, role}] in the targets' order (a parent before its children)."""
    from segmently_modules.query import rules_of
    seen, out = set(), []
    for t in targets:
        for target in ([t.split("/", 1)[0], t] if "/" in t else [t]):
            for d in rules_of(ws, target):
                if d["exists"] and d["indexable"] and not d["indexed"] and d["doc"] not in seen:
                    seen.add(d["doc"])
                    out.append({"doc": d["doc"], "target": target, "role": d["role"]})
    return out


def procedure() -> str:
    """module-sync's rules-index procedure, from "Build or refresh" up to "Keep it current"."""
    from segmently_modules.config import builtin_packs_root
    text = (builtin_packs_root() / "core/skills/module-sync/references/rules-index.md").read_text("utf-8")
    start, end = text.find("**Build or refresh**"), text.find("**Keep it current**")
    return text[start:end if end > start else None].strip()


def prompt(ws, item: dict, today: str) -> str:
    heading = ws.config["lint"].get("critical_rules_heading", "Critical Rules")
    return (f"You index the critical rules of one module doc, in place, and nothing else.\n\n"
            f"Repository root: {ws.root}\nDoc: {item['doc']} (module `{item['target']}`, role "
            f"`{item['role']}`)\nToday: {today}\n\n"
            f"Follow this procedure for this one doc (\"the doc\" below; you are the only writer of it):\n\n"
            f"{procedure()}\n\n"
            f"Limits: change only the doc's critical-rules section (the heading starts with "
            f"`{heading}`; a new section goes at the end of the doc): its entries and its `Indexed:` "
            f"line, which you write last, with today's date. Never another part of the doc, never "
            f"another file, a registry field or code; never commit. Write with your file-edit tool "
            f"only, never through a shell. The engine checks the doc afterwards and undoes a change "
            f"outside the section. Reply with one line: the number of entries you added and the "
            f"contradictions you found.\n")


def confined(old: str, new: str, heading: str) -> bool:
    """Every hunk of old → new lies inside the critical-rules section (the old span for what is
    removed, the new span for what is added); blank lines are free."""
    a, b = old.split("\n"), new.split("\n")
    so, sn = section_span(old, heading), section_span(new, heading)
    inside = lambda sp, i, j: sp is not None and sp[0] - 1 <= i and j <= sp[1]
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        if i2 > i1 and not inside(so, i1, i2) and any(x.strip() for x in a[i1:i2]):
            return False
        if j2 > j1 and not inside(sn, j1, j2) and any(x.strip() for x in b[j1:j2]):
            return False
    return True


def _snapshot(modules_dir: Path) -> dict:
    out = {}
    for p in modules_dir.rglob("*"):
        if p.is_file():
            try:
                st = p.stat()
            except OSError:
                continue
            out[p] = (st.st_mtime_ns, st.st_size)
    return out


def _run_writer(argv: list[str], text: str, order: Path, cwd: Path, limit: int) -> tuple[int | None, str, str]:
    """Run one writer: the prompt on stdin, its own process group, killed at `limit` seconds.
    (exit code or None on a timeout, the last stderr characters, its stdout)."""
    env = {**os.environ, "SEGMENTLY_MODULES_WORK_ORDER": str(order)}  # its own segmently-modules starts no agent
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            cwd=cwd, env=env, start_new_session=True, text=True)
    try:
        out, err = proc.communicate(text, timeout=limit)
        return proc.returncode, (err or "")[-500:], out or ""
    except subprocess.TimeoutExpired:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(proc.pid, sig)
            except (ProcessLookupError, PermissionError):
                pass
            time.sleep(0.5)
        proc.communicate()
        return None, "timed out", ""
    except OSError as e:
        return 127, str(e), ""


def build_one(ws, item: dict, command: list[str], today: str, work: Path, limit: int) -> dict:
    from segmently_modules.config import search_settings
    heading = ws.config["lint"].get("critical_rules_heading", "Critical Rules")
    path = ws.root / item["doc"]
    before = path.read_text("utf-8")
    siblings = {p.name for p in path.parent.iterdir()}
    text = prompt(ws, item, today)
    order = work / (item["doc"].replace("/", "__") + ".json")
    order.write_text(json.dumps({**item, "root": str(ws.root), "heading": heading, "today": today,
                                 "prompt": text}, ensure_ascii=False), "utf-8")
    values = {**search_settings(ws.config), "doc": str(path), "root": str(ws.root),
              "doc_rule": "/" + str(path.resolve())}
    values = {k: str(v) for k, v in values.items()}
    started = time.monotonic()
    code, err, reply = _run_writer(_fill(command, values), text, order, ws.root, limit)
    out = {"doc": item["doc"], "target": item["target"], "seconds": round(time.monotonic() - started)}
    try:  # `claude -p --output-format json`: its cost and its last words, for the record
        envelope = json.loads(reply)
        if isinstance(envelope, dict):
            if isinstance(envelope.get("total_cost_usd"), (int, float)):
                out["cost_usd"] = round(envelope["total_cost_usd"], 4)
            if isinstance(envelope.get("result"), str):
                out["reply"] = envelope["result"].strip()[:300]
    except ValueError:
        if reply.strip():
            out["reply"] = reply.strip()[-300:]
    for p in path.parent.iterdir():  # a backup the writer left next to its doc
        if p.name not in siblings and p.is_file() and any(p.name == path.name + s for s in BACKUPS):
            p.unlink()
            out.setdefault("removed", []).append(str(p.relative_to(ws.root)))
    after = path.read_text("utf-8") if path.is_file() else None
    sec = critical_section(path, heading) if after is not None else {"indexed": None, "rules": []}
    if code != 0:
        status = "timeout" if code is None else \
            f"failed: the writer exited {code}" + (f" ({err.strip()[:200]})" if err.strip() else "")
    elif after is None:
        status = "failed: the doc is gone"
    elif not confined(before, after, heading):
        status = "refused: it changed the doc outside the critical-rules section"
    elif not sec["indexed"]:
        status = "failed: no Indexed: line"
    else:
        status = "built"
    if status != "built" and after != before:
        path.write_text(before, "utf-8")  # all or nothing: the doc as it was
        out["restored"] = True
    out["status"] = status
    if status == "built":
        out["rules"] = len(sec["rules"])
        out["added"] = len(sec["rules"]) - len(_rules_in(before, heading))
    return out


def _rules_in(text: str, heading: str) -> list:
    """The rules of a doc's text (critical_section reads files)."""
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(text)
    try:
        return critical_section(Path(f.name), heading)["rules"]
    finally:
        os.unlink(f.name)


def _fill(command: list[str], values: dict) -> list[str]:
    """The argv with this module's placeholders filled, one item at a time, never through a shell
    (`{{` / `}}` stay literal braces)."""
    out = []
    for item in command:
        s = item.replace("{{", "\0L").replace("}}", "\0R")
        for k in PLACEHOLDERS:
            s = s.replace("{" + k + "}", values.get(k, ""))
        out.append(s.replace("\0L", "{").replace("\0R", "}"))
    return out


def build(ws, items: list[dict]) -> dict:
    """Index `items` ([{doc, target, role}]) now, one writer per doc, `[init] max_parallel` at a
    time; the lock and the last result in `state_dir`. Refused (exit 2) without the permission or
    a writer, inside an agent run, or while another build runs."""
    if nested():
        raise UsageError("inside an agent run (SEGMENTLY_MODULES_WORK_ORDER is set): a writer starts no writer")
    if not allowed():
        raise UsageError(NOT_ALLOWED)
    command = writer_command()
    if command is None:
        raise UsageError(NO_WRITER)
    limit = timeout_s()
    state = state_dir(ws.root)
    state.mkdir(parents=True, exist_ok=True)
    lock = state / "build.lock"
    held = running(ws.root)
    if held and held.get("pid") != os.getpid():
        raise UsageError(f"a rules index build is running (pid {held['pid']}): {', '.join(held.get('docs', []))[:200]}")
    today = datetime.date.today().isoformat()
    lock.write_text(json.dumps({"pid": os.getpid(), "docs": [i["doc"] for i in items],
                                "started": datetime.datetime.now().isoformat(timespec="seconds")}), "utf-8")
    modules_dir = ws.root / ws.config["paths"]["modules_dir"]
    before = _snapshot(modules_dir)
    results = []
    try:
        work = Path(tempfile.mkdtemp(prefix="orders-", dir=state))
        parallel = max(1, int((ws.config.get("init") or {}).get("max_parallel", 4)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=parallel) as pool:
            futures = [pool.submit(build_one, ws, item, command, today, work, limit) for item in items]
            for f in futures:
                try:
                    results.append(f.result())
                except Exception as e:  # one doc's failure never stops the others
                    results.append({"doc": "?", "status": f"failed: {e}"})
        docs = {ws.root / i["doc"] for i in items}
        after = _snapshot(modules_dir)
        other = sorted(str(p.relative_to(ws.root)) for p in set(after) | set(before)
                       if p not in docs and before.get(p) != after.get(p)
                       and not any(str(p.relative_to(ws.root)) in r.get("removed", []) for r in results))
        summary = {k: sum(1 for r in results if r["status"].startswith(k)) for k in ("built", "failed", "refused", "timeout")}
        report = {"docs": results, "other_changes": other, "summary": summary,
                  "finished": datetime.datetime.now().isoformat(timespec="seconds")}
        (state / "last.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), "utf-8")
        return report
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def start_background(ws, items: list[dict]) -> dict:
    """`rules --build` for `items` in a detached process; returns at once. {status, docs, log}."""
    held = running(ws.root)
    if held:
        return {"status": "running", "docs": held.get("docs", []), "log": str(state_dir(ws.root) / "build.log")}
    state = state_dir(ws.root)
    state.mkdir(parents=True, exist_ok=True)
    log = state / "build.log"
    argv = [sys.executable, "-c", RUN_ENGINE, "rules", "--build", *[i["doc"] for i in items],
            "--root", str(ws.root), "--json"]
    with open(log, "w", encoding="utf-8") as out:
        subprocess.Popen(argv, cwd=ws.root, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                         start_new_session=True, env={**os.environ, "PYTHONPATH": os.pathsep.join(
                             p for p in [str(Path(__file__).resolve().parents[1]), os.environ.get("PYTHONPATH", "")] if p)})
    return {"status": "started", "docs": [i["doc"] for i in items], "log": str(log)}


def discover_hook(ws, targets: list[str], from_diff: bool) -> dict | None:
    """`discover --files`' `rules_build` under `[rules] index = "discover"`: the modify modules'
    docs without an index, and what the engine does about them. None when the setting is another."""
    from segmently_modules.config import rules_index_setting
    if rules_index_setting(ws.config) != "discover" or from_diff:
        return None
    items = pending(ws, targets)
    if not items:
        return {"status": "complete", "docs": []}
    docs = [i["doc"] for i in items]
    if os.environ.get("SEGMENTLY_MODULES_RUN_ID"):
        return {"status": "skipped", "docs": docs, "note": "inside a pipeline run: module-sync indexes them"}
    if nested():
        return {"status": "skipped", "docs": docs, "note": "inside an agent run"}
    try:
        if not allowed():
            return {"status": "not_allowed", "docs": docs, "note": NOT_ALLOWED}
        if writer_command() is None:
            return {"status": "no_writer", "docs": docs, "note": NO_WRITER}
    except UsageError as e:
        return {"status": "not_allowed", "docs": docs, "note": str(e)}
    return start_background(ws, items)
