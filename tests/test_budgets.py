"""Token budgets (D7): what every session pays for. Sizes are characters (`len` of the decoded
text), so they are deterministic. A bound is never loosened to make a test pass: shrink the
skill, or take the decision again."""

import tempfile
import unittest
from pathlib import Path

from modsys.config import BUILTIN_PACKS, builtin_packs_root
from modsys.skills import read_front_matter
from tests.helpers import copy_fixture, run

SKILL_MAX = 9_000       # each shipped SKILL.md
CORE_MAX = 53_200       # the core pack's nine SKILL.md together
# P8.2 (2026-10-03): the decision taken again for the shipped choice agent and the Codex path
DESCRIPTIONS_MAX = 6_600  # the shipped skills' `description` values together
SKILL_COUNT = 12        # core 9 + qa 2 + ui 1

# Measured on the bookshop fixture (characters of stdout; `<root>` is the copied fixture):
#   modsys context --task "add a payment retry to the checkout" --role developer --json --root <root>
#   modsys show catalog --json --root <root>
CONTEXT_MEASURED = 1866
SHOW_MEASURED = 541
CONTEXT_MAX = int(CONTEXT_MEASURED * 1.2)
SHOW_MAX = int(SHOW_MEASURED * 1.2)
TASK = "add a payment retry to the checkout"


def size_problem(name: str, text: str, limit: int = SKILL_MAX) -> str | None:
    """None when `text` fits in `limit` characters, else a message naming the file and both
    numbers."""
    n = len(text)
    return None if n <= limit else f"{name}: {n} characters, over the {limit} limit"


def shipped_skills() -> dict[str, tuple[str, Path]]:
    """{`<pack>/<dir>`: (pack, SKILL.md path)} for every skill of every built-in pack."""
    out = {}
    for pack in BUILTIN_PACKS:
        for path in sorted((builtin_packs_root() / pack / "skills").glob("*/SKILL.md")):
            out[f"{pack}/{path.parent.name}"] = (pack, path)
    return out


def text_of(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


class BoundCheckTest(unittest.TestCase):
    def test_exactly_at_the_bound_passes(self):
        self.assertIsNone(size_problem("core/x/SKILL.md", "a" * 9_000))

    def test_one_over_the_bound_fails_naming_the_file_and_both_numbers(self):
        msg = size_problem("core/x/SKILL.md", "a" * 9_001)
        self.assertIsNotNone(msg)
        self.assertIn("core/x/SKILL.md", msg)
        self.assertIn("9001", msg)
        self.assertIn("9000", msg)


class ShippedSkillsTest(unittest.TestCase):
    def test_the_skill_count_is_pinned(self):
        self.assertEqual(len(shipped_skills()), SKILL_COUNT,
                         "a skill was added or removed: update SKILL_COUNT and review the budgets")

    def test_every_skill_is_within_its_bound(self):
        problems = [p for name, (_, path) in shipped_skills().items()
                    if (p := size_problem(name, text_of(path)))]
        self.assertEqual(problems, [])

    def test_the_core_pack_is_within_its_total(self):
        core = {n: len(text_of(p)) for n, (pack, p) in shipped_skills().items() if pack == "core"}
        self.assertEqual(len(core), 9)
        self.assertLessEqual(sum(core.values()), CORE_MAX, f"core total over {CORE_MAX}: {core}")

    def test_the_descriptions_are_within_their_total(self):
        total = 0
        for name, (_, path) in shipped_skills().items():
            front = read_front_matter(path)
            self.assertIsNotNone(front, name)
            total += len(front["description"])
        # 6003 when measured (P6.1): what every session pays at startup, pinned.
        self.assertLessEqual(total, DESCRIPTIONS_MAX)


class OutputSizeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = str(copy_fixture(self._tmp.name))

    def out(self, *argv):
        code, out, err = run(*argv, "--json", "--root", self.root)
        self.assertEqual((code, err), (0, ""))
        return out

    def test_context_for_a_developer_task(self):
        out = self.out("context", "--task", TASK, "--role", "developer")
        self.assertLessEqual(len(out), CONTEXT_MAX, f"context is {len(out)} characters")

    def test_show_a_module(self):
        out = self.out("show", "catalog")
        self.assertLessEqual(len(out), SHOW_MAX, f"show is {len(out)} characters")


if __name__ == "__main__":
    unittest.main()
