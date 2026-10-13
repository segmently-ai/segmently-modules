"""`segmently-modules code-map list` / `files`, and the actionable `[[code_map]]` config errors."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import init_git, make_repo, mutate_registry, run, run_json

PACK = '[[code_map]]\nid = "src"\npattern = "src/{module}/**"\n'
TEAM = '[[code_map]]\nid = "tasks-extra"\nmodule = "tasks"\nglobs = ["lib/tasks/**", "bin/t*"]\n'
USER = '[[code_map]]\nid = "src"\npattern = "src/{module}/**"\nexclusive = true\n'
FIELD = ('[fields.code_paths]\ntype = "string[]"\nkind = "code_pointer"\n'
         'scope = ["module", "submodule"]\n')


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class CodeMapListTest(unittest.TestCase):  # P32-AC-008
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_repo(self._tmp.name, {"tasks": ["task"], "tasks/due": ["due"],
                                               "lists": ["list"]})
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def layers(self):
        write(self.root / ".segmently-modules/packs/acme/pack.toml", 'id = "acme"\n' + PACK)
        write(self.root / ".segmently-modules/config.toml",
              TEAM + '[[code_map]]\nid = "due"\nmodule = "tasks/due"\nglobs = ["lib/due/**"]\n')
        write(self.root / ".segmently-modules/config.user.toml", USER)

    def rows(self, *argv):
        code, env, err = run_json("code-map", "list", *argv, *self.R)
        self.assertEqual((code, err, env["schema"]), (0, "", "segmently-modules.code-map/1"))
        return env["data"]

    def test_no_rules(self):
        self.assertEqual(self.rows(), [])
        self.assertEqual(run("code-map", "list", *self.R)[1], "no [[code_map]] rules\n")

    def test_effective_rules_from_every_layer(self):
        self.layers()
        self.assertEqual(self.rows(), [
            {"id": "src", "module": None, "pattern": "src/{module}/**", "globs": None,
             "exclusive": True},
            {"id": "tasks-extra", "module": "tasks", "pattern": None,
             "globs": ["lib/tasks/**", "bin/t*"], "exclusive": False},
            {"id": "due", "module": "tasks/due", "pattern": None, "globs": ["lib/due/**"],
             "exclusive": False}])
        out = run("code-map", "list", *self.R)[1].splitlines()
        self.assertEqual(out[0].split(), ["src", "{module}", "src/{module}/**", "exclusive"])

    def test_filter_by_target(self):
        self.layers()
        self.assertEqual([r["id"] for r in self.rows("--module", "tasks")], ["src", "tasks-extra"])
        self.assertEqual([r["id"] for r in self.rows("--module", "tasks/due")], ["due"])
        self.assertEqual([r["id"] for r in self.rows("--module", "lists")], ["src"])

    def test_unknown_target_and_usage(self):
        for argv, needle in [(("list", "--module", "nosuch"), "unknown module 'nosuch'"),
                             (("list", "--module", "task"), "closest: tasks, tasks/due"),
                             (("list", "tasks"), "code-map list takes no TARGET"),
                             (("files",), "code-map files needs a TARGET"),
                             (("files", "tasks", "--module", "tasks"), "takes no --module")]:
            with self.subTest(argv=argv):
                code, out, err = run("code-map", *argv, "--json", *self.R)
                self.assertEqual((code, out), (2, ""))
                self.assertIn(needle, err)


class CodeMapFilesTest(unittest.TestCase):  # P32-AC-009
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_repo(
            self._tmp.name, {"tasks": ["task"], "tasks/due": ["due"], "db": ["database"]},
            PACK + '[[code_map]]\nid = "db"\nmodule = "db"\nglobs = ["app/**"]\n'
            '[[code_map]]\nid = "repos"\npattern = "app/repositories/{module}.py"\n'
            'exclusive = true\n' + FIELD,
            files=("src/tasks/a.py", "lib/due.py", "app/repositories/tasks.py",
                   "app/session.py", "src/tasks/cache.pyc"))
        mutate_registry(self.root, lambda d: d["modules"]["tasks"].update(
            code_paths=["lib/due.py"]))
        write(self.root / ".gitignore", "*.pyc\n")
        init_git(self.root)
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def files(self, target):
        code, env, err = run_json("code-map", "files", target, *self.R)
        self.assertEqual((code, err, env["schema"]), (0, "", "segmently-modules.code-map/1"))
        self.assertEqual(env["data"]["target"], target)
        self.assertEqual(env["data"]["total"], len(env["data"]["files"]))
        return {f["path"]: f["via"] for f in env["data"]["files"]}

    def test_every_source_per_file(self):
        write(self.root / "src/tasks/new.py", "x = 1\n")  # untracked, not ignored
        self.assertEqual(self.files("tasks"), {
            "app/repositories/tasks.py": ["code_map:repos"],
            "lib/due.py": ["code_pointer:code_paths"],
            "modules/tasks/MODULE.md": ["docs"],
            "src/tasks/a.py": ["code_map:src"],
            "src/tasks/new.py": ["code_map:src"]})
        self.assertEqual(self.files("db"), {"app/session.py": ["code_map:db"],
                                            "modules/db/MODULE.md": ["docs"]})
        self.assertEqual(self.files("tasks/due"),
                         {"modules/tasks/submodules/due/MODULE.md": ["docs"]})
        out = run("code-map", "files", "db", *self.R)[1].splitlines()
        self.assertEqual(out, ["app/session.py  (code_map:db)", "modules/db/MODULE.md  (docs)",
                               "2 file(s) map to db"])

    def test_coverage_filters_do_not_apply(self):
        write(self.root / ".segmently-modules/config.user.toml", '[coverage]\nexclude = ["src/**"]\n')
        self.assertIn("src/tasks/a.py", self.files("tasks"))

    def test_refusals(self):
        code, out, err = run("code-map", "files", "nosuch", "--json", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("unknown module 'nosuch'", err)
        with tempfile.TemporaryDirectory() as tmp:
            plain = make_repo(tmp, {"tasks": ["task"]})
            code, out, err = run("code-map", "files", "tasks", "--json", "--root", str(plain))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("code-map files needs a git repository", err)


class CodeMapContractTest(unittest.TestCase):  # P32-AC-022 (list / files)
    def test_garbage_config_and_interrupt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp, {"tasks": ["task"]}, "code_map = 5\n")
            code, out, err = run("code-map", "list", "--json", "--root", str(root))
            self.assertEqual((code, out), (2, ""))
            self.assertTrue(err.startswith("segmently-modules: error:"), err)
            self.assertNotIn("Traceback", err)
            (root / ".segmently-modules/config.toml").write_text("")
            with mock.patch("segmently_modules.code_map_cmd.rule_rows", side_effect=KeyboardInterrupt):
                self.assertEqual(run("code-map", "list", "--root", str(root))[0], 130)


class PatternWordingTest(unittest.TestCase):  # P32-AC-013
    def refused(self, config: str, where: str = "config.toml") -> str:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp, {"tasks": ["task"]})
            path = (root / ".segmently-modules" / "config.toml" if where == "config.toml"
                    else root / ".segmently-modules" / "packs" / "acme" / "pack.toml")
            write(path, config)
            code, out, err = run("code-map", "list", "--root", str(root))
            self.assertIn(str(path.resolve()), err)
        self.assertEqual((code, out), (2, ""))
        return err

    def test_pattern_without_module_segment(self):
        self.assertIn('code_map.d: pattern "docs/**" has no {module} segment — for a fixed '
                      'module use globs = ["docs/**"] and module = "tasks"',
                      self.refused('[[code_map]]\nid = "d"\npattern = "docs/**"\n'
                                   'module = "tasks"\n'))
        self.assertIn('and module = "NAME"',
                      self.refused('[[code_map]]\nid = "d"\npattern = "docs/**"\n'))

    def test_empty_module(self):
        self.assertIn("code_map.e: module must be a non-empty module or parent/child name",
                      self.refused('[[code_map]]\nid = "e"\nglobs = ["x/**"]\nmodule = ""\n'))

    def test_in_a_pack(self):
        self.refused('id = "acme"\n[[code_map]]\nid = "d"\npattern = "docs/**"\n', "pack")


if __name__ == "__main__":
    unittest.main()
