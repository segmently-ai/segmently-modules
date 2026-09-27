"""D8: the docs describe the built-in packs — `docs/skills.md` (new), the README "Core skills"
section and reference list, `writing-a-pack.md` (built-in packs, reserved ids), the
configuration reference and the `init` starter that enables `core`."""
import tomllib
import unittest
from pathlib import Path

from modsys.init_cmd import starter_config
from tests.test_builtin_content import PACKS

ENGINE = Path(__file__).resolve().parents[1]


def flat(rel: str) -> str:
    return " ".join((ENGINE / rel).read_text(encoding="utf-8").split())


class SkillDocsTest(unittest.TestCase):  # P4B-AC-023
    def test_skills_md_covers_every_item(self):
        text = flat("docs/skills.md")
        for sid in (s for ids in PACKS.values() for s in ids):
            self.assertIn(f"`{sid}`", text)
        for needle in ("## Enable them", "builtin = [\"core\", \"ui\", \"qa\"]",
                       "modsys packs sync --agent claude --agent codex", "## The core skills",
                       "## The ui and qa packs", "## Keeping them current",
                       "## Owning one skill: eject", "modsys eject module-sync",
                       "## Owning a whole pack: copy it", ".modsys/packs/ui",
                       "modsys sync-instructions", "reserved"):
            self.assertIn(needle, text)

    def test_writing_a_pack_covers_builtin_packs_and_reserved_ids(self):
        text = flat("docs/writing-a-pack.md")
        section = text.split("## Built-in packs and reserved ids", 1)[1].split(" ## ", 1)[0]
        for needle in ("[packs] builtin", "`core`, `qa` and `ui` are reserved",
                       "pack id 'ui' is reserved for the engine's built-in pack — enable it: "
                       "[packs] builtin = [\"ui\"]", "replaces the built-in pack", "(skills.md)"):
            self.assertIn(needle, section)

    def test_the_readme_section_and_reference(self):
        readme = (ENGINE / "README.md").read_text(encoding="utf-8")
        section = readme.split("## Core skills", 1)[1].split("\n## ", 1)[0]
        for sid in PACKS["core"]:
            self.assertIn(f"- `{sid}` — ", section)
        self.assertIn("(docs/skills.md)", section)
        reference = readme.split("## Reference", 1)[1]
        self.assertIn("[docs/skills.md](docs/skills.md)", reference)

    def test_the_configuration_reference(self):
        text = flat("docs/configuration.md")
        self.assertIn("| `builtin` | `[]` |", text)
        self.assertIn("**built-in packs**", text)
        self.assertIn("`modsys sync-instructions` lists it", text)

    def test_the_init_starter_enables_core(self):
        for layout in ("single", "per-module"):
            text = starter_config(layout)
            self.assertEqual(tomllib.loads(text)["packs"], {"builtin": ["core"]})
            self.assertIn('builtin = ["core"]                   # or ["core", "ui", "qa"]', text)


if __name__ == "__main__":
    unittest.main()
