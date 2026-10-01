"""per-module registry layout: module.json per module + generated index."""
import json
import tempfile
import unittest

from tests.helpers import copy_fixture, run, run_json

READ_VERBS = [("match", "refund a partial refund for an order"), ("show", "catalog", "--all-roles"),
              ("show", "payments/refunds", "--role", "developer"), ("related", "payments"),
              ("list",), ("lint", "--fail-on", "never"), ("schema",)]


def convert(root) -> None:
    """Split the fixture's registry into module.json files and switch the layout."""
    assert run("index", "split", "--root", str(root))[0] == 0
    (root / ".modsys" / "config.toml").write_text(
        '[paths]\nregistry_layout = "per-module"\n', encoding="utf-8")


class PerModuleLayoutTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.single = copy_fixture(f"{self._tmp.name}/a")
        self.per = copy_fixture(f"{self._tmp.name}/b")
        convert(self.per)

    def tearDown(self):
        self._tmp.cleanup()

    def test_split_writes_one_file_per_module(self):
        entry = json.loads((self.per / "modules" / "payments" / "module.json").read_text())
        self.assertEqual(entry["submodules"]["refunds"]["keywords"], ["refund", "partial refund"])
        self.assertFalse((self.per / "modules" / "legacy-search" / "module.json").exists())

    def test_read_verbs_identical_in_both_layouts(self):
        for argv in READ_VERBS:
            with self.subTest(argv=argv):
                a = run_json(*argv, "--root", str(self.single))
                b = run_json(*argv, "--root", str(self.per))
                self.assertEqual(a[:2], b[:2])

    def test_readers_use_module_files_even_when_index_is_stale(self):
        (self.per / "modules" / "registry.json").write_text('{"modules": {}}\n', encoding="utf-8")
        _, env, _ = run_json("list", "--root", str(self.per))
        self.assertEqual([r["module"] for r in env["data"]], ["catalog", "checkout", "payments"])

    def test_writer_touches_only_the_changed_module_file(self):
        others = {m: (self.per / "modules" / m / "module.json").read_bytes()
                  for m in ("checkout", "payments")}
        index = (self.per / "modules" / "registry.json").read_bytes()
        run("registry", "set", "catalog", "status", '"draft"', "--root", str(self.per))
        entry = json.loads((self.per / "modules" / "catalog" / "module.json").read_text())
        self.assertEqual(entry["status"], "draft")
        for m, before in others.items():
            self.assertEqual((self.per / "modules" / m / "module.json").read_bytes(), before)
        self.assertEqual((self.per / "modules" / "registry.json").read_bytes(), index)

    def test_index_check_and_build(self):
        R = ("--root", str(self.per))
        self.assertEqual(run("index", "build", "--check", *R)[0], 0)
        run("registry", "set", "catalog", "status", '"draft"', *R)
        code, env, _ = run_json("index", "build", "--check", *R)
        self.assertEqual((code, env["data"]["stale"], env["data"]["written"]), (1, True, False))
        code, env, _ = run_json("index", "build", *R)
        self.assertEqual((code, env["data"]["written"]), (0, True))
        index = json.loads((self.per / "modules" / "registry.json").read_text())
        self.assertEqual(index["modules"]["catalog"]["status"], "draft")
        self.assertEqual(index["version"], json.loads(  # top-level keys survive rebuilds
            (self.single / "modules" / "registry.json").read_text())["version"])
        self.assertEqual(run("index", "build", "--check", *R)[0], 0)

    def test_index_build_stamps_updated_at_only_when_modules_changed(self):
        R = ("--root", str(self.per))
        (self.per / ".modsys" / "config.toml").write_text(
            '[paths]\nregistry_layout = "per-module"\n'
            '[registry]\nupdated_at_path = "metadata.last_updated"\n', encoding="utf-8")
        run("index", "build", *R)
        self.assertEqual(json.loads((self.per / "modules" / "registry.json").read_text())
                         ["metadata"]["last_updated"], "2026-01-01T00:00:00Z")
        run("registry", "set", "catalog", "status", '"draft"', *R)
        run("index", "build", *R)
        self.assertNotEqual(json.loads((self.per / "modules" / "registry.json").read_text())
                            ["metadata"]["last_updated"], "2026-01-01T00:00:00Z")

    def test_refusals(self):
        code, _, err = run("index", "build", "--root", str(self.single))
        self.assertEqual(code, 2)
        self.assertIn('registry_layout = "per-module"', err)
        (self.per / "modules" / "catalog" / "module.json").write_text("{", encoding="utf-8")
        code, _, err = run("list", "--root", str(self.per))
        self.assertEqual(code, 2)
        self.assertIn("catalog/module.json: invalid JSON", err)
        (self.single / ".modsys" / "config.toml").write_text(
            '[paths]\nregistry_layout = "sharded"\n', encoding="utf-8")
        code, _, err = run("list", "--root", str(self.single))
        self.assertEqual(code, 2)
        self.assertIn("registry_layout: expected one of", err)

    def test_split_refuses_to_overwrite_a_different_file(self):
        (self.single / "modules" / "catalog" / "module.json").write_text('{"x": 1}\n')
        code, _, err = run("index", "split", "--root", str(self.single))
        self.assertEqual(code, 2)
        self.assertIn("exists with different content", err)

    def test_split_dry_run_writes_nothing(self):
        code, env, _ = run_json("index", "split", "--dry-run", "--root", str(self.single))
        self.assertEqual(code, 0)
        self.assertEqual(env["data"]["files"], ["modules/catalog/module.json",
                                                "modules/checkout/module.json",
                                                "modules/payments/module.json"])
        self.assertFalse((self.single / "modules" / "catalog" / "module.json").exists())


class MissingIndexTest(unittest.TestCase):  # AC-014
    def test_index_build_creates_a_missing_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            convert(root)
            (root / "modules" / "registry.json").unlink()
            code, env, _ = run_json("index", "build", "--root", str(root))
            self.assertEqual((code, env["data"]["stale"], env["data"]["written"]), (0, True, True))
            index = json.loads((root / "modules" / "registry.json").read_text())
            self.assertEqual(sorted(index["modules"]), ["catalog", "checkout", "payments"])


if __name__ == "__main__":
    unittest.main()
