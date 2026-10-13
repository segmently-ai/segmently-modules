"""The skill-creator eval files of `module-init` and `module-adopt` (P5b D8, SI-22, SI-23):
`evals.json` (three outcome cases each, `assertions` a grader checks) and `trigger-evals.json`
(twenty queries: should trigger, and near misses another built-in skill owns). No model runs
here — the controller runs the evals with in-session subagents at the gate."""
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import git
from tests.test_builtin_content import SKILLS
from tests.test_builtin_skills import FRAMEWORKS

ENGINE = Path(__file__).resolve().parents[1]
SUITE = ENGINE / "evals" / "skills"
TARGETS = ("module-init", "module-adopt")
EVAL_KEYS = ["id", "prompt", "expected_output", "files", "assertions"]
QUERY_MIN = 60
# the near misses: a query that must not trigger the skill -> the built-in skill that owns it
# (None: no skill should fire)
OWNERS = {
    "module-init": {
        "Add a new module called wishlist": "module-create",
        "CI says segmently-modules lint failed": "module-lint",
        "We already have a module registry written by another tool": "module-adopt",
        "I finished the refund changes": "module-sync",
        "The catalog MODULE.md is over the size budget": "module-split",
        "Which modules will this change": "module-discover",
        "Review this UI change": "designer",
        "Write acceptance criteria": "qa-acceptance",
        "How does the recommendations engine": "module-research",
        "Rename the payment gateway class": None},
    "module-adopt": {
        "This codebase has no module registry at all yet": "module-init",
        "CI fails on segmently-modules lint": "module-lint",
        "Create a new module for the loyalty points": "module-create",
        "I just changed how orders are shipped": "module-sync",
        "Before we plan the inventory rework": "module-scout",
        "Which modules does the diff on this branch touch": "module-discover",
        "The orders MODULE.md is far over budget": "module-split",
        "Refresh the QA acceptance baseline": "qa-acceptance-baseline",
        "Explain in depth how stock counts flow": "module-research",
        "Fix the failing unit test": None}}


def load(skill: str, name: str):
    return json.loads((SUITE / skill / name).read_text(encoding="utf-8"))


def trigger_problems(rows) -> list[str]:
    """What breaks the trigger-set rules: 20 {query, should_trigger} rows, 8–10 of each kind,
    every query at least 60 characters."""
    out = []
    if len(rows) != 20:
        out.append(f"{len(rows)} queries (20)")
    positives = sum(r.get("should_trigger") is True for r in rows)
    if not 8 <= positives <= 10 or not 8 <= len(rows) - positives <= 10:
        out.append(f"{positives} should trigger, {len(rows) - positives} should not (8–10 each)")
    out += [f"not {{query, should_trigger}}: {r}" for r in rows
            if set(r) != {"query", "should_trigger"} or not isinstance(r["should_trigger"], bool)]
    out += [f"shorter than {QUERY_MIN}: {r['query']}" for r in rows
            if len(r.get("query", "")) < QUERY_MIN]
    return out


class EvalFilesTest(unittest.TestCase):  # P5B-AC-031
    def test_the_outcome_cases(self):
        for skill in TARGETS:
            doc = load(skill, "evals.json")
            with self.subTest(skill=skill):
                self.assertEqual((list(doc), doc["skill_name"]), (["skill_name", "evals"], skill))
                self.assertEqual(len(doc["evals"]), 3)
                self.assertEqual([e["id"] for e in doc["evals"]], [1, 2, 3])
                for case in doc["evals"]:
                    self.assertEqual(list(case), EVAL_KEYS)
                    self.assertTrue(case["assertions"])
                    self.assertTrue(all(isinstance(a, str) and a.strip()
                                        for a in case["assertions"]))
                    self.assertTrue(case["prompt"].strip() and case["expected_output"].strip())
                    for path in case["files"]:
                        self.assertTrue((ENGINE / path).exists(), path)

    def test_the_trigger_sets(self):
        for skill in TARGETS:
            rows = load(skill, "trigger-evals.json")
            with self.subTest(skill=skill):
                self.assertEqual(trigger_problems(rows), [])
                misses = [r["query"] for r in rows if not r["should_trigger"]]
                owned = {}
                for q in misses:  # every near miss has exactly one row (never the last of two)
                    owners = [o for prefix, o in OWNERS[skill].items() if q.startswith(prefix)]
                    self.assertEqual(len(owners), 1, f"{q!r}: {len(owners)} OWNERS rows")
                    owned[q] = owners[0]
                self.assertEqual(sorted(owned), sorted(misses))
                others = [o for o in owned.values() if o]
                self.assertGreaterEqual(len(others), 6)
                self.assertTrue(set(others) <= set(SKILLS) - {skill})

    def test_the_rules_can_fail(self):
        good = load("module-init", "trigger-evals.json")
        seven = [dict(r, should_trigger=False) if i in (0, 1, 2) else r
                 for i, r in enumerate(good)]
        eleven = [dict(r, should_trigger=True) if i == 19 else r for i, r in enumerate(good)]
        self.assertEqual(trigger_problems(seven), ["7 should trigger, 13 should not (8–10 each)"])
        self.assertEqual(trigger_problems(eleven), ["11 should trigger, 9 should not (8–10 each)"])
        self.assertEqual(trigger_problems([{"query": "short", "should_trigger": True}] * 20),
                         ["20 should trigger, 0 should not (8–10 each)"]
                         + ["shorter than 60: short"] * 20)

    def test_generic_text(self):
        word = re.compile(r"\b(" + "|".join(FRAMEWORKS) + r")\b", re.I)
        for skill in TARGETS:
            for name in ("evals.json", "trigger-evals.json"):
                with self.subTest(skill=skill, file=name):
                    self.assertIsNone(word.search((SUITE / skill / name).read_text("utf-8")))


class AdoptCasesTest(unittest.TestCase):  # P5B-AC-031 (the repositories of module-adopt's cases)
    def test_the_three_repositories(self):
        spec = importlib.util.spec_from_file_location("cases", SUITE / "module-adopt/cases.py")
        cases = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cases)
        with tempfile.TemporaryDirectory() as tmp:
            one = cases.build(1, Path(tmp) / "one")
            registry = json.loads((one / "modules/registry.json").read_text())["modules"]
            self.assertEqual({e["owner_team"] for e in registry.values()},
                             {"team-inventory", "team-orders", "team-shipping"})
            self.assertIn("curator", registry["inventory"]["context_files"]["roles"])
            self.assertFalse((one / ".segmently-modules").exists())
            two = cases.build(2, Path(tmp) / "two")
            self.assertTrue((two / "docs/modules/registry.json").is_file())
            self.assertEqual(sorted(p.parent.name for p in (two / "docs/modules").glob(
                "*/module.json")), ["inventory", "orders", "shipping"])
            three = cases.build(3, Path(tmp) / "three")
            self.assertEqual((three / ".segmently-modules/config.toml").read_text(),
                             '[ci]\nbase = "origin/main"\n')
            again = cases.build(1, Path(tmp) / "again")
            self.assertEqual(git(one, "rev-parse", "HEAD"), git(again, "rev-parse", "HEAD"))
            self.assertEqual(git(one, "status", "--porcelain"), "")
            proc = subprocess.run([sys.executable, str(SUITE / "module-adopt/cases.py"), "4",
                                   str(Path(tmp) / "four")], capture_output=True, text=True)
            self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
