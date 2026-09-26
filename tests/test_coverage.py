"""`modsys coverage`: which repository files map to a module, and which map to none."""
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.helpers import FIXTURE, copy_fixture, git, init_git, run, run_json


def write(path: Path, text: str = "x = 1\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class CoverageTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        self.R = ("--root", str(self.root))
        for rel in ("src/checkout/cart.py", "README.md", "docs/résumé.md",
                    ".github/workflows/ci.yml", ".env.example", "build/out.js"):
            write(self.root / rel)
        write(self.root / ".gitignore", "build/\n")
        init_git(self.root)
        write(self.root / "tools/new.py")          # new, not ignored: counts
        write(self.root / "build/late.js")         # ignored: never counts

    def tearDown(self):
        self._tmp.cleanup()

    def config(self, text: str) -> None:
        write(self.root / ".modsys" / "config.toml", text)

    def coverage(self, *argv):
        code, env, err = run_json("coverage", *argv, *self.R)
        self.assertEqual(err, "")
        return code, env["data"] if env else None

    def test_file_set_is_tracked_plus_new_minus_ignored_dotfiles_and_module_docs(self):
        code, data = self.coverage()
        self.assertEqual(code, 0)
        self.assertEqual(data, {"total": 5, "mapped": 1, "share": 0.2,
                                "modules": {"catalog": 1},
                                "unmapped": ["README.md", "docs/résumé.md",
                                             "src/checkout/cart.py", "tools/new.py"]})

    def test_code_map_and_the_coverage_filters(self):
        self.config('[[code_map]]\nid = "src"\npattern = "src/{module}/**"\n')
        _, data = self.coverage()
        self.assertEqual((data["mapped"], data["share"], data["modules"]),
                         (2, 0.4, {"catalog": 1, "checkout": 1}))
        self.config('[[code_map]]\nid = "src"\npattern = "src/{module}/**"\n'
                    '[coverage]\nexclude = ["docs/**", "*.md"]\n')
        self.assertEqual(self.coverage()[1]["unmapped"], ["tools/new.py"])
        self.config('[coverage]\ninclude = ["src/**"]\n')  # a team include replaces "**"
        _, data = self.coverage()
        self.assertEqual((data["total"], data["unmapped"]), (2, ["src/checkout/cart.py"]))

    def test_fail_under(self):
        self.assertEqual(self.coverage("--fail-under", "20")[0], 0)
        code, data = self.coverage("--fail-under", "20.5")
        self.assertEqual((code, data["share"]), (1, 0.2))
        code, out, err = run("coverage", "--fail-under", "101", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("--fail-under must be between 0 and 100", err)

    def test_fail_under_compares_the_reported_share_exactly(self):
        # 29 of 100 files: share 0.29, and 0.29 * 100 is 28.999999999999996 in floating point
        for i in range(99):  # 28 more catalog files + src/catalog/service.py = 29 mapped
            write(self.root / ("src/catalog" if i < 28 else "other") / f"f{i:03}.py")
        self.config('[[code_map]]\nid = "src"\npattern = "src/{module}/**"\n[coverage]\n'
                    'exclude = ["README.md", "docs/**", "tools/**", "src/checkout/**"]\n')
        code, data = self.coverage("--fail-under", "29")
        self.assertEqual((code, data["total"], data["mapped"], data["share"]), (0, 100, 29, 0.29))
        self.assertEqual(self.coverage("--fail-under", "29.1")[0], 1)

    def test_share_rounds_down_and_never_overstates(self):
        # 1999 of 2000 mapped: round(1999 / 2000, 3) would report 1.0 / 100 % even though one
        # file is still unmapped — the share must round DOWN and --fail-under 100 must still
        # catch it.
        self.config('[[code_map]]\nid = "m"\nmodule = "catalog"\nglobs = ["many/mapped/**"]\n'
                    '[coverage]\ninclude = ["many/**"]\n')
        for i in range(1999):
            write(self.root / "many/mapped" / f"f{i:04}.py")
        write(self.root / "many" / "unmapped.py")
        code, data = self.coverage("--fail-under", "100")
        self.assertEqual((data["total"], data["mapped"], data["share"]), (2000, 1999, 0.999))
        self.assertEqual(code, 1)

    def test_no_counted_files_is_full_coverage(self):
        self.config('[coverage]\ninclude = ["nothing/**"]\n')
        self.assertEqual(self.coverage("--fail-under", "100"),
                         (0, {"total": 0, "mapped": 0, "share": 1.0, "modules": {},
                              "unmapped": []}))

    def test_text_output_lists_the_first_20_unmapped(self):
        for i in range(21):
            write(self.root / "misc" / f"m{i:02}.py")
        code, out, _ = run("coverage", "--fail-under", "50", *self.R)
        self.assertEqual(code, 1)
        self.assertIn("catalog", out)
        self.assertIn("mapped 1 of 26 file(s): share 0.038 (3.8 %)", out)
        self.assertIn("  … 5 more", out)
        self.assertIn("coverage 3.8 % is below --fail-under 50 %", out)


class CoverageRootTest(unittest.TestCase):
    def test_non_git_root_is_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, err = run("coverage", "--root", str(copy_fixture(tmp)))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("coverage needs a git repository", err)

    def test_root_in_a_git_subdirectory_counts_only_its_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            outer = Path(tmp) / "outer"
            shutil.copytree(FIXTURE, outer / "proj")
            write(outer / "top.py")
            git(outer, "init", "-q", "-b", "main")
            git(outer, "add", "-A")
            git(outer, "commit", "-q", "-m", "init")
            code, env, _ = run_json("coverage", "--root", str(outer / "proj"))
        self.assertEqual((code, env["data"]["total"], env["data"]["modules"]),
                         (0, 1, {"catalog": 1}))


if __name__ == "__main__":
    unittest.main()
