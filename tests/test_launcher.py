"""The plugin launcher `bin/modsys` (P6 D3; source `tools/launcher.sh`): the interpreter it
chooses — `MODSYS_PYTHON`, the names on PATH, the directories outside $HOME one at a time, then
`uv` — and how it runs the plugin's engine. Stub interpreters (sh scripts) log every start; a
temp copy of the launcher points its directory line at stub directories (SI-11). Each case
runs under `sh` and, when present, `dash`."""
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
SHELLS = ["sh"] + (["dash"] if shutil.which("dash") else [])
GOOD = """#!/bin/sh
echo "start $0" >> "$STUB_LOG"
[ "$1" = "-c" ] && exit 0
echo "run $0" >> "$STUB_LOG"
echo "PYTHONPATH=$PYTHONPATH" >> "$STUB_LOG"
echo "PYTHONDONTWRITEBYTECODE=$PYTHONDONTWRITEBYTECODE PYTHONSAFEPATH=$PYTHONSAFEPATH" \\
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
        (self.plugin / "runtime").mkdir()
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
               target: Path | None = None):
        self.log.write_text("")
        base = {"PATH": str(self.path_dir), "STUB_LOG": str(self.log),
                "HOME": os.environ.get("HOME", "/")}
        proc = subprocess.run([shutil.which(shell), str(target or self.launcher), *argv],
                              env={**base, **(env or {})}, input=stdin, capture_output=True,
                              text=True)
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
                    "arg=[python]", "arg=[-m]", "arg=[modsys]", "arg=[lint]", "arg=[--json]"])
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
                self.assertIn("PYTHONDONTWRITEBYTECODE=1 PYTHONSAFEPATH=1", lines)
                self.assertEqual([l for l in lines if l.startswith("arg=")], [
                    "arg=[-m]", "arg=[modsys]", "arg=[a b]", 'arg=["q"]', "arg=[$HOME]",
                    "arg=[]"])
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


class RealEngineTest(unittest.TestCase):  # P6-AC-007 (the Then): the real engine, the real Python
    def test_version_and_the_working_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp).resolve()
            plugin = tmp / "p"
            (plugin / "bin").mkdir(parents=True)
            shutil.copy(LAUNCHER, plugin / "bin/modsys")
            (plugin / "bin/modsys").chmod(0o755)
            shutil.copytree(ENGINE / "modsys", plugin / "runtime/modsys",
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
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
