"""P6 docs: each task's user-facing docs say what its code does — `builtin_delivery` (D2)."""
import unittest
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]


def flat(rel: str) -> str:
    return " ".join((ENGINE / rel).read_text(encoding="utf-8").split())


class DeliveryDocsTest(unittest.TestCase):  # P6-AC-025 (the D2 part)
    def test_configuration_skills_and_the_contract(self):
        config = flat("docs/configuration.md")
        for needle in ('| `builtin_delivery` | `"repo"` |',
                       "`core` → `modsys`, `ui` → `modsys-ui`, `qa` → `modsys-qa`",
                       "a pack cannot set it", "the user's wins", "`repo, plugin`",
                       "| MS067 | info |"):
            self.assertIn(needle, config)
        skills = flat("docs/skills.md")
        for needle in ("## From the repository or from a plugin", 'builtin_delivery = "plugin"',
                       'installing the plugin in a repository that keeps `"repo"` delivery gives '
                       "the agent each built-in skill twice", "MS067"):
            self.assertIn(needle, skills)
        contract = flat("docs/cli-contract.md")
        for needle in ("`notes` = the `note:` lines the text prints after the rows",
                       'eject needs "repo"'):
            self.assertIn(needle, contract)


class AgentsDocsTest(unittest.TestCase):  # P6-AC-025 (the D5 part)
    def test_the_five_agents_and_remove(self):
        config = flat("docs/configuration.md")
        self.assertIn("`claude` (`.claude/skills/`), `codex`, `cursor`, `gemini`, `copilot` (all "
                      "four read `.agents/skills/`", config)
        contract = flat("docs/cli-contract.md")
        for needle in ("sync `[--agent claude\\|codex\\|cursor\\|gemini\\|copilot]… [--check] "
                       "[--dry-run] [--remove]`", "`--remove` (needs `--agent`; with `--check` "
                       "exit 2", "GitHub Copilot sees each skill twice",
                       "a marker in `.agents/skills` means codex"):
            self.assertIn(needle, contract)
        skills = flat("docs/skills.md")
        for needle in ("## Other agents", "`modsys packs sync --agent cursor --remove`",
                       "Cursor, Gemini CLI and GitHub Copilot have no modsys plugin"):
            self.assertIn(needle, skills)


if __name__ == "__main__":
    unittest.main()
