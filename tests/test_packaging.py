"""`pyproject.toml` must keep setuptools' flat-layout package discovery pinned to `modsys*` —
a second top-level directory (like `evals/`) otherwise makes `pip install` / `pip wheel` fail
with "Multiple top-level packages discovered in a flat-layout" (C1)."""
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


if __name__ == "__main__":
    unittest.main()
