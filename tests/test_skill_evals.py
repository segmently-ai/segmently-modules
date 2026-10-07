"""The skill eval suite (D7): 15 `claude plugin eval` cases under evals/skills/ with documented
front matter and grader types, the graders every kind of case needs, and `run.py --dry-run`,
which assembles the plugin (byte-equal skills, a scaffold per case, a modsys launcher) and prints
the command without running `claude`. The seeded workspace itself is built and checked here."""
import ast
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from modsys.config import builtin_packs_root
from modsys.skills import file_hashes, front_matter
from tests.helpers import NO_AUTO_MAINTENANCE
from tests.test_builtin_content import SKILLS

# the ten skills the `claude plugin eval` suite covers (P4b); module-init and module-adopt are
# evaluated by the skill-creator files beside them (P5b D8, SI-22)
P4B_SKILLS = [s for s in SKILLS if s not in ("module-init", "module-adopt")]

ENGINE = Path(__file__).resolve().parents[1]
SUITE = ENGINE / "evals" / "skills"
PROMPT_KEYS = {"schema_version", "name", "description", "tags", "plugins", "runs",
               "expected_outcome", "model", "max_turns", "timeout_seconds", "allowed_tools",
               "append_system_prompt", "env"}
GRADER_TYPES = {"regex", "tool_used", "tool_order", "file_exists", "llm", "baseline"}
PRIMARY = {"module-scout": "show", "module-discover": "discover", "module-research": "show",
           "module-sync": "sync-instructions", "module-create": "create", "module-split": "show",
           "module-lint": "(ci|lint)", "designer": "discover",
           "qa-acceptance": "discover", "qa-acceptance-baseline": "show",
           "module-roles": "roles", "module-assistant": "next"}
WRAPPED = ("module-discover", "module-scout", "module-research")  # each with an agent
WRITERS = ("module-sync", "module-create", "module-split")


def cases() -> dict[str, Path]:
    return {p.parent.relative_to(SUITE).as_posix(): p.parent for p in SUITE.rglob("prompt.md")}


def graders(case: Path) -> dict[str, dict]:
    return {g.stem: front_matter(g.read_text(encoding="utf-8"))
            for g in sorted((case / "graders").glob("*.md"))}


def case_name(case: Path) -> str:
    return re.search(r"^name: (\S+)$", (case / "case.yaml").read_text("utf-8"), re.M).group(1)


class SuiteShapeTest(unittest.TestCase):  # P4B-AC-019
    def test_sixteen_cases(self):  # + module-assistant/trigger (2026-10-07)
        expected = ({f"{s}/trigger" for s in P4B_SKILLS} | {f"{s}/outcome" for s in WRITERS}
                    | {"negative/unrelated"})
        self.assertEqual(set(cases()), expected)
        self.assertEqual(len(expected), 16)
        names = [case_name(c) for c in cases().values()]
        self.assertEqual(len(set(names)), 16)

    def test_front_matter_case_yaml_and_grader_types(self):
        for rel, case in cases().items():
            with self.subTest(case=rel):
                meta = front_matter((case / "prompt.md").read_text("utf-8"))
                self.assertLessEqual(set(meta), PROMPT_KEYS)
                self.assertIn("Bash", meta["allowed_tools"])
                self.assertEqual((case / "case.yaml").read_text("utf-8"),
                                 f'schema_version: "1.1"\nname: {case_name(case)}\ncontext:\n'
                                 f"  scaffold_script: scaffold.sh\n")
                found = graders(case)
                self.assertTrue(found)
                self.assertEqual({g["type"] for g in found.values()} - GRADER_TYPES, set())

    def test_trigger_and_negative_graders(self):
        for skill in P4B_SKILLS:
            with self.subTest(skill=skill):
                found = graders(SUITE / skill / "trigger")
                self.assertEqual(found["skill-fired"],
                                 {"type": "tool_used", "tool": "Skill",
                                  "input_match": r'"skill"\s*:\s*"(?:[\w-]+:)?' + skill + '"'})
                if skill in WRAPPED:  # P8.6 D1: the skill runs in the conversation again; its
                    # agent only on request, so the trigger's own modsys command is the evidence
                    meta = front_matter((SUITE / skill / "trigger/prompt.md").read_text("utf-8"))
                    self.assertIn("Agent", meta["allowed_tools"])  # the chooser of step 1
                self.assertEqual(found["ran-modsys"]["tool"], "Bash")
                self.assertTrue(found["ran-modsys"]["input_match"].startswith(
                    f"modsys {PRIMARY[skill]}"))
        negative = graders(SUITE / "negative/unrelated")["no-skill"]
        self.assertEqual(negative, {"type": "tool_used", "tool": "Skill", "min": "0", "max": "0",
                                    "arm": "both"})

    def test_outcome_graders_look_at_results(self):
        for skill in WRITERS:
            with self.subTest(skill=skill):
                found = graders(SUITE / skill / "outcome").values()
                self.assertTrue(any(g["type"] in ("regex", "file_exists") for g in found))
                self.assertTrue(any(g.get("tool") == "Bash" for g in found))


class RunnerTest(unittest.TestCase):  # P4B-AC-019
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name).resolve() / "work"

    def tearDown(self):
        self._tmp.cleanup()

    def dry_run(self, *flags: str, out: Path | None = None) -> str:
        proc = subprocess.run([sys.executable, str(SUITE / "run.py"), "--dry-run", "--out",
                               str(out or self.out), *flags], capture_output=True, text=True,
                              timeout=120)
        self.assertEqual((proc.returncode, proc.stderr), (0, ""))
        return proc.stdout

    def command(self, *flags: str) -> list[str]:
        """The `claude plugin eval` argv a dry run with `flags` prints (a fresh work dir)."""
        out = Path(tempfile.mkdtemp(dir=self._tmp.name)) / "work"
        line = next(l for l in self.dry_run(*flags, out=out).splitlines()
                    if l.startswith("command: "))
        return shlex.split(line.removeprefix("command: "))

    def test_caller_flags_keep_the_cost_cap_and_no_publish(self):  # fix wave P-b
        cmd = self.command("--case", "x", "--runs", "1")
        self.assertEqual(cmd[cmd.index("--case"):cmd.index("--case") + 4],
                         ["--case", "x", "--runs", "1"])
        self.assertEqual((cmd.count("--max-cost-usd"), cmd[cmd.index("--max-cost-usd") + 1]),
                         (1, "20"))
        self.assertEqual(cmd.count("--no-publish"), 1)
        self.assertNotIn("--trust-plugin", cmd)  # a trust grant stays the caller's choice
        cmd = self.command("--case", "x", "--max-cost-usd", "3", "--no-publish")
        self.assertEqual((cmd.count("--max-cost-usd"), cmd[cmd.index("--max-cost-usd") + 1]),
                         (1, "3"))
        self.assertEqual(cmd.count("--no-publish"), 1)
        cmd = self.command("--max-cost-usd=4")
        self.assertEqual([a for a in cmd if a.startswith("--max-cost-usd")], ["--max-cost-usd=4"])

    def test_the_summary_lines(self):  # fix wave T8: no `claude` call
        spec = importlib.util.spec_from_file_location("skill_eval_runner", SUITE / "run.py")
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        result = Path(self._tmp.name) / "result.json"
        result.write_text(json.dumps({
            "cases": [{"name": "module-scout-trigger", "aggregates": {"score": 0.5},
                       "arms": {"with": [
                           {"costUsd": 0.25, "judgeCostUsd": 0.05,
                            "graders": [{"name": "skill-fired", "passed": True},
                                        {"name": "ran-modsys", "passed": True}]},
                           {"costUsd": 0.5, "error": "the sandbox refused to start",
                            "graders": [{"name": "skill-fired", "passed": False}]}]}},
                      {"name": "negative-unrelated", "aggregates": {"score": 1.0},
                       "arms": {"with": [{"costUsd": 0.125, "graders": []}],
                                "without": [{"costUsd": 0.125}]}}],
            "aggregates": {"overallScore": 0.75, "casesPassed": 1, "casesTotal": 2},
            "costUsd": 1.05, "partial": True, "partialReason": "cost ceiling reached"}))
        self.assertEqual(runner.summary(result), [
            "module-scout-trigger: score 0.5, cost $0.80, skill fired 1/2, error: the sandbox "
            "refused to start",
            "negative-unrelated: score 1.0, cost $0.25",
            "overall 0.75, cases passed 1/2, cost $1.05, partial: cost ceiling reached"])

    def test_the_dry_run_assembles_the_plugin(self):
        out = self.dry_run()
        plugin = self.out / "plugin"
        manifest = json.loads((plugin / ".claude-plugin/plugin.json").read_text())
        self.assertEqual(manifest["name"], "modsys-skills")
        for sid, pack in SKILLS.items():
            self.assertEqual(file_hashes(plugin / "skills" / sid),
                             file_hashes(builtin_packs_root() / pack / "skills" / sid))
        self.assertEqual(sorted(p.name for p in (plugin / "skills").iterdir()), sorted(SKILLS))
        for rel in cases():
            scaffold = plugin / "evals" / rel / "scaffold.sh"
            self.assertTrue(os.access(scaffold, os.X_OK), rel)
            self.assertIn(str(self.out / "runtime"), scaffold.read_text())
            self.assertFalse((plugin / "evals" / rel / "seed.sh").exists())
        self.assertTrue(os.access(self.out / "runtime/bin/modsys", os.X_OK))
        self.assertIn(f"command: claude plugin eval {plugin} --scaffold --ablation none --runs 2 "
                      f"--threshold 0.5 --max-cost-usd 20 --allow-tools Bash Write Edit "
                      f"--trust-plugin --no-publish --json {self.out / 'result.json'}\n", out)

    def test_the_scaffold_and_the_launcher_work(self):
        self.dry_run()
        work = Path(self._tmp.name) / "ws"
        work.mkdir()
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(NO_AUTO_MAINTENANCE)  # the scaffold commits (tests/helpers.py)
        env["PATH"] = f"{self.out / 'runtime/bin'}{os.pathsep}{env['PATH']}"
        scaffold = self.out / "plugin/evals/module-split/outcome/scaffold.sh"
        subprocess.run(["bash", str(scaffold)], cwd=work, env=env, check=True,
                       capture_output=True)
        proc = subprocess.run(["modsys", "packs", "list", "--json"], cwd=work, env=env,
                              capture_output=True, text=True, check=True)
        rows = json.loads(proc.stdout)["data"]
        self.assertEqual([r["id"] for r in rows if r["builtin"]], ["core", "qa", "ui"])
        proc = subprocess.run(["modsys", "lint", "--json"], cwd=work, env=env,
                              capture_output=True, text=True)
        self.assertEqual([f["code"] for f in json.loads(proc.stdout)["data"]["findings"]],
                         ["MS030"])  # the seed: a doc past the split signal

    def test_run_py_is_stdlib_only(self):
        tree = ast.parse((SUITE / "run.py").read_text(encoding="utf-8"))
        names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)
                 for a in n.names}
        names |= {n.module.split(".")[0] for n in ast.walk(tree)
                  if isinstance(n, ast.ImportFrom) and n.module}
        self.assertEqual(names - set(sys.stdlib_module_names), set())


if __name__ == "__main__":
    unittest.main()
