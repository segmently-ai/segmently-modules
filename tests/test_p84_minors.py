"""P8.4 fix wave, the final review's text minors: one coherent `[Unreleased]` story (M-1), the
module-roles Scope says children inherit (M-3), the built `modsys` plugin README tells Codex users
where the agents come from (M-4), the git-ignore note of `packs sync` covers the Codex agent files
(M-5) and the README names the pack lint codes as they are (M-6)."""
import re
import tempfile
import unittest
from pathlib import Path

from modsys.config import builtin_packs_root
from tests.helpers import changelog_since_first_release, copy_fixture, init_git, run, run_json
from tests.plugin_helpers import load_tool
from tests.test_builtin_skills import section

ENGINE = Path(__file__).resolve().parents[1]
AGENTS = ["module-discover-agent", "module-research-agent", "module-scout-agent"]
AGENT_NOTE = ("git ignores {k} of the {m} agent files in .codex/agents ({names}) — they are "
              "written but will not be committed; take them out of .gitignore to share them "
              "with the team")


def flat(text: str) -> str:
    return " ".join(text.split())


def unreleased() -> str:
    log = (ENGINE / "CHANGELOG.md").read_text(encoding="utf-8")
    return changelog_since_first_release(log)


def part(text: str, heading: str) -> str:
    return text.split(f"### {heading}\n", 1)[1].split("\n### ", 1)[0]


class ChangelogTest(unittest.TestCase):  # M-1
    def test_the_keyword_rule_is_told_once_in_its_final_words(self):
        text = flat(unreleased())
        self.assertEqual(text.count("adds a keyword only"), 1)
        self.assertEqual(text.count("keyword rule"), 0)
        self.assertNotIn("now says", text)
        sentence = text.split("adds a keyword only", 1)[1].split(";", 1)[0]
        for clause in ("for a new feature, command or concept that later tasks will name",
                       "that no keyword or the description covers yet",
                       "never a code identifier", "never one per task"):
            self.assertIn(clause, sentence)

    def test_the_wrong_value_rule_is_told_once(self):
        text = flat(unreleased())
        self.assertEqual(text.count("wrong value"), 1)  # P8.6 D2: only its removal is told
        self.assertNotIn("where a wrong value is computed and set, not only where it is read", text)
        self.assertIn("The rule that looked for where a wrong value is computed and set", text)

    def test_no_line_contradicts_the_caps_being_gone(self):
        text = flat(unreleased())
        self.assertIn("the fixed `SKILL_MAX` / `CORE_MAX` are gone", text)
        self.assertNotIn("within set sizes", text)
        self.assertIn("Token-budget tests keep the shipped skills' descriptions within a set "
                      "total and the `context` / `show` output within set lengths; skills, "
                      "route files and packs stay within their split signals unless a decision "
                      "is recorded", text)

    def test_the_finding_skills_are_one_change(self):  # P8.6: the thin form never shipped stable
        added, changed = (flat(part(unreleased(), h)) for h in ("Added", "Changed"))
        self.assertNotIn("are thin", added + changed)
        lead = "`module-discover`, `module-scout` and `module-research` keep their steps in `SKILL.md`"
        self.assertNotIn(lead, added)
        self.assertEqual(changed.count(lead), 1)


class ModuleRolesScopeTest(unittest.TestCase):  # M-3
    def test_children_inherit_the_parents_doc(self):
        text = (builtin_packs_root() / "core/skills/module-roles/SKILL.md").read_text("utf-8")
        scope = flat(section(text, "## Scope"))
        self.assertNotIn("per registered module and child", scope)
        self.assertIn("one `roles/<role>.md` doc per registered module (a split module's children "
                      "inherit the parent's: `roles add --all` writes none for them;", scope)


class PluginReadmeTest(unittest.TestCase):  # M-4
    def test_the_core_readme_says_where_codex_gets_the_agents(self):
        builder = load_tool("build_plugins")
        agents = ["module-chooser.md", *(f"{a}.md" for a in AGENTS)]
        text = flat(builder.readme("modsys", ["module-scout"], agents))
        codex = text.split("- Codex:", 1)[1].split(" - Cursor", 1)[0]
        self.assertIn("Codex reads no plugin agents: `modsys setup` and `modsys packs sync "
                      "--agent codex` write the three skills' agents to `.codex/agents/`", codex)
        delivery = text.split('set `builtin_delivery = "plugin"`', 1)[1]
        self.assertIn("it still writes Codex's three agent files in `.codex/agents/`", delivery)
        for name in ("modsys-ui", "modsys-qa"):  # the agents come with the core plugin only
            self.assertNotIn(".codex/agents", builder.readme(name, ["x"]))


class IgnoredAgentFilesTest(unittest.TestCase):  # M-5
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = copy_fixture(self._tmp.name)
        self.R = ("--root", str(self.root))
        (self.root / ".modsys/config.toml").write_text('[packs]\nbuiltin = ["core"]\n',
                                                       encoding="utf-8")

    def notes(self, *argv) -> list[str]:
        code, env, err = run_json("packs", "sync", *argv, *self.R)
        self.assertEqual((code, err), (0, ""))
        return [n for n in env["data"]["notes"] if n.startswith("git ignores")]

    def test_the_note_names_the_ignored_agent_files(self):
        (self.root / ".gitignore").write_text(".codex/\n", encoding="utf-8")
        init_git(self.root)
        want = AGENT_NOTE.format(k=3, m=3, names=", ".join(AGENTS))
        for argv in (("--dry-run",), (), ("--check",)):  # before and after the files exist
            with self.subTest(argv=argv):
                self.assertEqual(self.notes("--agent", "codex", *argv), [want])
        code, out, err = run("packs", "sync", "--agent", "codex", *self.R)
        self.assertEqual((code, err), (0, ""))
        self.assertIn(f"note: {want}\n", out)

    def test_one_ignored_file_and_the_skill_copies_beside_it(self):
        (self.root / ".gitignore").write_text(".agents/\n.codex/agents/module-scout-agent.toml\n",
                                              encoding="utf-8")
        init_git(self.root)
        notes = self.notes("--agent", "codex")
        self.assertEqual(len(notes), 2)
        self.assertTrue(notes[0].startswith("git ignores 11 of the 11 skill copies in "
                                            ".agents/skills ("), notes[0])
        self.assertEqual(notes[1], AGENT_NOTE.format(k=1, m=3, names="module-scout-agent"))

    def test_no_note_when_nothing_is_ignored_or_outside_git(self):
        self.assertEqual(self.notes("--agent", "codex", "--dry-run"), [])  # no repository
        init_git(self.root)
        self.assertEqual(self.notes("--agent", "codex"), [])

    def test_the_contract_quotes_the_note(self):
        row = next(line for line in (ENGINE / "docs/cli-contract.md").read_text("utf-8")
                   .splitlines() if line.startswith("| `packs new"))
        self.assertIn("`git ignores <n> of the <m> agent files in .codex/agents (<name>, …) — "
                      "they are written but will not be committed; take them out of .gitignore "
                      "to share them with the team`", row)


class ReadmeLintCodesTest(unittest.TestCase):  # M-6
    def test_the_pack_lint_codes_are_named_as_the_guide_lists_them(self):
        readme = flat((ENGINE / "README.md").read_text(encoding="utf-8"))
        packs = readme.split("## Packs and skills", 1)[1].split(" ## ", 1)[0]
        self.assertNotIn("MS060–MS065:", packs)
        self.assertIn("the pack lint codes (MS060–MS065, MS068 and MS069): "
                      "[docs/writing-a-pack.md](docs/writing-a-pack.md)", packs)
        guide = (ENGINE / "docs/writing-a-pack.md").read_text(encoding="utf-8")
        listed = re.findall(r"^\| (MS0\d\d) \|", guide, re.M)
        self.assertEqual(listed, ["MS060", "MS061", "MS062", "MS063", "MS064", "MS065", "MS068",
                                  "MS069"])


if __name__ == "__main__":
    unittest.main()
