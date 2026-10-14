"""`pyproject.toml` must keep setuptools' flat-layout package discovery pinned to `segmently-modules*` —
a second top-level directory (like `evals/`) otherwise makes `pip install` / `pip wheel` fail
with "Multiple top-level packages discovered in a flat-layout" (C1) — and ship every file under
`segmently_modules/defaults/`, the built-in packs at any depth included (P4B-AC-010)."""
from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from segmently_modules._toml import tomllib
from tests.helpers import glob_in
from tests.plugin_helpers import copy_engine

ENGINE = Path(__file__).resolve().parents[1]
PYPROJECT = ENGINE / "pyproject.toml"


def no_wheel_backend() -> str | None:
    """Why this Python cannot build a wheel offline (a visible skip), or None: pip and
    setuptools, and `bdist_wheel` — the `wheel` package, or setuptools 70.1 and newer."""
    if not (importlib.util.find_spec("setuptools") and importlib.util.find_spec("pip")):
        return "setuptools or pip is not installed for this Python"
    if importlib.util.find_spec("wheel"):
        return None
    found = re.findall(r"\d+", importlib.metadata.version("setuptools"))[:2]
    return (None if tuple(int(x) for x in found) >= (70, 1)
            else "setuptools below 70.1 without the wheel package: no bdist_wheel")


class PackagingTest(unittest.TestCase):
    def test_packages_find_is_pinned_to_segmently_modules(self):
        data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        find = data["tool"]["setuptools"]["packages"]["find"]
        self.assertEqual(find.get("include"), ["segmently_modules*"])

    def test_every_default_file_is_package_data(self):  # P4A-AC-028, P4B-AC-010
        data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        globs = data["tool"]["setuptools"]["package-data"]["segmently_modules"]
        package = ENGINE / "segmently_modules"
        files = [p.relative_to(package).as_posix() for p in (package / "defaults").rglob("*")
                 if p.is_file() and "__pycache__" not in p.parts and p.name != ".DS_Store"]
        self.assertTrue({"defaults/templates/roles/qa.md", "defaults/templates/agents-md.md",
                         "defaults/scaffold/SKILL.md", "defaults/packs/core/pack.toml",
                         "defaults/packs/ui/pack.toml", "defaults/packs/qa/pack.toml"}
                        <= set(files))
        # what setuptools ships: each pattern globbed from the package, `**` recursive, files only
        shipped = {f for g in globs for f in glob_in(package, g) if (package / f).is_file()}
        self.assertEqual(sorted(set(files) - shipped), [])

    def test_the_build_backend(self):  # P6-AC-018, P6-AC-035 (SI-14)
        data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        self.assertEqual(data["build-system"], {"requires": ["setuptools>=62.3"],
                                                "build-backend": "setuptools.build_meta"})
        self.assertEqual(data["project"]["dependencies"], [])
        self.assertEqual(data["project"]["scripts"], {"segmently-modules": "segmently_modules.cli:main"})

    def test_every_data_file_is_package_data(self):  # D6 x D1: the wheel ships every data file
        tracked = subprocess.run(["git", "-C", str(ENGINE), "ls-files", "-z", "--", "segmently_modules"],
                                 capture_output=True, text=True, check=True).stdout.split("\0")
        self.assertIn("segmently_modules/defaults/packs/core/pack.toml", tracked)
        data = [p for p in tracked if p and not p.endswith(".py")]  # the plugin ships all of them
        globs = tomllib.loads((ENGINE / "pyproject.toml").read_text(encoding="utf-8"))[
            "tool"]["setuptools"]["package-data"]["segmently_modules"]
        package = ENGINE / "segmently_modules"
        shipped = {f"segmently_modules/{f}" for g in globs for f in glob_in(package, g)}
        self.assertEqual([p for p in data if p not in shipped], [])
        self.assertEqual([p for p in data if not p.startswith("segmently_modules/defaults/")],
                         ["segmently_modules/_vendor/tomli/LICENSE"])  # the vendored code's licence

    @unittest.skipIf(no_wheel_backend(), no_wheel_backend() or "")
    def test_a_wheel_ships_every_default_file_and_no_tool(self):  # P6-AC-018 (offline)
        env = {k: v for k, v in os.environ.items() if not k.startswith("PIP_")}
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp).resolve()
            src = copy_engine(tmp / "engine", {"tests/test_x.py": "", "evals/x.py": ""})
            proc = subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-index",
                                   "--no-build-isolation", "-q", "-w", str(tmp / "wheel"),
                                   str(src)], capture_output=True, text=True,
                                  env={**env, "PIP_CONFIG_FILE": os.devnull})  # not the user's
            self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
            names = zipfile.ZipFile(next((tmp / "wheel").glob("*.whl"))).namelist()
        shipped = sorted(n for n in names if n.startswith("segmently_modules/defaults/"))
        defaults = sorted(p.relative_to(ENGINE).as_posix()
                          for p in (ENGINE / "segmently_modules/defaults").rglob("*")
                          if p.is_file() and "__pycache__" not in p.parts
                          and p.name != ".DS_Store")
        self.assertEqual(shipped, defaults)
        self.assertIn("segmently_modules/defaults/templates/init/module_prompt.md", shipped)
        self.assertEqual([n for n in names if n.startswith(("tools/", "tests/", "evals/"))], [])

    def test_the_fixtures_stay_test_data(self):  # P5A-AC-049
        data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        self.assertEqual(list(data["tool"]["setuptools"]["package-data"]), ["segmently_modules"])
        self.assertTrue(all(not g.startswith("..")
                            for g in data["tool"]["setuptools"]["package-data"]["segmently_modules"]))
        self.assertTrue((ENGINE / "tests/fixtures/bookshop_monorepo/package.json").is_file())
        self.assertFalse(list((ENGINE / "segmently_modules").rglob("bookshop_monorepo")))


if __name__ == "__main__":
    unittest.main()
