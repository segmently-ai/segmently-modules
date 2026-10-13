"""The core skill `module-assistant` (2026-10-07, owner): the module system's entry point — a thin
router whose four scenarios (start, how-to, next, plan) live in `references/`, a how-to catalog
split by topic, the plan-then-OK gate, and the agents' block that points to it. Its behaviour is
measured by skill-creator runs; these tests pin its shape and that every command it names is
real."""
import re
import unittest

from segmently_modules.config import builtin_packs_root
from segmently_modules.skills import read_front_matter
from tests.helpers import run
from tests.test_p84_routing import placeholder_problems

SKILL = builtin_packs_root() / "core" / "skills" / "module-assistant"
SCENARIOS = {"start": "references/start.md", "how-to": "references/how-to.md",
             "next": "references/next.md", "plan": "references/plan.md"}
TOPICS = ["setup", "modules", "roles-templates", "fields-code", "upkeep", "packs-hooks", "search"]
FILES = sorted(["SKILL.md", "references/exit-codes.md", *SCENARIOS.values(),
                *(f"references/how-to/{t}.md" for t in TOPICS)])
NEXT_KINDS = ["setup", "lint-error", "skills", "agents-md", "role", "ejected", "proposals",
              "lint-warning", "unmapped", "drift"]  # docs/cli-contract.md, `next`
IF_LINE = "If a `segmently-modules` command exits 1 or 2, read `references/exit-codes.md`."
COMMAND = re.compile(r"`(?:[^`\n]*?/)?segmently-modules ([a-z][a-z-]+)([^`\n]*)`")


def files() -> dict[str, str]:
    return {p.relative_to(SKILL).as_posix(): p.read_text("utf-8")
            for p in sorted(SKILL.rglob("*")) if p.is_file()}


class ShapeTest(unittest.TestCase):
    def setUp(self):
        self.files = files()
        self.skill = self.files["SKILL.md"]

    def test_the_files_it_ships(self):
        self.assertEqual(sorted(self.files), FILES)

    def test_front_matter_keys(self):
        self.assertEqual(set(read_front_matter(SKILL / "SKILL.md")),
                         {"name", "description", "argument-hint", "arguments"})
        self.assertIn('argument-hint: "[scenario] [goal]"', self.skill)
        self.assertIn("arguments: scenario goal", self.skill)

    def test_one_route_line_per_scenario_and_the_if_line(self):
        self.assertIn("**Route.** Take the scenario named by the invocation (`$scenario`) when one "
                      "is given, else by\nthe user's words", self.skill)
        for scenario, path in SCENARIOS.items():
            with self.subTest(scenario=scenario):
                self.assertEqual(len(re.findall(rf"^- \*\*{scenario}\*\* — [\s\S]*?→\s+`{path}`",
                                                self.skill, re.M)), 1)
        self.assertIn(IF_LINE, self.skill)

    def test_placeholders(self):
        self.assertEqual(placeholder_problems(self.files), [])
        self.assertEqual(self.skill.count("$scenario"), 1)
        self.assertEqual(self.skill.count("$goal"), 1)

    def test_the_gate(self):
        gates = self.skill.split("## Gates", 1)[1]
        for phrase in ("Read-only commands run without asking", "Before any write, show the plan",
                       "ask for the OK in a sentence that says what will happen",
                       "stops for a new OK",
                       "Never present a command or a flag you have not seen"):
            self.assertIn(phrase, " ".join(gates.split()), phrase)

    def test_every_scenario_file_says_whose_step_it_is(self):
        for path in SCENARIOS.values():
            with self.subTest(file=path):
                self.assertIn("Step 2 of `module-assistant`", self.files[path])

    def test_the_how_to_index_names_every_topic_file_once(self):
        index = self.files["references/how-to.md"]
        for topic in TOPICS:
            self.assertEqual(index.count(f"`references/how-to/{topic}.md`"), 1, topic)

    def test_next_maps_every_kind(self):
        table = self.files["references/next.md"]
        source = (builtin_packs_root().parent.parent / "next_cmd.py").read_text("utf-8")
        for kind in NEXT_KINDS:
            with self.subTest(kind=kind):
                self.assertIn(f'"{kind}"', source)  # a kind next still emits
                self.assertEqual(table.count(f"| `{kind}` |"), 1)


class CommandsAreRealTest(unittest.TestCase):
    """Every `segmently-modules <verb> …` the skill names in backticks is a verb, and every flag after it is
    one that verb's `--help` shows: the skill never teaches a command that does not exist."""

    def test_every_named_command_and_flag_exists(self):
        helps, problems = {}, []
        for name, text in files().items():
            for verb, rest in COMMAND.findall(text):
                if verb not in helps:
                    code, out, _ = run(verb, "--help")
                    helps[verb] = out if code == 0 else None
                if helps[verb] is None:
                    problems.append(f"{name}: segmently-modules {verb}")
                    continue
                problems += [f"{name}: segmently-modules {verb} {flag}"
                             for flag in re.findall(r"(--[a-z][a-z-]+)", rest)
                             if flag not in helps[verb]]
        self.assertGreater(len(helps), 20)
        self.assertEqual(problems, [])

    def test_the_check_can_fail(self):
        self.assertEqual(COMMAND.findall("run `segmently-modules next --nope` and `segmently-modules frobnicate`"),
                         [("next", " --nope"), ("frobnicate", "")])


class AgentsBlockTest(unittest.TestCase):
    def test_the_block_points_to_the_assistant(self):
        template = (builtin_packs_root().parent / "templates" / "agents-md.md").read_text("utf-8")
        self.assertIn("The `module-assistant` skill of the `core` pack", template)
        self.assertIn("`segmently-modules next` lists what the repository needs now", template)


if __name__ == "__main__":
    unittest.main()
