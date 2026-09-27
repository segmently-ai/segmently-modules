"""`pyproject.toml` must keep setuptools' flat-layout package discovery pinned to `modsys*` —
a second top-level directory (like `evals/`) otherwise makes `pip install` / `pip wheel` fail
with "Multiple top-level packages discovered in a flat-layout" (C1) — and ship every file under
`modsys/defaults/`, the built-in packs at any depth included (P4B-AC-010)."""
import glob
import tomllib
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
