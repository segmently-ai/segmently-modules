#!/usr/bin/env python3
"""Build the `adopter` persona's repository: a bookshop warehouse app whose module registry and
module docs another tool wrote — extra fields (`stock_paths`, a code pointer; `curator_team`), a
role no engine default knows (`archivist`), a registry-level timestamp (`last_modified`), a
directory under `modules/` that is not a module (`_templates/`), a child module — and no
`.segmently-modules/`. One commit with a fixed author, date and message: every build is the same. A config
alone (what `segmently-modules adopt` infers) makes `segmently-modules lint --fail-on warning` exit 0.

Usage: python3 evals/adoption/agents/adopter_repo.py DEST   (DEST must not exist)"""
import json
import os
import subprocess
import sys
from pathlib import Path

MODULES = {
    "inventory": ("Stock of every title: copies on hand, reorder points and shelf moves.",
                  ["inventory", "stock", "reorder", "shelf", "copies"], ["src/inventory/"],
                  "stock", ["developer", "archivist"]),
    "orders": ("Customer orders: placing, changing and cancelling an order for books.",
               ["order", "orders", "cancel", "purchase", "invoice"],
               ["src/orders/service.py"], "sales", ["developer"]),
    "shipping": ("Parcels: packing, carrier choice and tracking for paid orders.",
                 ["shipping", "parcel", "carrier", "tracking", "delivery"], ["src/shipping/"],
                 "logistics", ["developer", "archivist"]),
    "loyalty": ("Reader loyalty: points for every purchase and the rewards they buy.",
                ["loyalty", "points", "reward", "rewards", "member"],
                ["src/loyalty/points.py"], "sales", ["developer"]),
}
CODE = {"src/inventory/stock.py": "REORDER_POINT = 3\n",
        "src/orders/service.py": "def place(order_id: str) -> str:\n    return order_id\n",
        "src/shipping/carrier.py": "CARRIERS = ['post', 'courier']\n",
        "src/loyalty/points.py": "POINTS_PER_BOOK = 10\n",
        "src/loyalty/rewards/catalog.py": "REWARDS = {'bookmark': 50}\n"}


def registry() -> dict:
    modules = {}
    for name, (description, keywords, paths, team, roles) in MODULES.items():
        doc = f"modules/{name}/MODULE.md"
        modules[name] = {
            "name": name, "description": description, "status": "active",
            "keywords": keywords, "stock_paths": paths, "curator_team": team,
            "context_files": {"universal": doc,
                              "roles": {r: f"modules/{name}/roles/{r}.md" for r in roles}}}
    modules["loyalty"]["submodules"] = {"rewards": {
        "description": "Rewards a member can buy with points.", "keywords": ["reward"],
        "context_files": {"universal": "modules/loyalty/submodules/rewards/MODULE.md"}}}
    return {"generated_by": "shelfkeeper 2.3", "last_modified": "2026-02-01T09:30:00Z",
            "modules": modules}


def files() -> dict[str, str]:
    out = dict(CODE)
    out["README.md"] = ("# Bookshop warehouse\n\nStock, orders, shipping and loyalty. The module "
                        "registry in `modules/` is written by shelfkeeper.\n")
    out["modules/registry.json"] = json.dumps(registry(), indent=2) + "\n"
    out["modules/_templates/MODULE.md"] = "# ${name}\n\n${description}\n"
    for name, (description, _, _, _, roles) in MODULES.items():
        out[f"modules/{name}/MODULE.md"] = f"# {name.title()}\n\n{description}\n"
        for role in roles:
            out[f"modules/{name}/roles/{role}.md"] = f"# {name.title()} — {role}\n"
    out["modules/loyalty/submodules/rewards/MODULE.md"] = "# Rewards\n\nWhat points buy.\n"
    return out


def build(dest: Path) -> Path:
    dest = Path(dest)
    dest.mkdir(parents=True)
    for rel, text in files().items():
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        (dest / rel).write_text(text, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               GIT_AUTHOR_NAME="warehouse", GIT_AUTHOR_EMAIL="dev@warehouse.example",
               GIT_COMMITTER_NAME="warehouse", GIT_COMMITTER_EMAIL="dev@warehouse.example",
               GIT_AUTHOR_DATE="2026-02-01T09:30:00+0000",
               GIT_COMMITTER_DATE="2026-02-01T09:30:00+0000")
    for args in (("init", "-q", "-b", "main"), ("add", "--", "."),
                 ("commit", "-q", "-m", "warehouse: the registry from shelfkeeper")):
        subprocess.run(["git", "-C", str(dest), *args], check=True, capture_output=True,
                       env=env)
    return dest


if __name__ == "__main__":
    print(build(Path(sys.argv[1])))
