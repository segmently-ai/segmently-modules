"""`modsys init`: starter config, empty registry, .gitignore lines — idempotent."""
import os
import tempfile
import tomllib
import unittest
from pathlib import Path

from modsys.config import core_defaults, validate_layer
from modsys.fields import load_field_defs
from modsys.init_cmd import starter_config
from modsys.merge import merge
from modsys.workspace import Workspace
from tests.helpers import git, run, run_json

EMPTY_REGISTRY = '{\n  "modules": {}\n}\n'
IGNORE_LINES = ["modules/registry.json.lock", ".modsys/proposals/"]


def snapshot(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file() and ".git" not in p.relative_to(root).parts}


class InitTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve() / "repo"
        self.root.mkdir()
        git(self.root, "init", "-q", "-b", "main")
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def init(self, *argv):
        return run_json("init", *argv, *self.R)

    def test_empty_repo_gets_config_registry_and_gitignore(self):
        code, env, err = self.init()
        self.assertEqual((code, err, env["schema"]), (0, "", "modsys.init/1"))
        self.assertEqual(env["data"]["files"], [
            {"path": ".modsys/config.toml", "status": "created"},
            {"path": "modules/registry.json", "status": "created"},
            {"path": ".gitignore", "status": "created"}])
        self.assertEqual((env["data"]["layout"], env["data"]["dry_run"]), ("single", False))
        self.assertEqual(env["data"]["root"], str(self.root))
        self.assertEqual((self.root / "modules/registry.json").read_text(), EMPTY_REGISTRY)
        self.assertEqual((self.root / ".gitignore").read_text().splitlines(), IGNORE_LINES)
        self.assertEqual(run_json("list", *self.R)[:2], (0, {"schema": "modsys.list/1",
                                                            "data": []}))
        self.assertEqual(run("lint", *self.R)[0], 0)

    def test_second_run_changes_nothing(self):
        self.init()
        before = snapshot(self.root)
        code, env, _ = self.init()
        self.assertEqual(code, 0)
        self.assertEqual({f["status"] for f in env["data"]["files"]}, {"exists"})
        self.assertEqual(snapshot(self.root), before)

    def test_existing_gitignore_gets_only_the_missing_lines(self):
        (self.root / ".gitignore").write_text("node_modules/\n.modsys/proposals/")
        _, env, _ = self.init()
        self.assertIn({"path": ".gitignore", "status": "updated"}, env["data"]["files"])
        self.assertEqual((self.root / ".gitignore").read_text(),
                         "node_modules/\n.modsys/proposals/\nmodules/registry.json.lock\n")
        self.assertIn({"path": ".gitignore", "status": "exists"}, self.init()[1]["data"]["files"])

    def test_existing_registry_is_kept(self):
        reg = self.root / "modules/registry.json"
        reg.parent.mkdir()
        reg.write_text('{"modules": {"x": {}}}\n')
        _, env, _ = self.init()
        self.assertIn({"path": "modules/registry.json", "status": "exists"}, env["data"]["files"])
        self.assertEqual(reg.read_text(), '{"modules": {"x": {}}}\n')

    def test_dry_run_writes_nothing(self):
        code, env, _ = self.init("--dry-run")
        self.assertEqual((code, env["data"]["dry_run"]), (0, True))
        self.assertEqual({f["status"] for f in env["data"]["files"]}, {"created"})
        self.assertEqual(snapshot(self.root), {})
        code, out, _ = run("init", "--dry-run", *self.R)
        self.assertIn("would create  .modsys/config.toml", out)

    def test_text_output_states_the_root_first(self):
        """A user running `init` from a subdirectory sees where files went (M7): the plain-text
        render's first line is `root: <path>` (the JSON `data.root` already has it)."""
        code, out, _ = run("init", *self.R)
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[0], f"root: {self.root}")

    def test_per_module_layout(self):
        code, env, _ = self.init("--layout", "per-module")
        self.assertEqual((code, env["data"]["layout"]), (0, "per-module"))
        self.assertIn('\n[paths]\nregistry_layout = "per-module"',
                      (self.root / ".modsys/config.toml").read_text())
        self.assertEqual(Workspace.load(self.root).config["paths"]["registry_layout"],
                         "per-module")
        self.assertEqual((self.root / "modules/registry.json").read_text(), EMPTY_REGISTRY)
        code, _, err = run("create", "orders", "--description", "Order intake and order history.",
                           *[a for k in "abcde" for a in ("--keyword", f"order-{k}")],
                           "--non-interactive", *self.R)
        self.assertEqual((code, err), (0, ""))
        self.assertTrue((self.root / "modules/orders/module.json").is_file())
        self.assertEqual(self.init("--layout", "per-module")[0], 0)  # idempotent too

    def test_layout_that_conflicts_with_the_config_is_refused(self):
        self.init()
        before = snapshot(self.root)
        code, out, err = run("init", "--layout", "per-module", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("conflicts with the configured registry_layout 'single'", err)
        self.assertEqual(snapshot(self.root), before)

    def test_layout_over_an_existing_registry_is_refused(self):
        reg = self.root / "modules/registry.json"
        reg.parent.mkdir()
        reg.write_text('{"modules": {"x": {}}}\n')
        before = snapshot(self.root)
        code, out, err = run("init", "--layout", "per-module", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("conflicts with the configured registry_layout 'single'", err)
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse((self.root / ".modsys/config.toml").exists())
        self.assertEqual(reg.read_text(), '{"modules": {"x": {}}}\n')

    def test_root_defaults_to_the_git_top_level_else_cwd(self):
        sub = self.root / "a" / "b"
        sub.mkdir(parents=True)
        plain = Path(self._tmp.name).resolve() / "plain"
        plain.mkdir()
        cwd = os.getcwd()
        try:
            os.chdir(sub)
            code, env, _ = run_json("init")
            os.chdir(plain)
            code2, env2, _ = run_json("init", "--dry-run")
        finally:
            os.chdir(cwd)
        self.assertEqual((code, env["data"]["root"]), (0, str(self.root)))
        self.assertTrue((self.root / ".modsys/config.toml").is_file())
        self.assertFalse((sub / ".modsys").exists())
        self.assertEqual((code2, env2["data"]["root"]), (0, str(plain)))

    def test_root_must_be_a_directory(self):
        code, out, err = run("init", "--root", str(self.root / "nope"))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("is not a directory", err)

    def test_registry_not_found_names_the_fix(self):
        code, out, err = run("list", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("registry not found", err)
        self.assertIn("run `modsys init`", err)


class StarterConfigTest(unittest.TestCase):
    def uncommented(self, text: str) -> dict:
        """Every example line (`# key = …`) switched on; prose (`## …`) stays a comment."""
        return tomllib.loads("\n".join(l[2:] if l.startswith("# ") else l
                                       for l in text.splitlines()))

    def test_starter_is_valid_and_sets_nothing_but_the_layout(self):
        self.assertEqual(tomllib.loads(starter_config("single")), {})
        self.assertEqual(tomllib.loads(starter_config("per-module")),
                         {"paths": {"registry_layout": "per-module"}})

    def test_every_worked_example_is_valid_config(self):
        for layout in ("single", "per-module"):
            with self.subTest(layout=layout):
                layer = self.uncommented(starter_config(layout))
                validate_layer(layer, "starter")
                config = merge(core_defaults(), layer)
                self.assertEqual(load_field_defs(config)["code_paths"].kind, "code_pointer")
                rules = {r["id"]: r for r in config["code_map"]}
                self.assertEqual(rules["src"]["pattern"], "src/{module}/**")
                self.assertEqual(rules["catalog-search"]["module"], "catalog/search")
                self.assertIs(rules["catalog-repository"]["exclusive"], True)
                self.assertEqual(config["hooks"]["post_sync"][0]["id"], "notify")
                self.assertEqual(config["coverage"], {"include": ["**"], "exclude": ["docs/**"]})
                self.assertEqual(config["paths"]["registry_layout"], layout)
                self.assertEqual(config["ci"], {"base": "origin/main", "fail_on": "warning",
                                                "coverage_fail_under": 80})  # M-7

    def test_the_exclusive_comment_says_matched_and_routed(self):  # M-7, P31-R2 wording
        self.assertIn("matched and routed", starter_config("single"))
        self.assertNotIn("a file matched by an exclusive rule", starter_config("single"))


if __name__ == "__main__":
    unittest.main()
