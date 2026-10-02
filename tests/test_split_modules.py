"""P8.1 Task 2: split modules — a child without its own role doc is `inherited` (covered by the
parent's, as `show` reads it), `next` / `roles add --all` leave it alone, a split parent's modify
row names its children, and a child's doc update clears the parent's MS050."""
import json
import tempfile
import unittest

from tests.helpers import SPLIT_FIXTURE, copy_fixture, git, init_git, mutate_registry, run, run_json

CHILDREN = ["orders/checkout", "orders/refunds", "orders/invoices"]


class SplitBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name, SPLIT_FIXTURE)
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def role_row(self, role="developer"):
        _, env, _ = run_json("roles", "list", *self.R)
        return next(r for r in env["data"]["roles"] if r["name"] == role)


class InheritedRolesTest(SplitBase):
    def test_list_reports_inherited_json_and_text(self):  # P81-AC-010
        row = self.role_row()
        self.assertEqual(row["docs"], sorted(["catalog", "orders", "payments", "orders/checkout"]))
        self.assertEqual(row["inherited"], ["orders/invoices", "orders/refunds"])
        self.assertEqual(row["missing"], [])
        _, out, _ = run("roles", "list", *self.R)
        line = next(l for l in out.splitlines() if l.startswith("developer"))
        self.assertIn("2 inherited", line)
        self.assertIn("missing 0", line)

    def test_parent_without_doc_is_missing_children_still_inherited(self):  # SI-P81-5
        qa = self.role_row("qa")
        self.assertEqual(qa["missing"], ["catalog", "orders", "payments"])
        self.assertEqual(qa["inherited"], sorted(CHILDREN))

    def test_next_asks_nothing_for_inherited_children(self):  # P81-AC-011
        _, env, _ = run_json("next", *self.R)
        items = env["data"]["items"]
        dev = [i for i in items if i["summary"].startswith("developer:")]
        self.assertEqual(dev, [])  # every developer doc a target needs exists or is inherited
        qa = next(i for i in items if i["summary"].startswith("qa:"))
        self.assertIn("no doc in 3 module(s)", qa["summary"])  # genuinely missing, still asked
        for i in items:
            self.assertNotIn("refunds", json.dumps(i))
            self.assertNotIn("invoices", json.dumps(i))

    def test_add_all_skips_inherited_children(self):  # P81-AC-012
        mutate_registry(self.root, lambda d: d["modules"]["catalog"]["context_files"]["roles"]
                        .pop("developer"))
        (self.root / "modules/catalog/roles/developer.md").unlink()
        code, env, _ = run_json("roles", "add", "developer", "--all", *self.R)
        self.assertEqual(code, 0)
        status = {r["module"]: r["status"] for r in env["data"]["results"]}
        self.assertEqual(status["catalog"], "created")
        self.assertEqual(status["orders/refunds"], "inherited")
        self.assertEqual(status["orders/invoices"], "inherited")
        self.assertEqual(status["orders/checkout"], "exists")
        for child in ("refunds", "invoices"):
            self.assertFalse((self.root / f"modules/orders/submodules/{child}/roles").exists())
        _, out, _ = run("roles", "add", "developer", "--all", "--dry-run", *self.R)
        self.assertIn("2 inherited", out)

    def test_explicit_child_target_creates_its_doc(self):  # P81-AC-013
        parent_doc = (self.root / "modules/orders/roles/developer.md").read_bytes()
        code, env, _ = run_json("roles", "add", "developer", "orders/refunds", *self.R)
        self.assertEqual(code, 0)
        self.assertEqual(env["data"]["results"][0]["status"], "created")
        rel = "modules/orders/submodules/refunds/roles/developer.md"
        self.assertTrue((self.root / rel).is_file())
        self.assertEqual((self.root / "modules/orders/roles/developer.md").read_bytes(),
                         parent_doc)
        row = self.role_row()
        self.assertIn("orders/refunds", row["docs"])
        self.assertEqual(row["inherited"], ["orders/invoices"])

    def test_show_reads_the_parent_doc_for_an_inherited_child(self):  # P81-AC-014
        _, env, _ = run_json("show", "orders/refunds", "--role", "developer", *self.R)
        paths = {r["label"]: r["path"] for r in env["data"]["read"]}
        self.assertEqual(paths["parent baseline role:developer"],
                         "modules/orders/roles/developer.md")
        self.assertNotIn("child role:developer", paths)
        self.assertIn("orders/refunds", self.role_row()["inherited"])


class ChildrenRowTest(SplitBase):
    def check_children(self, row):
        self.assertEqual([c["module"] for c in row["children"]], CHILDREN)
        self.assertEqual(row["children"][1], {
            "module": "orders/refunds",
            "description": "Returned books: refund requests, partial refunds and restocking.",
            "doc": "modules/orders/submodules/refunds/MODULE.md"})

    def test_discover_modify_row_has_children(self):  # P81-AC-015
        _, env, _ = run_json("discover", "--files", "src/orders/service.py", *self.R)
        row = env["data"]["modules"][0]
        self.assertEqual(row["module"], "orders")
        self.check_children(row)
        self.assertIn("modules/orders/roles/developer.md", row["docs_to_update"])

    def test_sync_instructions_row_has_children(self):  # P81-AC-015
        _, env, _ = run_json("sync-instructions", "--files", "src/orders/service.py", *self.R)
        row = env["data"]["modules"][0]
        self.check_children(row)
        self.assertIn("modules/orders/roles/developer.md", row["docs_to_update"])
        _, env, _ = run_json("sync-instructions", "--module", "orders", *self.R)
        self.check_children(env["data"]["modules"][0])

    def test_text_lines_and_no_children_elsewhere(self):  # P81-AC-016
        _, out, _ = run("discover", "--files", "src/orders/service.py", *self.R)
        lines = [l for l in out.splitlines() if l.startswith("          child")]
        self.assertEqual(len(lines), 3)
        self.assertIn("orders/refunds", lines[1])
        _, out, _ = run("sync-instructions", "--files", "src/orders/service.py", *self.R)
        self.assertEqual(len([l for l in out.splitlines() if l.startswith("  child")]), 3)
        _, env, _ = run_json("discover", "--files", "src/catalog/service.py",
                             "--task", "split orders refund", *self.R)
        for row in env["data"]["modules"]:
            if row["module"] == "catalog" or row["usage"] == "reference":
                self.assertNotIn("children", row)
        _, out, _ = run("discover", "--files", "src/catalog/service.py", *self.R)
        self.assertNotIn("child", out)
        _, env, _ = run_json("discover", "--task", "refund", *self.R)  # reference rows only
        self.assertTrue(env["data"]["modules"])
        for row in env["data"]["modules"]:
            self.assertEqual(row["usage"], "reference")
            self.assertNotIn("children", row)


class Ms050ChildTest(SplitBase):
    def setUp(self):
        super().setUp()
        init_git(self.root)

    def append(self, rel):
        with (self.root / rel).open("a") as fh:
            fh.write("More.\n")

    def codes(self):
        _, env, _ = run_json("lint", "--changed", "--fail-on", "never", *self.R)
        return {(f["code"], f["module"]) for f in env["data"]["findings"]
                if f["code"] == "MS050"}

    def test_child_doc_clears_the_parent(self):  # P81-AC-017
        self.append("src/orders/service.py")
        self.assertEqual(self.codes(), {("MS050", "orders")})
        self.append("modules/orders/submodules/checkout/MODULE.md")
        self.assertEqual(self.codes(), set())
        _, env, _ = run_json("sync-instructions", "--files", "src/orders/service.py",
                             "modules/orders/submodules/checkout/MODULE.md", *self.R)
        self.assertEqual(env["data"]["modules"][0]["drift"], [])

    def test_parent_doc_still_clears_and_no_doc_still_flags(self):  # P81-AC-017, SI-P81-11
        self.append("src/orders/service.py")
        self.append("modules/orders/MODULE.md")
        self.assertEqual(self.codes(), set())
        git(self.root, "checkout", "-q", "modules/orders/MODULE.md")
        self.assertEqual(self.codes(), {("MS050", "orders")})

    def test_a_sibling_child_doc_does_not_clear_a_child_target(self):
        mutate_registry(self.root, lambda d: d["modules"]["orders"]["submodules"]["refunds"]
                        .update(file_paths=["src/orders/service.py"]))
        git(self.root, "commit", "-qam", "refunds code")
        self.append("src/orders/service.py")
        self.append("modules/orders/submodules/checkout/MODULE.md")
        got = self.codes()  # the child's code, a sibling's doc: not covered; the parent's is
        self.assertIn(("MS050", "orders/refunds"), got)
        self.assertNotIn(("MS050", "orders"), got)

    def test_a_child_target_is_cleared_by_its_own_doc_or_its_parents(self):  # P81-AC-017
        mutate_registry(self.root, lambda d: d["modules"]["orders"]["submodules"]["refunds"]
                        .update(file_paths=["src/orders/service.py"]))
        git(self.root, "commit", "-qam", "refunds code")
        self.append("src/orders/service.py")
        self.assertIn(("MS050", "orders/refunds"), self.codes())  # the code alone: flagged
        for doc in ("modules/orders/submodules/refunds/MODULE.md", "modules/orders/MODULE.md"):
            with self.subTest(doc=doc):
                self.append(doc)
                self.assertNotIn(("MS050", "orders/refunds"), self.codes())
                git(self.root, "checkout", "-q", doc)
                self.assertIn(("MS050", "orders/refunds"), self.codes())


if __name__ == "__main__":
    unittest.main()
