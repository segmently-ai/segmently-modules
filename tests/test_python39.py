"""Python 3.9 is the floor (the `python3` of macOS's Command Line Tools — the package that brings
git — is 3.9.6): the floor stated alike in pyproject and the plugin launcher; the TOML reader
(Python's own `tomllib` from 3.11, the vendored tomli 2.3.2 before) reads every TOML
file the engine ships as `tomllib` does; the vendored files are the release's, unchanged;
`placeholder_names` is `Template.get_identifiers` (3.11) on every Python; no file uses syntax
newer than 3.9, and an annotation with `X | Y` (evaluated when its function is defined, before
3.10 a TypeError) only below `from __future__ import annotations`. CI runs the suite on Apple's
3.9 as well, where the import test below is the first to show what the rest would hit."""
import ast
import hashlib
import importlib
import pkgutil
import re
import string
import sys
import unittest
from pathlib import Path

import segmently_modules
from segmently_modules import _toml
from segmently_modules._vendor import tomli
from segmently_modules.init_work import placeholder_names

ENGINE = Path(__file__).resolve().parents[1]
VENDORED = {  # sha256 of the files of the PyPI sdist tomli-2.3.2.tar.gz (src/tomli/, LICENSE)
    "__init__.py": "d8678ce48a6a4b061d69b9be9b72a9449de5365222c316571b0c24b30b838409",
    "_parser.py": "6dcbfefc2500621671bc0f962e2f00ed7c3d9a71e4604d7ce2d438c6c0a09ff9",
    "_re.py": "9fcf88a3c64ad54f85ea3ce583b3da6dce3484b149b1ac04dae34b287f70ee25",
    "_types.py": "f864c6d9552a929c7032ace654ee05ef26ca75d21b027b801d77e65907138b74",
    "LICENSE": "b80816b0d530b8accb4c2211783790984a6e3b61922c2b5ee92f3372ab2742fe",
}
BAD_TOML = ["a = ", "[t]\nx = 1\n[t]\n", 'k = "unterminated', "x = 1\nx = 2\n", "= 1"]


def python_files() -> list[Path]:
    """The Python files of the engine's tree that run: the package (its vendored code aside),
    the tests (their fixtures aside), the tools and the evals."""
    files = [p for d in ("segmently_modules", "tests", "tools", "evals")
             for p in sorted((ENGINE / d).rglob("*.py"))]
    return [p for p in files if "_vendor" not in p.parts and "fixtures" not in p.parts]


def bar_annotations(tree: ast.AST) -> list[int]:
    """The lines of the annotations in `tree` that hold `X | Y`."""
    notes = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = node.args
            notes += [arg.annotation for arg in [*a.posonlyargs, *a.args, *a.kwonlyargs,
                                                 *filter(None, [a.vararg, a.kwarg])]]
            notes.append(node.returns)
        elif isinstance(node, ast.AnnAssign):
            notes.append(node.annotation)
    return sorted({n.lineno for note in notes if note is not None for n in ast.walk(note)
                   if isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr)})


class FloorTest(unittest.TestCase):
    def test_pyproject_and_the_launcher_state_three_nine(self):
        pyproject = (ENGINE / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('requires-python = ">=3.9"\n', pyproject)
        launcher = (ENGINE / "tools/launcher.sh").read_text(encoding="utf-8")
        self.assertIn("sys.exit(sys.version_info < (3, 9))", launcher)
        self.assertIn("--python '>=3.9'", launcher)
        for older in ("(3, 11)", ">=3.11", "3.11 or newer", "(3, 10)", ">=3.10", "3.10 or newer"):
            self.assertNotIn(older, launcher)

    def test_no_doc_names_an_older_floor(self):
        for path in [ENGINE / "README.md", ENGINE / "CONTRIBUTING.md",
                     *sorted((ENGINE / "docs").glob("*.md"))]:
            with self.subTest(doc=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertNotRegex(text, r"(Python|python) ?(≥|>=) ?3\.1[01]|3\.1[01] or newer")


class TomlTest(unittest.TestCase):
    def shipped(self) -> list[Path]:  # the scaffold's are templates, TOML once rendered
        files = sorted(p for p in (ENGINE / "segmently_modules").rglob("*.toml")
                       if "scaffold" not in p.parts)
        self.assertGreater(len(files), 3)
        return files

    def test_the_reader_is_pythons_own_where_there_is_one(self):
        if sys.version_info >= (3, 11):
            import tomllib
            self.assertIs(_toml.tomllib, tomllib)
        else:
            self.assertIs(_toml.tomllib, tomli)

    def test_the_vendored_reader_reads_the_shipped_files_alike(self):
        for path in self.shipped():
            with self.subTest(file=path.relative_to(ENGINE).as_posix()):
                text = path.read_text(encoding="utf-8")
                self.assertEqual(tomli.loads(text), _toml.tomllib.loads(text))

    @unittest.skipIf(sys.version_info < (3, 11), "no stdlib tomllib to compare with")
    def test_the_vendored_reader_refuses_alike(self):
        import tomllib
        for text in BAD_TOML:
            with self.subTest(text=text):
                with self.assertRaises(tomllib.TOMLDecodeError) as std:
                    tomllib.loads(text)
                with self.assertRaises(tomli.TOMLDecodeError) as ours:
                    tomli.loads(text)
                self.assertEqual(str(ours.exception), str(std.exception))

    def test_the_vendored_files_are_the_releases(self):
        folder = ENGINE / "segmently_modules/_vendor/tomli"
        self.assertEqual(sorted(p.name for p in folder.iterdir() if p.name != "__pycache__"),
                         sorted(VENDORED))
        for name, digest in VENDORED.items():
            with self.subTest(file=name):
                self.assertEqual(hashlib.sha256((folder / name).read_bytes()).hexdigest(), digest)
        self.assertEqual(tomli.__version__, "2.3.2")


class PlaceholderTest(unittest.TestCase):
    CASES = ["", "plain", "$a and ${b}", "$a $a ${a}", "$$a ${c", "$1 $_x ${y_2}", "a$ b",
             "${}", "$\n"]

    def test_the_names_of_get_identifiers(self):
        expected = {"": set(), "plain": set(), "$a and ${b}": {"a", "b"}, "$a $a ${a}": {"a"},
                    "$$a ${c": set(), "$1 $_x ${y_2}": {"_x", "y_2"}, "a$ b": set(), "${}": set(),
                    "$\n": set()}
        for text in self.CASES:
            with self.subTest(text=text):
                self.assertEqual(placeholder_names(text), expected[text])
                if hasattr(string.Template, "get_identifiers"):
                    self.assertEqual(placeholder_names(text),
                                     set(string.Template(text).get_identifiers()))


class SyntaxTest(unittest.TestCase):
    def test_every_engine_module_imports(self):
        failed = {}
        for info in pkgutil.walk_packages(segmently_modules.__path__, "segmently_modules."):
            if info.name == "segmently_modules.__main__":  # importing it runs the command line
                continue
            try:
                importlib.import_module(info.name)
            except Exception as e:  # noqa: BLE001 — every failure is the finding
                failed[info.name] = repr(e)
        self.assertEqual(failed, {})

    def test_no_syntax_newer_than_three_nine(self):
        for path in python_files():
            with self.subTest(file=path.relative_to(ENGINE).as_posix()):
                ast.parse(path.read_text(encoding="utf-8"), str(path), feature_version=(3, 9))

    def test_a_bar_annotation_only_under_the_future_import(self):
        future = re.compile(r"^from __future__ import annotations$", re.M)
        hits = {}
        for path in python_files():
            text = path.read_text(encoding="utf-8")
            lines = bar_annotations(ast.parse(text))
            if lines and not future.search(text):
                hits[path.relative_to(ENGINE).as_posix()] = lines[:3]
        self.assertEqual(hits, {})


if __name__ == "__main__":
    unittest.main()
