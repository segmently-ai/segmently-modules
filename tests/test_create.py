"""modsys create: answers, roles, templates, children, rollback."""
import io
import json
import tempfile
import unittest
from unittest import mock

from modsys.output import UsageError
from tests.helpers import copy_fixture, run, run_json

KW = ["--keyword", "review", "--keyword", "rating", "--keyword", "stars",
      "--keyword", "comment", "--keyword", "moderation"]
DESC = ["--description", "Customer reviews of books: ratings, comments and moderation."]


class CreateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def reg(self):
        return json.loads((self.root / "modules/registry.json").read_text())["modules"]

    def team(self, text):
        (self.root / ".modsys/config.toml").write_text(text, encoding="utf-8")

    def test_new_module_end_to_end_and_lint_clean(self):
        code, env, _ = run_json("create", "reviews", *DESC, *KW, "--non-interactive", *self.R)
        self.assertEqual((code, env["schema"]), (0, "modsys.create/1"))
        self.assertEqual(env["data"]["files"], [
            "modules/reviews/MODULE.md", "modules/reviews/roles/architect.md",
            "modules/reviews/roles/developer.md", "modules/reviews/roles/po.md",
            "modules/reviews/roles/qa.md"])
        entry = self.reg()["reviews"]
        self.assertEqual(list(entry), ["name", "description", "status", "keywords", "context_files"])
        self.assertEqual(entry["status"], "planned")
        self.assertEqual(entry["context_files"]["roles"]["qa"], "modules/reviews/roles/qa.md")
        text = (self.root / "modules/reviews/MODULE.md").read_text()
        self.assertTrue(text.startswith("# Reviews\n\n> Customer reviews of books"))
        _, env, _ = run_json("lint", *self.R)
        self.assertEqual(env["data"]["summary"], {"error": 0, "warning": 0, "info": 0})

    def test_missing_answers_listed(self):
        code, out, err = run("create", "reviews", "--non-interactive", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("missing answers: description, keywords", err)
        self.assertFalse((self.root / "modules/reviews").exists())

    def test_answer_validation(self):
        cases = [(["--description", "too short", *KW], "description must be 20–200"),
                 ([*DESC, "--keyword", "a", "--keyword", "b"], "at least 5 distinct"),
                 ([*DESC, *KW, "--status", "wip"], "status 'wip' not in"),
                 ([*DESC, *KW, "--role", "security"], "unknown role(s): security")]
        for argv, needle in cases:
            with self.subTest(needle=needle):
                code, _, err = run("create", "reviews", *argv, "--non-interactive", *self.R)
                self.assertEqual(code, 2)
                self.assertIn(needle, err)
        answers = self.root / "a.json"
        answers.write_text(json.dumps({"description": DESC[1], "keywords": KW[1::2], "owner": "x"}))
        code, _, err = run("create", "reviews", "--answers", str(answers), *self.R)
        self.assertEqual(code, 2)
        self.assertIn("unknown answer key(s): owner", err)

    def test_name_and_existence_refusals(self):
        for name, needle in [("Reviews", "use lowercase words"), ("user_reviews", "lowercase"),
                             ("catalog", "already exists"), ("legacy-search", "already exists")]:
            with self.subTest(name=name):
                code, _, err = run("create", name, *DESC, *KW, *self.R)
                self.assertEqual(code, 2)
                self.assertIn(needle, err)

    def test_roles_by_tag_and_by_name(self):
        self.team('[roles.designer]\napplies_when = "ui"\n')
        _, env, _ = run_json("create", "reviews", *DESC, *KW, "--tag", "ui", *self.R)
        self.assertIn("modules/reviews/roles/designer.md", env["data"]["files"])
        _, env, _ = run_json("create", "ratings", *DESC, *KW, *self.R)
        self.assertNotIn("modules/ratings/roles/designer.md", env["data"]["files"])
        _, env, _ = run_json("create", "badges", *DESC, *KW, "--role", "designer", *self.R)
        self.assertIn("modules/badges/roles/designer.md", env["data"]["files"])

    def test_ask_on_create_field(self):
        self.team('[fields.owner_team]\ntype = "string"\nask_on_create = true\n')
        code, _, err = run("create", "reviews", *DESC, *KW, "--non-interactive", *self.R)
        self.assertEqual(code, 2)
        self.assertIn("missing answers: owner_team", err)
        answers = self.root / "a.json"
        answers.write_text(json.dumps({"description": DESC[1], "keywords": KW[1::2],
                                       "owner_team": "growth"}))
        run("create", "reviews", "--answers", str(answers), *self.R)
        self.assertEqual(self.reg()["reviews"]["owner_team"], "growth")

    def test_child_module(self):
        code, env, _ = run_json("create", "disputes", "--parent", "payments",
                                "--description", "Chargeback disputes raised by card issuers.",
                                "--keyword", "dispute", *self.R)
        self.assertEqual((code, env["data"]["module"]), (0, "payments/disputes"))
        child = self.reg()["payments"]["submodules"]["disputes"]
        self.assertEqual(list(child), ["description", "keywords", "context_files"])
        self.assertTrue((self.root / "modules/payments/submodules/disputes/roles/developer.md")
                        .is_file())
        self.assertEqual(run("lint", *self.R)[0], 0)
        code, _, err = run("create", "x", "--parent", "nope", *DESC, *KW, *self.R)
        self.assertIn("unknown parent module 'nope'", err)

    def test_template_resolution_order(self):
        over = self.root / ".modsys/overrides/templates"
        over.mkdir(parents=True)
        (over / "MODULE.md").write_text("# ${title} (team template)\n")
        pack = self.root / ".modsys/packs/bookshop"
        (pack / "templates/roles").mkdir(parents=True)
        (pack / "templates/roles/qa.md").write_text("# ${title} QA from pack\n")
        (pack / "roles").mkdir()
        (pack / "roles/designer.md").write_text("# ${title} designer from role template\n")
        self.team('[roles.designer]\ntemplate = "roles/designer.md"\n')
        # the team layer has no owner, so the role's template keeps pointing into the pack
        run("create", "reviews", *DESC, *KW, "--role", "designer", *self.R)
        read = lambda p: (self.root / "modules/reviews" / p).read_text()
        self.assertEqual(read("MODULE.md"), "# Reviews (team template)\n")
        self.assertEqual(read("roles/qa.md"), "# Reviews QA from pack\n")
        self.assertEqual(read("roles/designer.md"), "# Reviews designer from role template\n")
        self.assertIn("# Reviews — developer", read("roles/developer.md"))

    def test_dry_run_writes_nothing(self):
        before = (self.root / "modules/registry.json").read_bytes()
        code, env, _ = run_json("create", "reviews", *DESC, *KW, "--dry-run", *self.R)
        self.assertEqual((code, env["data"]["dry_run"]), (0, True))
        self.assertEqual((self.root / "modules/registry.json").read_bytes(), before)
        self.assertFalse((self.root / "modules/reviews").exists())

    def test_interactive_prompts_fill_gaps(self):
        with mock.patch("modsys.create.interactive", return_value=True), \
                mock.patch("builtins.input", side_effect=[
                    DESC[1], "review, rating, stars, comment, moderation"]):
            code, _, _ = run("create", "reviews", *self.R)
        self.assertEqual(code, 0)
        self.assertEqual(self.reg()["reviews"]["keywords"][0], "review")

    def test_registry_failure_rolls_back_docs(self):
        with mock.patch("modsys.store.RegistryStore.save",
                        side_effect=UsageError("registry changed since it was read")):
            code, _, err = run("create", "disputes", "--parent", "payments",
                               "--description", "Chargeback disputes raised by card issuers.",
                               "--keyword", "dispute", *self.R)
        self.assertEqual(code, 2)
        self.assertIn("changed since it was read", err)
        self.assertFalse((self.root / "modules/payments/submodules/disputes").exists())
        self.assertTrue((self.root / "modules/payments/submodules/refunds/MODULE.md").exists())

    def test_create_in_per_module_layout(self):
        run("index", "split", *self.R)
        self.team('[paths]\nregistry_layout = "per-module"\n')
        run("create", "reviews", *DESC, *KW, *self.R)
        entry = json.loads((self.root / "modules/reviews/module.json").read_text())
        self.assertEqual(entry["name"], "reviews")
        self.assertEqual(run("index", "build", "--check", *self.R)[0], 1)  # index now stale


class CreateBoundaryTest(unittest.TestCase):  # AC-027, AC-032
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def create(self, name, description, keywords):
        argv = ["create", name, "--description", description, "--dry-run", "--non-interactive"]
        for k in keywords:
            argv += ["--keyword", k]
        return run(*argv, *self.R)

    def test_answer_boundaries(self):
        five = ["a1", "a2", "a3", "a4", "a5"]
        ok_desc = "x" * 20
        cases = [("n" * 48, ok_desc, five, 0), ("n" * 49, ok_desc, five, 2),
                 ("reviews", "x" * 19, five, 2), ("reviews", "x" * 20, five, 0),
                 ("reviews", "x" * 200, five, 0), ("reviews", "x" * 201, five, 2),
                 ("reviews", ok_desc, five[:4], 2), ("reviews", ok_desc, five, 0)]
        for name, desc, kws, expected in cases:
            with self.subTest(name_len=len(name), desc_len=len(desc), kws=len(kws)):
                self.assertEqual(self.create(name, desc, kws)[0], expected)

    def test_no_terminal_never_prompts(self):
        with mock.patch("sys.stdin", io.StringIO("")):
            code, out, err = run("create", "reviews", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("missing answers: description, keywords", err)
        self.assertFalse((self.root / "modules/reviews").exists())


if __name__ == "__main__":
    unittest.main()
