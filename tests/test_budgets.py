"""Token budgets (D7): what every session pays for. Sizes are characters (`len` of the decoded
text), so they are deterministic. The descriptions are a hard budget (every session pays every
description). A skill, a route file or a pack above its split signal (D5, owner 2026-10-04) is a
decomposition decision, never a cap: route it, split it, or record the discussion with the owner
in SPLIT_DECISIONS — a shipped skill is never trimmed to fit a number."""

import ast
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from modsys.config import BUILTIN_PACKS, builtin_packs_root
from modsys.skills import read_front_matter
from tests.helpers import copy_fixture, run

# P8.2 (2026-10-03): the decision taken again for the shipped choice agent and the Codex path
DESCRIPTIONS_MAX = 7_000  # the shipped skills' `description` values together (2026-10-07, owner:
# raised from 6_600 for module-assistant's trigger)
SKILL_COUNT = 14        # core 11 + qa 2 + ui 1

# A shipped crossing of `skill_split_signal` / `pack_split_signal` (lint MS068 / MS069) that the
# owner discussed and kept. Keys: "<pack>/<skill>", "<pack>/<skill>/<file stem>", "pack <pack>".
# A value: "discussed with the owner YYYY-MM-DD: keep|route|split ..., because <why>". P8.4 ships
# none (SI-P84-4); an entry whose crossing is gone is stale and fails the test.
SPLIT_DECISIONS: dict[str, str] = {}
DECISION = re.compile(r"^discussed with the owner (\d{4}-\d{2}-\d{2}): (keep|route|split)\b.*, "
                      r"because \S.*$", re.DOTALL)

# Measured on the bookshop fixture (characters of stdout; `<root>` is the copied fixture):
#   modsys context --task "add a payment retry to the checkout" --role developer --json --root <root>
#   modsys show catalog --json --root <root>
CONTEXT_MEASURED = 1866
SHOW_MEASURED = 541
CONTEXT_MAX = int(CONTEXT_MEASURED * 1.2)
SHOW_MAX = int(SHOW_MEASURED * 1.2)
TASK = "add a payment retry to the checkout"


def shipped_skills(root: Path | None = None) -> dict[str, tuple[str, Path]]:
    """{`<pack>/<dir>`: (pack, SKILL.md path)} for every skill of every built-in pack (under
    `root`: a copy of the packs a test changed)."""
    out = {}
    for pack in BUILTIN_PACKS:
        for path in sorted(((root or builtin_packs_root()) / pack / "skills").glob("*/SKILL.md")):
            out[f"{pack}/{path.parent.name}"] = (pack, path)
    return out


def decision_key(pack: str, skill: str, name: str = "SKILL.md") -> str:
    """The `SPLIT_DECISIONS` key of a skill file: `<pack>/<skill>` for its `SKILL.md`,
    `<pack>/<skill>/<stem>` for a `references/<stem>.md` file (what `crossings()` records)."""
    return f"{pack}/{skill}" if name == "SKILL.md" else f"{pack}/{skill}/{Path(name).stem}"


def crossings(root: Path | None = None) -> dict[str, str]:
    """{decision key: lint message} for every MS068 / MS069 finding of `lint` with all three
    built-in packs enabled (`root`: where the packs are read from — a test seam)."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = copy_fixture(tmp)
        (repo / ".modsys").mkdir(exist_ok=True)
        (repo / ".modsys" / "config.toml").write_text('[packs]\nbuiltin = ["core", "qa", "ui"]\n',
                                                      encoding="utf-8")
        with mock.patch("modsys.config.builtin_packs_root",
                        return_value=root or builtin_packs_root()):
            code, out, err = run("lint", "--fail-on", "never", "--json", "--root", str(repo))
        assert (code, err) == (0, ""), err
        skills = shipped_skills(root)
        owner = {key.split("/")[1]: key.split("/")[0] for key in skills}
        found = {}
        for f in json.loads(out)["data"]["findings"]:
            if f["code"] == "MS069":
                found["pack " + f["message"].split("'")[1]] = f["message"]
            elif f["code"] == "MS068":
                label = f["message"].split(":")[0]
                sid, _, stem = label.partition("/")
                found[decision_key(owner[sid], sid, f"{stem}.md" if stem else "SKILL.md")] = \
                    f["message"]
    return found


ENGINE = Path(__file__).resolve().parents[1]
CAPS = ("SKILL_MAX", "CORE_MAX")  # the fixed caps D5 removed: no module defines one again


def cap_definitions(paths, base: Path = ENGINE) -> list[str]:
    """`<file>:<line> <name>` (the file relative to `base`) for every module-level assignment
    of a name in CAPS (plain, annotated or augmented, a tuple target too) in the Python files
    `paths`."""
    found = []
    for path in sorted(paths):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            targets = (node.targets if isinstance(node, ast.Assign)
                       else [node.target] if isinstance(node, (ast.AnnAssign, ast.AugAssign))
                       else [])
            names = [n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)]
            found += [f"{path.relative_to(base).as_posix()}:{node.lineno} {name}"
                      for name in names if name in CAPS]
    return found


def split_problems(found: dict[str, str], decisions: dict[str, str]) -> list[str]:
    """What the engine test fails on: a crossing without a recorded decision, a recorded
    decision that is malformed, or a decision whose crossing is gone."""
    problems = [f"{key}: {message} — decompose it, or record the owner's decision in "
                f"SPLIT_DECISIONS" for key, message in found.items() if key not in decisions]
    problems += [f"{key}: the recorded decision is not 'discussed with the owner YYYY-MM-DD: "
                 f"keep|route|split ..., because ...': {value!r}"
                 for key, value in decisions.items() if not DECISION.match(value)]
    problems += [f"{key}: remove the stale decision (it no longer crosses)"
                 for key in decisions if key not in found]
    return problems


class SplitDecisionsTest(unittest.TestCase):
    """The crossing rules, proven on a copy of the packs with one skill grown past the signal."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "packs"
        shutil.copytree(builtin_packs_root(), self.root)
        self.key = "core/module-lint"
        skills = self.root / "core" / "skills"
        md = skills / "module-lint" / "SKILL.md"
        text = md.read_text(encoding="utf-8")
        md.write_text(text + "x" * (9_001 - len(text)), encoding="utf-8")  # S + 1 characters
        for sid in ("module-sync", "module-discover"):  # keep the core total under its signal
            md = skills / sid / "SKILL.md"
            md.write_text(md.read_text(encoding="utf-8")[:2_000], encoding="utf-8")

    def test_a_crossing_without_a_decision_fails_naming_the_skill_and_both_numbers(self):
        problems = split_problems(crossings(self.root), {})
        self.assertEqual(len(problems), 1)
        self.assertIn(self.key, problems[0])
        self.assertIn("9001 characters > skill split signal 9000", problems[0])

    def test_a_recorded_decision_passes(self):
        decisions = {self.key: "discussed with the owner 2026-10-04: keep, because one scenario"}
        self.assertEqual(split_problems(crossings(self.root), decisions), [])

    def test_a_decision_without_a_valid_date_or_choice_fails(self):
        for value in ("keep, because one scenario",
                      "discussed with the owner 2026-10: keep, because x",
                      "discussed with the owner 2026-10-04: trim, because x",
                      "discussed with the owner 2026-10-04: keep"):
            with self.subTest(value=value):
                problems = split_problems(crossings(self.root), {self.key: value})
                self.assertEqual(len(problems), 1)
                self.assertIn(self.key, problems[0])

    def test_a_decision_for_a_skill_that_no_longer_crosses_is_stale(self):
        decisions = {"core/module-scout": "discussed with the owner 2026-10-04: keep, because x"}
        problems = split_problems({}, decisions)
        self.assertEqual(len(problems), 1)
        self.assertIn("remove the stale decision", problems[0])

    def test_a_route_file_and_a_pack_are_keyed_by_stem_and_pack(self):
        refs = self.root / "core" / "skills" / "module-lint" / "references"
        (refs / "big.md").write_text("y" * 9_001, encoding="utf-8")
        found = crossings(self.root)
        self.assertIn("core/module-lint/big", found)
        self.assertNotIn("pack core", found)  # a route file is never part of the pack total
        pack = self.root / "qa" / "skills"
        grown = next(pack.glob("*/SKILL.md"))
        grown.write_text(grown.read_text(encoding="utf-8") + "z" * 60_000, encoding="utf-8")
        self.assertIn("pack qa", crossings(self.root))


class ShippedSkillsTest(unittest.TestCase):
    def test_the_skill_count_is_pinned(self):
        self.assertEqual(len(shipped_skills()), SKILL_COUNT,
                         "a skill was added or removed: update SKILL_COUNT and review the budgets")

    def test_no_shipped_skill_route_or_pack_crosses_a_split_signal_unrecorded(self):
        self.assertEqual(split_problems(crossings(), SPLIT_DECISIONS), [])

    def test_the_caps_are_gone(self):  # final review M-2: every test and engine module
        sources = [*(ENGINE / "tests").rglob("*.py"), *(ENGINE / "modsys").rglob("*.py")]
        self.assertGreater(len(sources), 100)
        self.assertEqual(cap_definitions(sources), [])

    def test_the_cap_scan_finds_a_planted_cap(self):
        with tempfile.TemporaryDirectory() as tmp:  # never inside the engine's own tests/
            planted = Path(tmp) / "tests" / "test_planted.py"
            planted.parent.mkdir()
            planted.write_text("import os\nSKILL_MAX = 9000\nCORE_MAX: int = 1\n"
                               "LIMIT, SKILL_MAX = 1, 2\ndef f():\n    CORE_MAX = 1\n",
                               encoding="utf-8")
            self.assertEqual(cap_definitions([planted], Path(tmp)),
                             ["tests/test_planted.py:2 SKILL_MAX",
                              "tests/test_planted.py:3 CORE_MAX",
                              "tests/test_planted.py:4 SKILL_MAX"])

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
