"""Build a git copy of `bookshop_monorepo/` with a fixed history — the same author, committer,
dates and messages every time, so two builds give the same commit ids. The first commit adds
the whole tree; each later commit appends one comment line to the files it names, giving the
co-change signal of `init map` its pairs: payments + recommendations (they also import each
other: the one merge hint) and cart + catalog (a one-way import: no hint).

Usage (tests, the adoption eval): `build(dest)` -> dest, a directory that must not exist."""
import os
import shutil
import subprocess
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent / "bookshop_monorepo"
PAYMENTS = ["services/payments/payments/gateway.py",
            "services/recommendations/recommendations/engine.py"]
HISTORY = [  # (message, the files the commit changes) after the first commit
    ("payments and recommendations: suggest a book after a charge", PAYMENTS),
    ("payments and recommendations: score by customer", PAYMENTS),
    ("cart and catalog: price per line", ["packages/cart/src/lines.ts",
                                          "packages/catalog/src/books.ts"]),
    ("cart and catalog: find by isbn", ["packages/cart/src/index.ts",
                                        "packages/catalog/src/index.ts"]),
    ("storefront: the book page", ["apps/storefront/src/main.ts"]),
    ("ui-kit: a text field", ["packages/ui-kit/src/forms/text-field.tsx"]),
]


def _git(dest: Path, day: int, *args: str) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    date = f"2026-01-{day:02d}T10:00:00+0000"
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               GIT_AUTHOR_NAME="bookshop", GIT_AUTHOR_EMAIL="dev@bookshop.example",
               GIT_COMMITTER_NAME="bookshop", GIT_COMMITTER_EMAIL="dev@bookshop.example",
               GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    subprocess.run(["git", "-C", str(dest), *args], check=True, capture_output=True, env=env)


def build(dest: Path) -> Path:
    dest = Path(dest)
    shutil.copytree(FIXTURE, dest)
    _git(dest, 1, "init", "-q", "-b", "main")
    _git(dest, 1, "add", "--", ".")
    _git(dest, 1, "commit", "-q", "-m", "bookshop: the first version")
    for day, (message, paths) in enumerate(HISTORY, start=2):
        for rel in paths:
            mark = "#" if rel.endswith(".py") else "//"
            with (dest / rel).open("a", encoding="utf-8") as fh:
                fh.write(f"{mark} change {day}\n")
        _git(dest, day, "add", "--", *paths)
        _git(dest, day, "commit", "-q", "-m", message)
    return dest
