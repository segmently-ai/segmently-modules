"""E-B blind-agent fixtures: the prompts keep their placeholders and rules, the rubric its
PASS line."""
import unittest
from pathlib import Path

AGENTS = Path(__file__).resolve().parents[1] / "evals" / "adoption" / "agents"


class AgentFixturesTest(unittest.TestCase):
    def read(self, name: str) -> str:
        return (AGENTS / name).read_text(encoding="utf-8")

    def test_prompts_carry_placeholders_rules_and_the_log_format(self):
        for name, goals in (("greenfield.md", 5), ("brownfield.md", 4)):
            with self.subTest(prompt=name):
                text = self.read(name)
                for needle in ("{WORKDIR}", "{VENV}", "{DOCS}", "source peek", "--help",
                               "FRICTION.md", "## Log", "## Summary", "blocker", "major",
                               "minor", f"{goals}. "):
                    self.assertIn(needle, text)
                self.assertNotIn(f"{goals + 1}. ", text)

    def test_brownfield_pins_the_public_repository(self):
        text = self.read("brownfield.md")
        self.assertIn("https://github.com/nsidnev/fastapi-realworld-example-app", text)
        self.assertIn("checkout -q 029eb77", text)
        self.assertIn("at least 80 %", text)

    def test_rubric_pass_line(self):
        text = " ".join(self.read("rubric.md").split())
        self.assertIn("**PASS** = all goal steps done, 0 source peeks, 0 blockers, commands ≤ 40 "
                      "(greenfield) or ≤ 45 (brownfield), and — brownfield — the coverage "
                      "reported and ≥ 0.8.", text)


if __name__ == "__main__":
    unittest.main()
