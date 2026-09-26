"""`--files` path checks (`discover`, `sync`), the `discover` file -> module view, and no
`score` without a task."""
import json
import sys
import tempfile
import unittest

from tests.helpers import git, init_git, make_repo, run, run_json

RULES = ('[[code_map]]\nid = "src"\npattern = "src/{module}/**"\n\n'
         '[[code_map]]\nid = "repos"\npattern = "app/repositories/{module}.py"\n\n'
         '[[code_map]]\nid = "db"\nmodule = "db"\nglobs = ["app/**"]\n')
FILES = ("src/tasks/a.py", "src/lists/b.py", "README.md", "app/repositories/tasks.py")


class Repo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_repo(self._tmp.name, {"tasks": ["task", "todo"], "lists": ["list"],
                                               "db": ["database"]}, RULES, FILES)
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()


class FilesChecksTest(Repo):  # P32-AC-005
    def test_existing_file_and_a_typo(self):
        for verb in (("discover",), ("sync", "--dry-run")):
            with self.subTest(verb=verb[0]):
                code, env, err = run_json(*verb, "--files", "src/tasks/a.py", *self.R)
                self.assertEqual((code, err, env["data"]["missing_files"]), (0, "", []))
                code, env, _ = run_json(*verb, "--files", "src/tsks/x.py", "src/tasks/a.py",
                                        *self.R)
                self.assertEqual((code, env["data"]["missing_files"]), (0, ["src/tsks/x.py"]))
                code, out, _ = run(*verb, "--files", "src/tsks/x.py", *self.R)
                self.assertIn("not on disk: src/tsks/x.py (typo? a deleted file still maps)", out)

    def test_a_deleted_tracked_file_still_maps(self):
        init_git(self.root)
        (self.root / "src/tasks/a.py").unlink()
        _, env, _ = run_json("sync", "--files", "src/tasks/a.py", "--dry-run", *self.R)
        self.assertEqual(env["data"]["missing_files"], ["src/tasks/a.py"])
        self.assertEqual([m["module"] for m in env["data"]["modules"]], ["tasks"])

    def test_a_directory_is_refused_and_no_hook_runs(self):
        marker = self.root / "ran.txt"
        (self.root / ".modsys/config.toml").write_text(
            RULES + f'\n[[hooks.post_sync]]\nid = "mark"\nrun = [{json.dumps(sys.executable)}, '
                    f'"-c", "open(\'ran.txt\', \'w\').write(\'1\')"]\n', encoding="utf-8")
        for arg in ("src/tasks", "src/tasks/"):
            for verb in (("discover",), ("sync",)):
                with self.subTest(arg=arg, verb=verb[0]):
                    code, out, err = run(*verb, "--files", arg, "src/lists/b.py", *self.R)
                    self.assertEqual((code, out), (2, ""))
                    self.assertEqual(err, "modsys: error: src/tasks: is a directory — list its "
                                          "files (e.g. git ls-files src/tasks)\n")
        self.assertFalse(marker.exists())
        self.assertEqual(run("sync", "--files", "src/lists/b.py", *self.R)[0], 0)
        self.assertTrue(marker.exists())  # the hook does run on a valid file list

    def test_from_diff_lists_real_changes_only(self):
        init_git(self.root)
        git(self.root, "rm", "-q", "src/lists/b.py")
        git(self.root, "commit", "-q", "-m", "drop b")
        for verb in (("discover",), ("sync", "--dry-run")):
            with self.subTest(verb=verb[0]):
                code, env, _ = run_json(*verb, "--from-diff", "HEAD~1..HEAD", *self.R)
                self.assertEqual((code, env["data"]["missing_files"]), (0, []))

    def test_paths_outside_the_repository_are_still_refused(self):
        for arg in ("../outside.py", "/etc/hosts"):
            with self.subTest(arg=arg):
                code, out, err = run("discover", "--files", arg, *self.R)
                self.assertEqual((code, out), (2, ""))
                self.assertIn("is outside the repository", err)

    def test_a_submodule_gitlink_is_a_single_changed_path(self):  # M-8
        sub = self.root / "vendor" / "lib"
        sub.mkdir(parents=True)
        (sub / ".git").write_text("gitdir: ../../.git/modules/vendor/lib\n")
        code, env, err = run_json("discover", "--files", "vendor/lib", "src/tasks/a.py", *self.R)
        self.assertEqual((code, err, env["data"]["missing_files"]), (0, "", []))
        self.assertEqual([f["path"] for f in env["data"]["files"]],
                         ["src/tasks/a.py", "vendor/lib"])


class FileViewTest(Repo):  # P32-AC-006
    def test_every_changed_file_with_its_targets(self):
        code, env, _ = run_json("discover", "--files", "src/tasks/a.py", "src/lists/b.py",
                                "README.md", "app/repositories/tasks.py", "./src/tasks/a.py",
                                *self.R)
        self.assertEqual(code, 0)
        self.assertEqual(env["data"]["files"], [
            {"path": "README.md", "modules": []},
            {"path": "app/repositories/tasks.py", "modules": ["db", "tasks"]},
            {"path": "src/lists/b.py", "modules": ["lists"]},
            {"path": "src/tasks/a.py", "modules": ["tasks"]}])
        out = run("discover", "--files", "src/lists/b.py", "README.md",
                  "app/repositories/tasks.py", *self.R)[1]
        for line in ("file      README.md -> (no module)",
                     "file      app/repositories/tasks.py -> db, tasks",
                     "file      src/lists/b.py -> lists"):
            self.assertIn(line, out.splitlines())

    def test_a_task_alone_has_no_file_rows(self):
        _, env, _ = run_json("discover", "--task", "fix src/tasks/a.py for a task", *self.R)
        self.assertEqual(env["data"]["files"], [])
        self.assertIn("src/tasks/a.py", env["data"]["modules"][0]["touched_files"])
        self.assertNotIn("file  ", run("discover", "--task", "a task", *self.R)[1])


class ScoreWithoutTaskTest(Repo):  # P32-AC-007
    def test_files_only_mode_has_no_score(self):
        _, env, _ = run_json("discover", "--files", "src/tasks/a.py", *self.R)
        self.assertEqual([(m["module"], m["score"]) for m in env["data"]["modules"]],
                         [("tasks", None)])
        out = run("discover", "--files", "src/tasks/a.py", *self.R)[1]
        self.assertEqual(out.splitlines()[0].split(), ["modify", "tasks", "via", "diff"])

    def test_with_a_task_a_module_found_only_through_the_change_scores_0(self):
        _, env, _ = run_json("discover", "--task", "fix task sorting", "--files",
                             "src/lists/b.py", *self.R)
        self.assertEqual({m["module"]: m["score"] for m in env["data"]["modules"]},
                         {"tasks": 3, "lists": 0})


if __name__ == "__main__":
    unittest.main()
