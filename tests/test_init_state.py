"""`modsys init map|confirm|status|resume` (D3): the init state machine — valid and invalid
transitions, an interrupted phase and `init resume` (row 5.2 for phases 1–2), the data of each
action, atomic writes and the headless contract."""
import io
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from modsys import __version__
from modsys.init_flow import NO_P4, TEST_STOP
from tests.helpers import git, run, run_json

ENGINE = Path(__file__).resolve().parents[1]
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
WORK = ".modsys/init"


def snapshot(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file() and ".git" not in p.relative_to(root).parts}


class InitRepo(unittest.TestCase):
    UNITS = ("x", "y", "z")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve() / "repo"
        for unit in self.UNITS:
            path = self.root / "src" / unit / "main.py"
            path.parent.mkdir(parents=True)
            path.write_text(f"NAME = '{unit}'\n")
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "add", "--", "src")
        git(self.root, "commit", "-q", "-m", "code")
        self.R = ("--root", str(self.root))
        self.work = self.root / WORK

    def tearDown(self):
        self._tmp.cleanup()

    def init(self, *argv, code=0) -> dict:
        got, env, err = run_json("init", *argv, *self.R)
        self.assertEqual((got, err), (code, ""), env)
        self.assertEqual(env["schema"], "modsys.init/1")
        return env["data"]

    def refused(self, *argv) -> str:
        before = snapshot(self.root)
        code, out, err = run("init", *argv, "--json", *self.R)
        self.assertEqual((code, out), (2, ""), err)
        self.assertTrue(err.startswith("modsys: error: "), err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(snapshot(self.root), before)
        return err

    def state(self) -> dict:
        return json.loads((self.work / "state.json").read_text())

    def statuses(self) -> tuple:
        phases = self.state()["phases"]
        return tuple(phases[p]["status"] for p in ("preflight", "map", "gate-map"))

    def outputs(self) -> tuple[bytes, bytes]:
        return ((self.work / "preflight.json").read_bytes(),
                (self.work / "proposal.json").read_bytes())

    def proposal(self) -> dict:
        return json.loads((self.work / "proposal.json").read_text())

    def edit_proposal(self, fn) -> None:
        doc = self.proposal()
        fn(doc["candidates"])
        (self.work / "proposal.json").write_text(json.dumps(doc, indent=2) + "\n")

    def temps(self) -> list[str]:
        return sorted(p.name for p in self.work.iterdir() if p.name.endswith(".tmp"))


class ValidTransitionsTest(InitRepo):  # P5A-AC-025
    def test_the_state_table(self):
        before = snapshot(self.root)
        data = self.init("status")  # row 0
        self.assertEqual(data, {"action": "status", "phase": None, "phases": {},
                                "next": "run modsys init map"})
        self.assertEqual(snapshot(self.root), before)
        data = self.init("map")  # row 1
        self.assertEqual([(f["path"], f["status"]) for f in data["files"]],
                         [(".modsys/config.toml", "created"), ("modules/registry.json", "created"),
                          (".gitignore", "created")])
        self.assertEqual(sorted(p.name for p in self.work.iterdir()),
                         ["preflight.json", "proposal.json", "state.json"])
        self.assertEqual((self.state()["phase"], self.statuses()), ("map", ("done", "done",
                                                                             "pending")))
        first = self.outputs()
        before = snapshot(self.root)
        data = self.init("status")  # row 2
        self.assertIn(f"edit {WORK}/proposal.json", data["next"])
        self.assertIn("modsys init confirm", data["next"])
        self.assertEqual(snapshot(self.root), before)
        self.init("map")  # row 3: recomputed, byte-identical
        self.assertEqual(self.outputs(), first)
        data = self.init("resume")  # row 4
        self.assertEqual((data["ran"], data["message"]), ([], None))
        self.assertIn("modsys init confirm", data["next"])
        self.edit_proposal(lambda c: (c[0].update(include=False), c[1].update(name="why")))
        data = self.init("confirm")  # row 5
        self.assertEqual((data["status"], data["included"], data["excluded"]),
                         ("confirmed", ["why", "z"], ["x"]))
        self.assertEqual(json.loads((self.work / "confirmed.json").read_text()), self.proposal())
        self.assertEqual((self.state()["phase"], self.statuses()), ("gate-map", ("done",) * 3))
        data = self.init("status")  # row 6
        self.assertIn("gate 3 passed", data["next"])
        self.assertIn("phase 4 (fan-out) comes with a later engine version", data["next"])
        state = (self.work / "state.json").read_bytes()
        data = self.init("resume", code=1)  # row 7
        self.assertEqual((data["message"], data["ran"]), (NO_P4, []))
        self.assertEqual((self.work / "state.json").read_bytes(), state)
        confirmed = (self.work / "confirmed.json").read_bytes()
        self.assertEqual(self.init("confirm")["status"], "unchanged")  # row 8
        self.assertEqual((self.work / "confirmed.json").read_bytes(), confirmed)
        self.edit_proposal(lambda c: c[2].update(name="zed"))
        self.assertEqual(self.init("confirm")["status"], "updated")  # row 9
        self.init("map", "--restart")  # row 10
        self.assertFalse((self.work / "confirmed.json").exists())
        self.assertEqual(self.outputs(), first)
        self.assertEqual(self.statuses(), ("done", "done", "pending"))
        self.assertEqual(self.temps(), [])

    def test_the_state_shape(self):
        self.init("map")
        state = self.state()
        self.assertEqual(set(state), {"schema", "engine", "started_at", "phase", "phases",
                                      "modules"})
        self.assertEqual((state["schema"], state["engine"], state["modules"]),
                         ("modsys.init-state/1", __version__, {}))
        self.assertEqual(list(state["phases"]), ["preflight", "map", "gate-map"])
        self.assertTrue(ISO.match(state["started_at"]))
        for phase, entry in state["phases"].items():
            self.assertEqual(set(entry), {"status", "started_at", "finished_at", "sha256"})
            if entry["status"] == "done":
                self.assertTrue(ISO.match(entry["started_at"]) and ISO.match(entry["finished_at"]))


class InvalidTransitionsTest(InitRepo):  # P5A-AC-026
    def test_without_a_state(self):
        self.assertIn("run modsys init map", self.refused("resume"))
        self.assertIn("modsys init map", self.refused("confirm"))
        self.assertFalse((self.root / ".modsys").exists())

    def test_after_gate_3_and_an_edited_proposal(self):
        self.init("map")
        self.edit_proposal(lambda c: c[0].update(include=False))
        err = self.refused("map")
        self.assertIn("init map would lose the edits — run modsys init confirm, or modsys init "
                      "map --restart to discard them", err)
        self.init("confirm")
        err = self.refused("map")
        self.assertIn("gate 3 passed", err)
        self.assertIn("modsys init map --restart", err)

    def test_a_registry_with_modules(self):
        registry = self.root / "modules/registry.json"
        registry.parent.mkdir()
        registry.write_text('{"modules": {"x": {"description": "The x module."}}}\n')
        err = self.refused("map")
        self.assertIn("modsys adopt", err)
        self.assertIn("modsys coverage", err)
        self.assertFalse((self.root / ".modsys").exists())
        self.assertFalse((self.root / ".gitignore").exists())

    def test_corrupt_files(self):
        self.init("map")
        for rel, text in (("state.json", "{not json"),
                          ("state.json", json.dumps({"schema": "modsys.init-state/9"})),
                          ("proposal.json", "{not json")):
            good = (self.work / rel).read_bytes()
            (self.work / rel).write_text(text)
            for action in ("status", "resume", "confirm", "map"):
                with self.subTest(file=rel, text=text[:12], action=action):
                    err = self.refused(action)
                    self.assertIn(f"{WORK}/{rel}", err)
                    self.assertIn("modsys init map --restart", err)
            (self.work / rel).write_bytes(good)

    def test_flags_and_actions(self):
        for action in ("status", "confirm", "resume"):
            with self.subTest(action=action):
                self.assertIn("--restart works with map only",
                              self.refused(action, "--restart"))
        for action in ("status", "resume"):
            with self.subTest(dry_run=action):
                self.assertIn("--dry-run", self.refused(action, "--dry-run"))
        err = self.refused("bogus")
        self.assertIn("unknown init action 'bogus' (actions: map, confirm, status, resume)", err)
        self.assertIn("--layout works with plain init and init map",
                      self.refused("status", "--layout", "single"))


class InterruptTest(InitRepo):  # P5A-AC-027 (row 5.2, phases 1–2)
    def baseline(self) -> tuple:
        self.init("map")
        outputs = self.outputs()
        shutil.rmtree(self.work)
        return outputs

    def stopped(self, seam: str | None, *argv) -> None:
        env = {TEST_STOP: seam} if seam else {}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(run("init", *argv, *self.R), (130, "", "modsys: interrupted\n"))

    def test_an_interrupted_preflight(self):
        first = self.baseline()
        self.stopped("preflight", "map")
        self.assertEqual((self.state()["phase"], self.statuses()[0]), ("preflight", "running"))
        self.assertFalse((self.work / "preflight.json").exists())
        self.assertEqual(self.temps(), [])
        self.assertIn("phase preflight was interrupted", self.init("status")["next"])
        data = self.init("resume")
        self.assertEqual(data["ran"], ["preflight", "map"])
        self.assertEqual((self.outputs(), self.statuses()), (first, ("done", "done", "pending")))

    def test_an_interrupted_map(self):
        first = self.baseline()
        for seam in ("map", "map:renamed", None):
            with self.subTest(seam=seam):
                if seam is None:  # Ctrl-C during map
                    with mock.patch("modsys.mapper.build", side_effect=KeyboardInterrupt):
                        self.stopped(None, "map", "--restart")
                else:
                    self.stopped(seam, "map", "--restart")
                self.assertEqual(self.statuses()[:2], ("done", "running"))
                self.assertEqual((self.work / "proposal.json").exists(), seam == "map:renamed")
                self.assertIn("phase map was interrupted", self.init("status")["next"])
                mtime = (self.work / "preflight.json").stat().st_mtime_ns
                self.assertEqual(self.init("resume")["ran"], ["map"])
                self.assertEqual((self.work / "preflight.json").stat().st_mtime_ns, mtime)
                self.assertEqual((self.outputs(), self.statuses()),
                                 (first, ("done", "done", "pending")))
                self.assertEqual(self.temps(), [])

    def test_init_map_instead_of_resume_and_the_seam_is_inert(self):
        first = self.baseline()
        self.stopped("map", "map")
        self.init("map")
        self.assertEqual(self.outputs(), first)
        with mock.patch.dict(os.environ, {TEST_STOP: "nothing"}):
            self.init("map")
        self.assertEqual(self.outputs(), first)
        docs = [ENGINE / "README.md", *sorted((ENGINE / "docs").glob("*.md"))]
        self.assertFalse([d.name for d in docs if TEST_STOP in d.read_text(encoding="utf-8")])


class ActionDataTest(InitRepo):  # P5A-AC-029
    def test_the_keys_of_each_action(self):
        before = snapshot(self.root)
        data = self.init("map", "--dry-run")
        self.assertEqual(set(data), {"action", "root", "files", "preflight", "proposal",
                                     "candidates", "unassigned", "hints", "phase", "next",
                                     "dry_run"})
        self.assertEqual((data["dry_run"], data["candidates"], data["phase"]), (True,
                                                                                ["x", "y", "z"],
                                                                                None))
        self.assertEqual(snapshot(self.root), before)
        with mock.patch("sys.stdin", io.StringIO("")), \
                mock.patch("builtins.input", side_effect=AssertionError("prompted")):
            data = self.init("map")
            self.assertEqual((data["action"], data["dry_run"], data["unassigned"],
                              data["hints"]), ("map", False, 0, 0))
            self.assertEqual((data["preflight"], data["proposal"]),
                             (f"{WORK}/preflight.json", f"{WORK}/proposal.json"))
            data = self.init("confirm", "--dry-run")
            self.assertEqual(set(data), {"action", "confirmed", "included", "excluded", "status",
                                         "dry_run"})
            self.assertFalse((self.work / "confirmed.json").exists())
            self.init("confirm")
        self.assertEqual(set(self.init("status")), {"action", "phase", "phases", "next"})
        self.assertEqual(set(self.init("resume", code=1)), {"action", "ran", "phase", "next",
                                                            "message"})
        self.assertEqual(set(self.init()), {"root", "layout", "files", "dry_run"})

    def test_text_output(self):
        self.init("map")
        out = run("init", "status", *self.R)[1].splitlines()
        self.assertEqual(out[:3], ["preflight  done", "map        done", "gate-map   pending"])
        self.assertTrue(out[3].startswith("next: gate 3: edit "))
        self.init("confirm")
        code, out, err = run("init", "resume", *self.R)
        self.assertEqual((code, err), (1, ""))
        self.assertIn(NO_P4, out.splitlines())


class WritesAndRacesTest(InitRepo):  # P5A-AC-044 (init)
    def test_a_symlinked_work_directory(self):
        self.init("map")
        target = self.root.parent / "elsewhere"
        self.work.rename(target)
        self.work.symlink_to(target)
        kept = snapshot(target)
        for argv in (("map", "--restart"), ("map",), ("status",), ("confirm",), ("resume",)):
            with self.subTest(argv=argv):
                self.assertIn(f"{WORK} is a symlink", self.refused(*argv))
        self.assertEqual(snapshot(target), kept)

    def test_stale_temp_files_and_interleaved_runs(self):
        self.init("map")
        stale = self.work / ".proposal.json.crash.tmp"
        stale.write_text("{half")
        self.assertIn("gate 3", self.init("status")["next"])
        self.init("map")
        self.assertFalse(stale.exists())
        from modsys import mapper
        real = mapper.build
        calls = []

        def interleaved(*args):
            if not calls:
                calls.append(1)
                self.init("map")  # a second run finishes while the first is in its map phase
            return real(*args)

        with mock.patch("modsys.mapper.build", side_effect=interleaved):
            self.init("map")
        for name in ("state.json", "preflight.json", "proposal.json"):
            json.loads((self.work / name).read_text())
        self.assertEqual(self.statuses(), ("done", "done", "pending"))
        self.assertEqual(self.temps(), [])


class InitContractTest(InitRepo):  # P5A-AC-046 (init)
    def test_garbage_config_interrupt_and_options_after_the_action(self):
        self.init("map")
        config = self.root / ".modsys/config.toml"
        good = config.read_text()
        for text in ("[init]\nexclude = 5\n", "code_map = 5\n"):
            config.write_text(text)
            for action in ("map", "confirm", "status", "resume"):
                with self.subTest(config=text, action=action):
                    err = self.refused(action)
                    self.assertIn("config.toml", err)
        config.write_text(good)
        with mock.patch("modsys.init_flow.InitFlow.run_phases", side_effect=KeyboardInterrupt):
            self.assertEqual(run("init", "map", *self.R), (130, "", "modsys: interrupted\n"))
        self.init("map")
        with mock.patch("modsys.init_flow.InitFlow.validate", side_effect=RuntimeError("boom")):
            with mock.patch.dict(os.environ):
                os.environ.pop("MODSYS_DEBUG", None)
                code, out, err = run("init", "confirm", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("modsys: internal error: RuntimeError: boom", err)
        code, out, err = run("init", "--json", "status", "--root", str(self.root))
        self.assertEqual((code, err, json.loads(out)["schema"]), (0, "", "modsys.init/1"))


if __name__ == "__main__":
    unittest.main()
