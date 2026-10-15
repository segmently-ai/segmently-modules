"""module-discover reads with fewer turns and less code (DCP-AC-025, DCP-AC-035): one rule under
`## Steps`, binding every step, runs the independent read commands of one step together — one
Bash call or parallel tool calls — and never batches a command that needs an earlier output; step
6 reads a file the search found outline first — its signatures with their line numbers — and then
only the ranges where the change lands, not whole files. The outline example is a real command:
it lists the signatures of a file in several languages and none of their bodies."""
from __future__ import annotations

import re
import shlex
import tempfile
import unittest
from pathlib import Path

from segmently_modules.config import builtin_packs_root
from tests.helpers import git, init_git
from tests.test_builtin_skills import section

ENGINE = Path(__file__).resolve().parents[1]
SKILL = builtin_packs_root() / "core/skills/module-discover/SKILL.md"
BATCH = [  # DCP-AC-025, in this order
    "Run the independent read commands of one step together — in one Bash call (`a; b; c`, or a "
    "loop) or as parallel tool calls — instead of one per turn:",
    "step 2's `show` of every candidate, step 3's `related` of every kept module, step 5's "
    "`show --all-roles` of every module and then the docs they list, step 6's searches of every "
    "module.",
    "Never batch commands whose input depends on an earlier output (a split module's child after "
    "its INDEX, step 3 after step 2's scores).",
]
EXAMPLES = {"2": "segmently-modules show <module> --json",  # the step each example names runs it
            "3": "segmently-modules related <module> --json",
            "5": "segmently-modules show <module> --all-roles --json"}
OUTLINE = [  # DCP-AC-035, in this order
    "Read a file the search found outline first: its exported or top-level signatures with their "
    "line numbers (e.g. `git grep -n -E '^(export |def |class |func |pub )' -- <file>`, or a "
    "symbol tool when you have one),",
    "then only the ranges around the lines the change lands on (Read with an offset and a limit, "
    "or `sed -n '<from>,<to>p' <file>`), not whole files.",
]
FILES = {  # bookshop sources in four languages: path -> (text, the outline git grep prints)
    "shop/shelf.py": ("import re\n\nclass Shelf:\n    def titles(self):\n        return []\n\n"
                      "def find_book(title):\n    words = title.split()\n    return words\n",
                      ["3:class Shelf:", "7:def find_book(title):"]),
    "shop/order.ts": ("import { Book } from \"./book\";\n\n"
                      "export function placeOrder(book: Book): number {\n  const total = 1;\n"
                      "  return total;\n}\n\nexport class Basket {}\n",
                      ["3:export function placeOrder(book: Book): number {",
                       "8:export class Basket {}"]),
    "shop/stock.go": ("package shop\n\nfunc CountCopies(isbn string) int {\n\treturn 0\n}\n",
                      ["3:func CountCopies(isbn string) int {"]),
    "shop/price.rs": ("use std::fmt;\n\npub fn book_price(pages: u32) -> u32 {\n    pages * 2\n}\n",
                      ["3:pub fn book_price(pages: u32) -> u32 {"]),
}


def raw() -> str:
    return SKILL.read_bytes().decode("utf-8")


def flat(s: str) -> str:
    return " ".join(s.split())


def steps() -> str:
    return section(raw(), "## Steps")


def step(n: int) -> str:
    """Step `n` of `## Steps`, flat: from its numbered line to the next one."""
    body = steps()
    start = re.search(rf"^{n}\. \*\*", body, re.M)
    end = re.search(rf"^{n + 1}\. \*\*", body, re.M)
    return flat(body[start.start():end.start() if end else len(body)]) if start else ""


def at(body: str, phrases: list[str]) -> list[int]:
    return [body.find(p) for p in phrases]


class BatchingTest(unittest.TestCase):  # DCP-AC-025
    def test_the_rule_binds_every_step(self):
        body = flat(steps())
        found = at(body, BATCH)
        self.assertNotIn(-1, found)
        self.assertEqual(found, sorted(found))
        self.assertEqual([body.count(p) for p in BATCH], [1, 1, 1])
        self.assertLess(found[-1], body.index("1. **Candidates.**"))  # before the first step
        self.assertEqual(flat(raw()).count(BATCH[0]), 1)  # once in the whole skill

    def test_never_batch_dependent_commands(self):
        self.assertIn("Never batch commands whose input depends on an earlier output", flat(steps()))

    def test_each_example_names_the_step_that_runs_it(self):
        body = flat(steps())
        for number, command in EXAMPLES.items():
            with self.subTest(step=number):
                self.assertIn(f"step {number}'s `{command.split()[1]}", body)
                self.assertIn(f"`{command}`", step(int(number)))
        self.assertIn("step 6's searches of every module", body)
        self.assertIn("git grep -n -e <term>", step(6))


class OutlineFirstTest(unittest.TestCase):  # DCP-AC-035
    def test_step_6_reads_the_outline_then_ranges(self):
        body = step(6)
        found = at(body, OUTLINE)
        self.assertNotIn(-1, found)
        self.assertEqual(found, sorted(found))
        self.assertLess(body.index("git grep -n -e <term>"), found[0])  # after the search
        for phrase in ("outline first", "signatures with their line numbers",
                       "only the ranges around the lines the change lands on", "not whole files"):
            self.assertIn(phrase, body)
        self.assertEqual(flat(raw()).count(OUTLINE[0]), 1)  # step 6 only

    def test_language_neutral(self):
        pattern = self.command()[4]  # the pattern names several languages' forms, no single one
        for form in ("export ", "def ", "class ", "func ", "pub "):
            self.assertIn(form, pattern)
        self.assertIn("e.g. `git grep", step(6))  # an example, not the only way

    def command(self) -> list[str]:
        spans = re.findall(r"`(git grep -n -E [^`]+)`", step(6))
        self.assertEqual(len(spans), 1)
        return shlex.split(spans[0])

    def test_the_outline_command_prints_signatures_not_bodies(self):
        argv = self.command()
        self.assertEqual(argv[:4], ["git", "grep", "-n", "-E"])
        self.assertEqual(argv[-2:], ["--", "<file>"])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            for rel, (text, _) in FILES.items():
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text(text, encoding="utf-8")
            init_git(root)
            for rel, (text, outline) in FILES.items():
                with self.subTest(file=rel):
                    out = git(root, *argv[1:-1], rel)
                    self.assertEqual(out.splitlines(), [f"{rel}:{line}" for line in outline])
            out = git(root, *argv[1:-1], *FILES)  # several files in one call (the batching rule)
        self.assertEqual(out.splitlines(), sorted(f"{rel}:{line}" for rel, (_, outline)
                                                  in FILES.items() for line in outline))
        self.assertNotIn("return", out)


class ChangelogTest(unittest.TestCase):  # R-5
    def test_the_unreleased_line(self):
        log = (ENGINE / "CHANGELOG.md").read_text(encoding="utf-8")
        unreleased = log.split("## [Unreleased]", 1)[1].split("\n## [", 1)[0]
        lines = [ln for ln in unreleased.splitlines()
                 if ln.startswith("- module-discover batches independent reads and reads code "
                                  "outline-first")]
        self.assertEqual(len(lines), 1)


if __name__ == "__main__":
    unittest.main()
