"""P8.4 task 1, the build part (D3): the one agent table, the wrapped skills' procedures, and the
`modsys` plugin's three agents generated from them next to `module-chooser` — exact bytes, what
ships under `agents/` (direct children of `modsys/defaults/agents/` only), the refusals, and a
byte-stable build (P84-AC-003, P84-AC-004, P84-AC-005)."""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from modsys import skills
from modsys.config import builtin_packs_root
from modsys.skills import _front_matter, front_matter, read_front_matter, strict_yaml_problem
from tests.helpers import git
from tests.plugin_helpers import (CLAUDE, ENGINE, NO_CLAUDE, claude_env, copy_engine, load_tool,
                                  run_tool, tree)

NAMES = ["module-discover-agent", "module-research-agent", "module-scout-agent"]
WRAPPED = {"module-discover-agent": "module-discover", "module-research-agent": "module-research",
           "module-scout-agent": "module-scout"}
CORE = "modsys/defaults/packs/core/skills"
AGENTS = "modsys/defaults/agents"
TOOLS = "Read, Grep, Glob, Bash, Agent"


def procedure_rel(skill: str) -> str:
    return f"{CORE}/{skill}/references/procedure.md"


def header(name: str) -> bytes:
    """The generated agent's front matter and the blank line before its procedure."""
    description = skills.SKILL_AGENTS[name]["description"]
    return (f"---\nname: {name}\ndescription: {description}\ntools: {TOOLS}\nmodel: sonnet\n"
            f"---\n\n").encode("utf-8")


class AgentTableTest(unittest.TestCase):  # SI-P84-10: one table, read by the builder too
    def test_the_three_names_and_their_skills(self):
        self.assertEqual({n: s["skill"] for n, s in skills.SKILL_AGENTS.items()}, WRAPPED)
        self.assertEqual(skills.PROCEDURE, "references/procedure.md")
        for spec in skills.SKILL_AGENTS.values():
            self.assertEqual(sorted(spec), ["description", "skill"])

    def test_one_sentence_each_and_never_a_skill_description(self):
        described = {read_front_matter(p)["description"]
                     for p in builtin_packs_root().glob("*/skills/*/SKILL.md")}
        self.assertTrue(described)
        for name, spec in skills.SKILL_AGENTS.items():
            text = spec["description"]
            with self.subTest(agent=name):
                self.assertLessEqual(len(text), 200)
                self.assertTrue(text.endswith(".") and text[0].isupper(), text)
                self.assertNotIn(". ", text)  # one sentence
                self.assertNotIn(text, described)
                self.assertIsNone(strict_yaml_problem("description", text))  # a plain YAML value
                self.assertTrue(text.isascii())
                self.assertIsNone(re.search(r"[#\n\t]", text))

    def test_the_builder_reads_the_same_table_without_importing_the_engine(self):
        builder = load_tool("build_plugins")
        self.assertEqual(builder.agent_table(ENGINE), (skills.SKILL_AGENTS, skills.PROCEDURE))
        self.assertNotIn("SKILL_AGENTS = {", (ENGINE / "tools/build_plugins.py").read_text())

    def test_procedures_are_self_contained(self):  # SI-P84-10: no other file, no $name
        for name, skill in WRAPPED.items():
            path = ENGINE / procedure_rel(skill)
            with self.subTest(skill=skill):
                text = path.read_bytes().decode("utf-8")
                self.assertTrue(text.endswith("\n") and not text.startswith("\n"))
                self.assertNotIn("\r", text)
                self.assertIsNone(re.search(r"references/|SKILL\.md", text))
                self.assertIsNone(re.search(r"\$(?:[A-Za-z0-9_{]|ARGUMENTS)", text))
                self.assertIsNone(re.search(r"/U[s]ers/|[Ѐ-ӿ]", text))


class BuiltAgentsTest(unittest.TestCase):  # P84-AC-003
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls._tmp.name).resolve()
        cls.engine = copy_engine(cls.base / "engine")
        cls.out = cls.base / "out"
        proc = run_tool(cls.engine, "build_plugins", "--out", str(cls.out))
        assert proc.returncode == 0, proc.stderr
        cls.stdout, cls.stderr = proc.stdout, proc.stderr

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_exactly_four_agents_in_the_core_plugin(self):
        agents = self.out / "modsys/agents"
        self.assertEqual(sorted(p.name for p in agents.iterdir()),
                         ["module-chooser.md"] + [f"{n}.md" for n in NAMES])
        self.assertEqual((agents / "module-chooser.md").read_bytes(),
                         (self.engine / AGENTS / "module-chooser.md").read_bytes())
        for path in agents.iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644, path.name)
        self.assertEqual(stat.S_IMODE(agents.stat().st_mode), 0o755)
        for name in ("modsys-ui", "modsys-qa"):
            self.assertFalse((self.out / name / "agents").exists(), name)
        self.assertEqual(self.stderr, "")

    def test_each_generated_agent_is_its_front_matter_then_the_procedure(self):
        for name, skill in WRAPPED.items():
            with self.subTest(agent=name):
                built = (self.out / "modsys/agents" / f"{name}.md").read_bytes()
                procedure = (self.engine / procedure_rel(skill)).read_bytes()
                self.assertEqual(built, header(name) + procedure)
                text = built.decode("utf-8")
                self.assertEqual(text.split("\n", 6)[:6], [
                    "---", f"name: {name}",
                    f"description: {skills.SKILL_AGENTS[name]['description']}",
                    f"tools: {TOOLS}", "model: sonnet", "---"])
                self.assertEqual(front_matter(text), {
                    "name": name, "description": skills.SKILL_AGENTS[name]["description"],
                    "tools": TOOLS, "model": "sonnet"})

    def test_the_procedures_ship_in_skills_and_runtime(self):
        for skill in WRAPPED.values():
            data = (self.engine / procedure_rel(skill)).read_bytes()
            self.assertEqual((self.out / "modsys/skills" / skill / "references/procedure.md")
                             .read_bytes(), data)
            self.assertEqual((self.out / "modsys/runtime" / procedure_rel(skill)).read_bytes(),
                             data)

    def test_the_count_names_every_file(self):
        built = self.out / "modsys"
        count = len([p for p in built.rglob("*") if p.is_file()])
        self.assertEqual(self.stdout.splitlines()[0],
                         f"built modsys {json.loads((built / 'plugin.json').read_text())['version']}"
                         f": {count} files in {built}")

    def test_the_readme_names_the_agents(self):
        text = (self.out / "modsys/README.md").read_text(encoding="utf-8")
        for name in NAMES:
            self.assertIn(f"`{name}`", text)
        self.assertIn("`references/procedure.md`", text)

    def test_one_committed_procedure_change_changes_only_its_three_files(self):
        engine = copy_engine(self.base / "engine-edit")
        rel = procedure_rel("module-scout")
        path = engine / rel
        path.write_bytes(path.read_bytes() + b"\nOne more line about the brief.\n")
        git(engine, "commit", "-q", "-am", "scout procedure")
        proc = run_tool(engine, "build_plugins", "--out", str(self.base / "out-edit"))
        self.assertEqual((proc.returncode, proc.stderr), (0, ""))
        before, after = tree(self.out), tree(self.base / "out-edit")
        self.assertEqual(sorted(before), sorted(after))
        self.assertEqual(sorted(k for k in before if before[k] != after[k]), [
            "modsys/agents/module-scout-agent.md", f"modsys/runtime/{rel}",
            "modsys/skills/module-scout/references/procedure.md"])
        self.assertEqual(after["modsys/agents/module-scout-agent.md"][1],
                         header("module-scout-agent") + path.read_bytes())

    def test_the_manifests_carry_no_agent(self):
        builder = load_tool("build_plugins")
        for name in ("modsys", "modsys-ui", "modsys-qa"):
            version = json.loads((self.out / name / "plugin.json").read_text())["version"]
            for rel, value in builder.manifests(name, version).items():
                text = (self.out / name / rel).read_text(encoding="utf-8")
                self.assertEqual(text, json.dumps(value, indent=2, ensure_ascii=False) + "\n")
                self.assertNotIn("agents", json.loads(text))

    def test_two_builds_identical_umask_and_time_zone(self):  # P84-AC-005 (unit part)
        second = self.base / "again"
        proc = subprocess.run(
            ["/bin/sh", "-c", 'umask 077 && exec "$0" "$@"', sys.executable,
             str(self.engine / "tools/build_plugins.py"), "--out", str(second)],
            capture_output=True, text=True, env={**os.environ, "TZ": "Asia/Tokyo",
                                                 "PYTHONHASHSEED": "7"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(tree(self.out), tree(second))
        self.assertEqual(proc.stdout, self.stdout.replace(str(self.out), str(second)))

    @unittest.skipUnless(CLAUDE, NO_CLAUDE)
    def test_claude_validate_accepts_the_plugin_next_to_its_agents(self):
        # `claude plugin validate` does not inspect agents/ (it lists no contents for them and
        # passes a broken agent): this proves only that the plugin stays valid with agents/ in
        # it. The agents' front matter (P84-AC-005): FrontMatterTest.
        proc = subprocess.run([CLAUDE, "plugin", "validate", "--strict", "--json",
                               str(self.out / "modsys")], capture_output=True, text=True,
                              timeout=120, env=claude_env(self.base / "claude-config"))
        self.assertEqual(proc.returncode, 0, proc.stdout)
        report = json.loads(proc.stdout)
        self.assertTrue(report["success"], report)
        self.assertEqual(report["manifest"]["errors"], [])


FIELDS = ["name", "description", "tools", "model"]  # D3: exactly these, in this order


def front_matter_problems(agents: Path, sources: Path) -> list[str]:
    """Why the files in a built `agents/` would not load as agents: front matter the engine's
    reader cannot parse, a plain value a strict YAML loader rejects, other fields than D3's, or
    values other than the agent table's (a generated agent) or its source file's (any other)."""
    problems = []
    for path in sorted(agents.iterdir()):
        text = path.read_bytes().decode("utf-8")
        parsed = _front_matter(text)
        if parsed is None or not text.startswith("---\n"):
            problems.append(f"{path.name}: no front matter")
            continue
        meta, plain = parsed
        if list(meta) != FIELDS:
            problems.append(f"{path.name}: fields {list(meta)}")
        problems += [f"{path.name}: {problem}" for key in sorted(plain)
                     if (problem := strict_yaml_problem(key, meta[key]))]
        if not text.split("\n---\n", 1)[-1].startswith("\n"):
            problems.append(f"{path.name}: no blank line after the front matter")
        name = path.name[:-3]
        if name in skills.SKILL_AGENTS:
            want = {"name": name, "description": skills.SKILL_AGENTS[name]["description"],
                    "tools": TOOLS, "model": "sonnet"}
        else:
            want = front_matter((sources / path.name).read_bytes().decode("utf-8"))
            if want is None or want.get("name") != name:
                problems.append(f"{path.name}: its name is not its file name")
        if meta != want:
            problems.append(f"{path.name}: {meta} != {want}")
    return problems


class FrontMatterTest(unittest.TestCase):  # P84-AC-005: the four agents' front matter
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls._tmp.name).resolve()
        cls.engine = copy_engine(cls.base / "engine")
        proc = run_tool(cls.engine, "build_plugins", "--out", str(cls.base / "out"))
        assert proc.returncode == 0, proc.stderr
        cls.agents = cls.base / "out/modsys/agents"

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_every_built_agent_loads(self):
        self.assertEqual(sorted(p.name for p in self.agents.iterdir()),
                         ["module-chooser.md"] + [f"{n}.md" for n in NAMES])
        self.assertEqual(front_matter_problems(self.agents, self.engine / AGENTS), [])

    def test_a_broken_header_is_found(self):  # the check can fail: one header broken in a copy
        good = f"description: {skills.SKILL_AGENTS['module-scout-agent']['description']}\n"
        for broken in (("name: module-scout-agent\n", "name: [unclosed\n"),
                       (good, "description: Reads: modules\n"),
                       ("model: sonnet\n", ""),
                       ("tools: Read, Grep, Glob, Bash, Agent\n", "tools: 42\n"),
                       ("model: sonnet\n---\n", "model: sonnet\n"),
                       ("model: sonnet\n", "model: sonnet\ncolor: blue\n"),
                       ("---\n\n", "---\n")):
            with self.subTest(broken=broken[1]):
                copy = self.base / "broken"
                shutil.rmtree(copy, ignore_errors=True)
                shutil.copytree(self.agents, copy)
                path = copy / "module-scout-agent.md"
                text = path.read_text(encoding="utf-8")
                self.assertIn(broken[0], text)
                path.write_text(text.replace(broken[0], broken[1], 1), encoding="utf-8")
                problems = front_matter_problems(copy, self.engine / AGENTS)
                self.assertTrue(problems)
                self.assertTrue(all(p.startswith("module-scout-agent.md: ") for p in problems),
                                problems)


class WhatShipsTest(unittest.TestCase):  # P84-AC-004
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name).resolve()
        self.engine = copy_engine(self.tmp / "engine")
        self.out = self.tmp / "out"

    def tearDown(self):
        self._tmp.cleanup()

    def commit(self, *rels: str, message: str = "change") -> None:
        git(self.engine, "add", "-A", "--", *rels)
        git(self.engine, "commit", "-q", "-m", message)

    def write(self, rel: str, text: str) -> None:
        (self.engine / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.engine / rel).write_text(text, encoding="utf-8")

    def build(self):
        return run_tool(self.engine, "build_plugins", "--out", str(self.out))

    def refused(self, needle: str) -> str:
        before = tree(self.out) if self.out.exists() else None
        proc = self.build()
        self.assertEqual((proc.returncode, proc.stdout), (2, ""), proc.stderr)
        self.assertEqual(proc.stderr.count("\n"), 1, proc.stderr)
        self.assertTrue(proc.stderr.startswith("build_plugins.py: error: "), proc.stderr)
        self.assertIn(needle, proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertEqual(tree(self.out) if self.out.exists() else None, before)
        return proc.stderr

    def agents(self) -> list[str]:
        return sorted(p.relative_to(self.out / "modsys/agents").as_posix()
                      for p in (self.out / "modsys/agents").rglob("*"))

    def test_direct_children_only_and_never_untracked(self):
        self.write(f"{AGENTS}/extra.md", "---\nname: extra\ndescription: Extra.\n---\nx\n")
        self.write(f"{AGENTS}/sub/x.md", "---\nname: x\ndescription: Nested.\n---\nx\n")
        self.commit(AGENTS)
        self.write(f"{AGENTS}/local.md", "untracked\n")
        proc = self.build()
        self.assertEqual((proc.returncode, proc.stderr), (0, ""))
        self.assertEqual(self.agents(), sorted(["extra.md", "module-chooser.md"]
                                               + [f"{n}.md" for n in NAMES]))
        self.assertFalse((self.out / "modsys/agents/sub").exists())
        self.assertTrue((self.out / f"modsys/runtime/{AGENTS}/sub/x.md").is_file())
        self.assertFalse((self.out / f"modsys/runtime/{AGENTS}/local.md").exists())

    def test_a_tracked_agent_that_collides_with_a_generated_one(self):
        self.assertEqual(self.build().returncode, 0)  # an earlier build stays as it was
        self.write(f"{AGENTS}/module-discover-agent.md", "---\nname: module-discover-agent\n---\n")
        self.commit(AGENTS)
        err = self.refused(f"{AGENTS}/module-discover-agent.md")
        self.assertIn(procedure_rel("module-discover"), err)
        self.assertIn("module-discover-agent", err)

    def test_a_collision_on_a_fresh_out_creates_nothing(self):
        self.write(f"{AGENTS}/module-scout-agent.md", "x\n")
        self.commit(AGENTS)
        self.refused(f"{AGENTS}/module-scout-agent.md")
        self.assertFalse(self.out.exists())

    def test_a_missing_procedure(self):
        git(self.engine, "rm", "-q", procedure_rel("module-research"))
        git(self.engine, "commit", "-q", "-m", "no procedure")
        self.assertEqual(self.build().returncode, 2)
        self.out.mkdir()
        self.refused(procedure_rel("module-research"))
        self.assertEqual(list(self.out.iterdir()), [])

    def test_an_untracked_procedure(self):
        self.assertEqual(self.build().returncode, 0)
        git(self.engine, "rm", "-q", "--cached", procedure_rel("module-discover"))
        git(self.engine, "commit", "-q", "-m", "untrack the procedure")
        self.assertTrue((self.engine / procedure_rel("module-discover")).is_file())
        self.refused(procedure_rel("module-discover"))

    def test_a_tracked_procedure_deleted_on_disk(self):
        (self.engine / procedure_rel("module-scout")).unlink()
        self.refused(procedure_rel("module-scout"))

    def test_an_uncommitted_procedure_edit_is_built_and_named(self):
        path = self.engine / procedure_rel("module-discover")
        path.write_bytes(path.read_bytes() + b"Edited.\n")
        proc = self.build()
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stderr, "build_plugins.py: warning: built from a work tree with "
                                      f"uncommitted changes: {procedure_rel('module-discover')}\n")
        self.assertEqual((self.out / "modsys/agents/module-discover-agent.md").read_bytes(),
                         header("module-discover-agent") + path.read_bytes())

    def test_a_skill_of_the_table_the_core_pack_does_not_declare(self):
        pack = self.engine / "modsys/defaults/packs/core/pack.toml"
        pack.write_text(pack.read_text().replace(
            '[skills.module-scout]\npath = "skills/module-scout"\n\n', ""), encoding="utf-8")
        self.commit("modsys/defaults/packs/core/pack.toml")
        self.refused("module-scout-agent")


if __name__ == "__main__":
    unittest.main()
