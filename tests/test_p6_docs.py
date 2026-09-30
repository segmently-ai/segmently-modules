"""P6 docs: each task's user-facing docs say what its code does."""
import re
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


class ReleasingDocsTest(unittest.TestCase):  # P6-AC-025 (docs/releasing.md: D1, D3, D4, D7, D9)
    def test_the_maintainer_doc(self):
        text = flat("docs/releasing.md")
        for needle in ("python3 tools/build_plugins.py", "python3 tools/publish.py --channel dev",
                       "python3 tools/release.py", "--publish-slug <owner>/<publish repo>",
                       "| `stable` | `stable` | `modsys` | `X.Y.Z` |",
                       "| `dev` | `dev` | `modsys-dev` | `X.Y.Z-dev.h<8 hex>` |",
                       "`<plugin>--v<version>`", "`MODSYS_GUARD` names the private leak guard",
                       "The organisation of `--publish-slug` must appear nowhere",
                       "a throw-away `CLAUDE_CONFIG_DIR`", "no model call", "All or nothing",
                       "an owner command, each time", "Creating the publish repository on GitHub "
                       "is the owner's as well", "`MODSYS_PYTHON`",
                       "## Before a stable release: the skill evals",
                       "should-trigger at least 0.8 and false-trigger at most 0.1",
                       "never in a pipeline"):
            self.assertIn(needle, text)
        evals = flat("evals/skills/README.md")  # D9: the plugin-eval suite is run by hand
        self.assertIn("It is not a release gate and never runs in CI", evals)
        self.assertNotIn("the gate", evals)
        self.assertIn("that suite is run by hand, never by the unit suite or CI",
                      flat("docs/skills.md"))


class InstallFromGitDocsTest(unittest.TestCase):  # P6-AC-025 (the D6 part), P6-AC-021
    def test_the_readme_lines_use_placeholders(self):
        readme = (ENGINE / "README.md").read_text(encoding="utf-8")
        for needle in ("uv tool install git+ssh://git@github.com/<owner>/<repo>.git",
                       "uvx --from git+ssh://git@github.com/<owner>/<repo>.git modsys --version",
                       "pipx install git+ssh://git@github.com/<owner>/<repo>.git",
                       "Add `@v<version>` to the URL"):
            self.assertIn(needle, readme)


class CiDocsTest(unittest.TestCase):  # P6-AC-025 (the D8 part, SI-2)
    def test_releasing_says_what_ci_runs(self):
        text = flat("docs/releasing.md")
        for needle in ("## CI", "`.github/workflows/ci.yml` runs on every push to any branch",
                       "on Python 3.11 and 3.14", "without credentials", "It makes no model call "
                       "and reads no secret; nothing runs on a schedule",
                       "The private guard is not part of CI",
                       "The release repeats the validation and runs the full smoke install"):
            self.assertIn(needle, text)


class InstallDocsTest(unittest.TestCase):  # P6-AC-025 (D10), P6-AC-021 (D13)
    def test_the_five_routes(self):
        readme = flat("README.md")
        for needle in ("claude plugin marketplace add <owner>/<publish repo>#stable",
                       "claude plugin install modsys@modsys",
                       "codex plugin marketplace add <owner>/<publish repo> --ref stable",
                       "codex plugin add modsys@modsys",
                       "uv tool install git+ssh://git@github.com/<owner>/<repo>.git",
                       "modsys packs sync --agent cursor", "--agent gemini, --agent copilot",
                       "uvx --from git+ssh://git@github.com/<owner>/<repo>.git modsys --version",
                       "pipx install git+ssh://git@github.com/<owner>/<repo>.git",
                       "`#dev` instead of `#stable`, `--ref dev`, and the marketplace "
                       "`modsys-dev`", '`builtin_delivery = "plugin"`',
                       "[docs/releasing.md](docs/releasing.md)"):
            self.assertIn(needle, readme)

    def test_every_repository_url_is_a_placeholder(self):
        docs = [ENGINE / "README.md", *sorted((ENGINE / "docs").glob("*.md"))]
        self.assertIn(ENGINE / "docs/releasing.md", docs)
        seen = 0
        for doc in docs:
            for url in re.findall(r"github\.com[:/]\S*", doc.read_text(encoding="utf-8")):
                with self.subTest(doc=doc.name, url=url):
                    self.assertTrue(url[len("github.com") + 1:].startswith("<owner>/"), url)
                seen += 1
        self.assertGreaterEqual(seen, 6)


if __name__ == "__main__":
    unittest.main()
