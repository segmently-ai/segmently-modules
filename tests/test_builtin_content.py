"""The shipped built-in packs through the engine (D1, D5): their rows in `packs list`, all thirteen
skills through `packs sync` / `eject` / MS063 / `agents-md`, the `ui` / `qa` role templates in
`create`, a clean lint, enable / disable transitions and a team skill with a core id."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from modsys import __version__
from modsys.config import builtin_packs_root
from modsys.skills import file_hashes, read_front_matter
from tests.helpers import copy_fixture, init_git, run, run_json

CORE = ["module-scout", "module-discover", "module-research", "module-sync", "module-roles",
        "module-create", "module-split", "module-lint", "module-init",
        "module-adopt"]  # P5B-AC-030 (D7): 7 -> 9; P8.4 D2: + module-roles
PACKS = {"core": CORE, "qa": ["qa-acceptance", "qa-acceptance-baseline"],
         "ui": ["designer"]}
SKILLS = {sid: pack for pack, ids in PACKS.items() for sid in ids}
STANDARD = ["architect.md", "developer.md", "po.md", "qa.md"]


class ShippedPacks(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        self.R = ("--root", str(self.root))
        self.engine = builtin_packs_root()

    def tearDown(self):
        self._tmp.cleanup()

    def enable(self, *ids: str) -> None:
        (self.root / ".modsys/config.toml").write_text(
            "[packs]\nbuiltin = [" + ", ".join(f'"{i}"' for i in ids) + "]\n")

    def ok(self, *argv, code=0):
        got, env, err = run_json(*argv, *self.R)
        self.assertEqual((got, err), (code, ""), env)
        return env["data"]

    def sync(self, *agents: str, code=0) -> list[tuple]:
        flags = [a for agent in agents or ("claude",) for a in ("--agent", agent)]
        data = self.ok("packs", "sync", *flags, code=code)
        return [(r["agent"], r["skill"], r["status"]) for r in data["skills"]]


class ShippedRowsTest(ShippedPacks):  # P4B-AC-006 (content)
    def test_the_three_packs(self):
        self.enable("core", "ui", "qa")
        rows = {r["id"]: r for r in self.ok("packs", "list") if r["builtin"]}
        self.assertEqual(sorted(rows), ["core", "qa", "ui"])
        self.assertEqual({p: [s["id"] for s in r["skills"]] for p, r in rows.items()}, PACKS)
        self.assertEqual({p: r["roles"] for p, r in rows.items()},
                         {"core": [], "qa": ["qa_acceptance"], "ui": ["designer"]})
        for pack, row in rows.items():
            self.assertEqual((row["version"], Path(row["dir"])), (__version__, self.engine / pack))
            self.assertTrue(all(s["description"] for s in row["skills"]))


class ShippedMachineryTest(ShippedPacks):  # P4B-AC-008
    def test_sync_all_thirteen_skills_to_both_agents(self):  # thirteen since P8.4 D2
        self.enable("core", "ui", "qa")
        rows = self.sync("claude", "codex")
        self.assertEqual(len(rows), 26)
        self.assertEqual({r[2] for r in rows}, {"created"})
        for sid, pack in SKILLS.items():
            for agent_dir in (".claude/skills", ".agents/skills"):
                dest = self.root / agent_dir / sid
                marker = json.loads((dest / ".modsys-managed").read_text())
                self.assertEqual((marker["pack"], marker["version"], marker["source"]),
                                 (pack, __version__, "pack"))
                self.assertEqual(file_hashes(dest),
                                 file_hashes(self.engine / pack / "skills" / sid))
        data = self.ok("packs", "sync", "--check", "--agent", "claude", "--agent", "codex")
        self.assertEqual({r["status"] for r in data["skills"]}, {"unchanged"})
        self.assertEqual(len(data["skills"]), 26)

    def test_the_core_pack_alone(self):  # P5B-AC-030
        self.enable("core")
        rows = self.sync("claude", "codex")
        self.assertEqual((len(rows), {r[2] for r in rows}), (20, {"created"}))
        self.assertEqual(sorted({r[1] for r in rows}), sorted(CORE))

    def test_eject_and_an_engine_upgrade(self):
        self.enable("core", "ui", "qa")
        init_git(self.root)
        self.sync("claude", "codex")
        self.assertEqual(self.ok("eject", "module-sync")["pack"], "core")
        copy = self.root / ".modsys/overrides/skills/module-sync"
        record = json.loads((copy / ".modsys-ejected").read_text())
        self.assertEqual((record["pack"], record["version"]), ("core", __version__))
        (copy / "SKILL.md").write_text((copy / "SKILL.md").read_text() + "\nTeam rule.\n")
        data = self.ok("packs", "sync", "--agent", "claude", "--agent", "codex")
        self.assertEqual([(r["agent"], r["status"], r["source"]) for r in data["skills"]
                          if r["skill"] == "module-sync"],
                         [("claude", "updated", "ejected"), ("codex", "updated", "ejected")])
        upgraded = Path(self._tmp.name) / "engine-packs"
        shutil.copytree(self.engine, upgraded)
        md = upgraded / "core/skills/module-sync/SKILL.md"
        md.write_text(md.read_text() + "\nA new upstream step.\n")
        with mock.patch("modsys.config.builtin_packs_root", return_value=upgraded):
            lint = self.ok("lint", "--fail-on", "never")
            diff = self.ok("eject", "module-sync", "--diff")
            rows = self.sync("claude")
        self.assertEqual([f["message"] for f in lint["findings"] if f["code"] == "MS063"],
                         ["ejected skill 'module-sync' is behind pack 'core' (the pack's files "
                          "changed since the eject) — review: modsys eject module-sync --diff"])
        self.assertTrue(diff["behind"])
        self.assertIn("-A new upstream step.", diff["diff"])
        self.assertEqual({s for _, s, st in rows if st != "unchanged"}, set())

    def test_the_agents_md_block_and_the_role_templates(self):
        self.enable("core", "ui", "qa")
        self.ok("agents-md", "--target", "AGENTS.md")
        text = (self.root / "AGENTS.md").read_text()
        for sid, pack in SKILLS.items():
            meta = read_front_matter(self.engine / pack / "skills" / sid / "SKILL.md")
            first = ' '.join(meta['description'].split()).split('. ')[0].rstrip('.')
            self.assertIn(f"- `{sid}` — {first}.", text)
        rows = {r["template"]: r for r in self.ok("templates", "list")}
        for template, pack in (("roles/designer.md", "ui"), ("roles/qa_acceptance.md", "qa")):
            self.assertEqual((rows[template]["source"], rows[template]["path"]),
                             (f"role-template:{pack}", str(self.engine / pack / template)))
            self.assertTrue(Path(rows[template]["path"]).is_file())


class ShippedLintTest(ShippedPacks):  # P4B-AC-009
    def test_every_pack_lints_clean(self):
        plain = run_json("lint", *self.R)
        for ids in (("core",), ("ui",), ("qa",), ("core", "ui", "qa")):
            with self.subTest(builtin=ids):
                self.enable(*ids)
                code, env, err = run_json("lint", *self.R)
                self.assertEqual((code, err), (plain[0], ""))
                self.assertEqual([f for f in env["data"]["findings"]
                                  if f["code"].startswith("MS06")], [])
        init_git(self.root)
        self.assertEqual(run("ci", "--base", "HEAD", *self.R)[0], 0)


class RoleTemplatesTest(ShippedPacks):  # P4B-AC-016
    def create(self, *flags) -> list[str]:
        shutil.rmtree(self.root / "modules/reviews", ignore_errors=True)
        data = self.ok("create", "reviews", "--non-interactive", "--description",
                       "Customer reviews of books: ratings and moderation.", "--keywords",
                       "review, rating, stars, comment, moderation", *flags)
        registry = self.root / "modules/registry.json"
        entries = json.loads(registry.read_text())
        entries["modules"].pop("reviews")
        registry.write_text(json.dumps(entries, indent=2) + "\n")
        return sorted(Path(f).name for f in data["files"] if "/roles/" in f)

    def test_which_role_docs_are_scaffolded(self):
        self.enable("ui", "qa")
        self.assertEqual(self.create(), STANDARD)
        self.assertEqual(self.create("--tag", "ui"), sorted(STANDARD + ["designer.md"]))
        self.assertEqual(self.create("--tag", "qa"), sorted(STANDARD + ["qa_acceptance.md"]))
        both = self.create("--role", "designer", "--role", "qa_acceptance")
        self.assertEqual(both, sorted(STANDARD + ["designer.md", "qa_acceptance.md"]))
        self.enable()
        self.assertEqual(self.create("--tag", "ui"), STANDARD)

    def test_the_rendered_docs(self):
        self.enable("ui", "qa")
        self.ok("create", "reviews", "--non-interactive", "--description",
                "Customer reviews of books: ratings and moderation.", "--keywords",
                "review, rating, stars, comment, moderation", "--tag", "ui", "--tag", "qa")
        designer = (self.root / "modules/reviews/roles/designer.md").read_text()
        self.assertTrue(designer.startswith("# Reviews — designer\n"))
        for heading in ("## UX invariants", "## Interaction states",
                        "## Layout and accessibility", "## Visual patterns"):
            self.assertIn(f"\n{heading}\n", designer)
        qa = (self.root / "modules/reviews/roles/qa_acceptance.md").read_text()
        self.assertTrue(qa.startswith("# Reviews — qa_acceptance\n"))
        for needle in ("## P0", "## P1", "## P2", "### AC-001:", "- **Given**", "- **When**",
                       "- **Then**"):
            self.assertIn(needle, qa)
        self.assertNotIn("${", designer + qa)


class TransitionsTest(ShippedPacks):  # P4B-AC-028
    def test_enable_disable_and_a_local_edit(self):
        self.enable("core")
        self.assertEqual([s for _, _, s in self.sync()], ["created"] * 10)  # P5b D7: 7 -> 9; P8.4 D2: 10
        self.enable()
        self.assertEqual([s for _, _, s in self.sync()], ["removed"] * 10)
        self.assertFalse((self.root / ".claude/skills/module-scout").exists())
        self.enable("core")
        self.assertEqual([s for _, _, s in self.sync()], ["created"] * 10)
        edited = self.root / ".claude/skills/module-lint/SKILL.md"
        edited.write_text(edited.read_text() + "\nLocal note.\n")
        self.enable()
        data = self.ok("packs", "sync", "--agent", "claude", code=1)
        self.assertEqual({r["skill"]: (r["status"], r["reason"]) for r in data["skills"]
                          if r["status"] != "removed"},
                         {"module-lint": ("conflict", "SKILL.md (locally edited; not removed)")})
        self.assertEqual(sum(r["status"] == "removed" for r in data["skills"]), 9)

    def test_dropping_one_pack(self):
        self.enable("core", "ui")
        self.sync()
        self.enable("core")
        self.assertEqual({(s, st) for _, s, st in self.sync() if st != "unchanged"},
                         {("designer", "removed")})


class TeamSkillWithACoreIdTest(ShippedPacks):  # P4B-AC-029
    def test_a_team_pack_declares_module_sync(self):
        self.enable("core")
        team = self.root / ".modsys/packs/team"
        (team / "skills/module-sync").mkdir(parents=True)
        (team / "pack.toml").write_text('id = "team"\nversion = "9.0.0"\n'
                                        '[skills.module-sync]\npath = "skills/module-sync"\n')
        (team / "skills/module-sync/SKILL.md").write_text(
            "---\nname: module-sync\ndescription: The team's own doc sync.\n---\n")
        self.sync()
        marker = json.loads((self.root / ".claude/skills/module-sync/.modsys-managed").read_text())
        self.assertEqual(marker["pack"], "team")
        lint = self.ok("lint", "--fail-on", "never")
        self.assertEqual([(f["message"], f["path"]) for f in lint["findings"]
                          if f["code"] == "MS065"],
                         [("skill 'module-sync' of pack 'core' is shadowed by pack 'team' "
                           "(higher precedence); rename one", str(self.engine / "core/pack.toml"))])

    def test_a_hand_written_skill_with_a_core_name(self):
        self.enable("core")
        mine = self.root / ".claude/skills/module-scout"
        mine.mkdir(parents=True)
        (mine / "SKILL.md").write_text("---\nname: module-scout\ndescription: Ours.\n---\n")
        rows = self.sync(code=1)
        self.assertEqual([(s, st) for _, s, st in rows if st != "created"],
                         [("module-scout", "conflict")])
        self.assertEqual(len(rows), 10)  # P5b D7; P8.4 D2
        out = run("packs", "sync", "--agent", "claude", *self.R)[1]
        self.assertIn("a skill written by hand: move or rename it, then sync again", out)

    def test_an_ejected_core_skill_outlives_the_pack(self):
        self.enable("core")
        self.sync()
        self.ok("eject", "module-lint")
        self.enable()
        rows = self.sync()
        self.assertEqual([(s, st) for _, s, st in rows if st != "removed"],
                         [("module-lint", "updated")])
        lint = self.ok("lint", "--fail-on", "never")
        self.assertEqual([(f["severity"], f["message"]) for f in lint["findings"]
                          if f["code"] == "MS063"],
                         [("info", "ejected skill 'module-lint': pack 'core' no longer declares "
                                   "it; the ejected copy is its only source")])


if __name__ == "__main__":
    unittest.main()
