"""P8.4 Task 3: the core skill `module-roles` and the slimmer `module-sync` (D2, D6's D1 text):
P84-AC-017 … AC-023. The scenario `## A new role` moved word for word out of `module-sync`; the
rest of `module-sync` is pinned by hashes of the text shipped before this task."""
import hashlib
import json
import re
import tempfile
import tomllib
import unittest
from pathlib import Path

from modsys.agents_md_cmd import render_block
from modsys.config import BUILTIN_PACKS, builtin_packs_root
from modsys.skills import read_front_matter
from tests.helpers import copy_fixture, run, run_json
from tests.test_builtin_skills import argv, command_guard, commands, section, skill_files

ENGINE = Path(__file__).resolve().parents[1]
CORE = builtin_packs_root() / "core"
ROLES = CORE / "skills/module-roles/SKILL.md"
SYNC = CORE / "skills/module-sync/SKILL.md"
DESCRIPTIONS_MAX = 6_600
OLD_DESCRIPTIONS_TOTAL = 6_003

# the `## A new role` section of module-sync as the previous task shipped it (951 characters)
OLD_SECTION = """When the team (or a newer modsys) adds a role, the existing modules lack its doc.

If `modsys roles list --json` does not list the role, declare it first: a [roles.ROLE] table with
order, standard = true (every module gets the doc) and a one-line description in the team config,
.modsys/config.toml, or in a pack the team owns — ask the user what the role is for when unclear.
Then continue with step 1.

1. `modsys roles add ROLE --all --dry-run` — show the user the docs it would create or register and
   the registered ones missing on disk.
2. `modsys roles add ROLE --all --json` — writes them, never over an existing doc; `--recreate`
   only for a registered doc whose file is gone.
3. Fill each new doc with what that role needs for that module, from its code and docs — one module
   at a time, never inventing components.
4. `modsys lint --json` — fix what the new docs caused.
5. `modsys next --json` — report what is left.
"""
OLD_NOT_TO_USE = [  # P8.7 D5: the first one also covers a session that only learned something
    "- Nothing was done or learned yet: use `module-scout` or `module-discover`.",
    "- The work needs a new module: use `module-create` first.",
    "- A module doc grew too long (lint MS030 / MS031): use `module-split`.",
    "- Only lint findings need fixing: use `module-lint`."]
D1_BULLET = (
    "- `keywords`: most changes add none. Add one only for a new feature, command or concept that "
    "people will name in later tasks and that no keyword or the description covers yet — never a "
    "code identifier (a class, function, file or variable name: code search finds those), never "
    "one per task. Keywords only grow; a split parent keeps all of them — never remove one from "
    "it.")
OLD_KEYWORDS = (  # the bullet before D1 (as a nested step-5 item, original line breaks)
    "   - `keywords`: most changes add none — add one only for a new feature, command or concept later\n"
    "     tasks will name, never a code identifier (class, function, file or variable: code search finds\n"
    "     those). Keywords only grow; a split parent keeps all of them — never remove one from it.\n")


def flat(text: str) -> str:
    return " ".join(text.split())


def sentences(text: str) -> list[str]:
    """The normalized sentences (and list items) of a text: split after `. ` and at item starts."""
    items = re.sub(r"(?<=\.)\s+(?=\d\. )", "\n", flat(text)).splitlines()
    return [s for item in items for s in re.split(r"(?<=[a-z`)]\.)\s+(?=[A-Z`])", item) if s]


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def shipped_descriptions() -> dict[str, str]:
    out = {}
    for pack in BUILTIN_PACKS:
        data = tomllib.loads((builtin_packs_root() / pack / "pack.toml").read_text("utf-8"))
        for sid, spec in data.get("skills", {}).items():
            out[sid] = read_front_matter(builtin_packs_root() / pack / spec["path"] / "SKILL.md")[
                "description"]
    return out


class RolesSkillShapeTest(unittest.TestCase):  # P84-AC-017
    def setUp(self):
        self.text = ROLES.read_text("utf-8")
        self.front = read_front_matter(ROLES)

    def test_front_matter_and_description(self):
        self.assertEqual(self.text.split("\n---\n", 1)[0].splitlines()[1:2], ["name: module-roles"])
        self.assertEqual(set(self.front), {"name", "description"})  # one scenario: no argument keys
        description = self.front["description"]
        for phrase in ('"add a role"', '"a new role for every module"',
                       '"the upgrade brought a role"'):
            self.assertIn(phrase, description)
        self.assertLessEqual(len(description), DESCRIPTIONS_MAX - OLD_DESCRIPTIONS_TOTAL)

    def test_the_thirteen_descriptions_fit_the_budget(self):
        found = shipped_descriptions()
        self.assertEqual(len(found), 13)
        self.assertLessEqual(sum(len(d) for d in found.values()), DESCRIPTIONS_MAX)

    def test_sections_scope_and_gates(self):
        for heading in ("## When to use", "## When not to use", "## Scope", "## Steps",
                        "## Gates", "## Exit codes"):
            self.assertEqual(self.text.count(f"\n{heading}\n"), 1, heading)
        self.assertTrue(section(self.text, "## Scope").strip().startswith("Writes"))
        scope = flat(section(self.text, "## Scope"))
        for needle in ("`*.legacy.md`", "never edits", "review and commit"):
            self.assertIn(needle, scope)
        not_to_use = section(self.text, "## When not to use")
        for sibling in ("`module-sync`", "`module-create`"):
            self.assertIn(sibling, not_to_use)
        self.assertIn("what it is for is unclear", flat(section(self.text, "## Gates")))
        self.assertTrue(section(self.text, "## Exit codes").strip())

    def test_one_scenario_no_route_no_references(self):
        self.assertFalse((ROLES.parent / "references").exists())
        self.assertEqual(sorted(skill_files(ROLES.parent)), ["SKILL.md"])
        self.assertNotIn("Route", self.text)
        self.assertNotIn("$", self.text)

    def test_the_declared_pack_row(self):
        data = tomllib.loads((CORE / "pack.toml").read_text("utf-8"))
        self.assertEqual(data["skills"]["module-roles"], {"path": "skills/module-roles"})
        self.assertEqual(len([s for s in data["skills"]]), 10)


class MovedWordForWordTest(unittest.TestCase):  # P84-AC-018
    def test_every_sentence_and_step_is_in_module_roles_in_order(self):
        text = flat(ROLES.read_text("utf-8"))
        at = 0
        for sentence in sentences(OLD_SECTION):
            i = text.find(sentence, at)
            self.assertGreaterEqual(i, 0, sentence)
            at = i + len(sentence)
        steps = re.findall(r"^(\d)\. ", section(ROLES.read_text("utf-8"), "## Steps"), re.M)
        self.assertEqual(steps, ["1", "2", "3", "4", "5"])

    def test_the_old_text_is_in_module_roles_verbatim_apart_from_the_upgrade_line(self):
        steps = section(ROLES.read_text("utf-8"), "## Steps")
        upgrade = steps.split("\n\nIf `modsys roles list --json`", 1)[0].split(
            "\n\n", 1)[1]
        self.assertIn("modsys next --json", upgrade)
        self.assertIn("start at step 1", upgrade)
        without = steps.replace(upgrade + "\n\n", "", 1)
        self.assertEqual(flat(without), flat(OLD_SECTION))

    def test_the_upgrade_case_is_one_line_naming_next_and_roles_add(self):
        steps = flat(section(ROLES.read_text("utf-8"), "## Steps"))
        self.assertIn("When `modsys next --json` names the roles add command with --all for a role "
                      "(the upgrade brought the role), the role is declared already — start at "
                      "step 1.", steps)

    def test_nothing_of_it_is_left_in_module_sync(self):
        text = SYNC.read_text("utf-8")
        self.assertNotIn("## A new role", text)
        self.assertNotIn("modsys roles", text)
        for sentence in sentences(OLD_SECTION):
            self.assertNotIn(sentence, flat(text))

    def test_module_sync_when_not_to_use_gains_exactly_one_bullet(self):
        bullets = [b for b in section(SYNC.read_text("utf-8"), "## When not to use").splitlines()
                   if b.strip()]
        self.assertEqual(bullets[:4], OLD_NOT_TO_USE)
        self.assertEqual(len(bullets), 5)
        self.assertIn("`module-roles`", bullets[4])


class RolesRunsOnTheFixtureTest(unittest.TestCase):  # P84-AC-019
    PLANTED = "# reviewer\n\nPlanted by the team: keep these bytes.\n"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = copy_fixture(Path(self._tmp.name).resolve())
        self.R = ("--root", str(self.root))
        (self.root / ".modsys").mkdir(exist_ok=True)
        (self.root / ".modsys/config.toml").write_text(
            '[roles.reviewer]\norder = 60\nstandard = true\n'
            'description = "What a reviewer checks in a change to the module"\n', "utf-8")
        planted = self.root / "modules/catalog/roles/reviewer.md"
        planted.parent.mkdir(parents=True, exist_ok=True)
        planted.write_text(self.PLANTED, "utf-8")

    def tree(self) -> dict[str, bytes]:
        return {p.relative_to(self.root).as_posix(): p.read_bytes()
                for p in sorted(self.root.rglob("*")) if p.is_file()}

    def step(self, *args) -> dict:
        code, env, err = run_json(*args, *self.R)
        self.assertEqual((code, err), (0, ""), err)
        return env["data"]

    def test_the_skills_commands_in_order(self):
        listed = self.step("roles", "list")
        reviewer = next(r for r in listed["roles"] if r["name"] == "reviewer")
        self.assertEqual(reviewer["missing"], ["catalog", "checkout", "payments"])
        before = self.tree()
        plan = self.step("roles", "add", "reviewer", "--all", "--dry-run")
        self.assertEqual(self.tree(), before)  # the dry run writes nothing
        done = self.step("roles", "add", "reviewer", "--all")
        by = {r["module"]: r["status"] for r in done["results"]}
        self.assertEqual(by, {r["module"]: r["status"] for r in plan["results"]})
        self.assertEqual((by["checkout"], by["payments"], by["catalog"]),
                         ("created", "created", "registered"))
        for module in ("checkout", "payments"):
            self.assertTrue((self.root / f"modules/{module}/roles/reviewer.md").is_file())
        self.assertEqual((self.root / "modules/catalog/roles/reviewer.md").read_text("utf-8"),
                         self.PLANTED)  # never over an existing doc
        self.assertEqual(self.step("lint")["failed"], False)
        items = self.step("next")["items"]
        self.assertNotIn("modsys roles add reviewer --all", [i["command"] for i in items])
        self.assertEqual(self.step("roles", "list")["roles"][-1]["missing"], [])

    def test_the_skill_commands_all_parse(self):
        files = skill_files(ROLES.parent)
        self.assertEqual(command_guard(files), [])  # the real parser accepts every command
        verbs = {argv(c)[0] for c in commands(files["SKILL.md"])}
        self.assertEqual(verbs, {"roles", "lint", "next"})


class KeywordBulletTest(unittest.TestCase):  # P84-AC-020
    def shipped_files(self):
        roots = (ENGINE / "modsys/defaults", ENGINE / "docs", ENGINE / "README.md",
                 ENGINE / "evals")
        for root in roots:
            files = [root] if root.is_file() else sorted(root.rglob("*"))
            for path in files:
                if path.is_file() and path.suffix in {".md", ".toml", ".sh", ".py", ".json"}:
                    yield path

    def test_the_d1_bullet_is_in_step_5_once(self):
        steps = section(SYNC.read_text("utf-8"), "## Steps")
        self.assertEqual(flat(steps).count(D1_BULLET), 1)
        self.assertNotIn(flat(OLD_KEYWORDS), flat(SYNC.read_text("utf-8")))

    def test_the_old_wording_is_in_no_shipped_file(self):
        for path in self.shipped_files():
            self.assertNotIn("most changes add none — add one only for a new feature",
                             flat(path.read_text("utf-8")), path)

    def test_docs_skills_gains_the_two_clauses_in_one_sentence(self):
        text = flat((ENGINE / "docs/skills.md").read_text("utf-8"))
        sentence = next(s for s in re.split(r"(?<=\.)\s+", text) if "adds a keyword only" in s)
        for clause in ("that no keyword or the description covers yet", "never a code identifier",
                       "never one per task"):
            self.assertIn(clause, sentence)


class ModuleSyncShapeTest(unittest.TestCase):  # P84-AC-021, as P8.7 D5 rewrote the skill
    """P8.4 pinned module-sync byte for byte outside its keyword bullet; P8.7 (D5: session first)
    rewrote it on purpose (its contract: `tests/test_p87_writing_skills.py`). What still holds:
    no agent runs it, its front matter has two keys, it stays under the skill split signal, and
    its steps route only by step into the four reference files."""
    def setUp(self):
        self.text = SYNC.read_text("utf-8")

    def test_no_arguments_no_agent_and_its_references(self):
        self.assertEqual(set(read_front_matter(SYNC)), {"name", "description"})
        self.assertEqual(sorted(p.name for p in (SYNC.parent / "references").iterdir()),
                         ["choose.md", "placement.md", "report.md", "session.md"])
        for path in (ENGINE / "modsys/defaults/agents").rglob("*"):
            if path.is_file():
                self.assertNotIn("module-sync", path.read_text("utf-8"), path)

    def test_the_size_does_not_grow(self):
        self.assertLessEqual(len(self.text), 8_996)


class ThirteenSkillsTest(unittest.TestCase):  # P84-AC-022
    def test_the_core_pack_lists_and_counts_ten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(Path(tmp).resolve())
            (root / ".modsys").mkdir(exist_ok=True)
            (root / ".modsys/config.toml").write_text('[packs]\nbuiltin = ["core"]\n', "utf-8")
            code, env, err = run_json("packs", "list", "--root", str(root))
        self.assertEqual((code, err), (0, ""))
        core = next(r for r in env["data"] if r["id"] == "core")
        ids = [s["id"] for s in core["skills"]]
        self.assertEqual(len(ids), 10)
        self.assertIn("module-roles", ids)

    def test_the_agents_md_block_lists_thirteen_lines_and_stays_small(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(Path(tmp).resolve())
            (root / ".modsys").mkdir(exist_ok=True)
            (root / ".modsys/config.toml").write_text(
                '[packs]\nbuiltin = ["core", "ui", "qa"]\n', "utf-8")
            code, _, err = run("agents-md", "--target", "AGENTS.md", "--root", str(root))
            self.assertEqual((code, err), (0, ""))
            text = (root / "AGENTS.md").read_text("utf-8")
        lines = re.findall(r"^- `(module-[a-z-]+|designer-review|qa-[a-z-]+)` — (.*)$", text, re.M)
        self.assertEqual(len(lines), 13)
        first = flat(read_front_matter(ROLES)["description"]).split(". ")[0].rstrip(".") + "."
        self.assertIn(("module-roles", first), lines)
        self.assertLess(len(text), 3_200)

    def test_docs_name_it(self):
        skills = flat((ENGINE / "docs/skills.md").read_text("utf-8"))
        self.assertIn("`module-sync`, `module-roles`, `module-create`", skills)
        self.assertIn("13 skills × 2 agents", skills)
        self.assertRegex(skills, r"\| `module-roles` \| ")
        self.assertIn("`module-roles` — ", (ENGINE / "README.md").read_text("utf-8"))
        releasing = flat((ENGINE / "docs/releasing.md").read_text("utf-8"))
        self.assertIn("thirteen skill descriptions", releasing)
        self.assertIn("ten core skills", releasing)
        self.assertNotIn("twelve skill descriptions", releasing)

    def test_the_adoption_eval_counts_thirteen(self):
        text = (ENGINE / "evals/adoption/run_eval.py").read_text("utf-8")
        for needle in ('"module-roles"', '== 26 and rows == BUILTIN_SKILLS',
                       '"packs sync: 13 skills x 2 agents created"',
                       '"agents-md lists the thirteen skills"'):
            self.assertIn(needle, text)


class SkillEvalCaseTest(unittest.TestCase):  # P84-AC-023
    CASE = ENGINE / "evals/skills/module-roles/trigger"

    def test_the_trigger_case_exists_with_its_graders(self):
        self.assertEqual((self.CASE / "case.yaml").read_text("utf-8"),
                         'schema_version: "1.1"\nname: module-roles-trigger\ncontext:\n'
                         "  scaffold_script: scaffold.sh\n")
        fired = (self.CASE / "graders/skill-fired.md").read_text("utf-8")
        self.assertIn("module-roles", fired)
        ran = (self.CASE / "graders/ran-modsys.md").read_text("utf-8")
        self.assertIn("input_match: 'modsys roles\\b'", ran)
        seed = (self.CASE / "seed.sh").read_text("utf-8")
        self.assertIn("[roles.reviewer]", seed)


if __name__ == "__main__":
    unittest.main()
