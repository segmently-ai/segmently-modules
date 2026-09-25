"""modsys migrate: content-detected upgrades of old registry shapes."""
import json
import tempfile
import unittest

from tests.helpers import copy_fixture, mutate_registry, run, run_json


def old_shape(d) -> None:
    """A synthetic pre-migration registry: legacy context keys and flat dependencies."""
    cat = d["modules"]["catalog"]
    items = list(cat.items())
    cat.clear()
    cat.update(("context_paths" if k == "context_files" else k, v) for k, v in items)
    d["modules"]["checkout"]["depends_on_modules"] = ["catalog", "payments"]
    d["modules"]["checkout"]["related_modules"].append(
        {"module": "catalog", "relation": "depends-on", "description": "already there"})
    refunds = d["modules"]["payments"]["submodules"]["refunds"]
    refunds["contextPaths"] = refunds.pop("context_files")


class MigrateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def reg(self):
        return json.loads((self.root / "modules/registry.json").read_text())["modules"]

    def test_current_fixture_has_nothing_to_migrate(self):
        before = (self.root / "modules/registry.json").read_bytes()
        code, env, _ = run_json("migrate", *self.R)
        self.assertEqual((code, env["schema"], env["data"]["applied"]), (0, "modsys.migrate/1", []))
        self.assertEqual((self.root / "modules/registry.json").read_bytes(), before)

    def test_old_shape_migrates_and_lints_clean(self):
        original_order = list(self.reg()["catalog"])
        mutate_registry(self.root, old_shape)
        code, env, _ = run_json("migrate", *self.R)
        self.assertEqual([m["id"] for m in env["data"]["applied"]], ["001", "002"])
        reg = self.reg()
        self.assertEqual(list(reg["catalog"]), original_order)  # key kept in place
        self.assertIn("context_files", reg["payments"]["submodules"]["refunds"])
        self.assertNotIn("depends_on_modules", reg["checkout"])
        edges = [(e["module"], e["relation"]) for e in reg["checkout"]["related_modules"]]
        self.assertEqual(edges.count(("catalog", "depends-on")), 1)  # no duplicate edge
        self.assertIn(("payments", "depends-on"), edges)
        self.assertEqual(run("lint", *self.R)[0], 0)
        _, env, _ = run_json("migrate", *self.R)
        self.assertEqual(env["data"]["applied"], [])  # idempotent

    def test_conflict_is_reported_and_left_alone(self):
        mutate_registry(self.root, lambda d: d["modules"]["catalog"].update(
            context_paths={"universal": "modules/catalog/MODULE.md"}))
        _, env, _ = run_json("migrate", *self.R)
        self.assertIn("catalog: kept 'context_paths' — context_files already exists",
                      env["data"]["applied"][0]["notes"][0])
        self.assertIn("context_paths", self.reg()["catalog"])

    def test_only_and_dry_run(self):
        mutate_registry(self.root, old_shape)
        before = (self.root / "modules/registry.json").read_bytes()
        code, env, _ = run_json("migrate", "--only", "002", "--dry-run", *self.R)
        self.assertEqual([m["id"] for m in env["data"]["applied"]], ["002"])
        self.assertIn('-      "depends_on_modules": [', env["data"]["diff"])
        self.assertEqual((self.root / "modules/registry.json").read_bytes(), before)
        code, _, err = run("migrate", "--only", "999", *self.R)
        self.assertEqual(code, 2)
        self.assertIn("unknown migration '999'", err)


if __name__ == "__main__":
    unittest.main()
