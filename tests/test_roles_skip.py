"""`modsys roles skip ROLE TARGET… [--note TEXT]`: a module (or a child) that needs no doc for a
role says so in the registry — `context_files.roles.<role>` is `false`, or `{"skip": NOTE}` with a
note. `roles list` counts it as `skipped`, not `missing`; `next` stops naming it; `roles add --all`
leaves it alone while an explicit TARGET writes the doc in its place; lint accepts the mark and
flags a role value that is neither a path, a list of paths nor a mark; `show` names the role as
not needed."""
import json

from tests.helpers import mutate_registry, run, run_json
from tests.test_layout import convert
from tests.test_roles import Repo, holder, snap

NOTE = "Payments are tested end to end through checkout"


class SkipTest(Repo):
    def skip(self, *argv) -> list[tuple]:
        data = self.ok("roles", "skip", *argv)
        return [(r["module"], r["status"]) for r in data["results"]]

    def row(self, role: str) -> dict:
        return {r["name"]: r for r in self.ok("roles", "list")["roles"]}[role]

    def test_the_mark_and_the_counts(self):
        self.assertEqual(self.skip("qa", "checkout"), [("checkout", "marked")])
        self.assertEqual(self.skip("qa", "payments", "--note", NOTE), [("payments", "marked")])
        self.assertIs(holder(self.root, "checkout")["context_files"]["roles"]["qa"], False)
        self.assertEqual(holder(self.root, "payments")["context_files"]["roles"]["qa"],
                         {"skip": NOTE})
        qa = self.row("qa")
        self.assertEqual((qa["docs"], qa["missing"], qa["skipped"], qa["inherited"]),
                         (["catalog"], [], ["checkout", "payments"], ["payments/refunds"]))
        code, out, err = run("roles", "list", *self.R)
        self.assertEqual((code, err), (0, ""))
        line = next(x for x in out.splitlines() if x.startswith("qa "))
        self.assertIn("missing 0", line)
        self.assertIn("not needed 2", line)
        self.assertNotIn("not needed", next(x for x in out.splitlines()
                                            if x.startswith("developer ")))

    def test_again_is_unchanged_and_a_new_note_replaces_the_old(self):
        self.skip("qa", "checkout")
        self.assertEqual(self.skip("qa", "checkout"), [("checkout", "unchanged")])
        self.assertEqual(self.skip("qa", "checkout", "--note", NOTE), [("checkout", "marked")])
        self.assertEqual(self.skip("qa", "checkout", "--note", NOTE), [("checkout", "unchanged")])
        self.assertEqual(self.skip("qa", "checkout"), [("checkout", "marked")])  # note dropped
        self.assertIs(holder(self.root, "checkout")["context_files"]["roles"]["qa"], False)
        code, out, err = run("roles", "skip", "qa", "checkout", *self.R)
        self.assertEqual((code, err), (0, ""))
        self.assertIn("qa: 1 unchanged — nothing to do", out)

    def test_next_stops_naming_the_role(self):
        def roles():
            code, env, err = run_json("next", *self.R)
            self.assertEqual((code, err), (0, ""))
            return [i["summary"] for i in env["data"]["items"] if i["kind"] == "role"]
        self.assertIn("qa: no doc in 2 module(s): checkout, payments", roles())
        self.skip("qa", "checkout", "payments")
        self.assertFalse([s for s in roles() if s.startswith("qa:")], roles())

    def test_add_all_leaves_the_mark_an_explicit_target_replaces_it(self):
        self.skip("qa", "checkout", "--note", NOTE)
        before = snap(self.root)
        data = self.ok("roles", "add", "qa", "--all")
        status = {r["module"]: r["status"] for r in data["results"]}
        self.assertEqual((status["checkout"], status["payments"]), ("skipped", "created"))
        self.assertEqual(holder(self.root, "checkout")["context_files"]["roles"]["qa"],
                         {"skip": NOTE})
        self.assertFalse((self.root / "modules/checkout/roles/qa.md").exists())
        self.assertNotEqual(snap(self.root), before)
        data = self.ok("roles", "add", "qa", "checkout")
        self.assertEqual([(r["module"], r["status"]) for r in data["results"]],
                         [("checkout", "created")])
        self.assertEqual(holder(self.root, "checkout")["context_files"]["roles"]["qa"],
                         "modules/checkout/roles/qa.md")
        self.assertTrue((self.root / "modules/checkout/roles/qa.md").is_file())
        self.assertNotIn("checkout", self.row("qa")["skipped"])

    def test_a_target_with_a_doc_on_disk_is_refused_one_whose_file_is_gone_is_marked(self):
        before = snap(self.root)
        err = self.refused("roles", "skip", "qa", "checkout", "catalog")
        self.assertIn("'catalog' has a qa doc (modules/catalog/roles/qa.md) — roles skip marks "
                      "a module without one; delete the doc first", err)
        self.assertEqual(snap(self.root), before)  # checkout was not marked either
        (self.root / "modules/catalog/roles/qa.md").unlink()
        self.assertEqual(self.skip("qa", "catalog"), [("catalog", "marked")])
        self.assertIs(holder(self.root, "catalog")["context_files"]["roles"]["qa"], False)

    def test_a_child(self):
        self.assertEqual(self.skip("qa", "payments/refunds"), [("payments/refunds", "marked")])
        self.assertIs(holder(self.root, "payments/refunds")["context_files"]["roles"]["qa"],
                      False)
        qa = self.row("qa")
        self.assertEqual((qa["skipped"], qa["inherited"]), (["payments/refunds"], []))

    def test_a_dry_run_writes_nothing(self):
        before = snap(self.root)
        data = self.ok("roles", "skip", "qa", "checkout", "--dry-run")
        self.assertEqual((data["dry_run"], data["results"]),
                         (True, [{"module": "checkout", "status": "marked"}]))
        code, out, _ = run("roles", "skip", "qa", "checkout", "--dry-run", *self.R)
        self.assertEqual(code, 0)
        self.assertIn("would mark", out)
        self.assertIn("(dry run: nothing written)", out)
        self.assertEqual(snap(self.root), before)

    def test_the_per_module_layout(self):
        convert(self.root)
        self.assertEqual(self.skip("qa", "checkout", "--note", NOTE), [("checkout", "marked")])
        entry = holder(self.root, "checkout", "modules/checkout/module.json")
        self.assertEqual(entry["context_files"]["roles"]["qa"], {"skip": NOTE})
        self.assertEqual(self.row("qa")["skipped"], ["checkout"])
        code, _env, err = run_json("lint", *self.R)
        self.assertEqual((code, err), (0, ""))

    def test_refusals_write_nothing(self):
        before = snap(self.root)
        for argv, why in (
                (("roles", "skip"), "roles skip needs a ROLE"),
                (("roles", "skip", "qa"), "roles skip needs a TARGET"),
                (("roles", "skip", "qa", "--all"), "roles skip takes TARGETs, not --all — to "
                                                   "turn a role off for every module, set "
                                                   "enabled = false in [roles.qa]"),
                (("roles", "skip", "qa", "checkout", "--recreate"),
                 "--recreate applies to roles add"),
                (("roles", "skip", "qa", "checkout", "--note", " "), "--note needs a text"),
                (("roles", "add", "qa", "checkout", "--note", NOTE),
                 "--note applies to roles skip"),
                (("roles", "list", "--note", NOTE), "--note applies to roles skip"),
                (("roles", "skip", "nope", "checkout"), "unknown role 'nope'"),
                (("roles", "skip", "qa", "nowhere"), "unknown module 'nowhere'"),
                (("roles", "skip", "qa", "legacy-search"), "is a pointer stub")):
            with self.subTest(argv=argv):
                self.assertIn(why, self.refused(*argv))
        self.assertEqual(snap(self.root), before)


class LintTest(Repo):
    def findings(self) -> list[tuple]:
        code, env, err = run_json("lint", *self.R)
        self.assertEqual(err, "")
        return [(f["code"], f["module"], f["message"]) for f in env["data"]["findings"]
                if f["code"] in ("MS004", "MS013")]

    def test_a_mark_passes_anything_else_that_is_no_path_is_flagged(self):
        mutate_registry(self.root, lambda d: d["modules"]["checkout"].setdefault(
            "context_files", {}).setdefault("roles", {}).update(qa=False, po={"skip": NOTE}))
        self.assertEqual(self.findings(), [])
        for bad in (True, 5, {"skip": ""}, {"skip": 5}, {"skip": NOTE, "why": "x"}, {}):
            with self.subTest(bad=bad):
                mutate_registry(self.root, lambda d: d["modules"]["checkout"]["context_files"]
                                ["roles"].update(po=bad))
                self.assertEqual(self.findings(), [
                    ("MS013", "checkout", "context_files.roles.po is neither a doc path, a list "
                                          "of doc paths nor a not-needed mark (false or "
                                          f'{{"skip": "<note>"}}): {json.dumps(bad)}')])


class ShowTest(Repo):
    def show(self, *argv) -> dict:
        code, env, err = run_json("show", *argv, *self.R)
        self.assertEqual((code, err), (0, ""))
        return env["data"]

    def test_show_names_a_role_that_is_not_needed(self):
        self.ok("roles", "skip", "qa", "checkout")
        self.ok("roles", "skip", "po", "payments", "--note", NOTE)
        self.assertEqual(self.show("checkout", "--role", "qa")["not_needed"],
                         [{"role": "qa", "note": None}])
        self.assertEqual(self.show("payments", "--all-roles")["not_needed"],
                         [{"role": "po", "note": NOTE}])
        self.assertEqual(self.show("payments/refunds", "--role", "po")["not_needed"],
                         [{"role": "po", "note": NOTE}])  # the parent's mark covers the child
        self.assertNotIn("not_needed", self.show("checkout", "--role", "po"))
        self.assertNotIn("not_needed", self.show("checkout"))  # no role asked for
        code, out, _ = run("show", "payments", "--role", "po", *self.R)
        self.assertEqual(code, 0)
        self.assertIn(f"  skip  role:po not needed — {NOTE}", out)
        code, out, _ = run("show", "checkout", "--role", "qa", *self.R)
        self.assertIn("  skip  role:qa not needed\n", out)
