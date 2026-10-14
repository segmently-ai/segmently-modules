"""D8: the docs describe the built-in packs — `docs/skills.md` (new), the README "Core skills"
section and reference list, `writing-a-pack.md` (built-in packs, reserved ids), the
configuration reference and the `init` starter that enables `core`."""
import unittest
from pathlib import Path

from segmently_modules._toml import tomllib
from segmently_modules.init_cmd import starter_config
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
                       "segmently-modules packs sync --agent claude --agent codex", "## The core skills",
                       "## The ui and qa packs", "## Keeping them current",
                       "## Owning one skill: eject", "segmently-modules eject module-sync",
                       "## Owning a whole pack: copy it", ".segmently-modules/packs/ui",
                       "segmently-modules sync-instructions", "reserved"):
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
        self.assertIn("`segmently-modules sync-instructions` lists it", text)

    def test_the_config_file_is_optional(self):  # fix wave G9
        layers = flat("docs/configuration.md").split("## Layers", 1)[1].split(" ## ", 1)[0]
        self.assertIn("Every file layer is optional", layers)
        self.assertIn("with no `.segmently-modules/config.toml` on disk", layers)

    def test_an_engine_upgrade_and_the_copies(self):  # fix wave M2
        text = flat("docs/skills.md")
        current = text.split("## Keeping them current", 1)[1].split(" ## ", 1)[0]
        self.assertNotIn("not the version", current)
        for needle in ("managed marker records the version", "`updated`",
                       "`packs sync --check`", "stale"):
            self.assertIn(needle, current)

    def test_what_clears_ms063(self):  # fix wave I-3 (c)
        eject = flat("docs/skills.md").split("## Owning one skill: eject", 1)[1].split(" ## ")[0]
        pack = flat("docs/writing-a-pack.md").split("## Owning a skill: eject", 1)[1].split(
            " ## ")[0]
        ref = next(line for line in (ENGINE / "segmently_modules/defaults/packs/core/skills/module-lint/"
                                              "references/lint-codes.md").read_text(
            encoding="utf-8").splitlines() if line.startswith("| MS063 |"))
        for name, text in (("skills.md", eject), ("writing-a-pack.md", pack),
                           ("lint-codes.md", ref)):
            with self.subTest(doc=name):  # P5a D1: review, take by hand, then --rebase
                self.assertIn("--diff", text)
                self.assertIn("by hand", text)
                self.assertIn("--rebase", text)
                self.assertIn("delete the copy", text)
                self.assertNotIn("does not clear it", text)
                self.assertNotIn("eject again and re-apply", text)
        self.assertIn("an engine upgrade alone", eject)

    def test_the_init_starter_enables_core(self):
        for layout in ("single", "per-module"):
            text = starter_config(layout)
            self.assertEqual(tomllib.loads(text)["packs"], {"builtin": ["core"]})
            self.assertIn('builtin = ["core"]                   # or ["core", "ui", "qa"]', text)


if __name__ == "__main__":
    unittest.main()
