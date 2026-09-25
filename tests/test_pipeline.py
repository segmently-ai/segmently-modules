"""Pipeline verbs: context (read set before planning) and discover (touch set after it)."""
import io
import tempfile
import unittest
from unittest import mock

from tests.helpers import copy_fixture, run, run_json


class ContextTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def test_read_set_for_a_role(self):
        code, env, _ = run_json("context", "--task", "add isbn to book listing",
                                "--role", "developer", *self.R)
        self.assertEqual((code, env["schema"]), (0, "modsys.context/1"))
        self.assertEqual([m["module"] for m in env["data"]["modules"]], ["catalog"])
        self.assertEqual([(r["module"], r["label"]) for r in env["data"]["read"]],
                         [("catalog", "universal"), ("catalog", "role:developer")])

    def test_shared_docs_listed_once(self):
        _, env, _ = run_json("context", "--task", "refund a partial refund", "--role", "developer",
                             *self.R)
        paths = [r["path"] for r in env["data"]["read"]]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertIn("modules/payments/submodules/refunds/roles/developer.md", paths)

    def test_task_file_and_refusals(self):
        task = self.root / "task.md"
        task.write_text("Show the author on the book page.\n")
        _, env, _ = run_json("context", "--task-file", str(task), "--all-roles", *self.R)
        self.assertIn("role:qa", [r["label"] for r in env["data"]["read"]])
        for argv, needle in [(("--task", " "), "give the task"),
                             (("--task", "isbn", "--role", "security"), "unknown role"),
                             (("--task", "isbn", "--top", "-1"), "--top must be >= 0")]:
            with self.subTest(needle=needle):
                code, out, err = run("context", *argv, *self.R)
                self.assertEqual((code, out), (2, ""))
                self.assertIn(needle, err)
        self.assertEqual(run_json("context", "--task", "nothing relevant here", *self.R)[1]
                         ["data"]["modules"], [])


class DiscoverTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def modules(self, env):
        return {m["module"]: m for m in env["data"]["modules"]}

    def test_path_in_task_means_modify_keyword_only_means_reference(self):
        code, env, _ = run_json("discover", "--task",
                                "Fix src/catalog/service.py so the order total shows the book price",
                                *self.R)
        self.assertEqual((code, env["schema"]), (0, "modsys.discover/1"))
        mods = self.modules(env)
        self.assertEqual((mods["catalog"]["usage"], mods["catalog"]["sources"]),
                         ("modify", ["keyword", "path"]))
        self.assertEqual(mods["catalog"]["docs_to_update"], [
            "modules/catalog/MODULE.md", "modules/catalog/roles/developer.md",
            "modules/catalog/roles/qa.md"])
        self.assertEqual((mods["checkout"]["usage"], mods["checkout"]["docs_to_update"],
                          mods["checkout"]["docs_to_read"]),
                         ("reference", [], ["modules/checkout/MODULE.md"]))
        self.assertEqual(env["data"]["summary"],
                         {"total_modules": 2, "by_usage": {"modify": 1, "reference": 1}})

    def test_changed_files_and_files_outside_modules(self):
        (self.root / "tools").mkdir()
        (self.root / "tools/report.py").write_text("x = 1\n")
        _, env, _ = run_json("discover", "--task", "Tidy up tools/report.py and the refund flow",
                             "--files", "src/catalog/service.py", *self.R)
        mods = self.modules(env)
        self.assertEqual((mods["catalog"]["usage"], mods["catalog"]["sources"]),
                         ("modify", ["diff"]))
        self.assertEqual(mods["payments/refunds"]["usage"], "reference")
        self.assertEqual(env["data"]["files_outside_modules"], ["tools/report.py"])


class TaskFromStdinTest(unittest.TestCase):  # AC-034
    def test_task_from_stdin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            with mock.patch("sys.stdin", io.StringIO("add isbn to book listing")):
                _, env, _ = run_json("context", "--task-file", "-", "--root", str(root))
        self.assertEqual([m["module"] for m in env["data"]["modules"]], ["catalog"])


if __name__ == "__main__":
    unittest.main()
