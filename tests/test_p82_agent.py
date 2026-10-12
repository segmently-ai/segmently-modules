"""P8.2 task 4: the shipped choice agent `modsys:module-chooser` (D4): its source, the build that
ships it in the core plugin only, the reproducible build, the thin read-only text, the package
data and the docs (P82-AC-013 agents glob, 029…033)."""
import glob
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from tests.helpers import changelog_since_first_release, git
from tests.plugin_helpers import CLAUDE, ENGINE, NO_CLAUDE, claude_env, copy_engine, run_tool, tree

AGENT_REL = "modsys/defaults/agents/module-chooser.md"
AGENT_DIR = ENGINE / "modsys/defaults/agents"
DESCRIPTION = ("Answers a modsys choose work order - picks the modules a task needs by meaning "
               "and replies with the answer JSON only. The modsys skills hand it the work "
               "order's file in their by-meaning step.")
D4 = f"""---
name: module-chooser
description: {DESCRIPTION}
tools: Read, Grep, Glob
model: sonnet
---

You answer one modsys work order. The message names its file, the output of `modsys choose`:
the task, the rules, one card per module and the answer schema. That file is your whole task.

1. Read the whole file.
2. Follow its rules, at the depth they set; open other files only as they allow. Change nothing.
3. Reply with the answer alone: one JSON object that matches the answer schema, with the
   `catalog_digest` the file gives - no other text, no code fence.
"""
MANIFESTS = (".claude-plugin/plugin.json", "plugin.json", ".codex-plugin/plugin.json")


def frontmatter(text: str) -> dict[str, str]:
    head = text.split("---\n")[1]
    return dict(line.split(": ", 1) for line in head.splitlines())


class AgentSourceTest(unittest.TestCase):  # P82-AC-029
    def test_byte_identical_to_d4(self):
        data = (ENGINE / AGENT_REL).read_bytes()
        self.assertEqual(data, D4.encode("utf-8"))
        self.assertTrue(data.endswith(b"\n") and b"\r" not in data)
        self.assertEqual(data.decode("ascii"), D4)

    def test_frontmatter_and_steps(self):
        text = (ENGINE / AGENT_REL).read_text(encoding="utf-8")
        self.assertEqual(frontmatter(text), {
            "name": "module-chooser", "description": DESCRIPTION,
            "tools": "Read, Grep, Glob", "model": "sonnet"})
        for step in ("1. Read the whole file.",
                     "2. Follow its rules, at the depth they set; open other files only as they "
                     "allow. Change nothing.",
                     "3. Reply with the answer alone: one JSON object that matches the answer "
                     "schema, with the\n   `catalog_digest` the file gives - no other text, no "
                     "code fence."):
            self.assertIn(step, text)

    def test_tracked_mode_644_and_the_only_file(self):
        out = git(ENGINE, "ls-files", "-s", "--", "modsys/defaults/agents")
        self.assertEqual([(l.split()[0], l.split("\t")[1]) for l in out.splitlines()],
                         [("100644", AGENT_REL)])
        self.assertEqual(sorted(p.name for p in AGENT_DIR.iterdir()), ["module-chooser.md"])


class AgentThinTest(unittest.TestCase):  # P82-AC-032
    def test_read_only_and_no_rule_text(self):
        text = (ENGINE / AGENT_REL).read_text(encoding="utf-8")
        tools = [t.strip() for t in frontmatter(text)["tools"].split(",")]
        self.assertEqual(tools, ["Read", "Grep", "Glob"])
        for bad in ("Bash", "Write", "Edit", "NotebookEdit", "WebFetch", "mcp__"):
            self.assertNotIn(bad, frontmatter(text)["tools"])
        for rule in ("Read every card", "by meaning", "$max_picks", "$depth"):
            self.assertNotIn(rule, text.split("---\n", 2)[2])
        self.assertIsNone(re.search(r"/U[s]ers/|github\.com[:/][\w-]+/|[Ѐ-ӿ]", text))


class PackageDataTest(unittest.TestCase):  # P82-AC-013 (the agents glob)
    def test_glob_covers_the_agent(self):
        data = tomllib.loads((ENGINE / "pyproject.toml").read_text(encoding="utf-8"))
        globs = data["tool"]["setuptools"]["package-data"]["modsys"]
        self.assertIn("defaults/agents/*.md", globs)
        shipped = {f for g in globs for f in glob.glob(g, root_dir=ENGINE / "modsys",
                                                       recursive=True)}
        self.assertIn("defaults/agents/module-chooser.md", shipped)


class BuildTest(unittest.TestCase):  # P82-AC-030, 031
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls._tmp.name).resolve()
        cls.engine = copy_engine(cls.base / "engine")
        cls.out = cls.base / "out"
        proc = run_tool(cls.engine, "build_plugins", "--out", str(cls.out))
        assert proc.returncode == 0, proc.stderr
        cls.stdout = proc.stdout

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def count(self, stdout: str, name: str) -> int:
        return int(re.search(rf"built {name} \S+: (\d+) files", stdout).group(1))

    def test_core_ships_the_agent(self):
        built = self.out / "modsys/agents/module-chooser.md"
        self.assertEqual(built.read_bytes(), (ENGINE / AGENT_REL).read_bytes())
        self.assertEqual(stat.S_IMODE(built.stat().st_mode), 0o644)
        self.assertEqual(stat.S_IMODE(built.parent.stat().st_mode), 0o755)
        for name in ("modsys-ui", "modsys-qa"):
            self.assertFalse((self.out / name / "agents").exists(), name)

    def test_manifests_carry_no_agents_key(self):
        for name in ("modsys", "modsys-ui", "modsys-qa"):
            for rel in MANIFESTS:
                self.assertNotIn("agents", json.loads((self.out / name / rel).read_text()))

    def test_readmes(self):
        core = (self.out / "modsys/README.md").read_text(encoding="utf-8")
        self.assertIn("`module-chooser`", core)
        self.assertIn("modsys templates override choose/rules.md", core)
        for name in ("modsys-ui", "modsys-qa"):
            self.assertNotIn("module-chooser", (self.out / name / "README.md").read_text())

    def test_every_tracked_agent_file_and_never_an_untracked_one(self):
        eng = copy_engine(self.base / "engine2")
        agents = eng / "modsys/defaults/agents"
        (agents / "extra.md").write_text("---\nname: extra\n---\nx\n", encoding="utf-8")
        git(eng, "add", "modsys/defaults/agents/extra.md")
        git(eng, "commit", "-q", "-m", "extra")
        (agents / "local.md").write_text("untracked\n", encoding="utf-8")
        out = self.base / "out2"
        proc = run_tool(eng, "build_plugins", "--out", str(out))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(sorted(p.name for p in (out / "modsys/agents").iterdir()),
                         ["extra.md", "module-chooser.md", "module-discover-agent.md",
                          "module-research-agent.md", "module-scout-agent.md"])  # P8.4 D3
        self.assertFalse((out / "modsys/runtime/modsys/defaults/agents/local.md").exists())
        # the count grows by the shipped agent file and its runtime copy
        self.assertEqual(self.count(proc.stdout, "modsys"),
                         self.count(self.stdout, "modsys") + 2)

    def test_two_builds_identical(self):
        second = self.base / "again"
        proc = subprocess.run(
            ["/bin/sh", "-c", 'umask 077 && exec "$0" "$@"', sys.executable,
             str(self.engine / "tools/build_plugins.py"), "--out", str(second)],
            capture_output=True, text=True, env={**os.environ, "TZ": "Asia/Tokyo"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(tree(self.out), tree(second))

    @unittest.skipUnless(CLAUDE, NO_CLAUDE)
    def test_claude_validates_the_agent(self):
        proc = subprocess.run([CLAUDE, "plugin", "validate", "--strict", "--json",
                               str(self.out / "modsys")], capture_output=True, text=True,
                              timeout=120, env=claude_env(self.base / "claude-config"))
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertTrue(json.loads(proc.stdout)["success"])


class DocsTest(unittest.TestCase):  # P82-AC-033
    def test_skills_doc(self):
        text = " ".join((ENGINE / "docs/skills.md").read_text(encoding="utf-8").split())
        for needle in ("`modsys:module-chooser`", "Read, Grep, Glob", "model: <search.claude_model>",
                       "`model: sonnet`", "only a call without a model",
                       "modsys templates override choose/rules.md",
                       "replaces the agent file in the plugin cache",
                       'builtin_delivery = "repo"'):  # "Codex ignores `agents/`": P84-AC-010
            self.assertIn(needle, text)

    def test_readme_and_changelog(self):
        for doc in ("README.md", "CHANGELOG.md"):
            self.assertIn("module-chooser", (ENGINE / doc).read_text(encoding="utf-8"), doc)
        log = (ENGINE / "CHANGELOG.md").read_text(encoding="utf-8")
        unreleased = changelog_since_first_release(log)
        self.assertIn("module-chooser", unreleased)


if __name__ == "__main__":
    unittest.main()
