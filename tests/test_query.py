import json
import tempfile
import unittest

from tests.helpers import FIXTURE, copy_fixture, run, run_json

R = ("--root", str(FIXTURE))


class ShowTest(unittest.TestCase):
    def test_all_roles_follow_config_order_and_code_pointers(self):
        code, env, _ = run_json("show", "catalog", "--all-roles", *R)
        self.assertEqual(code, 0)
        data = env["data"]
        self.assertEqual([r["label"] for r in data["read"]],
                         ["universal", "role:developer", "role:qa", "role:designer"])
        self.assertTrue(all(r["exists"] for r in data["read"]))
        self.assertEqual(data["code"], ["src/catalog/service.py"])

    def test_child_role_plus_parent_baseline(self):
        _, env, _ = run_json("show", "payments/refunds", "--role", "developer", *R)
        self.assertEqual([r["label"] for r in env["data"]["read"]],
                         ["universal (parent INDEX)", "child universal (refunds)",
                          "child role:developer", "parent baseline role:developer"])

    def test_parent_lists_children(self):
        _, env, _ = run_json("show", "payments", *R)
        self.assertEqual(env["data"]["submodules"],
                         {"refunds": "Refund requests and partial refunds"})

    def test_stub_unknown_module_and_unknown_role(self):
        code, env, _ = run_json("show", "legacy-search", *R)
        self.assertEqual(code, 1)
        self.assertIn("retired", env["data"]["stub"])
        code, _, err = run("show", "nope", *R)
        self.assertEqual(code, 2)
        self.assertIn("unknown module", err)
        code, _, err = run("show", "catalog", "--role", "security", *R)
        self.assertEqual(code, 2)
        self.assertIn("unknown role", err)


class RelatedAndListTest(unittest.TestCase):
    def test_reverse_edges(self):
        _, env, _ = run_json("related", "payments", *R)
        self.assertEqual(env["data"]["edges"], [])
        self.assertEqual(env["data"]["reverse"],
                         [{"from": "checkout", "module": "payments/refunds",
                           "relation": "depends-on",
                           "description": "Cancelled orders trigger refunds"}])

    def test_relation_filter(self):
        _, env, _ = run_json("related", "catalog", "--relation", "complements", *R)
        self.assertEqual(len(env["data"]["edges"]), 1)

    def test_list(self):
        _, env, _ = run_json("list", *R)
        self.assertEqual([r["module"] for r in env["data"]],
                         ["catalog", "checkout", "payments"])
        self.assertEqual(env["data"][0]["description"], "Book catalog: titles, authors, formats")
        self.assertEqual(env["data"][2]["children"], "refunds")

    def test_broken_registry_exit_2_names_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            (root / "modules" / "registry.json").write_text("{", encoding="utf-8")
            code, _, err = run("list", "--root", str(root))
        self.assertEqual(code, 2)
        self.assertIn("registry.json", err)


class ContractAndQueryGapTest(unittest.TestCase):  # AC-001, AC-021 … AC-024
    def test_output_contract_matrix(self):
        code, out, err = run("list", "--json", *R)
        self.assertEqual((code, set(json.loads(out)), err), (0, {"schema", "data"}, ""))
        code, out, _ = run("list", *R)
        self.assertEqual(code, 0)
        self.assertFalse(out.lstrip().startswith("{"))
        self.assertIn("3 modules", out)
        code, out, err = run("show", *R)                    # argparse: missing module
        self.assertEqual((code, out), (2, ""))
        self.assertIn("usage", err.lower())
        code, out, err = run("show", "nope", "--json", *R)  # UsageError
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("modsys: error:"))

    def test_bare_module_typo_hint_path_outside_and_abs_path(self):
        _, env, _ = run_json("show", "catalog", *R)
        self.assertEqual([r["label"] for r in env["data"]["read"]], ["universal"])
        self.assertEqual(env["data"]["code"], ["src/catalog/service.py"])
        code, _, err = run("show", "cat", *R)
        self.assertEqual(code, 2)
        self.assertIn("closest: catalog", err)
        code, _, err = run("show", "src/catalog/service.py", *R)
        self.assertEqual(code, 2)
        self.assertIn("outside modules/", err)
        abs_path = str(FIXTURE / "modules" / "payments" / "submodules" / "refunds" / "MODULE.md")
        _, env, _ = run_json("show", abs_path, *R)
        self.assertEqual(env["data"]["module"], "payments/refunds")

    def test_missing_file_flagged(self):  # AC-022
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            (root / "modules" / "catalog" / "roles" / "qa.md").unlink()
            _, env, _ = run_json("show", "catalog", "--all-roles", "--root", str(root))
            code, out, _ = run("show", "catalog", "--all-roles", "--root", str(root))
        qa = [r for r in env["data"]["read"] if r["label"] == "role:qa"][0]
        self.assertFalse(qa["exists"])
        self.assertEqual(code, 0)
        self.assertIn("(MISSING ON DISK)", out)

    def test_related_unknown_relation_and_stub(self):  # AC-023
        code, _, err = run("related", "catalog", "--relation", "uses", *R)
        self.assertEqual(code, 2)
        self.assertIn("depends-on", err)
        code, env, _ = run_json("related", "legacy-search", *R)
        self.assertEqual(code, 1)
        self.assertIn("stub", env["data"])

    def test_list_status_filter(self):  # AC-024
        self.assertEqual(run_json("list", "--status", "draft", *R)[1]["data"], [])


if __name__ == "__main__":
    unittest.main()
