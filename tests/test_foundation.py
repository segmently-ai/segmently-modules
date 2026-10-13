"""P3 groundwork: pack provenance, Workspace.load for programmatic callers, registry content hash."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from segmently_modules.config import discover_packs, load_config
from segmently_modules.registry import load_registry
from segmently_modules.workspace import Workspace
from tests.helpers import FIXTURE


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class PackProvenanceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cfg = Path(self._tmp.name) / ".segmently-modules"
        write(self.cfg / "packs/ui/pack.toml",
              'id = "ui"\npriority = 20\n'
              '[roles.designer]\norder = 50\ntemplate = "roles/designer.md"\n'
              '[fields.figma_url]\ntype = "string"\n'
              '[[hooks.post_sync]]\nid = "notify"\nrun = ["./hooks/notify.py"]\n')

    def tearDown(self):
        self._tmp.cleanup()

    def test_roles_fields_and_hooks_record_their_pack(self):
        config = load_config(self.cfg)
        self.assertEqual(config["roles"]["designer"]["owner"], "ui")
        self.assertEqual(config["fields"]["figma_url"]["owner"], "ui")
        self.assertEqual(config["hooks"]["post_sync"][0]["owner"], "ui")
        self.assertNotIn("owner", config["roles"]["developer"])  # core role

    def test_pack_dirs_map_ids_to_directories(self):
        config = load_config(self.cfg)
        self.assertEqual(config["_pack_dirs"], {"ui": str(self.cfg / "packs" / "ui")})

    def test_parsed_pack_data_is_not_mutated(self):
        load_config(self.cfg)
        data = discover_packs(self.cfg)[0]["data"]
        self.assertNotIn("owner", data["roles"]["designer"])
        self.assertNotIn("owner", data["hooks"]["post_sync"][0])

    def test_team_config_keeps_pack_owner_when_disabling_a_hook(self):
        write(self.cfg / "config.toml", '[[hooks.post_sync]]\nid = "notify"\nenabled = false\n')
        hook = load_config(self.cfg)["hooks"]["post_sync"][0]
        self.assertEqual((hook["owner"], hook["enabled"]), ("ui", False))


class WorkspaceLoadTest(unittest.TestCase):
    def test_load_without_argparse(self):
        ws = Workspace.load(FIXTURE)
        self.assertEqual(ws.root, FIXTURE.resolve())
        self.assertEqual(ws.config_dir, (FIXTURE / ".segmently-modules").resolve())
        self.assertIn("catalog", ws.registry.modules)
        self.assertIn("file_paths", ws.fields)

    def test_load_with_explicit_config_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace.load(FIXTURE, Path(tmp))
            self.assertNotIn("file_paths", ws.fields)  # the fixture pack is not loaded


class RegistryHashTest(unittest.TestCase):
    def test_sha256_of_loaded_bytes(self):
        p = FIXTURE / "modules" / "registry.json"
        self.assertEqual(load_registry(p).sha256, hashlib.sha256(p.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
