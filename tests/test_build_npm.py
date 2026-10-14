"""tools/build_npm.py — the npm package `@segmently/modules`: the core plugin's launcher and runtime
plus package.json, README.md and LICENSE; the engine version in npm form; two builds
byte-identical; --out replaced only when it is an earlier build; and, with npm on PATH, the
packed package installs into a throw-away prefix and runs this Python's engine through the
launcher (without npm, a visible skip)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import engine_version, git
from tests.plugin_helpers import ENGINE, copy_engine, load_tool, run_tool, tree

NPM = shutil.which("npm")


class BuildNpmTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls._tmp.name).resolve()
        cls.engine = copy_engine(cls.tmp / "engine")  # with pyproject.toml and LICENSE
        cls.tool = load_tool("build_npm")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def build(self, out: Path, *argv: str):
        proc = run_tool(self.engine, "build_npm", "--out", str(out), *argv)
        return proc

    def test_the_package(self):
        out = self.tmp / "a" / "npm"
        proc = self.build(out)
        self.assertEqual((proc.returncode, proc.stderr), (0, ""))
        version = self.tool.npm_version(engine_version(self.engine))
        self.assertEqual(proc.stdout.splitlines()[1],
                         f"publish: npm publish {out} --tag {self.tool.dist_tag(version)}")
        shipped = git(self.engine, "ls-files", "segmently_modules").split()
        got = {rel: v for rel, v in tree(out).items() if not rel.endswith("/")}
        self.assertEqual(sorted(got), sorted(["package.json", "README.md", "LICENSE",
                                              "bin/segmently-modules",
                                              *(f"runtime/{p}" for p in shipped)]))
        for rel in shipped:
            self.assertEqual(got[f"runtime/{rel}"][1], (self.engine / rel).read_bytes())
        self.assertEqual(got["bin/segmently-modules"],
                         (0o755, (self.engine / "tools/launcher.sh").read_bytes()))
        self.assertEqual(got["LICENSE"][1], (self.engine / "LICENSE").read_bytes())
        doc = json.loads(got["package.json"][1])
        self.assertEqual(doc, {
            "name": "@segmently/modules", "version": version,
            "description": "Code-structure-centric context layer for AI coding agents",
            "license": "MIT", "homepage": "https://github.com/segmently-ai/segmently-modules",
            "repository": {"type": "git",
                           "url": "git+https://github.com/segmently-ai/segmently-modules.git"},
            "bugs": {"url": "https://github.com/segmently-ai/segmently-modules/issues"},
            "keywords": ["segmently-modules", "module-registry", "documentation",
                         "agent-skills"],
            "bin": {"segmently-modules": "bin/segmently-modules"},
            "files": ["bin/", "runtime/"], "os": ["darwin", "linux"],
            "publishConfig": {"access": "public"}})
        readme = got["README.md"][1].decode("utf-8")
        for needle in ("npm install -g @segmently/modules", "npx @segmently/modules --help",
                       "Python 3.9 or newer", "Command Line Tools", "SEGMENTLY_MODULES_PYTHON"):
            self.assertIn(needle, readme)
        self.assertEqual({mode for rel, (mode, _) in tree(out).items() if rel.endswith("/")},
                         {0o755})

    def test_two_builds_are_byte_identical_and_replace_only_their_own(self):
        out = self.tmp / "b" / "npm"
        self.assertEqual(self.build(out).returncode, 0)
        first = tree(out)
        self.assertEqual(self.build(out).returncode, 0)  # an earlier build is replaced
        self.assertEqual(tree(out), first)
        self.assertEqual(sorted(p.name for p in out.parent.iterdir()), ["npm"])

    def test_versions(self):
        self.assertEqual(self.tool.npm_version("9.3.1"), "9.3.1")
        self.assertEqual(self.tool.npm_version("9.3.1.dev3"), "9.3.1-dev.3")
        self.assertEqual((self.tool.dist_tag("9.3.1"), self.tool.dist_tag("9.3.1-dev.3")),
                         ("latest", "next"))
        with self.assertRaises(self.tool.BuildError):
            self.tool.npm_version("9.3.1rc1")
        out = self.tmp / "c" / "npm"
        self.assertEqual(self.build(out, "--version", "9.1.0-dev.7").returncode, 0)
        self.assertEqual(json.loads((out / "package.json").read_text())["version"],
                         "9.1.0-dev.7")
        self.assertNotIn("/tree/v", (out / "README.md").read_text(encoding="utf-8"))  # main's docs
        self.assertEqual(self.build(out, "--version", "9.1.0").returncode, 0)
        self.assertIn("segmently-modules/tree/v9.1.0.",
                      (out / "README.md").read_text(encoding="utf-8"))

    def test_refusals_write_nothing(self):
        for out, needle in ((self.engine, "is this engine tree or holds it"),
                            (self.engine.parent, "is this engine tree or holds it")):
            with self.subTest(out=out):
                proc = self.build(out)
                self.assertEqual((proc.returncode, proc.stdout), (2, ""))
                self.assertIn(needle, proc.stderr)
        other = self.tmp / "d" / "npm"
        other.mkdir(parents=True)
        (other / "keep.txt").write_text("mine")
        proc = self.build(other)
        self.assertEqual((proc.returncode, proc.stdout), (2, ""))
        self.assertIn("is not a build of @segmently/modules", proc.stderr)
        self.assertEqual(sorted(p.name for p in other.parent.iterdir()), ["npm"])
        self.assertEqual([p.name for p in other.iterdir()], ["keep.txt"])
        proc = self.build(self.tmp / "e" / "npm", "--version", "1.2")
        self.assertEqual(proc.returncode, 2)
        self.assertFalse((self.tmp / "e" / "npm").exists())

    @unittest.skipUnless(NPM, "npm not on PATH")
    def test_npm_installs_it_and_the_command_runs(self):
        out = self.tmp / "f" / "npm"
        self.assertEqual(self.build(out).returncode, 0)
        work = self.tmp / "f"
        rc = work / "npmrc"
        rc.write_text("")  # no user config: no registry, no token
        env = {**os.environ, "npm_config_userconfig": str(rc),
               "npm_config_cache": str(work / "cache"), "npm_config_update_notifier": "false",
               "npm_config_fund": "false", "npm_config_audit": "false"}
        packed = subprocess.run([NPM, "pack", str(out), "--pack-destination", str(work)],
                                capture_output=True, text=True, env=env, cwd=work)
        self.assertEqual(packed.returncode, 0, packed.stderr)
        tarball = work / packed.stdout.strip().splitlines()[-1]
        prefix = work / "prefix"
        installed = subprocess.run([NPM, "install", "--global", "--offline", "--prefix",
                                    str(prefix), str(tarball)],
                                   capture_output=True, text=True, env=env, cwd=work)
        self.assertEqual(installed.returncode, 0, installed.stderr)
        package = prefix / "lib/node_modules/@segmently/modules"
        self.assertEqual(sorted(tree(package)), sorted(tree(out)))  # npm dropped nothing
        command = prefix / "bin/segmently-modules"
        self.assertTrue(command.is_symlink())
        run_env = {**os.environ, "SEGMENTLY_MODULES_PYTHON": sys.executable}
        version = subprocess.run([str(command), "--version"], capture_output=True, text=True,
                                 env=run_env, cwd=work)
        self.assertEqual((version.returncode, version.stdout.strip(), version.stderr),
                         (0, f"segmently-modules {engine_version(self.engine)}", ""))
        shop = work / "bookshop"
        shutil.copytree(ENGINE / "tests/fixtures/bookshop", shop)
        lint = subprocess.run([str(command), "lint", "--root", str(shop), "--json"],
                              capture_output=True, text=True, env=run_env, cwd=work)
        self.assertEqual(lint.returncode, 0, lint.stdout + lint.stderr)
        self.assertEqual(json.loads(lint.stdout)["schema"], "segmently-modules.lint/1")


if __name__ == "__main__":
    unittest.main()
