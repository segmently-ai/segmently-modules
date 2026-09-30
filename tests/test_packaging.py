"""`pyproject.toml` must keep setuptools' flat-layout package discovery pinned to `modsys*` —
a second top-level directory (like `evals/`) otherwise makes `pip install` / `pip wheel` fail
with "Multiple top-level packages discovered in a flat-layout" (C1) — and ship every file under
`modsys/defaults/`, the built-in packs at any depth included (P4B-AC-010)."""
import glob
import importlib.util
import subprocess
import sys
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path

from tests.plugin_helpers import copy_engine

ENGINE = Path(__file__).resolve().parents[1]
PYPROJECT = ENGINE / "pyproject.toml"


class PackagingTest(unittest.TestCase):
    def test_packages_find_is_pinned_to_modsys(self):
        data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        find = data["tool"]["setuptools"]["packages"]["find"]
        self.assertEqual(find.get("include"), ["modsys*"])

    def test_every_default_file_is_package_data(self):  # P4A-AC-028, P4B-AC-010
        data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        globs = data["tool"]["setuptools"]["package-data"]["modsys"]
        package = ENGINE / "modsys"
        files = [p.relative_to(package).as_posix() for p in (package / "defaults").rglob("*")
                 if p.is_file() and "__pycache__" not in p.parts and p.name != ".DS_Store"]
        self.assertTrue({"defaults/templates/roles/qa.md", "defaults/templates/agents-md.md",
                         "defaults/scaffold/SKILL.md", "defaults/packs/core/pack.toml",
                         "defaults/packs/ui/pack.toml", "defaults/packs/qa/pack.toml"}
                        <= set(files))
        # what setuptools ships: each pattern globbed from the package, `**` recursive, files only
        shipped = {Path(f).as_posix() for g in globs
                   for f in glob.glob(g, root_dir=package, recursive=True)
                   if (package / f).is_file()}
        self.assertEqual(sorted(set(files) - shipped), [])

    def test_the_build_backend(self):  # P6-AC-018, P6-AC-035 (SI-14)
        data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        self.assertEqual(data["build-system"], {"requires": ["setuptools>=62.3"],
                                                "build-backend": "setuptools.build_meta"})
        self.assertEqual(data["project"]["dependencies"], [])
        self.assertEqual(data["project"]["scripts"], {"modsys": "modsys.cli:main"})

    @unittest.skipUnless(importlib.util.find_spec("setuptools") and
                         importlib.util.find_spec("pip"),
                         "setuptools or pip is not installed for this Python")
    def test_a_wheel_ships_every_default_file_and_no_tool(self):  # P6-AC-018 (offline)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp).resolve()
            src = copy_engine(tmp / "engine", {"tests/test_x.py": "", "evals/x.py": ""})
            proc = subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-index",
                                   "--no-build-isolation", "-q", "-w", str(tmp / "wheel"),
                                   str(src)], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
            names = zipfile.ZipFile(next((tmp / "wheel").glob("*.whl"))).namelist()
        shipped = sorted(n for n in names if n.startswith("modsys/defaults/"))
        defaults = sorted(p.relative_to(ENGINE).as_posix()
                          for p in (ENGINE / "modsys/defaults").rglob("*")
                          if p.is_file() and "__pycache__" not in p.parts
                          and p.name != ".DS_Store")
        self.assertEqual(shipped, defaults)
        self.assertIn("modsys/defaults/templates/init/module_prompt.md", shipped)
        self.assertEqual([n for n in names if n.startswith(("tools/", "tests/", "evals/"))], [])

    def test_the_fixtures_stay_test_data(self):  # P5A-AC-049
        data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        self.assertEqual(list(data["tool"]["setuptools"]["package-data"]), ["modsys"])
        self.assertTrue(all(not g.startswith("..")
                            for g in data["tool"]["setuptools"]["package-data"]["modsys"]))
        self.assertTrue((ENGINE / "tests/fixtures/bookshop_monorepo/package.json").is_file())
        self.assertFalse(list((ENGINE / "modsys").rglob("bookshop_monorepo")))


if __name__ == "__main__":
    unittest.main()
