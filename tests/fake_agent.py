"""A stand-in for a user's agent command in the P8.1 tests (never a model): it reads the work
order on stdin and answers deterministically. argv[1] is a JSON file of its behaviour:
`answer` (the text it prints), `exit` (its exit code), `sleep` (seconds to block after it has
written `started`), `stderr` (text), `log` (a JSON file it writes: its argv, its stdin, the
files `MODSYS_WORK_ORDER` / `MODSYS_SCHEMA` name and their content, its environment),
`started` (a marker file), `grandchild` (a file to write the pid of a `sleep` child into),
`nested` (an argv to run as a child and record: rc, stdout, stderr), `flood` (bytes to print), `helper` (seconds a session-leading helper holds stdout)."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    cfg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    stdin = sys.stdin.read()
    record = {"argv": sys.argv[2:], "stdin": stdin, "env": dict(os.environ), "cwd": os.getcwd()}
    for key, name in (("MODSYS_WORK_ORDER", "work_order_file"), ("MODSYS_SCHEMA", "schema_file")):
        path = os.environ.get(key)
        record[name] = {"path": path, "exists": bool(path) and Path(path).is_file(),
                        "content": Path(path).read_text(encoding="utf-8")
                        if path and Path(path).is_file() else None}
    if cfg.get("nested"):
        done = subprocess.run(cfg["nested"], capture_output=True, text=True, cwd=cfg.get("cwd"),
                              env={**os.environ, **cfg.get("nested_env", {})})
        record["nested"] = {"rc": done.returncode, "out": done.stdout, "err": done.stderr}
    if cfg.get("flood"):
        sys.stdout.write("x" * cfg["flood"])
        sys.stdout.flush()
    if cfg.get("log"):
        calls = []
        if Path(cfg["log"]).exists():
            calls = json.loads(Path(cfg["log"]).read_text(encoding="utf-8"))
        Path(cfg["log"]).write_text(json.dumps(calls + [record]), encoding="utf-8")
    if cfg.get("grandchild"):
        child = subprocess.Popen(["sleep", "60"])
        Path(cfg["grandchild"]).write_text(str(child.pid), encoding="utf-8")
    if cfg.get("helper"):  # a helper in its own session that keeps stdout (and stderr) open
        subprocess.Popen([sys.executable, "-c", f"import time; time.sleep({cfg['helper']})"],
                         start_new_session=True, stdin=subprocess.DEVNULL)
    if cfg.get("started"):
        Path(cfg["started"]).write_text(str(os.getpid()), encoding="utf-8")
    if cfg.get("sleep"):
        time.sleep(cfg["sleep"])
    if cfg.get("stderr"):
        sys.stderr.write(cfg["stderr"])
    if "answer" in cfg:
        sys.stdout.write(cfg["answer"])
    return cfg.get("exit", 0)


if __name__ == "__main__":
    sys.exit(main())
