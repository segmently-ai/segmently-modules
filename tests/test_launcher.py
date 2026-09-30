"""The plugin launcher `bin/modsys` (P6 D3; source `tools/launcher.sh`): the interpreter it
chooses — `MODSYS_PYTHON`, the names on PATH, the directories outside $HOME one at a time, then
`uv` — and how it runs the plugin's engine. Stub interpreters (sh scripts) log every start; a
temp copy of the launcher points its directory line at stub directories (SI-11). Each case
runs under `sh` and, when present, `dash` (without it, `DashTest` is a visible skip)."""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
LAUNCHER = ENGINE / "tools/launcher.sh"
DIRS_LINE = 'DIRS="/opt/homebrew/bin /usr/local/bin /usr/bin"\n'
DASH = shutil.which("dash")
SHELLS = ["sh"] + (["dash"] if DASH else [])
GOOD = """#!/bin/sh
echo "start $0" >> "$STUB_LOG"
[ "$1" = "-c" ] && exit 0
echo "run $0" >> "$STUB_LOG"
echo "PYTHONPATH=$PYTHONPATH" >> "$STUB_LOG"
echo "PYTHONDONTWRITEBYTECODE=$PYTHONDONTWRITEBYTECODE PYTHONSAFEPATH=${PYTHONSAFEPATH-unset}" \\
    >> "$STUB_LOG"
for a in "$@"; do echo "arg=[$a]" >> "$STUB_LOG"; done
if [ -n "$STUB_STDIN" ]; then read -r line; echo "stdin=$line" >> "$STUB_LOG"; fi
exit "${STUB_EXIT:-0}"
"""
OLD = '#!/bin/sh\necho "start $0" >> "$STUB_LOG"\nexit 1\n'  # the probe fails: Python 3.9
BROKEN = '#!/bin/sh\necho "start $0" >> "$STUB_LOG"\nexit 127\n'
UV = ('#!/bin/sh\necho "start $0 $*" >> "$STUB_LOG"\n[ "$1" = "--version" ] && '
      'exit "${UV_VERSION_EXIT:-0}"\nfor a in "$@"; do echo "arg=[$a]" >> "$STUB_LOG"; done\n'
      'exit 0\n')


class LauncherRepo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name).resolve()
        self.plugin = self.tmp / "my plugin"  # a space in the plugin path
        (self.plugin / "bin").mkdir(parents=True)
        (self.plugin / "runtime/modsys").mkdir(parents=True)
        (self.plugin / "runtime/modsys/__main__.py").write_text("")  # the stubs never read it
        self.path_dir = self.tmp / "path"
        self.stand_in = [self.tmp / d for d in ("opt-homebrew-bin", "usr-local-bin", "usr-bin")]
        for d in [self.path_dir, *self.stand_in]:
            d.mkdir()
        text = LAUNCHER.read_text(encoding="utf-8")
        self.assertEqual(text.count(DIRS_LINE), 1)
        self.launcher = self.plugin / "bin/modsys"
        self.launcher.write_text(text.replace(DIRS_LINE, 'DIRS="' + " ".join(
            str(d) for d in self.stand_in) + '"\n'), encoding="utf-8")
        self.launcher.chmod(0o755)
        os.symlink(shutil.which("readlink"), self.path_dir / "readlink")
        self.log = self.tmp / "log"

    def tearDown(self):
        for d in self.tmp.rglob("*"):  # a mode-000 stub directory must be removable
            if d.is_dir() and not d.is_symlink():
                d.chmod(0o755)
        self._tmp.cleanup()

    def stub(self, where: Path, name: str, text: str, mode: int = 0o755) -> Path:
        path = where / name
        path.write_text(text, encoding="utf-8")
        path.chmod(mode)
        return path

    def launch(self, shell: str, *argv: str, env: dict | None = None, stdin: str | None = None,
               target: Path | str | None = None, cwd: Path | None = None):
        self.log.write_text("")
        base = {"PATH": str(self.path_dir), "STUB_LOG": str(self.log),
                "HOME": os.environ.get("HOME", "/")}
        proc = subprocess.run([shutil.which(shell), str(target or self.launcher), *argv],
                              env={**base, **(env or {})}, input=stdin, capture_output=True,
                              text=True, cwd=cwd)
        return proc, self.log.read_text().splitlines()

    def ran(self, lines: list[str]) -> str | None:
        runs = [l[4:] for l in lines if l.startswith("run ")]
        return runs[0] if runs else None


class ChoiceTest(LauncherRepo):  # P6-AC-006
    def test_the_table(self):
        p, (hb, ul, ub) = self.path_dir, self.stand_in
        rows = [  # (name, setup, MODSYS_PYTHON, expected: the stub that runs, or None)
            (1, [(p, "python3.14", GOOD), (p, "python3.11", GOOD)], None, p / "python3.14"),
            (2, [(p, "python3.14", OLD), (p, "python3.13", BROKEN), (p, "python3.11", GOOD)],
             None, p / "python3.11"),
            (3, [(p, "python3.14", OLD), (p, "python3", GOOD)], None, p / "python3"),
            (4, [(ul, "python3.11", GOOD)], None, ul / "python3.11"),
            (5, [(hb, "python3.11", GOOD), (ul, "python3.14", GOOD)], None, hb / "python3.11"),
            (10, [(p, "python3.14", GOOD)], "good", self.tmp / "chosen"),
            (12, [(p, "python3.11", GOOD)], "", p / "python3.11"),
        ]
        for shell in SHELLS:
            for n, stubs, chosen, expected in rows:
                with self.subTest(shell=shell, row=n):
                    self.reset()
                    for where, name, text in stubs:
                        self.stub(where, name, text)
                    env = {}
                    if chosen == "good":
                        env["MODSYS_PYTHON"] = str(self.stub(self.tmp, "chosen", GOOD))
                    elif chosen == "":
                        env["MODSYS_PYTHON"] = ""
                    proc, lines = self.launch(shell, "list", env=env)
                    self.assertEqual((proc.returncode, proc.stderr), (0, ""), lines)
                    self.assertEqual(self.ran(lines), str(expected))

    @unittest.skipIf(os.geteuid() == 0, "root reads a mode-000 directory")
    def test_a_shim_in_a_directory_that_cannot_be_read(self):  # row 6: $HOME denied
        shims = self.tmp / "home-shims"
        shims.mkdir()
        self.stub(shims, "python3.11", GOOD)
        shims.chmod(0)
        self.stub(self.stand_in[2], "python3", GOOD)
        for shell in SHELLS:
            with self.subTest(shell=shell):
                proc, lines = self.launch(shell, "list",
                                          env={"PATH": f"{shims}:{self.path_dir}"})
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(self.ran(lines), str(self.stand_in[2] / "python3"))

    def test_uv_and_nothing(self):  # rows 7, 8, 9
        self.stub(self.stand_in[2], "python3", OLD)  # the macOS 3.9 case
        self.stub(self.path_dir, "uv", UV)
        for shell in SHELLS:
            with self.subTest(shell=shell, row=7):
                proc, lines = self.launch(shell, "lint", "--json")
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual([l for l in lines if l.startswith("arg=")], [
                    "arg=[run]", "arg=[--no-project]", "arg=[--python]", "arg=[>=3.11]",
                    "arg=[python]", "arg=[-P]", "arg=[-m]", "arg=[modsys]", "arg=[lint]",
                    "arg=[--json]"])
            for row, env in ((8, {"UV_VERSION_EXIT": "1"}), (9, None)):
                with self.subTest(shell=shell, row=row):
                    if row == 9:
                        (self.path_dir / "uv").unlink()
                    proc, lines = self.launch(shell, "list", env=env)
                    self.assertEqual((proc.returncode, proc.stdout), (127, ""))
                    self.assertEqual(proc.stderr.count("\n"), 1)
                    for needle in ("Python 3.11 or newer", "MODSYS_PYTHON", "uv"):
                        self.assertIn(needle, proc.stderr)
                    self.assertIsNone(self.ran(lines))
                    self.stub(self.path_dir, "uv", UV)

    def test_an_unusable_modsys_python(self):  # row 11 (SI-12): never a silent fall-through
        self.stub(self.path_dir, "python3.14", GOOD)
        old = self.stub(self.tmp, "old", OLD)
        broken = self.stub(self.tmp, "broken", BROKEN)
        plain = self.stub(self.tmp, "plain", GOOD, mode=0o644)
        for shell in SHELLS:
            for value, why in ((old, "is older than Python 3.11"),
                               (broken, "does not run (exit 127)"),
                               (plain, ""), ("/nonexistent", ": not found")):
                with self.subTest(shell=shell, value=value):
                    proc, lines = self.launch(shell, "list", env={"MODSYS_PYTHON": str(value)})
                    self.assertEqual((proc.returncode, proc.stdout), (127, ""))
                    self.assertTrue(proc.stderr.startswith(f"modsys: MODSYS_PYTHON={value}"),
                                    proc.stderr)
                    self.assertIn(why, proc.stderr)
                    self.assertIsNone(self.ran(lines))  # the PATH stub never runs
                    self.assertNotIn(f"start {self.path_dir}/python3.14", lines)
            with self.subTest(shell=shell, value="a backslash"):  # printed as it is: one line
                proc, _ = self.launch(shell, "list", env={"MODSYS_PYTHON": "/no/such\\ndir"})
                self.assertEqual((proc.returncode, proc.stdout), (127, ""))
                self.assertEqual(proc.stderr, "modsys: MODSYS_PYTHON=/no/such\\ndir: not found — "
                                              "unset it, or point it at Python 3.11 or newer\n")

    def reset(self) -> None:
        for d in [self.path_dir, *self.stand_in]:
            for f in d.iterdir():
                if f.name != "readlink":
                    f.unlink()
        for f in self.tmp.glob("chosen"):
            f.unlink()


class InvocationTest(LauncherRepo):  # P6-AC-007
    def setUp(self):
        super().setUp()
        self.stub(self.path_dir, "python3.14", GOOD)

    def test_runtime_first_bytecode_off_and_the_arguments(self):
        for shell in SHELLS:
            with self.subTest(shell=shell):
                proc, lines = self.launch(shell, "a b", '"q"', "$HOME", "",
                                          env={"PYTHONPATH": "/elsewhere"})
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertIn(f"PYTHONPATH={self.plugin}/runtime:/elsewhere", lines)
                # -P is a flag of the engine's process: nothing it starts inherits it
                self.assertIn("PYTHONDONTWRITEBYTECODE=1 PYTHONSAFEPATH=unset", lines)
                self.assertEqual([l for l in lines if l.startswith("arg=")], [
                    "arg=[-P]", "arg=[-m]", "arg=[modsys]", "arg=[a b]", 'arg=["q"]',
                    "arg=[$HOME]", "arg=[]"])
                self.assertEqual([l for l in lines if l.startswith("start ")],
                                 [f"start {self.path_dir}/python3.14"] * 2)  # probe + run

    def test_through_a_symlink(self):
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        os.symlink(os.path.relpath(self.launcher, elsewhere), elsewhere / "modsys")
        os.symlink(elsewhere / "modsys", self.tmp / "twice")
        for shell in SHELLS:
            for target in (elsewhere / "modsys", self.tmp / "twice"):
                with self.subTest(shell=shell, target=target.name):
                    proc, lines = self.launch(shell, "--version", target=target)
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    self.assertIn(f"PYTHONPATH={self.plugin}/runtime", lines)

    def test_exit_codes_stdin_and_home(self):
        for shell in SHELLS:
            for code in (0, 1, 2, 130):
                with self.subTest(shell=shell, code=code):
                    proc, _ = self.launch(shell, "x", env={"STUB_EXIT": str(code)})
                    self.assertEqual(proc.returncode, code)
            with self.subTest(shell=shell, what="stdin"):
                proc, lines = self.launch(shell, "x", env={"STUB_STDIN": "1"},
                                          stdin="piped line\n")
                self.assertIn("stdin=piped line", lines)
            with self.subTest(shell=shell, what="an unreadable HOME"):
                home = self.tmp / "home"
                home.mkdir(exist_ok=True)
                home.chmod(0)
                proc, lines = self.launch(shell, "x", env={"HOME": str(home)})
                self.assertEqual(self.ran(lines), str(self.path_dir / "python3.14"))

    def test_cdpath_and_a_relative_call(self):  # final review M-2
        decoy = self.tmp / "decoy"
        (decoy / "bin").mkdir(parents=True)
        for shell in SHELLS:
            with self.subTest(shell=shell):
                proc, lines = self.launch(shell, "x", target="bin/modsys", cwd=self.plugin,
                                          env={"CDPATH": str(decoy)})
                self.assertEqual((proc.returncode, proc.stderr), (0, ""))
                self.assertIn(f"PYTHONPATH={self.plugin}/runtime", lines)

    def test_a_plugin_without_its_runtime_runs_no_other_modsys(self):
        shutil.rmtree(self.plugin / "runtime")
        other = self.tmp / "other"  # another modsys the caller's PYTHONPATH holds
        (other / "modsys").mkdir(parents=True)
        (other / "modsys/__main__.py").write_text("print('the wrong modsys')\n")
        for shell in SHELLS:
            with self.subTest(shell=shell):
                proc, lines = self.launch(shell, "--version", env={"PYTHONPATH": str(other)})
                self.assertEqual((proc.returncode, proc.stdout), (127, ""))
                self.assertEqual(proc.stderr, f"modsys: {self.plugin} has no runtime/modsys — "
                                              "reinstall the plugin\n")
                self.assertEqual(lines, [])  # no interpreter started

    def test_a_symlink_without_readlink_and_a_colon(self):
        (self.path_dir / "readlink").unlink()
        os.symlink(self.launcher, self.tmp / "link")
        for shell in SHELLS:
            with self.subTest(shell=shell):
                proc, lines = self.launch(shell, "x", target=self.tmp / "link")
                self.assertEqual((proc.returncode, proc.stdout), (127, ""))
                self.assertEqual(proc.stderr, f"modsys: cannot follow the symlink {self.tmp}/link "
                                              "(readlink)\n")
                self.assertEqual(lines, [])
        colon = self.tmp / "a:b"
        shutil.copytree(self.plugin, colon)
        for shell in SHELLS:
            with self.subTest(shell=shell, what="a colon"):
                proc, lines = self.launch(shell, "x", target=colon / "bin/modsys")
                self.assertEqual((proc.returncode, proc.stdout), (127, ""))
                self.assertEqual(proc.stderr, f"modsys: {colon} holds a \":\" — install the "
                                              "plugin elsewhere\n")
                self.assertEqual(lines, [])

    def test_a_missing_name_starts_nothing(self):
        (self.path_dir / "python3.14").unlink()
        self.stub(self.path_dir, "python3.12", GOOD)
        proc, lines = self.launch("sh", "x")
        self.assertEqual([l for l in lines if l.startswith("start ")],
                         [f"start {self.path_dir}/python3.12"] * 2)

    def test_posix_syntax(self):
        for shell in SHELLS:
            with self.subTest(shell=shell):
                proc = subprocess.run([shutil.which(shell), "-n", str(LAUNCHER)],
                                      capture_output=True, text=True)
                self.assertEqual((proc.returncode, proc.stderr), (0, ""))
        self.assertTrue(LAUNCHER.read_text(encoding="utf-8").startswith("#!/bin/sh\n"))
        self.assertFalse(stat.S_IMODE(os.stat(LAUNCHER).st_mode) & 0o111)  # the source stays
        # 100644 in git: the builder gives bin/modsys its 0755


class DashTest(unittest.TestCase):  # final review T-7: the dash half never goes missing quietly
    @unittest.skipUnless(DASH, "dash not installed — the launcher cases ran under sh only")
    def test_the_dash_half_runs(self):
        self.assertEqual(SHELLS, ["sh", "dash"])


class RealEngineTest(unittest.TestCase):  # P6-AC-007 (the Then): the real engine, the real Python
    def plugin(self, tmp: Path) -> Path:
        plugin = tmp / "p"
        (plugin / "bin").mkdir(parents=True)
        shutil.copy(LAUNCHER, plugin / "bin/modsys")
        (plugin / "bin/modsys").chmod(0o755)
        shutil.copytree(ENGINE / "modsys", plugin / "runtime/modsys",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        return plugin

    def test_what_the_engine_starts_imports_as_anywhere(self):  # final review M-1
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp).resolve()
            plugin = self.plugin(tmp)
            repo = tmp / "repo"
            shutil.copytree(ENGINE / "tests/fixtures/bookshop", repo)
            (repo / ".modsys/config.toml").write_text(
                f'[[hooks.post_sync]]\nid = "notify"\nrun = ["{sys.executable}", '
                f'"./tools/notify.py"]\n')
            (repo / "tools").mkdir()
            (repo / "tools/helper.py").write_text("WORD = 'from the sibling'\n")
            (repo / "tools/notify.py").write_text(  # imports its sibling, as a script does
                "import json, os\nimport helper\nprint(json.dumps({'messages': [helper.WORD, "
                "os.environ.get('PYTHONSAFEPATH', 'unset')]}))\n")
            env = {k: v for k, v in os.environ.items() if k != "PYTHONSAFEPATH"}
            proc = subprocess.run([str(plugin / "bin/modsys"), "sync", "--files", "README.md",
                                   "--root", str(repo), "--json"], cwd=repo, capture_output=True,
                                  text=True, env={**env, "MODSYS_PYTHON": sys.executable})
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            hook = json.loads(proc.stdout)["data"]["hooks"]["hooks"][0]
            self.assertEqual((hook["status"], hook["messages"]),
                             ("ok", ["from the sibling", "unset"]))

    def test_version_and_the_working_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp).resolve()
            plugin = self.plugin(tmp)
            shadow = tmp / "cwd/modsys"  # a `modsys` package in the working directory and on
            shadow.mkdir(parents=True)  # the caller's PYTHONPATH never wins
            (shadow / "__init__.py").write_text("raise SystemExit('the wrong modsys')\n")
            (shadow / "__main__.py").write_text("raise SystemExit('the wrong modsys')\n")
            env = {**os.environ, "MODSYS_PYTHON": sys.executable,
                   "PYTHONPATH": str(tmp / "cwd")}
            env.pop("PYTHONDONTWRITEBYTECODE", None)
            version = re.search(r'^__version__ = "([^"]+)"$',
                                (ENGINE / "modsys/__init__.py").read_text(), re.M).group(1)
            proc = subprocess.run([str(plugin / "bin/modsys"), "--version"], cwd=tmp / "cwd",
                                  env=env, capture_output=True, text=True)
            self.assertEqual((proc.returncode, proc.stdout.strip(), proc.stderr),
                             (0, f"modsys {version}", ""))
            self.assertEqual(list(plugin.rglob("__pycache__")), [])


if __name__ == "__main__":
    unittest.main()
