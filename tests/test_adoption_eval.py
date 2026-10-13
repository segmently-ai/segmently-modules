"""E-A adoption eval (evals/adoption/run_eval.py): every scenario passes end to end, and a
failing step is reported in the scorecard, never as a traceback."""
import importlib.util
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "evals" / "adoption" / "run_eval.py"


def load_eval():
    spec = importlib.util.spec_from_file_location("run_eval", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AdoptionEvalTest(unittest.TestCase):
    def test_both_scenarios_pass(self):
        proc = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True,
                              timeout=300)
        card = json.loads(proc.stdout)
        failed = [(name, s["name"], s["detail"]) for name, result in card.items()
                  for s in result["steps"] if not s["ok"]]
        self.assertEqual((proc.returncode, failed), (0, []))
        self.assertEqual(set(card), {"greenfield", "brownfield", "packs", "skills", "adopt",
                                     "init-map", "init"})  # P5a D7 + P5b D10 (init)
        for result in card.values():
            self.assertTrue(result["ok"])
            self.assertGreater(result["commands"], 5)
        self.assertEqual({name: (len(r["steps"]), r["commands"]) for name, r in card.items()},
                         {"greenfield": (20, 26), "brownfield": (12, 20), "packs": (16, 15),
                          "skills": (11, 11), "adopt": (6, 7), "init-map": (8, 7),
                          "init": (10, 9)})
        self.assertIn("adoption eval: adopt ok (6 steps, 7 commands)", proc.stderr)
        self.assertIn("adoption eval: init-map ok (8 steps, 7 commands)", proc.stderr)
        self.assertIn("adoption eval: init ok (10 steps, 9 commands)", proc.stderr)

    def test_a_failed_step_stops_the_scenario_and_is_scored(self):
        run_eval = load_eval()

        def build(sc):
            sc.step("passes", lambda: "fine")
            sc.step("fails", lambda: run_eval.check(False, "expected failure"))
            sc.step("never runs", lambda: None)

        result = run_eval.run_scenario("probe", build)
        self.assertEqual(result, {"steps": [
            {"name": "passes", "ok": True, "detail": "fine"},
            {"name": "fails", "ok": False, "detail": "expected failure"}],
            "commands": 0, "ok": False})

    def test_a_failing_scenario_is_reported_and_the_other_still_runs(self):  # P32-AC-029
        env = {**os.environ, "SEGMENTLY_MODULES_EVAL_FAIL_STEP": "greenfield:init",  # the test seams
               "SEGMENTLY_MODULES_EVAL_SCENARIOS": "greenfield,brownfield"}  # P5b D10: under 60 s
        proc = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True,
                              timeout=300, env=env)
        card = json.loads(proc.stdout)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(card["greenfield"]["steps"][-1],
                         {"name": "init", "ok": False,
                          "detail": "forced by SEGMENTLY_MODULES_EVAL_FAIL_STEP (test seam)"})
        self.assertFalse(card["greenfield"]["ok"])
        self.assertTrue(card["brownfield"]["ok"])
        self.assertGreater(len(card["brownfield"]["steps"]), 5)

    def test_a_failing_packs_step_fails_only_that_scenario(self):  # P4A-AC-024
        env = {**os.environ, "SEGMENTLY_MODULES_EVAL_FAIL_STEP": "packs:eject api-review",
               "SEGMENTLY_MODULES_EVAL_SCENARIOS": "greenfield,brownfield,packs"}  # P5b D10
        proc = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True,
                              timeout=300, env=env)
        card = json.loads(proc.stdout)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual([s["name"] for s in card["packs"]["steps"]][-2:],
                         ["revert the edit: in sync again", "eject api-review"])
        self.assertFalse(card["packs"]["ok"])
        self.assertTrue(card["greenfield"]["ok"] and card["brownfield"]["ok"])
        self.assertIn("adoption eval: packs FAILED (10 steps, ", proc.stderr)

    def test_a_failing_skills_step_fails_only_that_scenario(self):  # P4B-AC-021
        env = {**os.environ, "SEGMENTLY_MODULES_EVAL_FAIL_STEP": "skills:eject module-sync",
               "SEGMENTLY_MODULES_EVAL_SCENARIOS": "greenfield,brownfield,packs,skills"}  # P5b D10
        proc = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True,
                              timeout=300, env=env)
        card = json.loads(proc.stdout)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual([s["name"] for s in card["skills"]["steps"]][-1], "eject module-sync")
        self.assertFalse(card["skills"]["ok"])
        self.assertTrue(all(card[name]["ok"] for name in ("greenfield", "brownfield", "packs")))
        self.assertIn("adoption eval: skills FAILED (9 steps, ", proc.stderr)

    def test_a_failing_adopt_or_init_map_step_stops_that_scenario(self):  # P5A-AC-038/039
        run_eval = load_eval()  # in-process: the seam is the same, the other scenarios idle
        for step, build, last in (
                ("adopt:adopt writes .segmently-modules/config.toml", run_eval.adopt,
                 ["adopt --dry-run writes nothing and names the declarations",
                  "adopt writes .segmently-modules/config.toml"]),
                ("init-map:init confirm", run_eval.init_map,
                 ["exclude one candidate, rename another", "init confirm"])):
            with self.subTest(step=step), \
                    mock.patch.dict(os.environ, {"SEGMENTLY_MODULES_EVAL_FAIL_STEP": step}):
                result = run_eval.run_scenario(step.split(":")[0], build)
                self.assertEqual((result["ok"], [s["name"] for s in result["steps"]][-2:]),
                                 (False, last))
                self.assertEqual(result["steps"][-1]["detail"],
                                 "forced by SEGMENTLY_MODULES_EVAL_FAIL_STEP (test seam)")

    def test_a_failing_init_step_fails_only_that_scenario(self):  # P5B-AC-035
        env = {**os.environ, "SEGMENTLY_MODULES_EVAL_FAIL_STEP": "init:init fanout: six work items",
               "SEGMENTLY_MODULES_EVAL_SCENARIOS": "adopt, init"}  # the test seams (names are stripped)
        proc = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True,
                              timeout=300, env=env)
        card = json.loads(proc.stdout)
        self.assertEqual((proc.returncode, list(card)), (1, ["adopt", "init"]))
        self.assertEqual([s["name"] for s in card["init"]["steps"]][-2:],
                         ["init confirm: six modules", "init fanout: six work items"])
        self.assertEqual((card["init"]["steps"][-1]["detail"], card["init"]["commands"]),
                         ("forced by SEGMENTLY_MODULES_EVAL_FAIL_STEP (test seam)", 2))
        self.assertTrue(card["adopt"]["ok"])
        self.assertIn("adoption eval: init FAILED (4 steps, 2 commands)", proc.stderr)
        env["SEGMENTLY_MODULES_EVAL_SCENARIOS"] = "init,nosuch"
        proc = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True,
                              timeout=60, env=env)
        self.assertEqual((proc.returncode, proc.stdout), (2, ""))
        self.assertIn("unknown scenario(s) in SEGMENTLY_MODULES_EVAL_SCENARIOS: nosuch", proc.stderr)

    def test_an_unexpected_error_is_a_failed_step(self):
        run_eval = load_eval()
        result = run_eval.run_scenario("probe", lambda sc: 1 / 0)
        self.assertEqual((result["ok"], result["steps"][-1]["detail"]),
                         (False, "ZeroDivisionError: division by zero"))


if __name__ == "__main__":
    unittest.main()
