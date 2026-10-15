"""Compact code lists (DCP-AC-019, 020, 021, 024): `code-map files TARGET --source-only` keeps the
files whose `via` holds more than `docs` and that match no test glob; `--paths` prints one
repository-relative path per line; the `[tests] globs` of every layer add to the engine's default
test globs; module-discover's code pass reads the compact list. Without the new flags every
`code-map` output stays as it was (pinned below)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from segmently_modules import config
from segmently_modules.config import builtin_packs_root
from tests.helpers import NO_AUTO_MAINTENANCE, copy_fixture, git, init_git, run, run_json
from tests.test_p81_skill_text import between, command, filled, section, text

ENGINE = Path(__file__).resolve().parents[1]
RULE = ('[[code_map]]\nid = "catalog-code"\nmodule = "catalog"\n'
        'globs = ["src/catalog/**", "*catalog*", "__tests__/**", "tests/**", "test/**"]\n')
SOURCES = (  # code: no test glob matches them (the near misses included)
    "catalog_cli.py",                    # a root-level source file
    "src/catalog/fixtures/books.json",   # dropped only once `[tests] globs` names fixtures
    "src/catalog/latest_listing.py",     # near miss of test_*.py
    "src/catalog/protest/banner.py",     # near miss of **/test/**
    "src/catalog/search.py",
    "src/catalog/service.py")            # the fixture's code_pointer file, routed by RULE too
TESTS = {  # one file per default test-glob form, below a directory and at the root
    "**/__tests__/**": "src/catalog/__tests__/listing.js",
    "**/tests/**": "src/catalog/tests/listing.py",
    "**/test/**": "src/catalog/test/listing.rb",
    "**/*.test.*": "src/catalog/listing.test.ts",
    "**/*.spec.*": "src/catalog/listing.spec.ts",
    "**/test_*.py": "src/catalog/test_listing.py",
    "**/*_test.*": "src/catalog/listing_test.go",
    "__tests__/**": "__tests__/catalog.js",
    "tests/**": "tests/catalog.py",
    "test/**": "test/catalog.rb",
    "*.test.*": "catalog.test.ts",
    "*.spec.*": "catalog.spec.ts",
    "test_*.py": "test_catalog.py",
    "*_test.*": "catalog_test.go",
}
DOCS = ("modules/catalog/MODULE.md", "modules/catalog/roles/designer.md",
        "modules/catalog/roles/developer.md", "modules/catalog/roles/qa.md")


class Repo(unittest.TestCase):
    """A bookshop copy whose `catalog` has docs, sources and a test file in every default form."""
    extra_config = ""
    extra_files: tuple = ()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = copy_fixture(self._tmp.name)
        self.team = self.root / ".segmently-modules/config.toml"
        self.team.write_text(RULE + self.extra_config, encoding="utf-8")
        for rel in [*SOURCES, *TESTS.values(), *self.extra_files]:
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text("x = 1\n", encoding="utf-8")
        init_git(self.root)
        self.R = ("--root", str(self.root))

    def files(self, target="catalog", *flags):
        code, env, err = run_json("code-map", "files", target, *flags, *self.R)
        self.assertEqual((code, err), (0, ""))
        return env

    def paths(self, target="catalog", *flags):
        code, out, err = run("code-map", "files", target, *flags, "--paths", *self.R)
        self.assertEqual((code, err), (0, ""))
        return out


class SourceOnlyTest(Repo):  # DCP-AC-019
    def test_docs_only_and_every_test_form_are_left_out(self):
        base, env = self.files(), self.files("catalog", "--source-only")
        every = {f["path"]: f["via"] for f in base["data"]["files"]}
        self.assertLessEqual({*SOURCES, *TESTS.values(), *DOCS}, set(every))  # the base lists all
        kept = [f["path"] for f in env["data"]["files"]]
        self.assertEqual(kept, sorted(SOURCES))
        self.assertEqual(env["data"]["files"], [f for f in base["data"]["files"]
                                                if f["path"] in SOURCES])  # via as in the base
        self.assertEqual(every["src/catalog/service.py"],
                         ["code_pointer:file_paths", "code_map:catalog-code"])
        for path in DOCS:
            self.assertEqual(every[path], ["docs"])

    def test_each_default_form_drops_its_file(self):
        kept = {f["path"] for f in self.files("catalog", "--source-only")["data"]["files"]}
        for glob, path in TESTS.items():
            with self.subTest(glob=glob):
                self.assertIn(glob, config.DEFAULT_TEST_GLOBS)
                self.assertNotIn(path, kept)

    def test_the_envelope_keeps_the_base_shape(self):
        base, env = self.files(), self.files("catalog", "--source-only")
        self.assertEqual(sorted(env), sorted(base))
        self.assertEqual(env["schema"], base["schema"])
        self.assertEqual(list(env["data"]), list(base["data"]))  # target, files, total
        self.assertEqual(env["data"]["target"], "catalog")
        self.assertEqual(env["data"]["total"], len(SOURCES))  # the count follows the list
        self.assertEqual(sorted(env["data"]["files"][0]), ["path", "via"])

    def test_text_form(self):
        code, out, err = run("code-map", "files", "catalog", "--source-only", *self.R)
        self.assertEqual((code, err), (0, ""))
        lines = out.splitlines()
        self.assertEqual(lines[-1], f"{len(SOURCES)} file(s) map to catalog")
        self.assertEqual([ln.split("  (")[0] for ln in lines[:-1]], sorted(SOURCES))

    def test_a_docs_only_module_has_no_source(self):
        env = self.files("checkout", "--source-only")
        self.assertEqual(env["data"], {"target": "checkout", "files": [], "total": 0})


class DocsAndCodeTest(Repo):  # task-3 review M-5: `via` holds `docs` and a code source
    extra_config = ('[[code_map]]\nid = "catalog-doc-as-code"\nmodule = "catalog"\n'
                    'globs = ["modules/catalog/roles/qa.md"]\n')

    def test_a_doc_a_rule_routes_as_code_is_kept(self):
        every = {f["path"]: f["via"] for f in self.files()["data"]["files"]}
        self.assertEqual(every["modules/catalog/roles/qa.md"],
                         ["docs", "code_map:catalog-doc-as-code"])  # `docs` first
        kept = [f["path"] for f in self.files("catalog", "--source-only")["data"]["files"]]
        self.assertEqual(kept, sorted([*SOURCES, "modules/catalog/roles/qa.md"]))
        for path in set(DOCS) - {"modules/catalog/roles/qa.md"}:  # docs only: left out
            self.assertNotIn(path, kept)


class PathsTest(Repo):  # DCP-AC-020
    def test_one_sorted_path_per_line(self):
        out = self.paths("catalog", "--source-only")
        self.assertEqual(out, "".join(f"{p}\n" for p in sorted(SOURCES)))
        lines = out.split("\n")
        self.assertEqual(lines[-1], "")  # one final newline
        self.assertEqual(lines[:-1], sorted(lines[:-1]))
        self.assertEqual([ln for ln in lines if ln != ln.rstrip()], [])  # no trailing spaces

    def test_without_source_only_every_file_of_the_target(self):
        every = [f["path"] for f in self.files()["data"]["files"]]
        self.assertEqual(self.paths(), "".join(f"{p}\n" for p in sorted(every)))
        self.assertIn("modules/catalog/MODULE.md\n", self.paths())
        self.assertIn("tests/catalog.py\n", self.paths())

    def test_zero_files_is_an_empty_stdout(self):
        self.assertEqual(self.paths("checkout", "--source-only"), "")
        self.assertEqual(self.paths("payments/refunds", "--source-only"), "")

    def test_smaller_than_the_json(self):
        code, base, err = run("code-map", "files", "catalog", "--json", *self.R)
        self.assertEqual((code, err), (0, ""))
        compact = self.paths("catalog", "--source-only")
        self.assertLess(len(compact.encode("utf-8")), len(base.encode("utf-8")))

    def test_paths_with_json_is_refused(self):
        for flags in (("--paths",), ("--source-only", "--paths")):
            with self.subTest(flags=flags):
                code, out, err = run("code-map", "files", "catalog", *flags, "--json", *self.R)
                self.assertEqual((code, out), (2, ""))
                self.assertTrue(err.startswith("segmently-modules: error: "), err)
                self.assertIn("--paths", err)
                self.assertIn("--json", err)
                self.assertNotIn("Traceback", err)

    def test_list_and_add_refuse_the_flags(self):
        before = self.team.read_bytes()
        for argv in (("list",), ("list", "--module", "catalog"),
                     ("add", "extra", "--glob", "lib/**", "--module", "catalog"),
                     ("add", "extra", "--glob", "lib/**", "--module", "catalog", "--dry-run")):
            for flag in ("--source-only", "--paths"):
                for json_flag in ((), ("--json",)):
                    with self.subTest(argv=argv, flag=flag, json=json_flag):
                        code, out, err = run("code-map", *argv, flag, *json_flag, *self.R)
                        self.assertEqual((code, out), (2, ""))
                        self.assertIn("--source-only and --paths apply to code-map files", err)
        self.assertEqual(self.team.read_bytes(), before)  # a refused add writes nothing

    def test_real_streams(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
                   GIT_CEILING_DIRECTORIES=os.environ["GIT_CEILING_DIRECTORIES"],
                   PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(ENGINE), **NO_AUTO_MAINTENANCE)

        def cli(*argv):
            return subprocess.run([sys.executable, "-m", "segmently_modules", "code-map", "files",
                                   *argv, *self.R], capture_output=True, env=env, cwd=str(ENGINE))

        done = cli("catalog", "--source-only", "--paths")
        self.assertEqual((done.returncode, done.stderr), (0, b""))
        self.assertEqual(done.stdout, "".join(f"{p}\n" for p in sorted(SOURCES)).encode())
        done = cli("checkout", "--source-only", "--paths")
        self.assertEqual((done.returncode, done.stdout, done.stderr), (0, b"", b""))
        done = cli("catalog", "--paths", "--json")
        self.assertEqual((done.returncode, done.stdout), (2, b""))
        self.assertTrue(done.stderr.startswith(b"segmently-modules: error: "), done.stderr)
        self.assertEqual(done.stderr.count(b"\n"), 1)


class TestGlobsAddTest(Repo):  # DCP-AC-021
    extra_config = '[tests]\nglobs = ["**/fixtures/**"]\n'

    def kept(self):
        return [f["path"] for f in self.files("catalog", "--source-only")["data"]["files"]]

    def test_the_team_glob_adds_to_the_defaults(self):
        kept = self.kept()
        self.assertNotIn("src/catalog/fixtures/books.json", kept)
        self.assertEqual(kept, sorted(set(SOURCES) - {"src/catalog/fixtures/books.json"}))
        for path in TESTS.values():  # a default-pattern test is still dropped
            self.assertNotIn(path, kept)
        self.assertEqual(self.paths("catalog", "--source-only").splitlines(), kept)

    def test_every_layer_adds(self):
        pack = self.root / ".segmently-modules/packs/bookshop/pack.toml"
        pack.write_text(pack.read_text(encoding="utf-8")
                        + '\n[tests]\nglobs = ["src/catalog/protest/**"]\n', encoding="utf-8")
        (self.root / ".segmently-modules/config.user.toml").write_text(
            '[tests]\nglobs = ["catalog_cli.py", "**/tests/**"]\n', encoding="utf-8")
        self.assertEqual(self.kept(), ["src/catalog/latest_listing.py", "src/catalog/search.py",
                                       "src/catalog/service.py"])

    def test_the_effective_list(self):
        defaults = config.DEFAULT_TEST_GLOBS
        self.assertEqual(config.effective_test_globs({}), list(defaults))
        self.assertEqual(config.effective_test_globs({"tests": {"globs": ["**/fixtures/**",
                                                                          "**/tests/**"]}}),
                         [*defaults, "**/fixtures/**"])  # a repeated default once
        self.assertEqual(len(set(defaults)), len(defaults))
        self.assertEqual(sorted(defaults), sorted(TESTS))

    def test_an_unknown_key_passes(self):  # unknown keys pass in every table (forward compat)
        self.team.write_text(RULE + '[tests]\nglobs = ["**/fixtures/**"]\nlater = 1\n',
                             encoding="utf-8")
        self.assertNotIn("src/catalog/fixtures/books.json", self.kept())

    def test_bad_values_are_refused(self):
        for body, given in (('globs = "**/fixtures/**"', "'**/fixtures/**'"),
                            ("globs = [1]", "[1]"),
                            ('globs = ["ok/**", 2]', "['ok/**', 2]"),
                            ('globs = [""]', "['']"),
                            ("globs = 3", "3"),
                            ("globs = { a = 1 }", "{'a': 1}")):
            with self.subTest(body=body):
                self.team.write_text(RULE + f"[tests]\n{body}\n", encoding="utf-8")
                for argv in (("files", "catalog", "--source-only"), ("files", "catalog")):
                    code, out, err = run("code-map", *argv, "--json", *self.R)
                    self.assertEqual((code, out), (2, ""))
                    self.assertIn(str(self.team.resolve()), err)
                    self.assertIn(f"[tests] globs: expected a list of non-empty strings, got "
                                  f"{given}", err)
                    self.assertEqual(err.count("\n"), 1)

    def test_a_table_is_required(self):
        self.team.write_text("tests = 5\n" + RULE, encoding="utf-8")
        code, out, err = run("code-map", "files", "catalog", "--source-only", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("[tests] must be a table, got 5", err)

    def test_a_bad_pack_layer_is_named(self):
        pack = self.root / ".segmently-modules/packs/bookshop/pack.toml"
        pack.write_text(pack.read_text(encoding="utf-8") + '\n[tests]\nglobs = [""]\n',
                        encoding="utf-8")
        code, out, err = run("code-map", "files", "catalog", "--source-only", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("pack.toml: [tests] globs: expected a list of non-empty strings", err)


class RootLevelGlobTest(Repo):  # task-3 review M-2: `**/` needs a directory before it
    extra_files = ("fixtures/shelf.json",)
    rule = '[[code_map]]\nid = "catalog-fixtures"\nmodule = "catalog"\nglobs = ["fixtures/**"]\n'
    extra_config = rule + '[tests]\nglobs = ["**/fixtures/**"]\n'

    def kept(self):
        return [f["path"] for f in self.files("catalog", "--source-only")["data"]["files"]]

    def test_the_root_needs_its_own_glob(self):
        kept = self.kept()
        self.assertIn("fixtures/shelf.json", kept)  # `**/fixtures/**` misses the root
        self.assertNotIn("src/catalog/fixtures/books.json", kept)
        self.team.write_text(RULE + self.rule + '[tests]\nglobs = ["fixtures/**", "**/fixtures/**"]\n',
                             encoding="utf-8")  # the documented pair covers both
        kept = self.kept()
        self.assertNotIn("fixtures/shelf.json", kept)
        self.assertNotIn("src/catalog/fixtures/books.json", kept)


# Without the new flags, `code-map list`, `add` and `files` print what the base printed (AC-027);
# the strings were taken from the base engine on this fixture, with the `[tests]` table set.
LIST_TEXT = "catalog-code             catalog                  src/catalog/**, *catalog*, __tests__/**, tests/**, test/**\n"
LIST_DATA = [{"id": "catalog-code", "module": "catalog", "pattern": None,
              "globs": ["src/catalog/**", "*catalog*", "__tests__/**", "tests/**", "test/**"],
              "exclusive": False}]
ADD_TEXT = ("would append to .segmently-modules/config.toml:\n[[code_map]]\nid = \"extra\"\n"
            "module = \"catalog\"\nglobs = [\"lib/**\"]\n")
ADD_DATA = {"id": "extra", "file": ".segmently-modules/config.toml",
            "block": "[[code_map]]\nid = \"extra\"\nmodule = \"catalog\"\nglobs = [\"lib/**\"]\n",
            "dry_run": True}


class UnflaggedOutputsTest(Repo):  # the regression pin: byte-identical to the base
    extra_config = '[tests]\nglobs = ["**/fixtures/**"]\n'

    def same(self, argv, text_out, data):
        code, out, err = run("code-map", *argv, *self.R)
        self.assertEqual((code, out, err), (0, text_out, ""))
        code, out, err = run("code-map", *argv, "--json", *self.R)
        envelope = {"schema": "segmently-modules.code-map/1", "data": data}
        self.assertEqual((code, out, err),
                         (0, json.dumps(envelope, indent=2, ensure_ascii=False) + "\n", ""))

    def test_list_and_add(self):
        self.same(("list",), LIST_TEXT, LIST_DATA)
        self.same(("list", "--module", "catalog"), LIST_TEXT, LIST_DATA)
        self.same(("add", "extra", "--glob", "lib/**", "--module", "catalog", "--dry-run"),
                  ADD_TEXT, ADD_DATA)

    def test_files(self):
        via = {"src/catalog/service.py": ["code_pointer:file_paths", "code_map:catalog-code"]}
        every = sorted({*SOURCES, *TESTS.values(), *DOCS})
        rows = [{"path": p, "via": via.get(p, ["docs"] if p in DOCS else
                                           ["code_map:catalog-code"])} for p in every]
        text_out = "".join(f"{r['path']}  ({', '.join(r['via'])})\n" for r in rows)
        self.same(("files", "catalog"), text_out + f"{len(rows)} file(s) map to catalog\n",
                  {"target": "catalog", "files": rows, "total": len(rows)})
        self.same(("files", "checkout"),
                  "modules/checkout/MODULE.md  (docs)\nmodules/checkout/roles/developer.md  "
                  "(docs)\n2 file(s) map to checkout\n",
                  {"target": "checkout", "files": [
                      {"path": "modules/checkout/MODULE.md", "via": ["docs"]},
                      {"path": "modules/checkout/roles/developer.md", "via": ["docs"]}],
                   "total": 2})


class DiscoverSkillTextTest(unittest.TestCase):  # DCP-AC-024
    COMPACT = "segmently-modules code-map files <module> --source-only --paths"
    LOOKUP = "git grep -l -e <term> -- $(segmently-modules code-map files <module> --paths)"

    def skill(self) -> str:
        path = builtin_packs_root() / "core/skills/module-discover/SKILL.md"
        return path.read_bytes().decode("utf-8")

    def step6(self) -> str:
        return between(section(text("module-discover"), "## Steps"),
                       "6. **Code touch points.**", "7. **Owners and docs to update.**")

    def test_step_6_names_the_compact_list(self):
        step = self.step6()
        self.assertIn(f"`show`'s `code` and `code_globs`, or `{self.COMPACT}`", step)
        self.assertIn("its source files, one per line, docs and tests left out (empty: nothing "
                      "to search)", step)  # task-3 review M-6b
        self.assertIn("never `code-map files … --json` without `--source-only`", step)
        self.assertIn("source files first, tests last — searched in the module's test paths "
                      "only for the behaviour the task changes, found with "
                      f"`{self.LOOKUP}`;", step)  # task-3 review M-6a
        self.assertIn("the rest of the repository only after an empty module search", step)
        self.assertNotIn("only when that gives nothing", step)  # task-3 review M-6c
        self.assertEqual(command("module-discover", "segmently-modules code-map files"),
                         self.COMPACT)

    def test_no_code_map_json_without_source_only(self):
        body = " ".join(self.skill().split())
        spans = list(re.finditer(r"`([^`]*code-map files[^`]*)`", body))
        self.assertGreaterEqual(len(spans), 3)
        for m in spans:  # a `--json` form only in the sentence that forbids it
            with self.subTest(span=m.group(1)):
                if "--json" in m.group(1) and "--source-only" not in m.group(1):
                    self.assertTrue(body[m.end():].startswith(" without `--source-only`"))
        self.assertNotIn("segmently-modules code-map files <module> --json", body)

    def test_the_full_list_is_never_printed(self):  # task-3 review M-6a
        body = " ".join(self.skill().split())
        spans = re.findall(r"`([^`]*code-map files[^`]*)`", body)
        full = [s for s in spans if "--paths" in s and "--source-only" not in s]
        self.assertEqual(full, [self.LOOKUP])  # only inside `$(…)`, as git grep's paths

    def test_the_test_lookup_prints_the_hits_not_the_list(self):  # task-3 review M-6a
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            (root / ".segmently-modules/config.toml").write_text(RULE, encoding="utf-8")
            for rel, body in (("src/catalog/search.py", "def shelf_price():\n    return 1\n"),
                              ("src/catalog/tests/test_search.py",
                               "assert shelf_price() == 1\n"),
                              ("src/catalog/tests/test_other.py", "assert True\n")):
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text(body, encoding="utf-8")
            init_git(root)
            args, _ = filled(self.LOOKUP.split("$(", 1)[1].rstrip(")"), {"<module>": "catalog"})
            code, listed, err = run(*args, "--root", str(root))
            self.assertEqual((code, err), (0, ""))
            self.assertIn("src/catalog/tests/test_other.py\n", listed)  # the list the shell
            hits = git(root, "grep", "-l", "-e", "shelf_price", "--", *listed.split())  # passes on
        self.assertEqual(hits.splitlines(), ["src/catalog/search.py",
                                             "src/catalog/tests/test_search.py"])

    def test_the_command_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            (root / ".segmently-modules/config.toml").write_text(RULE, encoding="utf-8")
            for rel in ("src/catalog/search.py", "src/catalog/tests/listing.py"):
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text("x = 1\n", encoding="utf-8")
            init_git(root)
            args, _ = filled(command("module-discover", "segmently-modules code-map files"),
                             {"<module>": "catalog"})
            code, out, err = run(*args, "--root", str(root))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, "src/catalog/search.py\nsrc/catalog/service.py\n")


class DocsTest(unittest.TestCase):  # R-5: the table, the flags and the changelog lines
    def read(self, name: str) -> str:
        return (ENGINE / name).read_text(encoding="utf-8")

    def test_the_tests_table(self):
        doc = self.read("docs/configuration.md")
        part = doc.split("\n## `[tests]`\n", 1)[1].split("\n## ", 1)[0]
        for glob in config.DEFAULT_TEST_GLOBS:
            self.assertIn(f"`{glob}`", part)
        for phrase in ("| `globs` |", "is ADDED to the built-in list", "never removes a built-in glob",
                       "naming the file and `[tests] globs`",
                       '[tests]\nglobs = ["fixtures/**", "**/fixtures/**"]'):  # review M-2
            self.assertIn(phrase, part)
        self.assertIn("A glob of yours follows the same rule: `**/fixtures/**` leaves out "
                      "`src/fixtures/x` but not a root-level `fixtures/x`; add `fixtures/**` as "
                      "well.", " ".join(part.split()))  # task-3 review M-2

    def test_the_flags(self):
        doc = " ".join(self.read("docs/configuration.md").split())
        self.assertIn("`--source-only` keeps the TARGET's source files", doc)
        self.assertIn("`--paths` prints one repository-relative path per line, sorted, without "
                      "`via`", doc)  # task-3 review M-3
        self.assertNotIn("without the sources", doc)
        row = [ln for ln in self.read("docs/cli-contract.md").splitlines()  # final review M-6
               if ln.startswith("| `code-map list\\|add\\|files [--source-only] [--paths]` |")]
        self.assertEqual(len(row), 1)
        for phrase in ("files `--source-only`: the same shape", "files `--paths`: no JSON",
                       "with `--json` exit 2", "`--source-only` and `--paths` with `list` or `add` exit 2"):
            self.assertIn(phrase, row[0])

    def test_the_changelog(self):
        log = self.read("CHANGELOG.md")
        unreleased = log.split("## [Unreleased]", 1)[1].split("\n## [", 1)[0]
        self.assertIn("`code-map files TARGET --source-only`", unreleased)
        self.assertIn("`[tests] globs`", unreleased)
        # task-3 review M-1 (final review: and `--c`): the abbreviations the new flags made ambiguous
        line = [ln for ln in unreleased.splitlines() if "abbreviat" in ln]
        self.assertEqual(len(line), 1)
        for phrase in ("`code-map add … --pat`", "`--pa`", "`--p`", "`code-map files … --s`",
                       "`choose --c`", "spell options in full"):
            self.assertIn(phrase, line[0])

    def test_the_abbreviations_are_ambiguous(self):  # what that changelog line says
        for argv, flag in ((("code-map", "add", "x", "--pat", "lib/{module}/**", "--dry-run"),
                            "--pat"),
                           (("code-map", "files", "catalog", "--s"), "--s"),
                           (("choose", "--task", "t", "--c", "x"), "--c")):
            with self.subTest(argv=argv):
                code, out, err = run(*argv)
                self.assertEqual((code, out), (2, ""))
                self.assertIn(f"ambiguous option: {flag} could match", err)


if __name__ == "__main__":
    unittest.main()
