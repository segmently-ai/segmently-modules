"""Templates as files (D1): per-role engine templates, the provenance of every template, and
`modsys templates list|override` (D2)."""
import string
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from modsys.config import core_defaults
from modsys.create import engine_templates
from tests.helpers import copy_fixture, make_repo, run, run_json

DESC = ["--description", "Customer reviews of books: ratings, comments and moderation."]
KW = ["--keywords", "review, rating, stars, comment, moderation"]
STANDARD = ("developer", "qa", "po", "architect")
TEAM_PACK = ('id = "team"\nversion = "0.1.0"\n\n[roles.reviewer]\norder = 100\n'
             'description = "What a reviewer checks"\ntemplate = "roles/reviewer.md"\n')


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class Fixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def create(self, *argv) -> dict:
        code, env, err = run_json("create", "reviews", *DESC, *KW, "--non-interactive", *argv,
                                  *self.R)
        self.assertEqual((code, err), (0, ""))
        return env["data"]

    def doc(self, role: str) -> str:
        return (self.root / f"modules/reviews/roles/{role}.md").read_text(encoding="utf-8")

    def team_pack(self) -> None:
        write(self.root / ".modsys/packs/team/pack.toml", TEAM_PACK)
        write(self.root / ".modsys/packs/team/roles/reviewer.md",
              "# ${title} — ${role} (team)\n\n> ${role_description}\n")

    def rows(self) -> list[dict]:
        code, env, err = run_json("templates", "list", *self.R)
        self.assertEqual((code, err, env["schema"]), (0, "", "modsys.templates/1"))
        return env["data"]


class PerRoleTemplatesTest(Fixture):  # P4A-AC-004
    def test_every_standard_role_has_its_own_template(self):
        self.create()
        roles = core_defaults()["roles"]
        texts = {}
        for role in STANDARD:
            with self.subTest(role=role):
                text = self.doc(role)
                lines = text.splitlines()
                self.assertEqual(lines[0], f"# Reviews — {role}")
                self.assertEqual(lines[2], f"> {roles[role]['description']}")
                self.assertTrue(3 <= sum(l.startswith("## ") for l in lines) <= 5, lines)
                self.assertLessEqual(len(lines), 40)
                self.assertNotIn("${", text)
                texts[role] = text
        self.assertEqual(len(set(texts.values())), 4)

    def test_the_engine_files_stay_short(self):
        for role in STANDARD:
            with self.subTest(role=role):
                text = (engine_templates() / "roles" / f"{role}.md").read_text(encoding="utf-8")
                self.assertLessEqual(len(text.splitlines()), 40)
                self.assertTrue(text.startswith("# ${title} — ${role}\n\n> ${role_description}\n"))

    def test_a_role_without_its_own_file_gets_the_generic_template(self):
        self.create("--role", "designer")
        self.assertEqual(self.doc("designer"),
                         "# Reviews — designer\n\n> UX invariants for UI modules\n\n<!-- What a "
                         "designer needs to know about this module. Keep it short; link to "
                         "code, don't copy it. -->\n")

    def test_an_override_still_wins(self):
        write(self.root / ".modsys/overrides/templates/roles/qa.md", "# ${title} QA (team)\n")
        self.create()
        self.assertEqual(self.doc("qa"), "# Reviews QA (team)\n")

    def test_the_new_module_lints_clean(self):
        self.create()
        _, env, _ = run_json("lint", *self.R)
        self.assertEqual(env["data"]["summary"], {"error": 0, "warning": 0, "info": 0})


class ProvenanceTest(Fixture):  # P4A-AC-005
    def by_template(self) -> dict:
        return {r["template"]: r for r in self.rows()}

    def test_engine_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp, {"tasks": ["task"]})
            _, env, _ = run_json("templates", "list", "--root", str(root))
        rows = env["data"]
        self.assertEqual([r["template"] for r in rows],
                         ["MODULE.md", "roles/developer.md", "roles/qa.md", "roles/po.md",
                          "roles/architect.md", "agents-md.md"])
        for r in rows:
            with self.subTest(template=r["template"]):
                self.assertEqual(set(r), {"template", "role", "source", "path"})
                self.assertEqual(r["source"], "engine")
                self.assertEqual(Path(r["path"]), engine_templates() / r["template"])
                self.assertTrue(Path(r["path"]).is_absolute() and Path(r["path"]).is_file())
        self.assertEqual([r["role"] for r in rows],
                         [None, "developer", "qa", "po", "architect", None])

    def test_a_pack_role_without_a_template_falls_back(self):
        row = self.by_template()["roles/designer.md"]
        self.assertEqual((row["role"], row["source"]), ("designer", "engine-fallback"))
        self.assertEqual(Path(row["path"]), engine_templates() / "roles" / "_role.md")

    def test_every_layer_names_itself(self):
        self.team_pack()
        write(self.root / ".modsys/packs/bookshop/templates/roles/qa.md", "# ${title} qa\n")
        write(self.root / ".modsys/overrides/templates/MODULE.md", "# ${title} (team)\n")
        write(self.root / ".modsys/config.toml", "[roles.po]\nenabled = false\n")
        rows = self.by_template()
        self.assertEqual(list(rows), ["MODULE.md", "roles/developer.md", "roles/qa.md",
                                      "roles/architect.md", "roles/designer.md",
                                      "roles/reviewer.md", "agents-md.md"])
        self.assertEqual({t: (r["source"], r["path"]) for t, r in rows.items()
                          if r["source"] not in ("engine", "engine-fallback")}, {
            "MODULE.md": ("override", ".modsys/overrides/templates/MODULE.md"),
            "roles/qa.md": ("pack:bookshop", ".modsys/packs/bookshop/templates/roles/qa.md"),
            "roles/reviewer.md": ("role-template:team", ".modsys/packs/team/roles/reviewer.md")})

    def test_create_renders_exactly_the_file_the_row_names(self):
        self.team_pack()
        write(self.root / ".modsys/packs/bookshop/templates/roles/qa.md", "# ${title} qa\n")
        rows = self.by_template()
        self.create("--role", "reviewer")
        for template in ("roles/developer.md", "roles/qa.md", "roles/reviewer.md"):
            with self.subTest(template=template):
                path = Path(rows[template]["path"])
                text = (path if path.is_absolute() else self.root / path).read_text("utf-8")
                role = rows[template]["role"]
                spec = {"reviewer": {"description": "What a reviewer checks"}}.get(
                    role, core_defaults()["roles"].get(role, {}))
                expected = string.Template(text).safe_substitute(
                    title="Reviews", role=role, role_description=spec["description"])
                self.assertEqual(self.doc(role), expected)

    def test_text_output_one_line_per_template(self):
        self.team_pack()
        out = run("templates", "list", *self.R)[1].splitlines()
        self.assertEqual(out[6].split(), ["roles/reviewer.md", "role-template:team",
                                          ".modsys/packs/team/roles/reviewer.md"])
        self.assertEqual(len(out), 8)


class OverrideTest(Fixture):  # P4A-AC-006
    def override(self, *argv, code=0):
        got, env, err = run_json("templates", "override", *argv, *self.R)
        self.assertEqual(got, code)
        return (env or {}).get("data"), err

    def test_copy_the_engine_template_then_it_wins(self):
        data, err = self.override("roles/qa.md")
        target = self.root / ".modsys/overrides/templates/roles/qa.md"
        self.assertEqual((data, err), ({"template": "roles/qa.md",
                                        "file": ".modsys/overrides/templates/roles/qa.md",
                                        "from": "engine", "dry_run": False}, ""))
        self.assertEqual(target.read_bytes(), (engine_templates() / "roles/qa.md").read_bytes())
        self.assertEqual({r["template"]: r["source"] for r in self.rows()}["roles/qa.md"],
                         "override")
        target.write_text("# ${title} QA (edited)\n", encoding="utf-8")
        self.create()
        self.assertEqual(self.doc("qa"), "# Reviews QA (edited)\n")

    def test_copy_a_pack_role_template(self):
        self.team_pack()
        data, _ = self.override("roles/reviewer.md")
        self.assertEqual(data["from"], "role-template:team")
        self.assertEqual((self.root / data["file"]).read_bytes(),
                         (self.root / ".modsys/packs/team/roles/reviewer.md").read_bytes())

    def test_dry_run_writes_nothing(self):
        data, _ = self.override("MODULE.md", "--dry-run")
        self.assertEqual((data["dry_run"], data["from"]), (True, "engine"))
        self.assertFalse((self.root / ".modsys/overrides").exists())
        self.assertEqual(run("templates", "override", "MODULE.md", "--dry-run", *self.R)[1],
                         "would create  .modsys/overrides/templates/MODULE.md  (a copy of the "
                         "engine template)\nnext: edit it — from now on it wins over every pack "
                         "and engine template (modsys templates list)\n")

    def test_refusals_write_nothing(self):
        self.override("roles/qa.md")
        before = (self.root / ".modsys/overrides/templates/roles/qa.md").read_bytes()
        cases = [(("roles/qa.md",), ".modsys/overrides/templates/roles/qa.md already exists — "
                                    "edit it"),
                 (("roles/nosuch.md",), "unknown template 'roles/nosuch.md' (templates: "
                                        "MODULE.md, roles/developer.md, roles/qa.md, roles/po.md, "
                                        "roles/architect.md, roles/designer.md, agents-md.md)"),
                 (("../x.md",), "not a file path"), (("/etc/hosts",), "not a file path"),
                 (("roles/../../x.md",), "not a file path")]
        for argv, needle in cases:
            with self.subTest(argv=argv):
                code, out, err = run("templates", "override", *argv, "--json", *self.R)
                self.assertEqual((code, out), (2, ""))
                self.assertTrue(err.startswith("modsys: error: "), err)
                self.assertIn(needle, err)
        self.assertEqual((self.root / ".modsys/overrides/templates/roles/qa.md").read_bytes(),
                         before)
        self.assertEqual(sorted(p.name for p in (self.root / ".modsys/overrides/templates")
                                .rglob("*")), ["qa.md", "roles"])
        self.assertFalse((self.root.parent / "x.md").exists())


class TemplatesContractTest(Fixture):  # P4A-AC-023
    def test_usage_errors(self):
        for argv, needle in [(("list", "roles/qa.md"), "templates list takes no TEMPLATE"),
                             (("list", "--dry-run"), "--dry-run applies to templates override"),
                             (("override",), "templates override needs a TEMPLATE")]:
            with self.subTest(argv=argv):
                code, out, err = run("templates", *argv, "--json", *self.R)
                self.assertEqual((code, out), (2, ""))
                self.assertIn(needle, err)

    def test_garbage_config_and_interrupt(self):
        write(self.root / ".modsys/config.toml", "code_map = 5\n")
        for action in (("list",), ("override", "roles/qa.md")):
            with self.subTest(action=action):
                code, out, err = run("templates", *action, "--json", *self.R)
                self.assertEqual((code, out), (2, ""))
                self.assertTrue(err.startswith("modsys: error: "), err)
                self.assertNotIn("Traceback", err)
        (self.root / ".modsys/config.toml").unlink()
        for action in (("list",), ("override", "roles/qa.md")):
            with self.subTest(interrupted=action), mock.patch(
                    "modsys.templates_cmd.resolve_template_source",
                    side_effect=KeyboardInterrupt):
                self.assertEqual(run("templates", *action, *self.R),
                                 (130, "", "modsys: interrupted\n"))
        self.assertFalse((self.root / ".modsys/overrides").exists())


if __name__ == "__main__":
    unittest.main()
