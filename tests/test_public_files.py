"""The public repository's own files: the MIT LICENSE with its holder, CONTRIBUTING.md and
SECURITY.md, and one release pin for every install line of the README (the stable release
commit moves them together)."""
import re
import unittest
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
PIN = re.compile(r"segmently-modules\.git@v(\d+\.\d+\.\d+)")


class PublicFilesTest(unittest.TestCase):
    def test_the_license(self):
        text = (ENGINE / "LICENSE").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("MIT License\n\nCopyright (c) 2026 Segmently\n"), text[:80])
        self.assertIn('THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND', text)

    def test_contributing_and_security(self):
        contributing = (ENGINE / "CONTRIBUTING.md").read_text(encoding="utf-8")
        for needle in ("python3 -m unittest discover -s tests -t .", "## [Unreleased]",
                       "docs/cli-contract.md", "MIT License"):
            self.assertIn(needle, contributing)
        security = (ENGINE / "SECURITY.md").read_text(encoding="utf-8")
        for needle in ("Report a vulnerability", "never in a public issue",
                       "SEGMENTLY_MODULES_AGENT_ALLOW_REPO_MODE=1", "[[hooks.post_sync]]"):
            self.assertIn(needle, security)

    def test_one_release_pin_in_the_readme(self):
        pins = PIN.findall((ENGINE / "README.md").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(pins), 5)
        self.assertEqual(len(set(pins)), 1, pins)
        self.assertNotIn("<owner>", (ENGINE / "README.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
