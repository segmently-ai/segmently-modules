import tempfile
import unittest
from pathlib import Path

from modsys.config import enabled_roles, load_config
from modsys.merge import merge
from modsys.output import UsageError


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class MergeTest(unittest.TestCase):
    def test_scalar_override_and_deep_merge(self):
        self.assertEqual(merge({"a": 1, "t": {"x": 1, "y": 2}}, {"a": 2, "t": {"y": 3}}),
                         {"a": 2, "t": {"x": 1, "y": 3}})

    def test_scalar_arrays_append_dedupe(self):
        self.assertEqual(merge(["a", "b"], ["b", "c"]), ["a", "b", "c"])

    def test_keyed_arrays_merge_by_id(self):
        base = [{"id": "h1", "run": ["a"], "enabled": True}]
        got = merge(base, [{"id": "h1", "enabled": False}, {"id": "h2", "run": ["b"]}])
        self.assertEqual(got, [{"id": "h1", "run": ["a"], "enabled": False},
                               {"id": "h2", "run": ["b"]}])


class LoadConfigTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cfg = Path(self._tmp.name) / ".modsys"

    def tearDown(self):
        self._tmp.cleanup()

    def test_core_defaults_without_config_dir(self):
        config = load_config(self.cfg)
        self.assertEqual(enabled_roles(config), ["developer", "qa", "po", "architect"])
        self.assertEqual(config["match"]["keyword_weight"], 3)
        self.assertEqual(config["_packs"], [])

    def test_pack_adds_role_and_team_then_user_override(self):
        write(self.cfg / "packs/ui/pack.toml",
              'id = "ui"\npriority = 20\n[roles.designer]\norder = 50\n'
              '[fields.figma_url]\ntype = "string"\n')
        write(self.cfg / "config.toml", "[match]\ntop = 5\n")
        write(self.cfg / "config.user.toml", "[match]\ntop = 3\n")
        config = load_config(self.cfg)
        self.assertEqual(enabled_roles(config),
                         ["developer", "qa", "po", "architect", "designer"])
        self.assertEqual(config["match"]["top"], 3)
        self.assertEqual(config["_packs"], ["ui"])
        self.assertEqual(config["fields"]["figma_url"]["owner"], "ui")
        self.assertNotIn("priority", config)  # pack meta keys are not merged

    def test_lower_priority_number_wins(self):
        write(self.cfg / "packs/a/pack.toml", 'id = "a"\npriority = 10\n[match]\ntop = 4\n')
        write(self.cfg / "packs/b/pack.toml", 'id = "b"\npriority = 90\n[match]\ntop = 9\n')
        self.assertEqual(load_config(self.cfg)["match"]["top"], 4)

    def test_role_can_be_disabled(self):
        write(self.cfg / "config.toml", "[roles.po]\nenabled = false\n")
        self.assertEqual(enabled_roles(load_config(self.cfg)),
                         ["developer", "qa", "architect"])

    def test_malformed_pack_is_usage_error_naming_file(self):
        write(self.cfg / "packs/bad/pack.toml", "id = \n")
        with self.assertRaises(UsageError) as ctx:
            load_config(self.cfg)
        self.assertIn("packs/bad/pack.toml", str(ctx.exception))

    def test_equal_priority_tie_resolved_by_id(self):  # AC-008
        write(self.cfg / "packs/b/pack.toml", 'id = "b"\npriority = 20\n[match]\ntop = 9\n')
        write(self.cfg / "packs/a/pack.toml", 'id = "a"\npriority = 20\n[match]\ntop = 4\n')
        config = load_config(self.cfg)
        self.assertEqual(config["match"]["top"], 4)
        self.assertEqual(config["_packs"], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
