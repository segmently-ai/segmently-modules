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


if __name__ == "__main__":
    unittest.main()
