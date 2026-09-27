"""`modsys packs new|list` (D4, D5): the scaffold of a working pack, its names and refusals,
and the list of installed packs."""
import builtins
import shutil
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from modsys.skills import front_matter, source_problem
from tests.helpers import copy_fixture, make_repo, run, run_json

DESC = ["--description", "Customer reviews of books: ratings, comments and moderation."]
KW = ["--keywords", "review, rating, stars, comment, moderation"]
TEAM = ("packs", "new", "team", "--role", "reviewer", "--skill", "api-review",
        "--description", "Team review conventions")


class PacksRepo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def ok(self, *argv) -> dict:
        code, env, err = run_json(*argv, *self.R)
        self.assertEqual((code, err, env["schema"]), (0, "", f"modsys.{argv[0]}/1"))
        return env["data"]

    def pack_toml(self, pack_id: str) -> dict:
        return tomllib.loads((self.root / f".modsys/packs/{pack_id}/pack.toml")
                             .read_text(encoding="utf-8"))

    def skill_md(self, pack_id: str, skill: str) -> str:
        return (self.root / f".modsys/packs/{pack_id}/skills/{skill}/SKILL.md").read_text(
            encoding="utf-8")


class PacksNewTest(PacksRepo):  # P4A-AC-009
    def test_one_role_and_one_skill(self):
        data = self.ok(*TEAM)
        self.assertEqual(data, {"pack": "team", "dir": ".modsys/packs/team", "dry_run": False,
                                "files": [".modsys/packs/team/pack.toml",
                                          ".modsys/packs/team/roles/reviewer.md",
                                          ".modsys/packs/team/skills/api-review/SKILL.md"]})
        self.assertEqual(sorted(p.relative_to(self.root / ".modsys/packs/team").as_posix()
                                for p in (self.root / ".modsys/packs/team").rglob("*")
                                if p.is_file()),
                         ["pack.toml", "roles/reviewer.md", "skills/api-review/SKILL.md"])
        self.assertEqual(self.pack_toml("team"), {
            "id": "team", "version": "0.1.0", "priority": 50,
            "description": "Team review conventions",
            "roles": {"reviewer": {"order": 100, "standard": False,
                                   "description": "What a reviewer needs to know about a module",
                                   "template": "roles/reviewer.md"}},
            "skills": {"api-review": {"path": "skills/api-review", "reads_roles": ["reviewer"]}}})
        text = self.skill_md("team", "api-review")
        meta = front_matter(text)
        self.assertEqual(meta["name"], "api-review")
        self.assertTrue(0 < len(meta["description"]) <= 1024)
        self.assertIn('modsys context --task "<the task in one sentence>" --role reviewer --json',
                      text)
        self.assertIn("modsys show <module> --role reviewer", text)
        self.assertIsNone(source_problem(self.root / ".modsys/packs/team/skills/api-review",
                                         "api-review", self.root / ".modsys/packs/team"))
        lint = self.ok("lint")
        self.assertEqual((lint["summary"], [f for f in lint["findings"]
                                            if f["code"].startswith("MS06")]),
                         ({"error": 0, "warning": 0, "info": 0}, []))

    def test_a_hostile_description_cannot_inject_toml(self):  # Review Focus
        text = 'Team "review" rules \\ é\n[roles.injected]\nid = "x"'
        self.ok("packs", "new", "team", "--description", text)
        self.assertEqual(self.pack_toml("team"), {"id": "team", "version": "0.1.0",
                                                  "priority": 50, "description": text})
        self.assertEqual(self.ok("packs", "list")[1]["description"], text)

    def test_a_module_gets_the_pack_role(self):
        self.ok(*TEAM)
        created = self.ok("create", "reviews", *DESC, *KW, "--role", "reviewer",
                          "--non-interactive")
        self.assertIn("modules/reviews/roles/reviewer.md", created["files"])
        doc = (self.root / "modules/reviews/roles/reviewer.md").read_text(encoding="utf-8")
        self.assertTrue(doc.startswith("# Reviews — reviewer\n\n> What a reviewer needs to know "
                                       "about a module\n"))
        self.assertNotIn("${", doc)
        rows = self.ok("show", "reviews", "--all-roles")["read"]
        self.assertIn({"label": "role:reviewer", "path": "modules/reviews/roles/reviewer.md",
                       "exists": True}, rows)
        shown = self.ok("show", "reviews", "--role", "reviewer")["read"]
        self.assertEqual([r["label"] for r in shown], ["universal", "role:reviewer"])
        rows = {r["template"]: r for r in self.ok("templates", "list")}
        self.assertEqual((rows["roles/reviewer.md"]["source"], rows["roles/reviewer.md"]["path"]),
                         ("role-template:team", ".modsys/packs/team/roles/reviewer.md"))

    def test_two_roles_and_two_skills(self):
        self.ok("packs", "new", "duo", "--role", "alpha", "--role", "beta", "--skill", "one",
                "--skill", "two")
        data = self.pack_toml("duo")
        self.assertEqual([data["roles"][r]["order"] for r in ("alpha", "beta")], [100, 110])
        self.assertEqual({s: v["reads_roles"] for s, v in data["skills"].items()},
                         {"one": ["alpha", "beta"], "two": ["alpha", "beta"]})
        text = self.skill_md("duo", "two")
        for role in ("alpha", "beta"):
            self.assertIn(f"modsys show <module> --role {role}", text)
        self.assertIn("Read each module's alpha and beta docs:", text)

    def test_a_bare_pack(self):
        data = self.ok("packs", "new", "bare")
        self.assertEqual(data["files"], [".modsys/packs/bare/pack.toml"])
        text = (self.root / ".modsys/packs/bare/pack.toml").read_text(encoding="utf-8")
        self.assertIn("# [roles.NAME]", text)
        self.assertIn("# [skills.NAME]", text)
        self.assertEqual(set(self.pack_toml("bare")), {"id", "version", "priority",
                                                        "description"})
        self.assertEqual(self.ok("lint")["summary"], {"error": 0, "warning": 0, "info": 0})
        rows = {r["id"]: r for r in self.ok("packs", "list")}
        self.assertEqual((rows["bare"]["roles"], rows["bare"]["skills"]), ([], []))

    def test_a_skill_without_a_role(self):
        self.ok("packs", "new", "team2", "--skill", "notes")
        self.assertEqual(self.pack_toml("team2")["skills"]["notes"]["reads_roles"], [])
        text = self.skill_md("team2", "notes")
        self.assertIn('modsys context --task "<the task in one sentence>" --json', text)
        self.assertIn("modsys show <module>`", text)
        self.assertNotIn("--role", text)

    def test_dry_run_writes_nothing(self):
        data = self.ok(*TEAM, "--dry-run")
        self.assertEqual((data["dry_run"], len(data["files"])), (True, 3))
        self.assertFalse((self.root / ".modsys/packs/team").exists())
        out = run(*TEAM, "--dry-run", *self.R)[1].splitlines()
        self.assertEqual(out[:3], [f"would create  {f}" for f in data["files"]])

    def test_a_root_without_a_config_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp, {"tasks": ["task"]})
            shutil.rmtree(root / ".modsys")
            code, env, err = run_json("packs", "new", "team", "--role", "reviewer",
                                      "--root", str(root))
            self.assertEqual((code, err), (0, ""))
            self.assertTrue((root / ".modsys/packs/team/roles/reviewer.md").is_file())

    def test_text_output(self):
        out = run(*TEAM, *self.R)[1].splitlines()
        self.assertEqual(out, ["created  .modsys/packs/team/pack.toml",
                               "created  .modsys/packs/team/roles/reviewer.md",
                               "created  .modsys/packs/team/skills/api-review/SKILL.md",
                               "next: modsys create NAME … --role reviewer (a module with the "
                               "reviewer doc); then modsys packs sync --agent claude --agent "
                               "codex (the skills into the agents' skill directories)"])


class PacksRefusalTest(PacksRepo):  # P4A-AC-010
    def refused(self, argv, needle, pack_id):
        code, out, err = run("packs", "new", *argv, "--json", *self.R)
        self.assertEqual((code, out), (2, ""), err)
        self.assertTrue(err.startswith("modsys: error: "), err)
        self.assertIn(needle, err)
        if pack_id != "bookshop":
            self.assertFalse((self.root / ".modsys/packs" / pack_id).exists())

    def test_pack_ids(self):
        for pack_id in ("t" * 48, "team-2"):
            with self.subTest(pack_id=pack_id):
                self.assertEqual(run("packs", "new", pack_id, "--dry-run", *self.R)[0], 0)
        for pack_id in ("t" * 49, "Team", "team_x", "2team"):
            with self.subTest(pack_id=pack_id):
                self.refused([pack_id], f"pack id {pack_id!r}: use lowercase words joined by "
                                        f"'-' (max 48)", pack_id)

    def test_existing_pack_directory_and_id(self):
        self.refused(["bookshop"], ".modsys/packs/bookshop/ already exists", "bookshop")
        (self.root / ".modsys/packs/other").mkdir()
        (self.root / ".modsys/packs/other/pack.toml").write_text('id = "team"\n')
        self.refused(["team"], "pack id 'team' is already installed "
                               "(.modsys/packs/other/pack.toml)", "team")

    def test_roles(self):
        self.refused(["team", "--role", "developer"],
                     "role 'developer' is already configured (engine defaults) — to change its "
                     "doc template: modsys templates override roles/developer.md", "team")
        self.refused(["team", "--role", "designer"],
                     "role 'designer' is already configured (pack 'bookshop')", "team")
        (self.root / ".modsys/config.toml").write_text('[roles.security]\norder = 60\n')
        self.refused(["team", "--role", "security"],
                     "role 'security' is already configured (the team config)", "team")
        for role in ("Reviewer", "1st", "a" * 49, "qa lead"):
            with self.subTest(role=role):
                self.refused(["team", "--role", role], f"role {role!r}: use lowercase letters, "
                                                       f"digits and '_'", "team")
        self.assertEqual(run("packs", "new", "team", "--role", "qa_lead", *self.R)[0], 0)

    def test_skills(self):
        self.assertEqual(run("packs", "new", "team", "--skill", "api-review", *self.R)[0], 0)
        self.refused(["other", "--skill", "api-review"],
                     "skill 'api-review' is already declared by pack 'team' "
                     "(.modsys/packs/team/pack.toml)", "other")
        for skill in ("API", "s" * 65, "api_review"):
            with self.subTest(skill=skill):
                self.refused(["other", "--skill", skill], f"skill {skill!r}: 1–64 characters: "
                                                          f"lowercase letters and digits", "other")

    def test_repeated_values(self):
        self.refused(["team", "--role", "reviewer", "--role", "reviewer"],
                     "--role 'reviewer' is repeated", "team")
        self.refused(["team", "--skill", "one", "--skill", "one"], "--skill 'one' is repeated",
                     "team")


class PacksListTest(PacksRepo):  # P4A-AC-011
    def test_no_packs(self):
        shutil.rmtree(self.root / ".modsys/packs/bookshop")
        self.assertEqual(self.ok("packs", "list"), [])
        self.assertEqual(run("packs", "list", *self.R)[1],
                         "no packs (create one: modsys packs new ID)\n")

    def test_rows_in_precedence_order(self):
        self.ok(*TEAM)
        rows = self.ok("packs", "list")
        self.assertEqual([r["id"] for r in rows], ["bookshop", "team"])
        self.assertEqual(rows[0], {"id": "bookshop", "version": "0.1.0", "priority": 50,
                                   "dir": ".modsys/packs/bookshop",
                                   "description": "Fixture pack: a custom role, a code-pointer "
                                                  "field, a deprecated field",
                                   "roles": ["designer"], "skills": []})
        skill = rows[1]["skills"][0]
        self.assertEqual({k: v for k, v in skill.items() if k != "description"},
                         {"id": "api-review", "path": "skills/api-review",
                          "reads_roles": ["reviewer"], "ejected": False})
        self.assertEqual(skill["description"],
                         front_matter(self.skill_md("team", "api-review"))["description"])
        self.assertEqual(run("packs", "list", *self.R)[1].splitlines(), [
            "bookshop 0.1.0 priority 50  .modsys/packs/bookshop", "  role   designer",
            "team 0.1.0 priority 50  .modsys/packs/team", "  role   reviewer",
            "  skill  api-review  reads reviewer"])

    def test_an_ejected_copy_and_an_unreadable_skill(self):
        self.ok(*TEAM)
        (self.root / ".modsys/overrides/skills/api-review").mkdir(parents=True)
        md = self.root / ".modsys/packs/team/skills/api-review/SKILL.md"
        md.write_text("# no front matter\n", encoding="utf-8")
        skill = self.ok("packs", "list")[1]["skills"][0]
        self.assertEqual((skill["ejected"], skill["description"]), (True, None))
        self.assertTrue(run("packs", "list", *self.R)[1].rstrip().endswith("(ejected)"))


class PacksContractTest(PacksRepo):  # P4A-AC-023
    def test_usage_errors(self):
        for argv, needle in [(("list", "team"), "packs list takes no ID"),
                             (("list", "--role", "x"), "packs list takes no --role"),
                             (("new",), "packs new needs an ID")]:
            with self.subTest(argv=argv):
                code, out, err = run("packs", *argv, "--json", *self.R)
                self.assertEqual((code, out), (2, ""))
                self.assertIn(needle, err)

    def test_garbage_config_and_interrupt(self):
        (self.root / ".modsys/config.toml").write_text("code_map = 5\n")
        for argv in (("list",), ("new", "team")):
            with self.subTest(argv=argv):
                code, out, err = run("packs", *argv, "--json", *self.R)
                self.assertEqual((code, out), (2, ""))
                self.assertTrue(err.startswith("modsys: error: "), err)
                self.assertNotIn("Traceback", err)
        (self.root / ".modsys/config.toml").unlink()
        with mock.patch("modsys.packs_cmd.pack_rows", side_effect=KeyboardInterrupt):
            self.assertEqual(run("packs", "list", *self.R), (130, "", "modsys: interrupted\n"))
        with mock.patch("modsys.packs_cmd.pack_rows", side_effect=RuntimeError("boom")):
            code, out, err = run("packs", "list", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("modsys: internal error: RuntimeError: boom"), err)
        calls = []

        def second_open_interrupts(*args, **kwargs):
            calls.append(args[0])
            if len(calls) == 2:
                raise KeyboardInterrupt
            return builtins.open(*args, **kwargs)

        with mock.patch("modsys.packs_cmd.open", create=True,
                        side_effect=second_open_interrupts):
            self.assertEqual(run(*TEAM, *self.R), (130, "", "modsys: interrupted\n"))
        self.assertEqual(len(calls), 2)
        self.assertFalse((self.root / ".modsys/packs/team").exists())  # the first file is gone


if __name__ == "__main__":
    unittest.main()
