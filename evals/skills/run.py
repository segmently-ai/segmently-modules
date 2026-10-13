#!/usr/bin/env python3
"""Skill evals (D7): run the cases under evals/skills/ with `claude plugin eval` against the
engine's built-in skills.

`claude plugin eval` loads a plugin, so this script first assembles one in a work directory:

  <out>/plugin/.claude-plugin/plugin.json   name "segmently-modules-skills", the engine version
  <out>/plugin/skills/<skill>/              every skill of the built-in packs core, ui, qa
  <out>/plugin/evals/<skill>/<case>/        the cases; each gets scaffold.sh = ./scaffold.sh
                                            (@RUNTIME@ filled in) + the case's own seed.sh
  <out>/runtime/{engine,fixture,bin}/       this engine's package, the bookshop fixture and a
                                            `segmently-modules` launcher for the agent's sandboxed shell

and runs `claude plugin eval <out>/plugin --scaffold <flags…>` with `<out>/runtime/bin` first on
PATH. Flags after the script's own are passed through; without any, the gate flags
(GATE_FLAGS) are used. With the caller's flags, the cost cap (`--max-cost-usd 20`) and
`--no-publish` are added unless the flags carry their own; `--trust-plugin` never is (a trust
grant is the caller's choice). Every run is a real, billed model call: `--dry-run` assembles and
prints the command without running it. The runtime lives outside your home directory (the sandbox
cannot read it), and so must the Python that runs this script. Stdlib only; never run by
unittest.

Usage: python3 evals/skills/run.py [--dry-run] [--out DIR] [claude plugin eval flags…]"""
import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parents[1]
PACKS = ENGINE / "segmently_modules" / "defaults" / "packs"
MAX_COST_USD = "20"  # the gate's cost ceiling, added to any flags that set none
GATE_FLAGS = ["--ablation", "none", "--runs", "2", "--threshold", "0.5", "--max-cost-usd",
              MAX_COST_USD, "--allow-tools", "Bash", "Write", "Edit", "--trust-plugin",
              "--no-publish"]
LAUNCHER = """#!/bin/sh
export PYTHONPATH="{engine}" PYTHONDONTWRITEBYTECODE=1
exec "{python}" -m segmently_modules "$@"
"""


def engine_version() -> str:
    for line in (ENGINE / "segmently_modules" / "__init__.py").read_text(encoding="utf-8").splitlines():
        if line.startswith("__version__"):
            return line.split("=", 1)[1].strip().strip('"')
    return "0"


def builtin_skills() -> dict[str, Path]:
    """{skill id: directory} of every skill the built-in packs declare."""
    out = {}
    for toml in sorted(PACKS.glob("*/pack.toml")):
        data = tomllib.loads(toml.read_text(encoding="utf-8"))
        for sid, spec in (data.get("skills") or {}).items():
            out[sid] = toml.parent / spec["path"]
    return out


def cases() -> list[Path]:
    """The case directories (every directory with a prompt.md), relative to HERE."""
    return sorted(p.parent.relative_to(HERE) for p in HERE.rglob("prompt.md"))


def assemble(out: Path) -> Path:
    """Build the plugin and the runtime under `out`; returns the plugin directory."""
    plugin, runtime = out / "plugin", out / "runtime"
    manifest = {"name": "segmently-modules-skills", "version": engine_version(),
                "description": "The segmently-modules built-in skills (packs core, ui, qa), assembled for "
                               "claude plugin eval"}
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps(manifest, indent=2) + "\n",
                                                           encoding="utf-8")
    for sid, source in builtin_skills().items():
        shutil.copytree(source, plugin / "skills" / sid)
    base = (HERE / "scaffold.sh").read_text(encoding="utf-8").replace("@RUNTIME@", str(runtime))
    for case in cases():
        target = plugin / "evals" / case
        shutil.copytree(HERE / case, target, ignore=shutil.ignore_patterns("seed.sh"))
        seed = HERE / case / "seed.sh"
        extra = seed.read_text(encoding="utf-8") if seed.is_file() else ""
        (target / "scaffold.sh").write_text(base + extra, encoding="utf-8")
        (target / "scaffold.sh").chmod(0o755)
    shutil.copytree(ENGINE / "segmently_modules", runtime / "engine" / "segmently_modules",
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ENGINE / "tests" / "fixtures" / "bookshop", runtime / "fixture")
    launcher = runtime / "bin" / "segmently-modules"
    launcher.parent.mkdir(parents=True)
    launcher.write_text(LAUNCHER.format(engine=runtime / "engine", python=sys.executable),
                        encoding="utf-8")
    launcher.chmod(0o755)
    return plugin


def command(plugin: Path, flags: list[str], out: Path) -> list[str]:
    """The `claude plugin eval` argv: the gate flags, or the caller's flags plus the defaults
    they lack — `--max-cost-usd 20` and `--no-publish` — and `--json <out>/result.json`."""
    flags = list(flags) or list(GATE_FLAGS)
    if not any(f == "--max-cost-usd" or f.startswith("--max-cost-usd=") for f in flags):
        flags += ["--max-cost-usd", MAX_COST_USD]
    if "--no-publish" not in flags:
        flags.append("--no-publish")
    if "--json" not in flags:
        flags += ["--json", str(out / "result.json")]
    return ["claude", "plugin", "eval", str(plugin), "--scaffold", *flags]


def summary(result: Path) -> list[str]:
    """One line per case — score, cost, how many runs fired the skill (the `skill-fired`
    grader), the first run error — and the aggregate, from the `--json` result file."""
    data = json.loads(result.read_text(encoding="utf-8"))
    lines = []
    for case in data.get("cases", []):
        runs = [r for arm in (case.get("arms") or {}).values() for r in arm]
        cost = sum((r.get("costUsd") or 0) + (r.get("judgeCostUsd") or 0) for r in runs)
        fired = [g.get("passed") for r in runs for g in r.get("graders") or []
                 if g.get("name") == "skill-fired"]
        errors = [r["error"] for r in runs if r.get("error")]
        lines.append(f"{case.get('name')}: score {(case.get('aggregates') or {}).get('score')}, "
                     f"cost ${cost:.2f}"
                     + (f", skill fired {sum(map(bool, fired))}/{len(fired)}" if fired else "")
                     + (f", error: {errors[0]}" if errors else ""))
    total = data.get("aggregates") or {}
    lines.append(f"overall {total.get('overallScore')}, cases passed {total.get('casesPassed')}"
                 f"/{total.get('casesTotal')}, cost ${data.get('costUsd')}"
                 + (f", partial: {data.get('partialReason')}" if data.get("partial") else ""))
    return lines


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dry-run", action="store_true",
                   help="assemble the plugin and print the command; run nothing")
    p.add_argument("--out", type=Path, help="work directory (new or empty; kept)")
    args, flags = p.parse_known_args(argv)
    flags = flags[1:] if flags[:1] == ["--"] else flags
    out = args.out or Path(tempfile.mkdtemp(prefix="segmently-modules-skill-evals-"))
    if out.exists() and any(out.iterdir()):
        print(f"run.py: {out} is not empty", file=sys.stderr)
        return 2
    out = out.resolve()
    plugin = assemble(out)
    cmd = command(plugin, flags, out)
    print(f"plugin: {plugin}")
    print(f"command: {shlex.join(cmd)}")
    if args.dry_run:
        return 0
    env = dict(os.environ, PATH=f"{out / 'runtime' / 'bin'}{os.pathsep}{os.environ['PATH']}")
    code = subprocess.run(cmd, env=env).returncode
    after = cmd[cmd.index("--json") + 1:][:1]
    result = Path(after[0]) if after and not after[0].startswith("-") else None
    if result and result.is_file():
        print("\n".join(summary(result)))
    print(f"claude plugin eval exit {code}; work directory {out}")
    return code


if __name__ == "__main__":
    sys.exit(main())
