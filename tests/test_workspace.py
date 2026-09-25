import os
import tempfile
import unittest
from pathlib import Path

from modsys.config import load_config
from modsys.output import UsageError
from modsys.registry import load_registry, resolve_module_arg, stub_head
from modsys.workspace import find_root
from tests.helpers import FIXTURE, run_json


class WorkspaceTest(unittest.TestCase):
    def test_schema_verb_includes_pack_declared_field(self):
        code, env, _ = run_json("schema", "--root", str(FIXTURE))
        self.assertEqual(code, 0)
        self.assertEqual(env["schema"], "modsys.schema/1")
        module = env["data"]["properties"]["modules"]["additionalProperties"]
        self.assertIn("file_paths", module["properties"])

    def test_root_autodetected_from_subdirectory(self):
        cwd = os.getcwd()
        try:
            os.chdir(FIXTURE / "src" / "catalog")
            code, env, _ = run_json("schema")
        finally:
            os.chdir(cwd)
        self.assertEqual(code, 0)
        module = env["data"]["properties"]["modules"]["additionalProperties"]
        self.assertIn("file_paths", module["properties"])


class RegistryTest(unittest.TestCase):
    def test_missing_registry_names_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(UsageError) as ctx:
                load_registry(Path(tmp) / "modules" / "registry.json")
        self.assertIn("modules/registry.json", str(ctx.exception))

    def test_invalid_json_names_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "registry.json"
            p.write_text("{", encoding="utf-8")
            with self.assertRaises(UsageError) as ctx:
                load_registry(p)
        self.assertIn("registry.json", str(ctx.exception))

    def test_resolve_module_arg(self):
        self.assertEqual(resolve_module_arg("catalog", "modules"), "catalog")
        self.assertEqual(resolve_module_arg("payments/refunds", "modules"), "payments/refunds")
        self.assertEqual(resolve_module_arg(
            "/abs/repo/modules/payments/submodules/refunds/MODULE.md", "modules"),
            "payments/refunds")

    def test_stub_head(self):
        config = load_config(FIXTURE / ".modsys")
        self.assertIn("retired", stub_head(FIXTURE, config, "legacy-search"))
        self.assertIsNone(stub_head(FIXTURE, config, "catalog"))


class RootAndRegistryGapTest(unittest.TestCase):  # AC-014, AC-015
    def test_git_only_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            (repo / ".git").mkdir(parents=True)
            (repo / "a" / "b").mkdir(parents=True)
            self.assertEqual(find_root(repo / "a" / "b"), repo.resolve())

    def test_registry_only_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            (repo / "modules").mkdir(parents=True)
            (repo / "modules" / "registry.json").write_text('{"modules": {}}')
            (repo / "deep").mkdir()
            self.assertEqual(find_root(repo / "deep"), repo.resolve())

    def test_nearest_git_stops_the_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            outer = Path(tmp) / "outer"
            (outer / "modules").mkdir(parents=True)
            (outer / "modules" / "registry.json").write_text('{"modules": {}}')
            inner = outer / "inner"
            (inner / ".git").mkdir(parents=True)
            (inner / "sub").mkdir()
            self.assertEqual(find_root(inner / "sub"), inner.resolve())

    def test_no_markers_is_usage_error(self):
        # assumes the system temp dir is not inside a git checkout (default on macOS/Linux)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(UsageError) as ctx:
                find_root(Path(tmp))
        self.assertIn("--root", str(ctx.exception))

    def test_modules_not_an_object(self):
        for text in ("[]", '{"modules": []}'):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp) / "registry.json"
                p.write_text(text, encoding="utf-8")
                with self.assertRaises(UsageError) as ctx:
                    load_registry(p)
                self.assertIn("no 'modules' object", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
