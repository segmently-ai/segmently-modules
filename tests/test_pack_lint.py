"""Pack lint (D6): MS060 unknown pack.toml keys, MS061 role templates, MS062 skills agents
cannot load, MS064 unread roles, MS065 shadowed skill ids — plain `lint` and `ci` only."""
import os
import tempfile
import unittest

from segmently_modules.config import PACK_META_KEYS
from segmently_modules.lint import PACK_SECTIONS
from tests.helpers import copy_fixture, init_git, run, run_json

SKILL = "---\nname: api-review\ndescription: Reviews API changes.\n---\n"
ROLE = ('[roles.reviewer]\norder = 100\ndescription = "Reviews"\n'
        'template = "roles/reviewer.md"\n')
SKILLS = '[skills.api-review]\npath = "skills/api-review"\nreads_roles = ["reviewer"]\n'


class PackLintRepo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        self.R = ("--root", str(self.root))
        self.team = self.root / ".segmently-modules/packs/team"

    def tearDown(self):
        self._tmp.cleanup()

    def pack(self, body: str, pack_id: str = "team", priority: int = 50, files=None) -> None:
        d = self.root / ".segmently-modules/packs" / pack_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "pack.toml").write_text(f'id = "{pack_id}"\nversion = "0.1.0"\n'
                                     f'priority = {priority}\n{body}', encoding="utf-8")
        default = {"roles/reviewer.md": "# ${title}\n", "skills/api-review/SKILL.md": SKILL}
        for rel, text in (default if files is None else files).items():
            (d / rel).parent.mkdir(parents=True, exist_ok=True)
            (d / rel).write_text(text, encoding="utf-8")

    def findings(self, *argv, prefix="MS06") -> list[tuple]:
        code, env, err = run_json("lint", "--fail-on", "never", *argv, *self.R)
        self.assertEqual((code, err), (0, ""))
        return [(f["code"], f["severity"], f["module"], f["message"], f["path"])
                for f in env["data"]["findings"] if f["code"].startswith(prefix)]


class PackKeysAndTemplatesTest(PackLintRepo):  # P4A-AC-012
    def test_unknown_keys(self):
        toml = ".segmently-modules/packs/team/pack.toml"
        self.pack('colour = "x"\n[role.designer]\norder = 1\n' + ROLE
                  + "standrad = true\nbudget = 200\nconsumed_by = []\n" + SKILLS + "reads = []\n")
        self.assertEqual(self.findings(), [
            ("MS060", "warning", "*", "pack 'team': unknown key 'colour' at the top level", toml),
            ("MS060", "warning", "*", "pack 'team': unknown key 'role' at the top level", toml),
            ("MS060", "warning", "*", "pack 'team': unknown key 'standrad' in [roles.reviewer]",
             toml),
            ("MS060", "warning", "*", "pack 'team': unknown key 'budget' in [roles.reviewer]",
             toml),
            ("MS060", "warning", "*", "pack 'team': unknown key 'consumed_by' in "
                                      "[roles.reviewer]", toml),
            ("MS060", "warning", "*", "pack 'team': unknown key 'reads' in [skills.api-review]",
             toml)])

    def test_every_known_key_passes(self):
        self.assertTrue(PACK_META_KEYS <= {"id", "version", "priority", "requires",
                                           "description", "skills", "agents"})
        sections = "".join(f"[{s}]\n" for s in PACK_SECTIONS
                           if s not in ("code_map", "schema_version"))
        self.pack('requires = ">=0.1"\ndescription = "d"\nagents = []\nschema_version = 1\n'
                  'code_map = []\n' + sections.replace("[roles]\n", "") + ROLE
                  + 'enabled = true\nstandard = false\napplies_when = "ui"\n' + SKILLS)
        self.assertEqual(self.findings(), [])

    def test_role_templates(self):
        (self.root / ".segmently-modules/outside.md").write_text("# outside\n")
        self.pack('[roles.reviewer]\ntemplate = "roles/missing.md"\n'
                  '[roles.auditor]\ntemplate = "../../outside.md"\n', files={})
        self.assertEqual(self.findings(), [
            ("MS061", "error", "*", "pack 'team': role 'reviewer' template 'roles/missing.md' "
                                    "does not exist", ".segmently-modules/packs/team/roles/missing.md"),
            ("MS061", "error", "*", "pack 'team': role 'auditor' template '../../outside.md' "
                                    "is outside the pack", ".segmently-modules/packs/team/pack.toml")])

    def test_roles_a_skill_reads(self):
        self.pack(ROLE + SKILLS.replace('["reviewer"]', '["reviewer", "nosuch"]'))
        self.assertEqual(self.findings(), [
            ("MS064", "warning", "*", "skill 'api-review' of pack 'team' reads role 'nosuch', "
                                      "which no layer configures", ".segmently-modules/packs/team/pack.toml")])
        (self.root / ".segmently-modules/config.toml").write_text("[roles.reviewer]\nenabled = false\n")
        self.assertEqual([f[3] for f in self.findings()], [
            "skill 'api-review' of pack 'team' reads role 'reviewer', which is disabled",
            "skill 'api-review' of pack 'team' reads role 'nosuch', which no layer configures"])

    def test_a_shadowed_skill_id(self):  # P4A-AC-007 (last row)
        self.pack(SKILLS.replace('["reviewer"]', "[]"), "a", priority=10)
        self.pack(SKILLS.replace('["reviewer"]', "[]"), "b", priority=50)
        self.assertEqual(self.findings(), [
            ("MS065", "warning", "*", "skill 'api-review' of pack 'b' is shadowed by pack 'a' "
                                      "(higher precedence); rename one",
             ".segmently-modules/packs/b/pack.toml")])

    def test_where_the_findings_show_and_what_fails(self):
        self.pack('colour = "x"\n' + SKILLS.replace('["reviewer"]', '["nosuch"]'))
        init_git(self.root)
        self.assertEqual(run("lint", "--fail-on", "error", *self.R)[0], 0)  # warnings only
        ci = run_json("ci", "--fail-on", "never", *self.R)[1]["data"]
        self.assertEqual([f["code"] for f in ci["steps"][0]["findings"]], ["MS060", "MS064"])
        (self.team / "pack.toml").write_text((self.team / "pack.toml").read_text()
                                             + '[roles.reviewer]\ntemplate = "roles/nope.md"\n')
        self.assertEqual(run("lint", "--fail-on", "error", *self.R)[0], 1)  # MS061
        (self.root / "modules/catalog/MODULE.md").write_text("# Catalog\n\nChanged.\n")
        self.assertEqual(self.findings("--changed", "--base", "HEAD"), [])


class SkillLoadableTest(PackLintRepo):  # P4A-AC-013
    def ms062(self) -> list[tuple]:
        return [(f[3].split(": ", 1)[1], f[4]) for f in self.findings() if f[0] == "MS062"]

    def test_the_scaffolds_lint_clean(self):  # P4A-AC-009 "plain lint reports no MS06x"
        for argv in (("team", "--role", "reviewer", "--skill", "api-review"),
                     ("duo", "--role", "alpha", "--role", "beta", "--skill", "one", "--skill",
                      "two"), ("bare",), ("team2", "--skill", "notes")):
            self.assertEqual(run("packs", "new", *argv, *self.R)[0], 0)
        self.assertEqual(self.findings(), [])
        code, env, _ = run_json("lint", *self.R)
        self.assertEqual((code, env["data"]["summary"]), (0, {"error": 0, "warning": 0,
                                                             "info": 0}))

    def test_path_problems(self):
        toml = ".segmently-modules/packs/team/pack.toml"
        self.pack(SKILLS.replace('["reviewer"]', "[]"), files={})
        self.assertEqual(self.ms062(), [("the path does not exist", toml)])
        (self.team / "skills").mkdir()
        (self.team / "skills/api-review").write_text("a file\n")
        self.assertEqual(self.ms062(), [("the path is not a directory", toml)])
        (self.root / ".segmently-modules/packs/other/skills/api-review").mkdir(parents=True)
        self.pack('[skills.api-review]\npath = "../other/skills/api-review"\n', files={})
        self.assertEqual(self.ms062(), [("the path is outside the pack directory", toml)])

    def test_a_symlink_anywhere_in_the_skill(self):
        self.pack(SKILLS.replace('["reviewer"]', "[]"))
        (self.team / "skills/api-review/references").mkdir()
        os.symlink("../SKILL.md", self.team / "skills/api-review/references/link.md")
        self.assertEqual(self.ms062(), [("symlink in source: references/link.md",
                                         ".segmently-modules/packs/team/skills/api-review")])

    def test_skill_md_problems(self):
        self.pack(SKILLS.replace('["reviewer"]', "[]"), files={"skills/api-review/x.md": "x\n"})
        self.assertEqual(self.ms062(), [("no SKILL.md", ".segmently-modules/packs/team/skills/api-review")])
        md = self.team / "skills/api-review/SKILL.md"
        for text, reason in [
                ("# no front matter\n", "SKILL.md has no front matter (a --- block at the top, "
                                        "closed by a --- line)"),
                ("---\ndescription: d\n---\n", "SKILL.md front matter has no name"),
                ("---\nname: other-name\ndescription: d\n---\n",
                 "SKILL.md name 'other-name' is not the skill id 'api-review'"),
                ("---\nname: api-review\ndescription: \n---\n",
                 "SKILL.md front matter has no description"),
                (f"---\nname: api-review\ndescription: {'d' * 1025}\n---\n",
                 "SKILL.md description has 1025 characters (max 1024)")]:
            with self.subTest(reason=reason):
                md.write_text(text, encoding="utf-8")
                self.assertEqual(self.ms062(), [(reason, ".segmently-modules/packs/team/skills/api-review/"
                                                         "SKILL.md")])
        md.write_text(SKILL, encoding="utf-8")
        self.assertEqual(self.ms062(), [])

    def test_a_description_strict_yaml_loaders_reject(self):  # fix wave F5
        self.pack(SKILLS.replace('["reviewer"]', "[]"))
        md = self.team / "skills/api-review/SKILL.md"
        colon = ("SKILL.md description: quote the value — a plain YAML value cannot contain ': ' "
                 "(agents' YAML loaders reject it)")
        md.write_text("---\nname: api-review\ndescription: Use when: the API changes\n---\n")
        self.assertEqual(self.ms062(), [(colon, ".segmently-modules/packs/team/skills/api-review/SKILL.md")])
        code, env, _ = run_json("packs", "sync", "--agent", "claude", *self.R)
        self.assertEqual((code, env["data"]["skills"][0]["status"],
                          env["data"]["skills"][0]["reason"]), (1, "invalid", colon))
        code, out, err = run("eject", "api-review", "--json", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn(f"skill 'api-review' of pack 'team' is not loadable: {colon} (lint MS062); "
                      f"nothing written", err)
        for text in ('description: "Use when: the API changes"\n',
                     "description: >\n  Use when: the API changes\n"):
            with self.subTest(text=text):
                md.write_text("---\nname: api-review\n" + text + "---\n")
                self.assertEqual(self.ms062(), [])
        md.write_text("---\nname: api-review\ndescription: @team reviews API changes\n---\n")
        self.assertEqual(self.ms062(), [(
            "SKILL.md description: quote the value — a plain YAML value cannot start with '@' "
            "(agents' YAML loaders reject it)", ".segmently-modules/packs/team/skills/api-review/SKILL.md")])


if __name__ == "__main__":
    unittest.main()
