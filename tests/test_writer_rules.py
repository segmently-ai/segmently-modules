"""Writers refuse what lint reports as an ERROR for the field (status, related_modules edges):
one shared rule set (modsys.rules), so a validated write never creates a lint error."""
import json
import tempfile
import unittest

from modsys.rules import edge_problems, status_problem
from tests.helpers import copy_fixture, mutate_registry, run, run_json

MODULES = {"catalog": {}, "payments": {"submodules": {"refunds": {}}}}
RELATIONS = ["depends-on", "complements"]
GOOD = {"module": "payments/refunds", "relation": "depends-on", "description": "Refund lines"}
BAD_EDGES = [  # (edge, the lint code a writer names and lint reports)
    ({**GOOD, "relation": "uses"}, "MS006"),
    ({k: v for k, v in GOOD.items() if k != "description"}, "MS007"),
    ({k: v for k, v in GOOD.items() if k != "module"}, "MS008"),
    ({**GOOD, "module": "ghost"}, "MS009"),
    ({**GOOD, "module": "payments/ghost"}, "MS010"),
]


class RulesTest(unittest.TestCase):
    def test_status_and_edge_rules(self):
        self.assertIsNone(status_problem("active", ["active"]))
        self.assertEqual(status_problem("gone", ["active"]), ("MS003", "status 'gone' not in ['active']"))
        self.assertEqual(edge_problems(GOOD, MODULES, RELATIONS), [])
        self.assertEqual(edge_problems({"relation": "x"}, MODULES, RELATIONS),
                         [("MS006", "relation 'x' not in ['depends-on', 'complements']"),
                          ("MS007", "missing description"), ("MS008", "missing module target")])


class WriterRulesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        self.path = self.root / "modules" / "registry.json"
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def refused(self, *argv):
        before = self.path.read_bytes()
        code, out, err = run(*argv, *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(self.path.read_bytes(), before)
        return err

    def lint_codes(self):
        _, env, _ = run_json("lint", "--fail-on", "never", *self.R)
        return {f["code"] for f in env["data"]["findings"] if f["severity"] == "error"}

    def test_status_outside_the_configured_statuses_is_refused(self):
        err = self.refused("registry", "set", "catalog", "status", '"shipped"')
        self.assertIn("field 'status': status 'shipped' not in", err)
        self.assertIn("(lint MS003)", err)
        (self.root / ".modsys" / "config.toml").write_text('[registry]\nstatuses = ["shipped"]\n')
        self.assertEqual(run("registry", "set", "catalog", "status", '"shipped"', *self.R)[0], 0)
        self.assertNotIn("MS003", self.lint_codes())

    def test_each_bad_edge_is_refused_with_the_code_lint_reports(self):
        for edge, code in BAD_EDGES:
            with self.subTest(code=code):
                err = self.refused("registry", "append", "catalog", "related_modules",
                                   json.dumps(edge))
                self.assertIn("field 'related_modules': appended edge:", err)
                self.assertIn(f"(lint {code})", err)
                with tempfile.TemporaryDirectory() as tmp:  # lint agrees on the same edge
                    root = copy_fixture(tmp)
                    mutate_registry(root, lambda r: r["modules"]["catalog"]
                                    ["related_modules"].append(edge))
                    _, env, _ = run_json("lint", "--fail-on", "never", "--root", str(root))
                    self.assertIn(code, {f["code"] for f in env["data"]["findings"]})

    def test_good_edge_is_written_and_lint_stays_free_of_errors(self):
        code, env, _ = run_json("registry", "append", "catalog", "related_modules",
                                json.dumps(GOOD), *self.R)
        self.assertEqual((code, env["data"]["changed"]), (0, True))
        self.assertEqual(self.lint_codes(), set())

    def test_set_names_the_bad_edge_by_index(self):
        err = self.refused("registry", "set", "catalog", "related_modules",
                           json.dumps([GOOD, BAD_EDGES[1][0]]))
        self.assertIn("related_modules[1]: missing description (lint MS007)", err)

    def test_removing_a_bad_edge_is_allowed(self):
        bad = BAD_EDGES[1][0]
        mutate_registry(self.root, lambda r: r["modules"]["catalog"]["related_modules"].append(bad))
        self.assertIn("MS007", self.lint_codes())
        self.assertEqual(run("registry", "remove", "catalog", "related_modules", json.dumps(bad),
                             *self.R)[0], 0)
        self.assertNotIn("MS007", self.lint_codes())

    def test_proposals_are_refused_at_propose_time(self):
        code, out, err = run("propose", "--module", "catalog", "--op", "append", "--field",
                             "related_modules", "--value", json.dumps(BAD_EDGES[0][0]),
                             "--reason", "r", "--run-id", "r1", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("(lint MS006)", err)
        self.assertEqual(list((self.root / ".modsys").glob("proposals/*.json")), [])


if __name__ == "__main__":
    unittest.main()
