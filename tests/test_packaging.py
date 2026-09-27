"""`pyproject.toml` must keep setuptools' flat-layout package discovery pinned to `modsys*` —
a second top-level directory (like `evals/`) otherwise makes `pip install` / `pip wheel` fail
with "Multiple top-level packages discovered in a flat-layout" (C1)."""
import tomllib
import unittest
from pathlib import Path, PurePosixPath

ENGINE = Path(__file__).resolve().parents[1]
PYPROJECT = ENGINE / "pyproject.toml"


class PackagingTest(unittest.TestCase):
    def test_packages_find_is_pinned_to_modsys(self):
        data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        find = data["tool"]["setuptools"]["packages"]["find"]
        self.assertEqual(find.get("include"), ["modsys*"])

    def test_every_default_file_is_package_data(self):  # P4A-AC-028: templates, scaffold
        data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        globs = data["tool"]["setuptools"]["package-data"]["modsys"]
        package = ENGINE / "modsys"
        files = [p.relative_to(package).as_posix() for p in (package / "defaults").rglob("*")
                 if p.is_file() and "__pycache__" not in p.parts]
        self.assertTrue({"defaults/templates/roles/qa.md", "defaults/templates/agents-md.md",
                         "defaults/scaffold/SKILL.md"} <= set(files))

        def shipped(f: str) -> bool:  # a setuptools glob: `*` never crosses a `/`
            return any(len(PurePosixPath(f).parts) == len(PurePosixPath(g).parts)
                       and PurePosixPath(f).match(g) for g in globs)

        self.assertEqual([f for f in files if not shipped(f)], [])


if __name__ == "__main__":
    unittest.main()
