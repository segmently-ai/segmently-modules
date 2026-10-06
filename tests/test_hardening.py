"""Hardening: coverage names the real git failure and counts only what it should; `init`
keeps a `.gitignore` intact and states the right conversion; P3.1 rulings and writer refusals
pinned; the suite is isolated from the developer's git setup."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from modsys.output import UsageError
from modsys.workspace import find_root
from tests.helpers import git, init_git, make_repo, run, run_json

LAYERED = ('[[code_map]]\nid = "repos"\npattern = "app/repositories/{module}.py"\n'
           'exclusive = true\n\n[[code_map]]\nid = "db"\nmodule = "db"\n'
           'globs = ["app/repositories/**"]\n')


def write(path: Path, text: str = "x = 1\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class Repo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_repo(self._tmp.name, {"tasks": ["task"], "db": ["database"]},
                              files=("src/tasks/a.py",))
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def refused(self, *argv) -> str:
        code, out, err = run(*argv, *self.R)
        self.assertEqual((code, out), (2, ""))
        return err


class CoverageGitFailureTest(Repo):  # P32-AC-023
    def test_a_plain_directory(self):
        self.assertIn("not inside a work tree", self.refused("coverage"))

    def test_a_broken_repository_names_gits_own_error(self):
        init_git(self.root)
        (self.root / ".git" / "config").write_text("this is [not config\n")
        err = self.refused("coverage")
        self.assertIn("git rev-parse --is-inside-work-tree failed: fatal: bad config line 1", err)
        self.assertNotIn("not inside a work tree", err)

    def test_git_not_installed(self):
        empty = Path(self._tmp.name) / "empty-bin"
        empty.mkdir()
        with mock.patch.dict(os.environ, {"PATH": str(empty)}):
            self.assertIn("git is not installed", self.refused("coverage"))


class CoverageCountedSetTest(Repo):  # P32-AC-024
    def test_an_empty_include_is_refused(self):
        write(self.root / ".modsys/config.toml", "[coverage]\ninclude = []\n")
        err = self.refused("coverage")
        self.assertIn("config.toml: [coverage] include", err)
        self.assertIn("omit include to count every file", err)

    def test_engine_files_never_count(self):
        (self.root / "modules/registry.json").rename(self.root / "registry.json")
        write(self.root / "registry.json.lock", "")
        write(self.root / "queue/r1-a.json", "{}\n")
        write(self.root / "modsys-config/config.toml",
              '[paths]\nregistry = "registry.json"\nproposals_dir = "queue/"\n')
        init_git(self.root)
        code, env, err = run_json("coverage", "--config-dir", str(self.root / "modsys-config"),
                                  *self.R)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual((env["data"]["total"], env["data"]["unmapped"]), (1, ["src/tasks/a.py"]))


class InitGitignoreAndLayoutTest(unittest.TestCase):  # P32-AC-025
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve() / "repo"
        self.root.mkdir()
        git(self.root, "init", "-q", "-b", "main")
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def test_crlf_gitignore_keeps_its_style(self):
        ignore = self.root / ".gitignore"
        ignore.write_bytes(b"node_modules/\r\n")
        self.assertEqual(run("init", *self.R)[0], 0)
        self.assertEqual(ignore.read_bytes(), b"node_modules/\r\nmodules/registry.json.lock\r\n"
                                              b".modsys/proposals/\r\n.modsys/init/\r\n.modsys/config.user.toml\r\n")  # P5a D3

    def test_a_symlinked_gitignore_stays_a_symlink(self):
        shared = self.root / "shared" / "ignore.txt"
        write(shared, "node_modules/\n")
        (self.root / ".gitignore").symlink_to(shared)
        self.assertEqual(run("init", *self.R)[0], 0)
        self.assertTrue((self.root / ".gitignore").is_symlink())
        self.assertEqual(shared.read_text(), "node_modules/\nmodules/registry.json.lock\n"
                                             ".modsys/proposals/\n.modsys/init/\n.modsys/config.user.toml\n")  # P5a D3

    def test_single_to_per_module_names_index_split(self):
        run("init", *self.R)
        code, out, err = run("init", "--layout", "per-module", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("modsys index split", err)

    def test_per_module_to_single_names_the_real_path_and_it_works(self):
        run("init", "--layout", "per-module", *self.R)
        self.assertEqual(run("create", "alpha", "--non-interactive", "--description",
                             "Alpha module for the conversion check.", "--keyword", "a1",
                             "--keyword", "a2", "--keyword", "a3", "--keyword", "a4",
                             "--keyword", "a5", *self.R)[0], 0)
        code, out, err = run("init", "--layout", "single", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertNotIn("index split", err)
        self.assertIn("modsys index build", err)
        self.assertIn('registry_layout = "single"', err)
        run("index", "build", *self.R)  # the path the message states
        config = self.root / ".modsys/config.toml"
        config.write_text(config.read_text().replace('registry_layout = "per-module"',
                                                     'registry_layout = "single"'))
        _, env, _ = run_json("list", *self.R)
        self.assertEqual([r["module"] for r in env["data"]], ["alpha"])


class RulingsTest(Repo):  # P32-AC-026
    def test_p31_r4_ms052_only_in_plain_lint(self):
        write(self.root / ".modsys/config.toml",
              '[[code_map]]\nid = "src"\npattern = "src/{module}/**"\n'
              '[[code_map]]\nid = "typo"\nmodule = "ghost"\nglobs = ["g/**"]\n')
        init_git(self.root)
        write(self.root / "src/tasks/a.py", "x = 2\n")
        _, env, _ = run_json("lint", "--fail-on", "never", *self.R)
        self.assertIn("MS052", [f["code"] for f in env["data"]["findings"]])
        _, env, _ = run_json("lint", "--changed", "--fail-on", "never", *self.R)
        self.assertEqual([f["code"] for f in env["data"]["findings"]], ["MS050"])

    def test_p31_r13_per_module_init_over_existing_module_files(self):
        (self.root / "modules/registry.json").unlink()
        for name in ("a", "b"):
            write(self.root / f"modules/{name}/module.json",
                  json.dumps({"name": name, "description": f"Module {name}."}) + "\n")
        self.assertEqual(run("init", "--layout", "per-module", *self.R)[0], 0)
        index = json.loads((self.root / "modules/registry.json").read_text())
        self.assertEqual(sorted(index["modules"]), ["a", "b"])
        self.assertEqual(run("index", "build", "--check", *self.R)[0], 0)

    def test_p31_r2_a_capture_naming_no_module_leaves_the_file_to_the_layer(self):
        write(self.root / ".modsys/config.toml", LAYERED)
        _, env, _ = run_json("sync", "--files", "app/repositories/base.py",
                             "app/repositories/tasks.py", "--dry-run", *self.R)
        self.assertEqual({m["module"]: m["files"] for m in env["data"]["modules"]},
                         {"db": ["app/repositories/base.py"],
                          "tasks": ["app/repositories/tasks.py"]})


class WriterRefusalPathsTest(Repo):  # P32-AC-027
    def queue(self, items: list) -> Path:
        path = self.root / ".modsys/proposals/q1-pipeline.json"
        write(path, json.dumps({"schema": "modsys.proposal/1", "run_id": "q1",
                                "agent": "pipeline", "created_at": "2026-01-01T00:00:00Z",
                                "items": items}))
        return path

    def registry(self) -> dict:
        return json.loads((self.root / "modules/registry.json").read_text())["modules"]

    def test_dry_run_refuses_first(self):
        before = (self.root / "modules/registry.json").read_bytes()
        err = self.refused("registry", "set", "tasks", "status", '"wip"', "--dry-run")
        self.assertIn("field 'status': status 'wip' not in", err)
        self.assertEqual((self.root / "modules/registry.json").read_bytes(), before)

    def test_hook_and_queued_proposals(self):
        hook = json.dumps({"proposals": [{"op": "set", "module": "tasks", "field": "status",
                                          "value": "wip", "reason": "hook"}]})
        write(self.root / ".modsys/config.toml",
              f'[[hooks.post_sync]]\nid = "gate"\nrequired = true\n'
              f'run = [{json.dumps(sys.executable)}, "-c", {json.dumps(f"print({hook!r})")}]\n')
        self.queue([{"id": "1", "op": "set", "module": "tasks", "field": "status",
                     "value": "wip", "reason": "r", "base_sha256": "x"},
                    {"id": "2", "op": "append", "module": "tasks", "field": "keywords",
                     "value": "todos", "reason": "r"}])
        code, env, _ = run_json("sync", "--files", "src/tasks/a.py", "--apply-proposals",
                                *self.R)
        self.assertEqual(code, 1)
        [hook_result] = env["data"]["hooks"]["hooks"]
        self.assertEqual((hook_result["status"], hook_result["queued"]), ("failed", 0))
        self.assertIn("field 'status': status 'wip' not in", hook_result["error"])
        self.assertIn("(lint MS003)", hook_result["error"])
        [queued] = env["data"]["proposals"]["files"]
        self.assertEqual([r["status"] for r in queued["results"]], ["rejected", "applied"])
        self.assertIn("field 'status': status 'wip' not in ['active'", queued["results"][0]["reason"])
        self.assertEqual((self.registry()["tasks"]["status"], self.registry()["tasks"]["keywords"]),
                         ("active", ["task", "todos"]))

    def test_apply_dry_run_previews_the_rejection(self):
        path = self.queue([{"id": "1", "op": "set", "module": "tasks", "field": "status",
                            "value": "wip", "reason": "r", "base_sha256": "x"}])
        before = (self.root / "modules/registry.json").read_bytes()
        code, env, _ = run_json("proposals", "apply", "--dry-run", *self.R)
        self.assertEqual(code, 1)
        self.assertEqual(env["data"]["files"][0]["results"][0]["status"], "rejected")
        self.assertEqual((self.root / "modules/registry.json").read_bytes(), before)
        self.assertTrue(path.exists())


class IsolationTest(unittest.TestCase):  # P32-AC-028 (the gate runs the suite twice)
    def test_git_config_and_repository_discovery_are_isolated(self):
        self.assertEqual(os.environ["GIT_CONFIG_GLOBAL"], os.devnull)
        self.assertEqual(os.environ["GIT_CONFIG_NOSYSTEM"], "1")
        self.assertEqual(os.environ["GIT_CEILING_DIRECTORIES"],
                         os.path.realpath(tempfile.gettempdir()))

    def test_git_never_starts_its_automatic_maintenance(self):  # CI on git 2.55: a background
        # repack wrote under `.git` while a test removed its temp dir
        with tempfile.TemporaryDirectory() as tmp:
            for key, value in (("maintenance.auto", "false\n"), ("gc.auto", "0\n")):
                self.assertEqual(git(Path(tmp), "config", key), value)  # the helpers' git
                self.assertEqual(subprocess.run(  # a tool's git, which inherits the environment
                    ["git", "-C", tmp, "config", key], capture_output=True, text=True,
                    check=True).stdout, value)

    def test_root_search_stops_at_a_ceiling(self):
        with tempfile.TemporaryDirectory() as tmp:
            outer = Path(tmp).resolve() / "outer"
            (outer / ".git").mkdir(parents=True)
            inner = outer / "ceiling" / "work"
            inner.mkdir(parents=True)
            self.assertEqual(find_root(inner), outer)
            with mock.patch.dict(os.environ, {"GIT_CEILING_DIRECTORIES": str(outer / "ceiling")}):
                with self.assertRaises(UsageError):
                    find_root(inner)
                self.assertEqual(find_root(outer / "ceiling"), outer)  # a start is searched


if __name__ == "__main__":
    unittest.main()
