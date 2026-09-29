"""`init eval-tasks --executor CMD` (D5, SI-15): the executor gets the routing prompt on stdin and
writes MODSYS_INIT_TASKS; the file is checked (JSON, known modules, a task for each)."""
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import run
from tests.init_helpers import SIX, WORK, executor, ok, shop, state


class EvalTasksTest(unittest.TestCase):  # P5B-AC-020
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.template = shop(Path(cls._tmp.name).resolve(), name="template")
        ok(cls.template, "init", "fanout")
        ok(cls.template, "init", "run", "--executor", executor())
        ok(cls.template, "init", "reconcile")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(dir=self._tmp.name)).resolve()
        self.root = self.base / "shop"
        shutil.copytree(self.template, self.root, symlinks=True)
        self.tasks = self.root / WORK / "routing-tasks.json"
        self.log = self.base / "calls.jsonl"

    def eval_tasks(self, *flags: str, force: bool = False) -> tuple[int, dict, str]:
        code, out, err = run("init", "eval-tasks", "--executor",
                             executor("--record", str(self.log), *flags), "--json", "--root",
                             str(self.root), *(["--force"] if force else []))
        return code, json.loads(out)["data"] if out else None, err

    def test_a_valid_file(self):
        code, data, err = self.eval_tasks()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual({k: data[k] for k in ("action", "file", "status", "tasks")},
                         {"action": "eval-tasks", "file": f"{WORK}/routing-tasks.json",
                          "status": "written", "tasks": 30})
        self.assertEqual(data["per_module"], dict.fromkeys(
            ["cart", "catalog", "payments", "recommendations", "storefront", "ui-kit"], 5))
        self.assertEqual(state(self.root)["phases"]["eval-tasks"]["status"], "done")
        call = json.loads(self.log.read_text().splitlines()[0])
        self.assertEqual(call["env"]["MODSYS_INIT_TASKS"], str(self.tasks))
        prompt = run("eval", "routing", "--prompt", "--root", str(self.root))[1]
        self.assertEqual(call["stdin_sha256"], hashlib.sha256(prompt.encode("utf-8")).hexdigest())

    def test_the_table(self):
        for mode, problem in (("unknown", "unknown module 'nosuch'"),
                              ("partial", "no task for module 'ui-kit'"),
                              ("invalid", "routing-tasks.json: invalid JSON"),
                              ("nothing", "routing-tasks.json: not written"),
                              ("fail", "the executor exited 3: the task writer gave up")):
            with self.subTest(mode=mode):
                self.setUp()
                code, data, err = self.eval_tasks("--tasks-mode", mode)
                self.assertEqual((code, data["status"]), (1, "failed"))
                self.assertIn(f"modsys: eval-tasks: {problem}", err.splitlines())
                self.assertNotEqual(state(self.root)["phases"]["eval-tasks"]["status"], "done")

    def test_an_existing_file_and_force(self):
        self.tasks.write_text("[]")
        code, data, err = self.eval_tasks()
        self.assertEqual((code, err, data["status"], data["message"]),
                         (0, "", "exists", "routing tasks exist — --force to regenerate"))
        self.assertFalse(self.log.exists())  # nothing ran
        self.assertEqual(self.tasks.read_text(), "[]")
        code, data, _ = self.eval_tasks(force=True)
        self.assertEqual((code, data["tasks"]), (0, 30))

    def rejected(self) -> Path:
        return self.root / WORK / "routing-tasks.rejected.json"

    def test_a_refused_file_is_moved_aside(self):  # I-4: the next step is eval-tasks again
        for mode in ("invalid", "partial"):
            with self.subTest(mode=mode):
                self.setUp()
                code, data, _ = self.eval_tasks("--tasks-mode", mode)
                self.assertEqual(code, 1)
                self.assertFalse(self.tasks.exists())
                self.assertTrue(self.rejected().is_file())
                self.assertIn("modsys init eval-tasks", data["next"])
                self.assertIn("routing-tasks.rejected.json", data["next"])
                verify = ok(self.root, "init", "verify")  # never stuck on the refused file
                self.assertIsNone(verify["routing"])
                self.assertIn("modsys init eval-tasks", verify["next"])
                code, data, err = self.eval_tasks()  # no --force: it runs again
                self.assertEqual((code, err, data["status"], data["tasks"]),
                                 (0, "", "written", 30))
                self.assertEqual(state(self.root)["phases"]["eval-tasks"]["status"], "done")

    def resume(self, *flags: str) -> dict:
        code, out, err = run("init", "resume", *flags, "--json", "--root", str(self.root))
        self.assertEqual((code, err), (0, ""))
        return json.loads(out)["data"]

    def test_resume_after_a_refused_file(self):  # I-4: never skipped because a file exists
        for mode, left in (("invalid", False), ("partial", False), ("partial", True)):
            with self.subTest(mode=mode, left_behind=left):
                self.setUp()
                self.assertEqual(self.eval_tasks("--tasks-mode", mode)[0], 1)
                if left:  # as a killed run would leave it: the file there, the phase running
                    shutil.copy(self.rejected(), self.tasks)
                data = self.resume()
                self.assertEqual(data["ran"], [])
                self.assertIn("modsys init eval-tasks", data["next"])
                data = self.resume("--non-interactive", "--executor", executor())
                self.assertEqual(data["ran"], ["eval-tasks", "verify"])
                routing = json.loads((self.root / WORK / "verify.json").read_text())["routing"]
                self.assertEqual({r["module"]: r["tasks"] for r in routing["per_module"]},
                                 dict.fromkeys(SIX, 5))
                self.assertEqual(state(self.root)["phases"]["eval-tasks"]["status"], "done")

    def test_ctrl_c_while_the_executor_writes(self):
        real = subprocess.run

        def half(argv, **kw):  # git runs as usual; the executor writes half a file, then Ctrl-C
            if argv[0] == "git":
                return real(argv, **kw)
            self.tasks.write_text('[{"task": "change how the cart')
            raise KeyboardInterrupt

        with mock.patch("subprocess.run", side_effect=half):
            got = run("init", "eval-tasks", "--executor", executor(), "--root", str(self.root))
        self.assertEqual(got, (130, "", "modsys: interrupted\n"))
        self.assertFalse(self.tasks.exists())
        self.assertTrue(self.rejected().is_file())
        self.assertEqual(state(self.root)["phases"]["eval-tasks"]["status"], "running")
        self.assertIn("modsys init eval-tasks", ok(self.root, "init", "status")["next"])
        self.assertEqual(self.eval_tasks()[1]["status"], "written")

    def test_before_reconcile(self):
        root = self.base / "early"
        shutil.copytree(self.template, root, symlinks=True)
        s = state(root)
        s["phases"]["reconcile"]["status"] = "pending"
        (root / WORK / "state.json").write_text(json.dumps(s))
        code, out, err = run("init", "eval-tasks", "--executor", executor(), "--root", str(root))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("modsys init reconcile", err)


if __name__ == "__main__":
    unittest.main()
