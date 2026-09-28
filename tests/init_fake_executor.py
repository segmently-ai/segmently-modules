"""A fake `init` executor for the tests and the adoption eval: it writes, from a work item alone,
deterministic docs a writer agent could have written — no model, stdlib only. Run as
`python3 tests/init_fake_executor.py` by `modsys init run --executor …` (stdin = the prompt;
env MODSYS_INIT_MODULE, MODSYS_INIT_STAGING, MODSYS_INIT_WORK), or import `write_docs`.

The bookshop_monorepo modules get the texts of `CANNED` (one keyword, `price`, is shared by
`catalog` and `cart`: the collision `init reconcile` finds); any other module gets texts built
from its name. `storefront` writes one edge of its own (to `catalog`, `complements`)."""
import json
import os
import sys
from pathlib import Path

CANNED = {  # module -> (description, keywords, purpose paragraph)
    "catalog": ("Book titles, authors and ISBN lookups: the books the shop sells.",
                ["catalog", "book", "books", "isbn", "author", "title", "price"],
                "Finds a book by its ISBN and formats its price for display."),
    "cart": ("The reader's cart: lines, quantities and totals before checkout.",
             ["cart", "basket", "line", "total", "quantity", "price"],
             "Adds up the lines a reader has chosen, one price at a time."),
    "ui-kit": ("Buttons, text fields and labels shared by the shop's pages.",
               ["button", "field", "form", "label", "widget"],
               "The reusable pieces every page is built from."),
    "storefront": ("The shop window: the book page a reader sees and buys from.",
                   ["storefront", "page", "shop", "window", "render"],
                   "Renders the page of one book with its buy button."),
    "payments": ("Charges a customer for an order and refunds it when asked.",
                 ["payment", "charge", "refund", "customer", "gateway"],
                 "Talks to the payment gateway for every order."),
    "recommendations": ("Suggests the next book a reader may like from the reading history.",
                        ["recommendation", "suggest", "reader", "history", "score"],
                        "Scores the books a reader might want next."),
    "tools": ("Helper scripts: a weekly sales report and a seed of sample books.",
              ["script", "report", "seed", "sales", "weekly"],
              "Scripts a developer runs by hand, never in production."),
}
EDGES = {"storefront": [{"module": "catalog", "relation": "complements",
                         "description": "shows the books the catalog holds"}]}


def texts(item: dict) -> tuple[str, list[str], str]:
    name = item["module"]
    if name in CANNED:
        return CANNED[name]
    words = [w for w in name.replace("-", " ").split() if w]
    keywords = list(dict.fromkeys(words + [f"{name}-{s}" for s in
                                           ("code", "docs", "change", "fix", "test")]))
    return (f"The {name} module of this repository: its code and what it does.", keywords,
            f"The {name} code, in one place.")


def write_docs(root: Path, item: dict, staging: Path | None = None) -> None:
    """The staging output of one work item: MODULE.md, one doc per role, entry.json."""
    staging = staging or Path(root) / item["staging_dir"]
    description, keywords, purpose = texts(item)
    title = item["module"].replace("-", " ").title()
    rows = [f"| {Path(f).stem.replace('_', ' ')} | `{f}` | a file of the module |"
            for f in item["files"][:5]]
    module_md = "\n".join([f"# {title}", "", f"> {description}", "", "## Purpose", "", purpose,
                           "", "## EXISTING Components - DO NOT CREATE NEW", "",
                           "| Name | Path | Purpose |", "|------|------|---------|", *rows, "",
                           "## Usage", "", "Read the files above before a change.", ""])
    (staging / "roles").mkdir(parents=True, exist_ok=True)
    (staging / "MODULE.md").write_text(module_md, encoding="utf-8")
    for role in item["roles"]:
        (staging / "roles" / f"{role}.md").write_text(
            f"# {title} — {role}\n\nWhat a {role} needs to know: the code lives under "
            f"{', '.join(item['paths'])}.\n", encoding="utf-8")
    entry = {"description": description, "keywords": keywords}
    edges = [e for e in EDGES.get(item["module"], [])
             if e["module"] in {n["to"] for n in item["neighbours"]}]
    if edges:
        entry["related_modules"] = edges
    (staging / "entry.json").write_text(json.dumps(entry, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    sys.stdin.read()  # the prompt: this fake writes from the work item alone
    item = json.loads(Path(os.environ["MODSYS_INIT_WORK"]).read_text(encoding="utf-8"))
    write_docs(Path.cwd(), item, Path(os.environ["MODSYS_INIT_STAGING"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
