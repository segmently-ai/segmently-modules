"""`tools/build_plugins.py` (P6 D1, row 6.1): the three plugins' layout and sources, manifests
from one table, a byte-reproducible build with the modes of git's index, `claude plugin
validate` (when `claude` is on PATH) and the refusals. The builder runs in a throw-away git copy
of this engine: it builds the tree it lives in."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
from pathlib import Path

from modsys.config import BUILTIN_PLUGINS
from tests.helpers import git
from tests.plugin_helpers import (CLAUDE, ENGINE, NO_CLAUDE, claude_env, copy_engine, load_tool,
                                  run_tool, tree)

PACKS = {"modsys": "core", "modsys-ui": "ui", "modsys-qa": "qa"}
MANIFESTS = (".claude-plugin/plugin.json", "plugin.json", ".codex-plugin/plugin.json")
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}(T\d{2}:\d{2})?")
COMMIT = re.compile(r"\b[0-9a-f]{40}\b")


class BuilderRepo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls._tmp.name).resolve()
        cls.engine = copy_engine(cls.base / "engine")
        cls.out = cls.base / "out"
        proc = run_tool(cls.engine, "build_plugins", "--out", str(cls.out))
        assert proc.returncode == 0, proc.stderr

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def tracked(self, engine: Path | None = None) -> list[str]:
        return git(engine or self.engine, "ls-files", "modsys").split()

    def skills(self, pack: str) -> dict[str, str]:
        data = tomllib.loads((self.engine / f"modsys/defaults/packs/{pack}/pack.toml")
                            .read_text())
        return {sid: f"modsys/defaults/packs/{pack}/{spec['path']}"
                for sid, spec in data["skills"].items()}


class LayoutTest(BuilderRepo):  # P6-AC-008
    def test_the_complete_file_sets(self):
        self.assertEqual(sorted(p.name for p in self.out.iterdir()),
                         ["modsys", "modsys-qa", "modsys-ui"])
        for name, pack in PACKS.items():
            with self.subTest(plugin=name):
                files = sorted(p.relative_to(self.out / name).as_posix()
                               for p in (self.out / name).rglob("*") if p.is_file())
                want = [*MANIFESTS, "README.md"]
                for sid, src in self.skills(pack).items():
                    want += [f"skills/{sid}/{rel[len(src) + 1:]}" for rel in self.tracked()
                             if rel.startswith(src + "/")]
                if name == "modsys":
                    want += ["bin/modsys"] + [f"runtime/{rel}" for rel in self.tracked()]
                self.assertEqual(files, sorted(want))
        self.assertIn("skills/module-lint/references/lint-codes.md",
                      [p.relative_to(self.out / "modsys").as_posix()
                       for p in (self.out / "modsys").rglob("*")])
        self.assertEqual(len(list((self.out / "modsys/skills").glob("*/SKILL.md"))), 9)

    def test_bytes_equal_to_the_sources(self):
        for name, pack in PACKS.items():
            for sid, src in self.skills(pack).items():
                for rel in (p for p in self.tracked() if p.startswith(src + "/")):
                    self.assertEqual((self.out / name / "skills" / sid / rel[len(src) + 1:])
                                     .read_bytes(), (self.engine / rel).read_bytes())
        for rel in self.tracked():
            self.assertEqual((self.out / "modsys/runtime" / rel).read_bytes(),
                             (self.engine / rel).read_bytes())
        self.assertEqual((self.out / "modsys/bin/modsys").read_bytes(),
                         (self.engine / "tools/launcher.sh").read_bytes())

    def test_what_never_ships(self):
        names = {p.name for p in self.out.rglob("*")}
        for bad in ("pack.toml", "__pycache__", ".DS_Store", ".modsys-managed",
                    ".modsys-ejected"):
            self.assertNotIn(bad, {p.name for p in self.out.rglob("*")
                                   if "runtime" not in p.relative_to(self.out).parts}
                             if bad == "pack.toml" else names)
        self.assertFalse([p for p in self.out.rglob("*.pyc")])
        for name in ("modsys-ui", "modsys-qa"):
            self.assertFalse((self.out / name / "bin").exists())
            self.assertFalse((self.out / name / "runtime").exists())
        for name in PACKS:
            top = {p.name for p in (self.out / name).iterdir()}
            self.assertFalse(top & {"tests", "evals", "tools", "docs", "roles", "templates"})
            self.assertFalse(list((self.out / name / "skills").rglob("roles")))

    def test_untracked_files_and_another_modsys_on_pythonpath(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp).resolve()
            engine = copy_engine(tmp / "engine")
            (engine / "modsys/scratch.py").write_text("x = 1\n")  # untracked
            (engine / "modsys/defaults/packs/core/skills/module-lint/notes.md").write_text("n\n")
            (engine / "modsys/__pycache__").mkdir(exist_ok=True)
            (engine / "modsys/__pycache__/cli.cpython-314.pyc").write_bytes(b"\0")
            shadow = tmp / "shadow/modsys"
            shadow.mkdir(parents=True)
            (shadow / "__init__.py").write_text('__version__ = "9.9.9"\n')
            proc = run_tool(engine, "build_plugins", "--out", str(tmp / "out"),
                            env={"PYTHONPATH": str(tmp / "shadow")})
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(tree(tmp / "out"), tree(self.out))

    def test_git_location_variables_of_the_caller_are_dropped(self):  # a run from a git hook
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp).resolve()
            proc = run_tool(self.engine, "build_plugins", "--out", str(tmp / "out"),
                            env={"GIT_INDEX_FILE": str(tmp / "another-index"),
                                 "GIT_DIR": str(tmp / "another.git"),
                                 "GIT_WORK_TREE": str(tmp)})
            self.assertEqual((proc.returncode, proc.stderr), (0, ""))
            self.assertEqual(tree(tmp / "out"), tree(self.out))
            self.assertEqual(sorted(p.name for p in tmp.iterdir()), ["out"])
        self.assertFalse((self.engine / "tools/__pycache__").exists())

    def test_the_default_out_is_git_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = copy_engine(Path(tmp).resolve() / "engine")
            proc = run_tool(engine, "build_plugins")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue((engine / "dist/plugins/modsys/bin/modsys").is_file())
            self.assertEqual(git(engine, "status", "--short"), "")
            built = engine / "dist/plugins/modsys"
            count = len([p for p in built.rglob("*") if p.is_file()])
            self.assertEqual(proc.stdout.splitlines()[0],
                             f"built modsys 0.1.0.dev0: {count} files in {built}")


class ManifestTest(BuilderRepo):  # P6-AC-009
    def load(self, name: str, rel: str) -> dict:
        text = (self.out / name / rel).read_text(encoding="utf-8")
        value = json.loads(text)
        self.assertEqual(text, json.dumps(value, indent=2, ensure_ascii=False) + "\n")
        return value

    def test_the_exact_keys(self):
        for name in PACKS:
            with self.subTest(plugin=name):
                claude = self.load(name, ".claude-plugin/plugin.json")
                root = self.load(name, "plugin.json")
                codex = self.load(name, ".codex-plugin/plugin.json")
                shared = ["name", "version", "description", "author", "keywords"]
                self.assertEqual(list(claude), shared + ([] if name == "modsys"
                                                         else ["dependencies"]))
                self.assertEqual(list(root), ["$schema"] + shared)
                self.assertEqual(list(codex), shared + ["skills"])
                if name != "modsys":
                    self.assertEqual(claude["dependencies"], ["modsys"])
                self.assertEqual(codex["skills"], "./skills/")
                self.assertEqual(root["$schema"], "https://agent-plugins.org/schemas/1.0.0/"
                                                  "plugin.schema.json")
                self.assertEqual(list(claude["author"]), ["name"])
                for manifest in (claude, root, codex):
                    self.assertEqual({k: manifest[k] for k in shared},
                                     {k: claude[k] for k in shared})
                    self.assertFalse({"homepage", "repository", "license"} & set(manifest))
                    text = json.dumps(manifest)
                    self.assertIsNone(ISO_DATE.search(text))
                    self.assertIsNone(COMMIT.search(text))
                self.assertEqual(claude["name"], name)
                self.assertEqual(claude["version"], "0.1.0.dev0")

    def test_one_table(self):
        builder = load_tool("build_plugins")
        self.assertEqual({n: s["pack"] for n, s in builder.PLUGINS.items()},
                         {v: k for k, v in BUILTIN_PLUGINS.items()})  # the engine's pack map
        for name in PACKS:
            rendered = builder.manifests(name, "0.1.0.dev0")
            for rel in MANIFESTS:
                self.assertEqual(self.load(name, rel), rendered[rel])
        self.assertEqual(list((ENGINE / "tools").rglob("*.json")), [])

    def test_a_given_version_everywhere(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            proc = run_tool(self.engine, "build_plugins", "--out", str(out), "--version",
                            "1.2.3")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            versions = {json.loads((out / n / rel).read_text())["version"]
                        for n in PACKS for rel in MANIFESTS}
            self.assertEqual(versions, {"1.2.3"})
            self.assertIn('__version__ = "0.1.0.dev0"',
                          (out / "modsys/runtime/modsys/__init__.py").read_text())

    def test_the_readmes(self):
        for name in PACKS:
            text = (self.out / name / "README.md").read_text(encoding="utf-8")
            for needle in ("Claude Code:", "Codex:", "Cursor, Gemini CLI, GitHub Copilot:",
                           "`modsys packs sync --agent cursor`", 'builtin_delivery = "plugin"',
                           "`#dev` / `--ref dev`", "<owner>/<publish repo>"):
                self.assertIn(needle, text)
            for url in re.findall(r"github\.com[:/][^\s`]*", text):
                self.assertTrue(url.split("com", 1)[1][1:].startswith("<owner>/"), url)
        for name in ("modsys-ui", "modsys-qa"):
            text = (self.out / name / "README.md").read_text(encoding="utf-8")
            self.assertIn("It needs the `modsys` plugin", text)
            self.assertIn("`codex plugin add modsys@modsys`", text)
            self.assertIn("install the CLI first", text)


class ReproducibleTest(BuilderRepo):  # P6-AC-010 (SI-13)
    def build(self, out: Path, umask: int, tz: str, seed: str) -> None:
        proc = subprocess.run(
            ["/bin/sh", "-c", f'umask {umask:03o} && exec "$0" "$@"', sys.executable,
             str(self.engine / "tools/build_plugins.py"), "--out", str(out)],
            capture_output=True, text=True, env={**os.environ, "TZ": tz,
                                                 "PYTHONHASHSEED": seed})
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_two_builds_and_the_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self.build(tmp / "a", 0o022, "UTC", "1")
            time.sleep(1.1)
            self.build(tmp / "b", 0o077, "Asia/Tokyo", "2")
            self.assertEqual(tree(tmp / "a"), tree(tmp / "b"))
            self.assertEqual(tree(tmp / "a"), tree(self.out))
            for rel, (mode, _) in tree(tmp / "b").items():
                want = 0o755 if rel.endswith("/") or rel == "modsys/bin/modsys" else 0o644
                self.assertEqual(mode, want, rel)
            for path in self.engine.rglob("*"):  # touching every source changes nothing
                if path.is_file() and ".git" not in path.parts:
                    os.utime(path)
            self.build(tmp / "c", 0o022, "UTC", "3")
            self.assertEqual(tree(tmp / "c"), tree(tmp / "a"))

    def test_an_executable_in_the_index_keeps_0755(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp).resolve()
            engine = copy_engine(tmp / "engine")
            rel = "modsys/defaults/packs/core/skills/module-lint/references/lint-codes.md"
            git(engine, "update-index", "--chmod=+x", rel)
            git(engine, "commit", "-q", "-m", "x")
            proc = run_tool(engine, "build_plugins", "--out", str(tmp / "out"))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            built = tree(tmp / "out")
            self.assertEqual(built["modsys/skills/module-lint/references/lint-codes.md"][0],
                             0o755)
            self.assertEqual(built[f"modsys/runtime/{rel}"][0], 0o755)
            self.assertEqual(built["modsys/skills/module-lint/SKILL.md"][0], 0o644)


class ValidateTest(BuilderRepo):  # P6-AC-011 (the plugins; the marketplace: test_publish)
    def validate(self, path: Path) -> tuple[int, dict]:
        proc = subprocess.run([CLAUDE, "plugin", "validate", "--strict", "--json", str(path)],
                              capture_output=True, text=True, timeout=120,
                              env=claude_env(self.base / "claude-config"))
        return proc.returncode, json.loads(proc.stdout)

    @unittest.skipUnless(CLAUDE, NO_CLAUDE)
    def test_claude_validates_each_plugin(self):
        for name in PACKS:
            with self.subTest(plugin=name):
                code, report = self.validate(self.out / name)
                self.assertEqual((code, report["success"], report["manifest"]["errors"],
                                  report["manifest"]["warnings"]), (0, True, [], []))

    @unittest.skipUnless(CLAUDE, NO_CLAUDE)
    def test_the_check_can_fail(self):
        for change in ({"name": None}, {"dependencies": "modsys"}):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                broken = Path(tmp) / "modsys-ui"
                shutil.copytree(self.out / "modsys-ui", broken)
                manifest = broken / ".claude-plugin/plugin.json"
                value = {**json.loads(manifest.read_text()), **change}
                manifest.write_text(json.dumps({k: v for k, v in value.items()
                                                if v is not None}))
                self.assertEqual(self.validate(broken)[0], 1)


class RefusalTest(unittest.TestCase):  # P6-AC-028, P6-AC-033
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name).resolve()
        self.engine = copy_engine(self.tmp / "engine")
        self.out = self.tmp / "out"

    def tearDown(self):
        self._tmp.cleanup()

    def refused(self, *argv: str, engine: Path | None = None, env: dict | None = None,
                code: int = 2) -> str:
        before = tree(self.out) if self.out.exists() else None
        proc = run_tool(engine or self.engine, "build_plugins", "--out", str(self.out), *argv,
                        env=env)
        self.assertEqual((proc.returncode, proc.stdout), (code, ""), proc.stderr)
        self.assertEqual(tree(self.out) if self.out.exists() else None, before)
        return proc.stderr

    def test_a_stale_earlier_build_is_replaced(self):
        self.assertEqual(run_tool(self.engine, "build_plugins", "--out", str(self.out))
                         .returncode, 0)
        (self.out / "modsys/stale.txt").write_text("old\n")
        (self.out / "other-tool").mkdir()
        (self.out / "other-tool/keep.txt").write_text("keep\n")
        self.assertEqual(run_tool(self.engine, "build_plugins", "--out", str(self.out))
                         .returncode, 0)
        self.assertFalse((self.out / "modsys/stale.txt").exists())
        self.assertEqual((self.out / "other-tool/keep.txt").read_text(), "keep\n")

    def test_an_interrupted_build_leaves_out_as_it_was(self):
        self.assertEqual(run_tool(self.engine, "build_plugins", "--out", str(self.out))
                         .returncode, 0)
        (self.out / "modsys/stale.txt").write_text("old\n")
        err = self.refused("--version", "0.9.0", code=130,
                           env={"MODSYS_BUILD_INTERRUPT_AFTER": "modsys"})
        self.assertEqual(err, "build_plugins.py: interrupted\n")

    def test_versions(self):
        for good in ("0.2.0", "0.2.0-dev.habcdef12"):
            with self.subTest(version=good):
                proc = run_tool(self.engine, "build_plugins", "--out", str(self.out),
                                "--version", good)
                self.assertEqual(proc.returncode, 0, proc.stderr)
        for bad in ("v0.2.0", "0.2", "", "0.2.0-dev.01"):
            with self.subTest(version=bad):
                err = self.refused("--version", bad)
                self.assertIn(f"--version {bad!r}: a SemVer 2.0 version is required", err)

    def test_not_a_git_work_tree(self):
        export = self.tmp / "export"
        export.mkdir()
        archive = subprocess.run(["git", "-C", str(self.engine), "archive", "HEAD"],
                                 capture_output=True, check=True).stdout
        subprocess.run(["tar", "-x", "-C", str(export)], input=archive, check=True)
        err = self.refused(engine=export)
        self.assertIn("is not a git work tree", err)

    def test_a_tracked_file_missing_and_a_symlink(self):
        (self.engine / "modsys/defaults/templates/roles/po.md").unlink()
        self.assertIn("modsys/defaults/templates/roles/po.md is tracked but missing on disk",
                      self.refused())
        git(self.engine, "checkout", "--", "modsys/defaults/templates/roles/po.md")
        link = self.engine / "modsys/defaults/packs/ui/skills/designer-review/extra.md"
        os.symlink("SKILL.md", link)
        self.assertIn("skill designer-review: modsys/defaults/packs/ui/skills/designer-review/"
                      "extra.md is a symlink", self.refused())
        git(self.engine, "add", str(link))
        git(self.engine, "commit", "-q", "-m", "a symlink")
        self.assertIn("extra.md is tracked as a symlink", self.refused())

    def test_out_at_or_above_the_engine(self):  # the engine copy lives in a directory `modsys`
        engine = copy_engine(self.tmp / "work/modsys")
        link = self.tmp / "link"
        os.symlink(self.tmp / "work", link)
        before = tree(engine)
        self.assertIn(".git/HEAD", before)
        for out in (self.tmp / "work", link, engine / "..", engine):
            with self.subTest(out=out):
                proc = run_tool(engine, "build_plugins", "--out", str(out))
                self.assertEqual((proc.returncode, proc.stdout), (2, ""), proc.stderr)
                self.assertTrue(proc.stderr.startswith("build_plugins.py: error: "), proc.stderr)
                self.assertIn("is this engine tree or holds it" if out != engine
                              else "exists and is not a build of the modsys plugin",
                              proc.stderr)
                self.assertEqual(tree(engine), before)  # nothing deleted, `.git` included
                self.assertEqual(sorted(p.name for p in (self.tmp / "work").iterdir()),
                                 ["modsys"])

    def test_a_foreign_directory_is_never_replaced(self):
        (self.out / "modsys").mkdir(parents=True)
        (self.out / "modsys/keep.txt").write_text("not a build\n")
        err = self.refused()
        self.assertIn(f"{self.out}/modsys exists and is not a build of the modsys plugin", err)
        shutil.rmtree(self.out)
        self.assertEqual(run_tool(self.engine, "build_plugins", "--out", str(self.out))
                         .returncode, 0)
        manifest = self.out / "modsys-qa/.claude-plugin/plugin.json"
        manifest.write_text(manifest.read_text().replace('"modsys-qa"', '"another-plugin"'))
        self.assertIn("modsys-qa exists and is not a build of the modsys-qa plugin",
                      self.refused())
        shutil.rmtree(self.out / "modsys-qa")
        (self.out / "modsys-qa").write_text("a file\n")
        self.assertIn("modsys-qa exists and is not a build", self.refused())

    def test_the_swap_is_all_or_nothing(self):
        self.assertEqual(run_tool(self.engine, "build_plugins", "--out", str(self.out))
                         .returncode, 0)
        (self.out / "modsys/stale.txt").write_text("old\n")
        for seam in ("swap:modsys", "swap:modsys-qa"):  # after the first and the last rename
            with self.subTest(seam=seam):
                err = self.refused("--version", "0.9.0", code=130,
                                   env={"MODSYS_BUILD_INTERRUPT_AFTER": seam})
                self.assertEqual(err, "build_plugins.py: interrupted\n")
        if os.geteuid() == 0:
            self.skipTest("root renames a read-only directory")
        (self.out / "modsys-ui").chmod(0o555)  # the second replacement cannot be renamed aside
        try:
            err = self.refused("--version", "0.9.0")
        finally:
            (self.out / "modsys-ui").chmod(0o755)
        self.assertIn("build_plugins.py: error: cannot write ", err)
        self.assertNotIn("Traceback", err)

    def test_out_holds_only_the_plugins_after_every_run(self):  # re-review N-2
        (self.out / "other-tool").mkdir(parents=True)
        (self.out / "other-tool/keep.txt").write_text("keep\n")
        want = ["modsys", "modsys-qa", "modsys-ui", "other-tool"]  # no staging directory

        def listing() -> list[str]:
            return sorted(p.name for p in self.out.iterdir())

        self.assertEqual(run_tool(self.engine, "build_plugins", "--out", str(self.out))
                         .returncode, 0)
        self.assertEqual(listing(), want)
        self.refused("--version", "v1")
        self.assertEqual(listing(), want)
        self.refused("--version", "0.9.0", code=130,
                     env={"MODSYS_BUILD_INTERRUPT_AFTER": "swap:modsys-ui"})
        self.assertEqual(listing(), want)
        if os.geteuid() == 0:
            self.skipTest("root removes any directory")
        locked = self.out / "modsys-ui/x"  # the earlier build holds what cannot be listed
        locked.mkdir()
        (locked / "f").write_text("f\n")
        locked.chmod(0)
        proc = run_tool(self.engine, "build_plugins", "--out", str(self.out))
        self.assertEqual((proc.returncode, proc.stderr), (0, ""))
        self.assertEqual(listing(), want)  # the earlier build is gone, with it
        self.assertFalse((self.out / "modsys-ui/x").exists())

    def test_no_git_and_an_out_that_cannot_be_written(self):
        empty = self.tmp / "empty-path"
        empty.mkdir()
        err = self.refused(env={"PATH": str(empty)})
        self.assertTrue(err.startswith("build_plugins.py: error: git is not installed or cannot "
                                       "run"), err)
        self.assertEqual(err.count("\n"), 1)
        if os.geteuid() == 0:
            self.skipTest("root writes into a read-only directory")
        locked = self.tmp / "locked"
        locked.mkdir()
        locked.chmod(0o555)
        try:
            for out in (locked, locked / "deeper/out"):
                proc = run_tool(self.engine, "build_plugins", "--out", str(out))
                self.assertEqual((proc.returncode, proc.stdout), (2, ""), proc.stderr)
                self.assertTrue(proc.stderr.startswith("build_plugins.py: error: cannot write "),
                                proc.stderr)
                self.assertEqual(list(locked.iterdir()), [])
        finally:
            locked.chmod(0o755)

    def test_a_refused_build_does_not_create_out(self):
        out = self.tmp / "new/deeper/out"
        proc = run_tool(self.engine, "build_plugins", "--out", str(out),
                        env={"MODSYS_BUILD_INTERRUPT_AFTER": "modsys-ui"})
        self.assertEqual(proc.returncode, 130)
        self.assertFalse((self.tmp / "new").exists())

    def test_uncommitted_changes_are_named(self):
        proc = run_tool(self.engine, "build_plugins", "--out", str(self.out))
        self.assertEqual((proc.returncode, proc.stderr), (0, ""))
        (self.engine / "modsys/scratch.py").write_text("x = 1\n")  # untracked: never ships
        launcher = self.engine / "tools/launcher.sh"
        launcher.write_text(launcher.read_text() + "# edited\n")
        cli = self.engine / "modsys/cli.py"
        cli.write_text(cli.read_text() + "# edited\n")
        proc = run_tool(self.engine, "build_plugins", "--out", str(self.out))
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stderr, "build_plugins.py: warning: built from a work tree with "
                                      "uncommitted changes: modsys/cli.py, tools/launcher.sh\n")
        self.assertTrue((self.out / "modsys/bin/modsys").read_text().endswith("# edited\n"))
        roles = sorted((self.engine / "modsys/defaults/templates/roles").glob("*.md"))[:5]
        for path in roles:
            path.write_text(path.read_text() + "\nEdited.\n")
        git(self.engine, "add", "--", str(roles[0]))  # staged or not: uncommitted
        proc = run_tool(self.engine, "build_plugins", "--out", str(self.out))
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stderr.count("\n"), 1)
        self.assertTrue(proc.stderr.rstrip().endswith(", … and 2 more"), proc.stderr)
        self.assertEqual(proc.stderr.count("modsys/"), 5)

    def test_a_usage_error(self):
        proc = run_tool(self.engine, "build_plugins", "--frobnicate")
        self.assertEqual((proc.returncode, proc.stdout), (2, ""))
        self.assertIn("usage:", proc.stderr)
        self.assertFalse((self.engine / "dist").exists())


if __name__ == "__main__":
    unittest.main()
