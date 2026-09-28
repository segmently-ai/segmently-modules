"""D10: the docs, the contract and the golden verb list describe the whole P4a surface — 24
verbs, packs, eject, templates and the managed block."""
import re
import unittest
from pathlib import Path

from modsys.cli import build_parser
from tests.test_cli_contract import GOLDEN

ENGINE = Path(__file__).resolve().parents[1]
NEW_VERBS = {"packs", "eject", "templates", "agents-md"}


def doc(rel: str) -> str:
    return " ".join((ENGINE / rel).read_text(encoding="utf-8").split())


class PackDocsTest(unittest.TestCase):  # P4A-AC-022
    def test_twenty_four_verbs_everywhere(self):
        parser = set(build_parser()._subparsers._group_actions[0].choices)
        contract = set(re.findall(r"^\| `([a-z-]+)",
                                  (ENGINE / "docs/cli-contract.md").read_text(encoding="utf-8"),
                                  re.M))
        golden = {argv[0] for argv, _ in GOLDEN}
        self.assertEqual((parser, golden), (contract, contract))  # the count: 25 (P4b)
        self.assertTrue(NEW_VERBS <= parser)

    def test_the_contract(self):
        contract = doc("docs/cli-contract.md")
        for needle in ("| `packs new\\|list\\|sync` |", "| `eject SKILL` |",
                       "| `templates list\\|override` |", "| `agents-md --target FILE…` |",
                       "{pack, dir, files: [path], dry_run}",
                       "skills: [{id, path, reads_roles, description, ejected}]",
                       "skills: [{agent, skill, pack, version, source, dir, status, files, "
                       "reason, same_as?}]", "summary: {created, updated, unchanged, removed, "
                                             "conflict, invalid}, failed}",
                       "{skill, pack, version, dir, files, dry_run}",
                       "{skill, pack, ejected_from, upstream_version, behind, files: [{path, "
                       "status}], diff, reason}",  # P5a D0d: + reason
                       "{template, role, source, path}",
                       "{template, file, from, dry_run}", "{targets: [{path, status, same_as?}], "
                                                          "check, dry_run}",
                       "/.modsys-managed", ".modsys-ejected", "<config_dir>/overrides/templates/",
                       "<config_dir>/overrides/skills/"):
            self.assertIn(needle, contract)

    def test_the_configuration_reference(self):
        config = doc("docs/configuration.md")
        for needle in ("## `[packs]`", "| `agents` |", "`[skills.<id>]` tables", "`reads_roles`",
                       "`roles/developer.md`, `roles/qa.md`, `roles/po.md`, `roles/architect.md`",
                       "`agents-md.md`", "modsys templates list", "writing-a-pack.md"):
            self.assertIn(needle, config)
        rows = dict(re.findall(r"^\| (MS06\d) \| [^|]+ \| (.*) \|$",
                               (ENGINE / "docs/configuration.md").read_text(encoding="utf-8"),
                               re.M))
        self.assertEqual(sorted(rows), ["MS060", "MS061", "MS062", "MS063", "MS064", "MS065",
                                        "MS066"])  # P5a D0a (M8)
        self.assertTrue(all("(plain `lint` only)" in text for text in rows.values()), rows)

    def test_writing_a_pack_walks_through_in_order(self):
        text = (ENGINE / "docs/writing-a-pack.md").read_text(encoding="utf-8")
        steps = ["modsys packs new team --role reviewer --skill api-review",
                 "modsys create reviews", "modsys show reviews --role reviewer",
                 "modsys packs sync --agent claude --agent codex",
                 "modsys packs sync --check", "## Conflicts", "modsys eject api-review",
                 "modsys eject api-review --diff", "MS063", "modsys agents-md --target CLAUDE.md"]
        positions = [text.find(step) for step in steps]
        self.assertNotIn(-1, positions, dict(zip(steps, positions)))
        self.assertEqual(positions, sorted(positions))
        for code in ("MS060", "MS061", "MS062", "MS063", "MS064", "MS065"):
            self.assertIn(f"| {code} |", text)

    def test_the_readme_links_the_pack_guide(self):
        readme = (ENGINE / "README.md").read_text(encoding="utf-8")
        section = readme.split("## Packs and skills", 1)[1].split("\n## ", 1)[0]
        self.assertIn("(docs/writing-a-pack.md)", section)
        reference = readme.split("## Reference", 1)[1]
        self.assertIn("[docs/writing-a-pack.md](docs/writing-a-pack.md)", reference)


if __name__ == "__main__":
    unittest.main()
