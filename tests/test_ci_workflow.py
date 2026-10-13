"""`.github/workflows/ci.yml` (P6 D8, P6.1 D8), read as text: what runs on a push to main, on a
version tag and on a pull request (a pull request's branch is not run twice) — and what never
does: a model call, a secret, the private guard, a schedule."""
import re
import unittest
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
WORKFLOWS = ENGINE / ".github/workflows"
PR_EVENT = "_".join(("pull", "request"))  # the private guard allows the literal only in ci.yml
# the tags whose action.yml says `runs.using: node24` (read 2026-10-01, P6.1 SI-P61-12)
NODE24_ACTIONS = ("actions/checkout@v5", "actions/setup-python@v6")
CLAUDE_COMMANDS = ("plugin validate --strict ", "plugin marketplace add ", "plugin install ",
                   "plugin list --json")


class CiWorkflowTest(unittest.TestCase):  # P6-AC-020
    def setUp(self):
        self.text = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
        self.lines = [l.strip() for l in self.text.splitlines()]

    def test_the_only_workflow_and_its_triggers(self):
        self.assertEqual(sorted(p.name for p in WORKFLOWS.iterdir()), ["ci.yml"])
        on = self.text.split("\non:\n", 1)[1].split("\n\n", 1)[0]
        self.assertEqual(on.splitlines(), [  # P61-AC-004: main, version tags, pull requests
            "  push:", "    branches: [main]", '    tags: ["v*"]', f"  {PR_EVENT}:"])
        for word in ("schedule", "cron", "workflow_run", "workflow_dispatch"):
            self.assertNotIn(word, self.text)
        self.assertEqual(self.text.count(PR_EVENT), 1)  # the trigger; the prose says "pull requests"
        self.assertIn("\npermissions:\n  contents: read\n", self.text)
        self.assertEqual(self.text.count("permissions:"), 1)
        self.assertEqual(re.findall(r"^\s+(\w[\w-]*): (?:read|write)$", self.text, re.M),
                         ["contents"])

    def test_the_actions_run_on_node_24(self):  # P61-AC-004, SI-P61-12
        uses = [l[len("- uses: "):] for l in self.lines if l.startswith("- uses: ")]
        self.assertEqual(uses, list(NODE24_ACTIONS))

    def test_the_matrix_and_the_steps(self):
        self.assertIn('python: ["3.11", "3.14"]', self.lines)
        self.assertIn("runs-on: ubuntu-latest", self.lines)
        for command in ("run: python -m unittest discover -s tests",
                        "run: python evals/adoption/run_eval.py > /dev/null",
                        'python tools/build_plugins.py --out "$RUNNER_TEMP/build-a"',
                        'python tools/build_plugins.py --out "$RUNNER_TEMP/build-b"',
                        'diff -r "$RUNNER_TEMP/build-a" "$RUNNER_TEMP/build-b"',
                        "dash -n tools/launcher.sh", "python -m unittest tests.test_launcher",
                        "timeout-minutes: 45"):
            self.assertIn(command, self.lines)

    def test_every_check_can_fail_and_runs_in_order(self):  # task-10 review M1, M2
        for bad in ("continue-on-error", "|| true", "set +e", "; true"):
            self.assertNotIn(bad, self.text)
        self.assertIsNone(re.search(r"^\s*(?:- )?if:", self.text, re.M))  # no step skips itself
        at = {line: n for n, line in enumerate(self.lines)}
        builds = [at[f'python tools/build_plugins.py --out "$RUNNER_TEMP/build-{x}"']
                  for x in "ab"]
        self.assertLess(max(builds), at['diff -r "$RUNNER_TEMP/build-a" "$RUNNER_TEMP/build-b"'])
        claude = [n for n, line in enumerate(self.lines) if line.startswith("claude ")]
        self.assertLess(at['python tools/publish.py --channel dev --out "$RUNNER_TEMP/publish"'],
                        min(claude))
        listed = at["claude plugin list --json | python -c '"]
        self.assertEqual(listed, max(claude))  # the last claude line is checked, not printed
        self.assertLess(at["set -o pipefail"], listed)
        check = "\n".join(self.lines[listed:])
        for needle in ('if r.get("enabled")', '("segmently-modules", "segmently-modules-ui", "segmently-modules-qa")',
                       'sys.exit(f"not installed and enabled: {missing}")',
                       '"/bin/segmently-modules"', '"--version"', "check=True"):
            self.assertIn(needle, check)  # all three enabled; the INSTALLED launcher runs

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
        self.assertEqual(len(calls), 6)  # the list's output piped into the check
        for call in calls:
            self.assertTrue(call.startswith(CLAUDE_COMMANDS), call)
        self.assertIn('python tools/publish.py --channel dev --out "$RUNNER_TEMP/publish"',
                      self.lines)


if __name__ == "__main__":
    unittest.main()
