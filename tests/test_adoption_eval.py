"""E-A adoption eval (evals/adoption/run_eval.py): both scenarios pass end to end, and a failing
step is reported in the scorecard, never as a traceback."""
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

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
        self.assertEqual(set(card), {"greenfield", "brownfield"})
        for result in card.values():
            self.assertTrue(result["ok"])
            self.assertGreater(result["commands"], 10)

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

    def test_an_unexpected_error_is_a_failed_step(self):
        run_eval = load_eval()
        result = run_eval.run_scenario("probe", lambda sc: 1 / 0)
        self.assertEqual((result["ok"], result["steps"][-1]["detail"]),
                         (False, "ZeroDivisionError: division by zero"))


if __name__ == "__main__":
    unittest.main()
