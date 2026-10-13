"""Row 5.2 for phase 4 (D1): `init run` killed mid-phase (the fake executor SIGKILLs it on its
third call), then `init resume` (or a second `init run`) — every module done once, its staging
dir holding exactly one set of docs, the same bytes as an uninterrupted run."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.init_helpers import (SIX, WORK, executor, invented, ok, shop, state, text, tree_sha,
                                with_note)

ENGINE = Path(__file__).resolve().parents[1]


class KillAndResumeTest(unittest.TestCase):  # P5B-AC-010
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        base = Path(cls._tmp.name).resolve()
        cls.template = shop(base, name="template")
        ok(cls.template, "init", "fanout")
        clean = base / "clean"
        shutil.copytree(cls.template, clean, symlinks=True)
        ok(clean, "init", "run", "--executor", executor())
        cls.uninterrupted = cls.docs(clean)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(dir=self._tmp.name)).resolve()
        self.root = self.base / "shop"
        shutil.copytree(self.template, self.root, symlinks=True)
        self.log = self.base / "calls.jsonl"

    def config(self, max_parallel: int) -> None:
        path = self.root / ".segmently-modules/config.toml"
        path.write_text(path.read_text() + f"\n[init]\nmax_parallel = {max_parallel}\n")

    def killed_run(self, switch: str = "--stop-after") -> dict:
        """`init run` in a session of its own, killed by the fake on its third call (with
        `--stop-group`: together with every executor it runs); the module statuses after."""
        proc = subprocess.run([sys.executable, "-m", "segmently_modules", "init", "run", "--executor",
                               executor("--record", str(self.log), switch, "2"),
                               "--root", str(self.root)], capture_output=True, text=True,
                              env={**os.environ, "PYTHONPATH": str(ENGINE)},
                              start_new_session=True)
        self.assertEqual(proc.returncode, -9, proc.stderr)
        return {m: e["status"] for m, e in state(self.root)["modules"].items()}

    def events(self, event: str, log: Path | None = None) -> list[str]:
        return [json.loads(l)["module"] for l in (log or self.log).read_text().splitlines()
                if json.loads(l)["event"] == event]

    def finish(self, *argv: str, log: Path | None = None) -> None:
        got, _, err = text(self.root, *argv, "--executor",
                           executor("--record", str(log or self.log)))
        self.assertEqual((got, err), (0, ""))
        self.assertEqual({e["status"] for e in state(self.root)["modules"].values()}, {"done"})
        for module in SIX:
            files = sorted(p.relative_to(self.root / WORK / "staging" / module).as_posix()
                           for p in (self.root / WORK / "staging" / module).rglob("*")
                           if p.is_file())
            self.assertEqual(files, ["MODULE.md", "entry.json", "roles/architect.md",
                                     "roles/developer.md", "roles/po.md", "roles/qa.md"])
        self.assertEqual(self.docs(self.root), self.uninterrupted)

    @staticmethod
    def docs(root: Path) -> dict:
        """sha256 of every module's staging dir (what the writers wrote)."""
        return {m: tree_sha(root / WORK / "staging" / m) for m in SIX}

    def test_one_at_a_time_then_resume(self):
        self.config(1)
        statuses = self.killed_run()
        self.assertEqual(statuses, {"cart": "done", "catalog": "done", "payments": "running",
                                    "recommendations": "pending", "storefront": "pending",
                                    "ui-kit": "pending"})
        self.assertTrue((self.root / WORK / "staging/payments/partial.tmp").is_file())
        out = text(self.root, "init", "status")[1].splitlines()
        self.assertIn("modules    2 done, 1 running, 3 pending, 0 failed", out)  # P5B-AC-027
        self.assertTrue(out[-1].startswith("next: segmently-modules init resume"), out[-1])
        self.finish("init", "resume", "--non-interactive")
        calls = self.events("start")
        self.assertEqual({m: calls.count(m) for m in SIX},
                         {"cart": 1, "catalog": 1, "payments": 2, "recommendations": 1,
                          "storefront": 1, "ui-kit": 1})

    def test_a_second_run_instead_of_resume(self):
        self.config(1)
        self.killed_run()
        self.finish("init", "run")
        self.assertEqual(self.events("start").count("payments"), 2)

    def test_four_at_a_time(self):
        self.config(4)
        statuses = self.killed_run("--stop-group")
        done = {m for m, s in statuses.items() if s == "done"}
        self.assertTrue({m for m, s in statuses.items() if s == "running"})
        # the resume records into a log of its own: a late write of an executor of the killed
        # group (one forked while the group was being killed) cannot land among its starts,
        # while a module the resume really started twice still shows twice
        resumed = self.base / "resume.jsonl"
        self.finish("init", "resume", log=resumed)
        again = self.events("start", resumed)
        self.assertEqual(sorted(again), sorted(m for m, s in statuses.items() if s != "done"))
        self.assertFalse(done & set(again))


class PreviousProblemsTest(unittest.TestCase):  # P5C-AC-010 (the executor drivers)
    def test_resume_and_run_hand_them_to_the_executor(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            template = shop(base, name="template")
            ok(template, "init", "fanout")
            ok(template, "init", "run", "--executor", executor("--invent-always", "cart"),
               code=1)
            for argv in (("init", "resume"), ("init", "run")):
                with self.subTest(argv=argv):
                    root, log = base / argv[1], base / f"{argv[1]}.jsonl"
                    shutil.copytree(template, root, symlinks=True)
                    item = json.loads((root / WORK / "work/cart.json").read_text())
                    ok(root, *argv, "--executor", executor("--record", str(log)))
                    calls = [json.loads(l) for l in log.read_text().splitlines()]
                    note = with_note(item["prompt"], invented("cart"))
                    self.assertEqual([c["stdin_sha256"] for c in calls
                                      if c["event"] == "start" and c["module"] == "cart"],
                                     [hashlib.sha256(note.encode("utf-8")).hexdigest()])
                    self.assertEqual(state(root)["modules"]["cart"],
                                     {"status": "done", "attempts": 3, "error": None})


if __name__ == "__main__":
    unittest.main()
