"""`tools/publish.py` (P6 D4, row 6.2): the channel versions, the two marketplace files per
channel and their merge by name, the structural check of the Codex marketplace and `claude
plugin validate` of the laid-out tree (when `claude` is on PATH)."""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

import segmently_modules
from segmently_modules._toml import tomllib
from tests.helpers import engine_version, git, release_version
from tests.plugin_helpers import (CLAUDE, ENGINE, NO_CLAUDE, claude_env, copy_engine, load_tool,
                                  run_tool)

publish = load_tool("publish")
builder = publish.build_plugins
ENG = engine_version()  # the tree under test: never a literal
REL = release_version(ENG)
NAMES = ["segmently-modules", "segmently-modules-qa", "segmently-modules-ui"]


def precedence(version: str) -> tuple:
    """SemVer 2.0 precedence of X.Y.Z[-pre] (enough for these versions): the release before its
    pre-releases."""
    core, _, pre = version.partition("-")
    return tuple(int(x) for x in core.split(".")) + ((1,) if not pre else (0, pre))


class VersionTest(unittest.TestCase):  # P6-AC-013 (SI-5, SI-6)
    def test_the_table(self):
        sha = "3fa9c1e2" + "0" * 56
        self.assertEqual(publish.channel_version("stable", ENG, sha), REL)
        self.assertEqual(publish.channel_version("dev", ENG, sha),
                         f"{REL}-dev.h3fa9c1e2")
        digits = publish.channel_version("dev", ENG, "01234567" + "8" * 56)
        self.assertEqual(digits, f"{REL}-dev.h01234567")
        self.assertTrue(builder.semver_ok(digits))
        self.assertFalse(builder.semver_ok(f"{REL}-dev.01234567"))  # why the `h`
        after = publish.channel_version("dev", "5.2.9.dev0", "ab" * 32)
        self.assertEqual(after, "5.2.9-dev.habababab")
        self.assertGreater(precedence(after), precedence(REL))
        self.assertEqual(publish.channel_version("stable", REL, "0" * 64), REL)
        for bad in ("0.1", f"{REL}rc1", f"v{REL}"):
            with self.assertRaises(builder.BuildError):
                publish.base_version(bad)

    def test_one_version_source(self):
        data = tomllib.loads((ENGINE / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(data["project"]["version"], segmently_modules.__version__)


class ContentHashTest(unittest.TestCase):  # P6-AC-013 (the hash input)
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls._tmp.name).resolve()
        cls.engine = copy_engine(cls.base / "engine")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def hash_of(self, name: str, version: str | None = None) -> str:
        out = self.base / name
        builder.build(self.engine, out, version)
        return publish.content_hash(out)

    def test_what_moves_the_hash(self):
        first = self.hash_of("a")
        self.assertEqual(self.hash_of("b"), first)
        self.assertEqual(self.hash_of("c", "9.9.9"), first)  # the version is not input
        (self.engine / "tests").mkdir(exist_ok=True)
        (self.engine / "tests/new_test.txt").write_text("x\n")
        self.assertEqual(self.hash_of("d"), first)  # outside the shipped trees
        skill = self.engine / "segmently_modules/defaults/packs/qa/skills/qa-acceptance/SKILL.md"
        original = skill.read_bytes()
        skill.write_bytes(original + b"\n")
        try:
            self.assertNotEqual(self.hash_of("e"), first)
        finally:
            skill.write_bytes(original)
        self.assertEqual(self.hash_of("f"), first)
        rel = "segmently_modules/defaults/packs/qa/skills/qa-acceptance/SKILL.md"
        git(self.engine, "update-index", "--chmod=+x", rel)  # a mode in the index moves it
        try:
            self.assertNotEqual(self.hash_of("g"), first)
        finally:
            git(self.engine, "update-index", "--chmod=-x", rel)
        for key, value in (("keywords", ["qa", "criteria"]), ("description", "Another text")):
            with self.subTest(manifest=key):  # a manifest-only change moves it too
                with mock.patch.dict(builder.PLUGINS["segmently-modules-qa"], {key: value}):
                    self.assertNotEqual(self.hash_of(f"h-{key}"), first)
        with mock.patch.dict(builder.AUTHOR, {"name": "someone else"}):
            self.assertNotEqual(self.hash_of("i"), first)
        self.assertEqual(self.hash_of("j"), first)

    def test_a_dev_build_and_its_launcher(self):
        out = self.base / "dev"
        version = publish.build_channel(self.engine, out, "dev")
        self.assertRegex(version, rf"^{re.escape(REL)}-dev\.h[0-9a-f]{{8}}$")
        self.assertEqual(publish.build_channel(self.engine, self.base / "dev2", "dev"), version)
        for name in NAMES:
            for rel in builder.MANIFESTS:
                self.assertEqual(json.loads((out / name / rel).read_text())["version"], version)
        proc = subprocess.run([str(out / "segmently-modules/bin/segmently-modules"), "--version"],
                              capture_output=True, text=True,
                              env={**os.environ, "SEGMENTLY_MODULES_PYTHON": sys.executable})
        self.assertEqual((proc.returncode, proc.stdout.strip()), (0, f"segmently-modules {ENG}"))


class MarketplaceTest(unittest.TestCase):  # P6-AC-012
    def test_the_files_per_channel(self):
        files = {ch: publish.marketplaces(ch) for ch in ("stable", "dev")}
        claude, codex = files["stable"]
        self.assertEqual(list(claude), ["name", "owner", "description", "plugins"])
        self.assertEqual((claude["name"], claude["owner"]), ("segmently-modules", {"name": "Segmently Modules "
                                                                         "maintainers"}))
        self.assertEqual([e["name"] for e in claude["plugins"]], NAMES)
        for entry in claude["plugins"]:
            self.assertEqual(list(entry), ["name", "source", "description"])
            self.assertEqual(entry["source"], f"./plugins/{entry['name']}")
        self.assertEqual(codex, {"name": "segmently-modules", "plugins": [
            {"name": n, "source": {"source": "local", "path": f"./plugins/{n}"}} for n in NAMES]})
        dev_claude, dev_codex = files["dev"]
        self.assertEqual((dev_claude["name"], dev_codex["name"]), ("segmently-modules-dev", "segmently-modules-dev"))
        self.assertEqual({k: v for k, v in dev_claude.items() if k not in ("name",
                                                                           "description")},
                         {k: v for k, v in claude.items() if k not in ("name", "description")})
        self.assertEqual(dev_codex["plugins"], codex["plugins"])

    def test_the_merge_keeps_what_is_not_ours(self):
        other = {"name": "other-tool", "source": "./plugins/other-tool", "category": "x"}
        stale = {"name": "segmently-modules", "source": "./old", "version": "0.0.1"}
        claude, codex = publish.marketplaces(
            "stable", {"name": "x", "owner": {"name": "someone"}, "metadata": {"a": 1},
                       "plugins": [other, stale]},
            {"name": "x", "interface": {"displayName": "X"},
             "plugins": [{"name": "other-tool", "source": {"source": "git", "url": "u"}}]})
        self.assertEqual([e["name"] for e in claude["plugins"]],
                         ["other-tool", "segmently-modules", "segmently-modules-qa", "segmently-modules-ui"])
        self.assertEqual(claude["plugins"][0], other)
        self.assertNotIn("version", claude["plugins"][1])
        self.assertEqual((claude["name"], claude["metadata"]), ("segmently-modules", {"a": 1}))
        self.assertEqual(codex["interface"], {"displayName": "X"})
        self.assertEqual(codex["plugins"][0], {"name": "other-tool",
                                               "source": {"source": "git", "url": "u"}})

    def test_the_merge_with_entries_of_every_shape(self):
        extra = {"name": "segmently-modules-extra", "source": "./plugins/segmently-modules-extra",  # not ours: a
                 "description": "An add-on, café — keeps its bytes"}  # glob would have caught it
        odd = [{"name": ["segmently-modules"]}, {"name": {"a": 1}}, {"name": 7}, {"source": "./x"}, "text",
               None]
        stale = {"name": "segmently-modules", "source": "./old"}
        again = {"name": "segmently-modules", "source": "./older"}
        old = {"name": "x", "plugins": [extra, stale, *odd, again,
                                        {"name": "segmently-modules-ui", "source": "./a"},
                                        {"name": "segmently-modules-ui", "source": "./b"}]}
        for which in (0, 1):
            with self.subTest(file=("claude", "codex")[which]):
                new = publish.marketplaces("dev", old if which == 0 else None,
                                           old if which == 1 else None)[which]
                ours = [e for e in new["plugins"] if isinstance(e, dict)
                        and isinstance(e.get("name"), str) and e["name"] in NAMES]
                self.assertEqual([e["name"] for e in ours], ["segmently-modules", "segmently-modules-ui",
                                                             "segmently-modules-qa"])  # never twice
                self.assertEqual(new["plugins"][:2], [extra, ours[0]])
                self.assertEqual(new["plugins"][2:8], odd)  # kept as they are, where they are
                self.assertEqual(new["plugins"][8:], ours[1:])
                text = publish.dump(new)
                self.assertIn(textwrap.indent(json.dumps(extra, indent=2, ensure_ascii=False),
                                              "    "), text)  # the same bytes in the file
                self.assertEqual(text.count('"name": "segmently-modules"'), 1)

    def test_an_old_file_the_merge_cannot_use(self):
        for bad in ([], "text", 5, [{"name": "other-tool"}]):
            with self.subTest(old=bad):
                with self.assertRaises(builder.BuildError) as caught:
                    publish.marketplaces("dev", bad, None)
                self.assertIn(".claude-plugin/marketplace.json is not a JSON object",
                              str(caught.exception))
                with self.assertRaises(builder.BuildError) as caught:
                    publish.marketplaces("dev", None, bad)
                self.assertIn(".agents/plugins/marketplace.json is not a JSON object",
                              str(caught.exception))
        for bad in ({"other-tool": {}}, "segmently-modules", 3):
            with self.subTest(plugins=bad):
                with self.assertRaises(builder.BuildError) as caught:
                    publish.marketplaces("dev", {"name": "x", "plugins": bad}, None)
                self.assertIn(".claude-plugin/marketplace.json: plugins is not a list",
                              str(caught.exception))
                with self.assertRaises(builder.BuildError) as caught:
                    publish.marketplaces("dev", None, {"name": "x", "plugins": bad})
                self.assertIn(".agents/plugins/marketplace.json: plugins is not a list",
                              str(caught.exception))
        claude, codex = publish.marketplaces("dev", {"name": "x"}, {})  # no list yet: ours
        self.assertEqual([e["name"] for e in claude["plugins"]], NAMES)
        self.assertEqual([e["name"] for e in codex["plugins"]], NAMES)

    def test_the_codex_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            for name in NAMES:
                (root / "plugins" / name).mkdir(parents=True)
            _, codex = publish.marketplaces("dev")
            path = root / publish.CODEX_MARKETPLACE
            path.parent.mkdir(parents=True)
            path.write_text(publish.dump(codex))
            self.assertEqual(publish.codex_problems(root), [])
            for change, problem in (
                    ({"path": "../x"}, "plugin 'segmently-modules': source.path '../x' does not start "
                                       "with ./"),
                    ({"path": "./../x"}, "plugin 'segmently-modules': source.path './../x' leaves the "
                                         "marketplace root"),
                    ({"path": "/abs"}, "plugin 'segmently-modules': source.path '/abs' does not start "
                                       "with ./"),
                    ({"path": "./plugins/missing"}, "plugin 'segmently-modules': source.path "
                                                    "'./plugins/missing' is not a directory")):
                with self.subTest(change=change):
                    bad = json.loads(publish.dump(codex))
                    bad["plugins"][0]["source"].update(change)
                    path.write_text(json.dumps(bad))
                    self.assertEqual(publish.codex_problems(root), [problem])
            bad = json.loads(publish.dump(codex))
            bad["plugins"][1]["name"] = "segmently-modules"
            del bad["plugins"][2]["name"]
            path.write_text(json.dumps(bad))
            self.assertEqual(publish.codex_problems(root), [
                "plugin 'segmently-modules': the name is used twice", "plugins[2]: name is missing"])
            bad = json.loads(publish.dump(codex))
            source = {"source": "local", "path": "./plugins/segmently-modules"}
            bad["plugins"] += [{"name": ["segmently-modules"], "source": source},
                               {"name": {"a": 1}, "source": source}, {"name": 7}, "text"]
            path.write_text(json.dumps(bad))
            self.assertEqual(publish.codex_problems(root), [
                "plugins[3]: name is not a string", "plugins[4]: name is not a string",
                "plugins[5]: name is not a string",
                "plugins[5]: source is not an object with a source type",
                "plugins[6]: name is missing",
                "plugins[6]: source is not an object with a source type"])

    def test_the_codex_check_compares_real_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp).resolve()
            root = tmp / "root"
            for name in NAMES:
                (root / "plugins" / name).mkdir(parents=True)
            (tmp / "outside").mkdir()
            shutil.rmtree(root / "plugins/segmently-modules-ui")
            os.symlink(tmp / "outside", root / "plugins/segmently-modules-ui")  # a link out of the root
            _, codex = publish.marketplaces("dev")
            (root / publish.CODEX_MARKETPLACE).parent.mkdir(parents=True)
            (root / publish.CODEX_MARKETPLACE).write_text(publish.dump(codex))
            problem = ["plugin 'segmently-modules-ui': source.path './plugins/segmently-modules-ui' leaves the "
                       "marketplace root"]
            self.assertEqual(publish.codex_problems(root), problem)
            (tmp / "other").mkdir()  # the same root spelled with `..`: nothing more leaves it
            self.assertEqual(publish.codex_problems(tmp / "other" / ".." / "root"), problem)
            os.symlink(root, tmp / "alias")
            self.assertEqual(publish.codex_problems(tmp / "alias"), problem)


class LayoutTest(unittest.TestCase):  # P6-AC-011 (the marketplace), P6-AC-012
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls._tmp.name).resolve()
        cls.engine = copy_engine(cls.base / "engine")
        cls.trees = {}
        for channel in ("dev", "stable"):
            proc = run_tool(cls.engine, "publish", "--channel", channel, "--out",
                            str(cls.base / channel))
            assert proc.returncode == 0, proc.stderr
            cls.trees[channel] = (cls.base / channel, proc.stdout)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_every_entry_has_its_plugin(self):
        for channel, (root, stdout) in self.trees.items():
            version = re.search(r"version (\S+),", stdout).group(1)
            self.assertEqual(version == REL, channel == "stable")
            claude = json.loads((root / publish.CLAUDE_MARKETPLACE).read_text())
            for entry in claude["plugins"]:
                manifest = root / entry["source"] / ".claude-plugin/plugin.json"
                self.assertEqual(json.loads(manifest.read_text())["version"], version)
            self.assertEqual(publish.codex_problems(root), [])
            self.assertEqual(publish.plugin_problems(root, version), [])
            self.assertEqual(publish.plugin_problems(root, "9.9.9"), [
                f"plugin '{n}': {rel} does not carry version 9.9.9" for n in NAMES
                for rel in builder.MANIFESTS])
        self.assertEqual(sorted(p.name for p in (self.base / "dev").iterdir()),
                         [".agents", ".claude-plugin", "plugins"])

    def test_modes_whatever_the_umask_and_no_bytecode(self):
        out = self.base / "umask"
        proc = subprocess.run(
            ["/bin/sh", "-c", 'umask 077 && exec "$0" "$@"', sys.executable,
             str(self.engine / "tools/publish.py"), "--channel", "dev", "--out", str(out)],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for path in [out, *out.rglob("*")]:
            rel = path.relative_to(out).as_posix()
            want = 0o755 if path.is_dir() or rel == "plugins/segmently-modules/bin/segmently-modules" else 0o644
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), want, rel)
        self.assertFalse((self.engine / "tools/__pycache__").exists())

    @unittest.skipIf(os.geteuid() == 0, "root writes into a read-only directory")
    def test_an_out_that_cannot_be_written(self):
        locked = self.base / "locked"
        locked.mkdir()
        locked.chmod(0o555)
        try:
            for out in (locked / "out", locked / "deeper/out"):
                proc = run_tool(self.engine, "publish", "--channel", "dev", "--out", str(out))
                self.assertEqual((proc.returncode, proc.stdout), (2, ""), proc.stderr)
                self.assertTrue(proc.stderr.startswith("publish.py: error: cannot write "
                                                       f"{locked}/"), proc.stderr)
                self.assertIn(": Permission denied", proc.stderr)
                self.assertEqual(proc.stderr.count("\n"), 1)  # never a traceback
                self.assertEqual(list(locked.iterdir()), [])
        finally:
            locked.chmod(0o755)

    def test_a_failure_removes_out_and_the_parents_it_made(self):
        def half_written(plugins, dest, channel):
            (dest / "plugins/segmently-modules").mkdir(parents=True)
            (dest / "plugins/segmently-modules/README.md").write_text("half\n")
            raise failure

        for failure, code, line in (
                (PermissionError(13, "Permission denied", "/somewhere/x"), 2,
                 "publish.py: error: cannot write /somewhere/x: Permission denied\n"),
                (shutil.Error([("a", "/somewhere/b", "No space left on device")]), 2,
                 "publish.py: error: cannot write /somewhere/b: No space left on device\n"),
                (builder.BuildError("planted"), 2, "publish.py: error: planted\n"),
                (KeyboardInterrupt(), 130, "publish.py: interrupted\n")):
            with self.subTest(failure=type(failure).__name__):
                out = self.base / "fresh/deeper/out"
                stdout, stderr = io.StringIO(), io.StringIO()
                with mock.patch.object(publish, "build_channel", return_value="0.0.0"), \
                        mock.patch.object(publish, "layout", half_written), \
                        contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    got = publish.main(["--channel", "dev", "--out", str(out)])
                self.assertEqual((got, stdout.getvalue(), stderr.getvalue()), (code, "", line))
                self.assertFalse((self.base / "fresh").exists())

    def test_an_existing_out_is_refused(self):
        proc = run_tool(self.engine, "publish", "--channel", "dev", "--out", str(self.base))
        self.assertEqual((proc.returncode, proc.stdout), (2, ""))
        self.assertIn("exists — give a new directory", proc.stderr)
        proc = run_tool(self.engine, "publish", "--channel", "beta", "--out", "x")
        self.assertEqual((proc.returncode, proc.stdout), (2, ""))
        self.assertIn("usage:", proc.stderr)

    @unittest.skipUnless(CLAUDE, NO_CLAUDE)
    def test_claude_validates_the_marketplace(self):
        env = claude_env(self.base / "claude-config")
        for channel, (root, _) in self.trees.items():
            with self.subTest(channel=channel):
                proc = subprocess.run([CLAUDE, "plugin", "validate", "--strict", "--json",
                                       str(root)], capture_output=True, text=True, timeout=120,
                                      env=env)
                report = json.loads(proc.stdout)
                self.assertEqual((proc.returncode, report["manifest"]["type"],
                                  report["manifest"]["errors"], report["manifest"]["warnings"]),
                                 (0, "marketplace", [], []))
        for n, change in enumerate(({"name": "segmently-modules"}, {"source": "../plugins/segmently-modules-qa"})):
            with self.subTest(change=change):  # the check can fail (PR: a missing directory
                broken = self.base / f"broken-{n}"  # passes Claude's check — ours catches it)
                shutil.copytree(self.trees["dev"][0], broken)
                doc = json.loads((broken / publish.CLAUDE_MARKETPLACE).read_text())
                doc["plugins"][1].update(change)
                (broken / publish.CLAUDE_MARKETPLACE).write_text(json.dumps(doc))
                proc = subprocess.run([CLAUDE, "plugin", "validate", "--strict", "--json",
                                       str(broken)], capture_output=True, text=True,
                                      timeout=120, env=env)
                self.assertEqual(proc.returncode, 1)


if __name__ == "__main__":
    unittest.main()
