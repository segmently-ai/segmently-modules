"""The repositories of the `module-adopt` skill evals (evals.json, ids 1–3): a synthetic
bookshop warehouse whose registry another tool wrote, built deterministically (one commit, a
fixed identity and date). Stdlib only; run as `python3 evals/skills/module-adopt/cases.py
<case id> <new directory>`.

  1  modules/registry.json with an extra field `owner_team` on every module and a role
     `curator` that no config declares; no .segmently-modules/
  2  the registry at docs/modules/registry.json (a generated index) with each module's entry in
     docs/modules/<name>/module.json — the per-module layout; no .segmently-modules/
  3  modules/registry.json with an undeclared field `stock_paths`, and a team config that
     already exists (.segmently-modules/config.toml with a [ci] section)"""
import json
import os
import subprocess
import sys
from pathlib import Path

MODULES = {"inventory": "Books on the shelves and in the back room, counted per title.",
           "orders": "Orders a reader places, from the basket to the paid order.",
           "shipping": "Parcels on their way: labels, carriers and delivery dates."}


def entry(name: str, doc_dir: str, **extra) -> dict:
    roles = {"developer": f"{doc_dir}/{name}/roles/developer.md"}
    return {"name": name, "description": MODULES[name], "status": "active",
            "keywords": [name, f"{name}-list", f"{name}-change", f"{name}-rule",
                         f"{name}-check"],
            "context_files": {"universal": f"{doc_dir}/{name}/MODULE.md", "roles": roles},
            **extra}


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def docs(root: Path, entries: dict) -> None:
    for name, e in entries.items():
        write(root, e["context_files"]["universal"], f"# {name.title()}\n\n> {e['description']}\n")
        for role, path in e["context_files"]["roles"].items():
            write(root, path, f"# {name.title()} — {role}\n\nWhat a {role} needs to know.\n")
        write(root, f"src/{name}/service.py", f"NAME = {name!r}\n")


def build(case: int, root: Path) -> Path:
    root = Path(root)
    root.mkdir(parents=True)
    if case == 1:
        entries = {n: entry(n, "modules", owner_team=f"team-{n}") for n in MODULES}
        entries["inventory"]["context_files"]["roles"]["curator"] = \
            "modules/inventory/roles/curator.md"
        docs(root, entries)
        write(root, "modules/registry.json", json.dumps({"modules": entries}, indent=2) + "\n")
    elif case == 2:
        entries = {n: entry(n, "docs/modules") for n in MODULES}
        docs(root, entries)
        for name, e in entries.items():
            write(root, f"docs/modules/{name}/module.json", json.dumps(e, indent=2) + "\n")
        write(root, "docs/modules/registry.json", json.dumps({"modules": entries}, indent=2)
              + "\n")
    elif case == 3:
        entries = {n: entry(n, "modules", stock_paths=[f"src/{n}/"]) for n in MODULES}
        docs(root, entries)
        write(root, "modules/registry.json", json.dumps({"modules": entries}, indent=2) + "\n")
        write(root, ".segmently-modules/config.toml", '[ci]\nbase = "origin/main"\n')
    else:
        raise SystemExit(f"unknown case {case} (1, 2, 3)")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               GIT_AUTHOR_NAME="warehouse", GIT_AUTHOR_EMAIL="dev@warehouse.example",
               GIT_COMMITTER_NAME="warehouse", GIT_COMMITTER_EMAIL="dev@warehouse.example",
               GIT_AUTHOR_DATE="2026-02-01T10:00:00+0000",
               GIT_COMMITTER_DATE="2026-02-01T10:00:00+0000")
    for args in (("init", "-q", "-b", "main"), ("add", "--", "."),
                 ("commit", "-q", "-m", "warehouse: the registry and its docs")):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, env=env)
    return root


if __name__ == "__main__":
    print(build(int(sys.argv[1]), Path(sys.argv[2])))
