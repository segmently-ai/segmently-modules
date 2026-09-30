"""`.github/workflows/ci.yml` (P6 D8), read as text: what runs on every push (a pull request's
branch included) — and what never does: a model call, a secret, the private guard, a schedule."""
import re
import unittest
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
WORKFLOWS = ENGINE / ".github/workflows"
CLAUDE_COMMANDS = ("plugin validate --strict ", "plugin marketplace add ", "plugin install ",
                   "plugin list --json")


class CiWorkflowTest(unittest.TestCase):  # P6-AC-020
    def setUp(self):
        self.text = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
        self.lines = [l.strip() for l in self.text.splitlines()]

    def test_the_only_workflow_and_its_triggers(self):
        self.assertEqual(sorted(p.name for p in WORKFLOWS.iterdir()), ["ci.yml"])
        on = self.text.split("\non:\n", 1)[1].split("\n\n", 1)[0]
        self.assertEqual(on.split(), ["push:"])  # every branch: a pull request's pushes too
        for word in ("schedule", "cron", "workflow_run", "workflow_dispatch", "branches"):
            self.assertNotIn(word, self.text)
        self.assertIn("\npermissions:\n  contents: read\n", self.text)
        self.assertEqual(self.text.count("permissions:"), 1)
        self.assertEqual(re.findall(r"^\s+(\w[\w-]*): (?:read|write)$", self.text, re.M),
                         ["contents"])

    def test_the_matrix_and_the_steps(self):
        self.assertIn('python: ["3.11", "3.14"]', self.lines)
        self.assertIn("runs-on: ubuntu-latest", self.lines)
        for command in ("run: python -m unittest discover -s tests",
                        "run: python evals/adoption/run_eval.py > /dev/null",
                        'python tools/build_plugins.py --out "$RUNNER_TEMP/build-a"',
                        'python tools/build_plugins.py --out "$RUNNER_TEMP/build-b"',
                        'diff -r "$RUNNER_TEMP/build-a" "$RUNNER_TEMP/build-b"',
                        "dash -n tools/launcher.sh", "python -m unittest tests.test_launcher"):
            self.assertIn(command, self.lines)

    def test_no_secret_no_model_call_no_guard(self):
        for bad in ("secrets.", "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "GH_TOKEN",
                    "GITHUB_TOKEN", "claude -p", "claude --print", "plugin eval",
                    "evals/skills/run.py", "--dangerously"):
            self.assertNotIn(bad, self.text)
        self.assertNotIn("GUARD", self.text.upper())  # the guard is private: never in CI

    def test_claude_runs_without_credentials_and_only_plugin_commands(self):
        self.assertIn("run: npm install -g @anthropic-ai/claude-code", self.lines)
        self.assertIn("CLAUDE_CONFIG_DIR: ${{ runner.temp }}/claude-config", self.lines)
        calls = [l[len("claude "):] for l in self.lines if l.startswith("claude ")]
        self.assertEqual(len(calls), 6)
        for call in calls:
            self.assertTrue(call.startswith(CLAUDE_COMMANDS), call)
        self.assertIn('python tools/publish.py --channel dev --out "$RUNNER_TEMP/publish"',
                      self.lines)


if __name__ == "__main__":
    unittest.main()
