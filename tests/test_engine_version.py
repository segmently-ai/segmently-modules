"""No test depends on the engine's version (P61-AC-002, D9): a scan of tests/*.py for the
literal of `modsys.__version__` and of its release form (a `v` tag form too), and the
version-rewrite logic of the tools at three partitions — a dev version, a release version
without `.devN`, a later dev version — on throw-away copies. The two partitions of the engine's
own version are derived from it (a literal would trip the scan); the third is fixed and far
from any real version. The versions of fixture packs and plugins live in the 9.x.y range, so a
minor or major bump of the engine never meets one (final review I-2)."""
import re
import tempfile
import types
import unittest
from pathlib import Path

from tests.helpers import (engine_version, next_dev, next_major, next_minor, next_release,
                           release_version)
from tests.plugin_helpers import ENGINE, copy_engine, load_tool, run_tool

LATER = "9.2.0.dev3"


def literal_hits(version: str, root: Path = ENGINE / "tests") -> list[str]:
    """`file:line` of every test line holding `version` as a whole version token, its tag form
    (`v` + version) included."""
    token = re.compile(r"(?<![\w.])v?" + re.escape(version) + r"(?!\w|\.\w)")
    return [f"{path.name}:{n}" for path in sorted(root.glob("*.py"))
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
            if token.search(line)]


class ScanTest(unittest.TestCase):  # P61-AC-002
    def test_no_test_holds_the_engines_version_or_its_release_form(self):
        version = engine_version()
        for literal in (version, release_version(version)):
            with self.subTest(literal=literal):
                self.assertEqual(literal_hits(literal), [], f"{literal} is read from the "
                                 "source: use tests.helpers.engine_version() and friends")

    def test_the_scan_sees_a_planted_literal_and_only_a_whole_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "test_a.py").write_text('x = 1\nV = "1.2.3.dev4"\nW = "11.2.3"\n'
                                                 'P = "1.2.3"\nQ = "1.2.3.dev40"\n'
                                                 'T = "v1.2.3"\nU = "xv1.2.3"\n')
            self.assertEqual(literal_hits("1.2.3.dev4", Path(tmp)), ["test_a.py:2"])
            self.assertEqual(literal_hits("1.2.3", Path(tmp)), ["test_a.py:4", "test_a.py:6"])

    def test_the_scan_sees_the_engines_next_minor_and_next_major(self):  # final review I-2
        """A bump to the next minor or major version is caught in each form a test could
        write it: the dev version, the release, the tag (`v` + release)."""
        for following in (next_minor(), next_major()):
            planted = [f"{following}.dev0", following, f"v{following}"]
            with self.subTest(version=following), tempfile.TemporaryDirectory() as tmp:
                (Path(tmp) / "test_b.py").write_text(
                    "".join(f'X{n} = "{v}"\n' for n, v in enumerate(planted)))
                self.assertEqual(literal_hits(f"{following}.dev0", Path(tmp)), ["test_b.py:1"])
                self.assertEqual(literal_hits(following, Path(tmp)),
                                 ["test_b.py:2", "test_b.py:3"])


class HelperTest(unittest.TestCase):
    def test_the_forms_derive_from_one_version(self):
        for version, release, following, minor, major in (
                ("3.4.5.dev0", "3.4.5", "3.4.6", "3.5.0", "4.0.0"),
                ("3.4.0", "3.4.0", "3.4.1", "3.5.0", "4.0.0"),
                ("7.2.0.dev3", "7.2.0", "7.2.1", "7.3.0", "8.0.0"),
                ("1.9.9.dev12", "1.9.9", "1.9.10", "1.10.0", "2.0.0")):
            with self.subTest(version=version):
                self.assertEqual(release_version(version), release)
                self.assertEqual(next_release(version), following)
                self.assertEqual(next_dev(version), following + ".dev0")
                self.assertEqual((next_minor(version), next_major(version)), (minor, major))

    def test_the_engine_version_is_the_source_line(self):
        import modsys
        self.assertEqual(engine_version(), modsys.__version__)


class PartitionTest(unittest.TestCase):  # P61-AC-002: the version-rewrite logic at 3 partitions
    PARTITIONS = (engine_version(), release_version(), LATER)  # dev, no devN, a later dev

    def test_the_channel_versions(self):
        publish = load_tool("publish")
        for version in self.PARTITIONS:
            with self.subTest(version=version):
                base = release_version(version)
                self.assertEqual(publish.base_version(version), base)
                self.assertEqual(publish.channel_version("stable", version, "0" * 64), base)
                self.assertEqual(publish.channel_version("dev", version, "ab" * 32),
                                 f"{base}-dev.habababab")

    def test_the_release_commit_and_the_next_version_commit(self):
        release = load_tool("release")
        for version in self.PARTITIONS:
            with self.subTest(version=version):
                made = []
                step = types.SimpleNamespace(channel="stable", version=release_version(version),
                                             bump=lambda v, message: made.append((v, message)))
                self.assertEqual(release.Release.next_version(step),
                                 f"the engine is at {next_dev(version)}")
                self.assertEqual(made, [(next_dev(version), "start modsys {}")])

    def test_a_build_of_a_copy_stamps_the_version(self):
        for version in self.PARTITIONS:
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                engine = copy_engine(Path(tmp).resolve() / "engine")
                for rel, pattern in (("modsys/__init__.py", r'^__version__ = "[^"]*"$'),
                                     ("pyproject.toml", r'^version = "[^"]*"$')):
                    text = (engine / rel).read_text(encoding="utf-8")
                    key = "__version__" if rel.endswith(".py") else "version"
                    (engine / rel).write_text(re.sub(pattern, f'{key} = "{version}"', text,
                                                     count=1, flags=re.M), encoding="utf-8")
                out = Path(tmp).resolve() / "out"
                proc = run_tool(engine, "build_plugins", "--out", str(out))
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertTrue(proc.stdout.startswith(f"built modsys {version}: "), proc.stdout)
                self.assertIn(f'__version__ = "{version}"',
                              (out / "modsys/runtime/modsys/__init__.py").read_text())


if __name__ == "__main__":
    unittest.main()
