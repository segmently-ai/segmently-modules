"""Built-in packs (D1): `[packs] builtin`, discovery below every repository pack, the engine
version, reserved ids, owning a whole pack by copying it, and the P4a machinery (sync, eject,
MS063, agents-md, templates) on a built-in source. The engine's pack tree is replaced by a small
synthetic one (`FakeBuiltins`) so these tests pin the mechanics, not the shipped texts."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from modsys import __version__
from modsys.config import builtin_packs_root
from tests.helpers import copy_fixture, init_git, run, run_json

SKILL = "---\nname: {sid}\ndescription: The {sid} skill of the {pack} pack.\n---\n\n# {sid}\n"
TREE = {
    "core/pack.toml": 'id = "core"\ndescription = "Core skills"\n'
                      '[skills.notes]\npath = "skills/notes"\n'
                      '[skills.lint-fix]\npath = "skills/lint-fix"\n',
    "ui/pack.toml": 'id = "ui"\ndescription = "UI"\n'
                    '[roles.designer]\norder = 60\nstandard = false\napplies_when = "ui"\n'
                    'description = "UX rules"\ntemplate = "roles/designer.md"\n'
                    '[fields.screen_ref]\ntype = "string"\ndescription = "UI field"\n'
                    '[skills.ui-check]\npath = "skills/ui-check"\nreads_roles = ["designer"]\n',
    "ui/roles/designer.md": "# ${title} — ${role}\n\n## UX invariants\n",
    "qa/pack.toml": 'id = "qa"\ndescription = "QA"\n'
                    '[roles.qa_acceptance]\norder = 25\nstandard = false\napplies_when = "qa"\n'
                    'description = "Acceptance baseline"\ntemplate = "roles/qa_acceptance.md"\n'
                    '[skills.qa-check]\npath = "skills/qa-check"\n'
                    'reads_roles = ["qa_acceptance"]\n',
    "qa/roles/qa_acceptance.md": "# ${title} — ${role}\n\n## P0\n",
}
SKILLS = {"notes": "core", "lint-fix": "core", "ui-check": "ui", "qa-check": "qa"}


class FakeBuiltins(unittest.TestCase):
    """A bookshop fixture copy whose engine built-in packs are the synthetic TREE."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        self.R = ("--root", str(self.root))
        self.tree = Path(self._tmp.name) / "builtins"
        write_tree(self.tree)
        patcher = mock.patch("modsys.config.builtin_packs_root", side_effect=lambda: self.tree)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self._tmp.cleanup()

    def config(self, text: str, name: str = "config.toml") -> None:
        (self.root / ".modsys" / name).write_text(text)

    def enable(self, *ids: str) -> None:
        self.config("[packs]\nbuiltin = [" + ", ".join(f'"{i}"' for i in ids) + "]\n")

    def ok(self, *argv, code=0):
        got, env, err = run_json(*argv, *self.R)
        self.assertEqual((got, err), (code, ""), env)
        return env["data"]

    def refused(self, *argv) -> str:
        code, out, err = run(*argv, "--json", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("modsys: error: "), err)
        return err

    def repo_pack(self, pack_id: str, body: str, priority: int = 50) -> Path:
        d = self.root / ".modsys/packs" / pack_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "pack.toml").write_text(f'id = "{pack_id}"\nversion = "1.0.0"\n'
                                     f'priority = {priority}\n{body}')
        return d


def write_tree(tree: Path) -> None:
    for rel, text in TREE.items():
        (tree / rel).parent.mkdir(parents=True, exist_ok=True)
        (tree / rel).write_text(text)
    for sid, pack in SKILLS.items():
        md = tree / pack / "skills" / sid / "SKILL.md"
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text(SKILL.format(sid=sid, pack=pack))


class BuiltinConfigTest(FakeBuiltins):  # P4B-AC-005
    def ids(self) -> list[tuple]:
        return [(r["id"], r["builtin"]) for r in self.ok("packs", "list")]

    def test_the_key_and_its_values(self):
        repo = [("bookshop", False)]
        self.assertEqual(self.ids(), repo)
        for value, expected in [("[]", []), ('["core"]', ["core"]),
                                ('["core", "ui", "qa"]', ["core", "qa", "ui"]),
                                ('["qa", "core", "ui"]', ["core", "qa", "ui"]),
                                ('["core", "core"]', ["core"])]:
            with self.subTest(value=value):
                self.config(f"[packs]\nbuiltin = {value}\n")
                self.assertEqual(self.ids(), repo + [(i, True) for i in expected])
        self.config('[packs]\nbuiltin = ["core"]\n')
        self.config('[packs]\nbuiltin = ["ui", "core"]\n', "config.user.toml")
        self.assertEqual(self.ids(), repo + [("core", True), ("ui", True)])

    def test_bad_values_are_config_errors(self):
        for value, needle in [
                ('["cor"]', ".modsys/config.toml: [packs] builtin: unknown built-in pack 'cor' "
                            "(built-in packs: core, qa, ui)"),
                ('"core"', ".modsys/config.toml: [packs] builtin: expected a list of strings, "
                           "got 'core'"),
                ("[1]", ".modsys/config.toml: [packs] builtin: expected a list of strings, "
                        "got [1]"),
                ("5", ".modsys/config.toml: [packs] builtin: expected a list of strings, got 5")]:
            for argv in (("packs", "list"), ("packs", "sync", "--agent", "claude"),
                         ("lint",), ("match", "book")):
                with self.subTest(value=value, verb=argv[0]):
                    self.config(f"[packs]\nbuiltin = {value}\n")
                    self.assertIn(needle, self.refused(*argv))

    def test_a_pack_cannot_enable_a_builtin_pack(self):
        self.repo_pack("team", '[packs]\nbuiltin = ["core"]\n')
        self.assertIn(".modsys/packs/team/pack.toml: [packs] builtin: a pack cannot enable "
                      "built-in packs — set it in .modsys/config.toml",
                      self.refused("packs", "list"))


class BuiltinDiscoveryTest(FakeBuiltins):  # P4B-AC-006
    def test_rows_in_precedence_order(self):
        shutil.rmtree(self.root / ".modsys/packs/bookshop")
        self.repo_pack("team", "", priority=50)
        self.repo_pack("late", "", priority=999999)
        self.enable("core", "ui", "qa")
        rows = self.ok("packs", "list")
        self.assertEqual([(r["id"], r["builtin"], r["priority"]) for r in rows],
                         [("team", False, 50), ("late", False, 999999), ("core", True, None),
                          ("qa", True, None), ("ui", True, None)])
        version = run("--version")[1].split()[-1]
        self.assertEqual(version, __version__)
        for row in rows[2:]:
            self.assertEqual(row["version"], version)
            self.assertTrue(Path(row["dir"]).is_absolute() and Path(row["dir"]).is_dir())
            self.assertEqual(Path(row["dir"]), self.tree / row["id"])
        self.assertEqual([(r["id"], r["roles"], [s["id"] for s in r["skills"]])
                          for r in rows[2:]],
                         [("core", [], ["notes", "lint-fix"]),
                          ("qa", ["qa_acceptance"], ["qa-check"]),
                          ("ui", ["designer"], ["ui-check"])])
        text = run("packs", "list", *self.R)[1].splitlines()
        self.assertEqual(text[0], "team 1.0.0 priority 50  .modsys/packs/team")
        self.assertIn(f"core {version} built-in  {self.tree / 'core'}", text)

    def test_a_repo_pack_and_the_team_config_win_over_a_builtin_pack(self):
        self.enable("ui")
        # the fixture's pack `bookshop` declares `designer` too (no template): its keys win, the
        # template stays the ui pack's
        rows = {r["template"]: r for r in self.ok("templates", "list")}
        self.assertEqual(rows["roles/designer.md"]["source"], "role-template:ui")
        self.assertEqual(rows["roles/designer.md"]["path"], str(self.tree / "ui/roles/designer.md"))
        self.repo_pack("team", '[fields.screen_ref]\ntype = "string"\ndescription = "Ours"\n')
        schema = self.ok("schema")["properties"]["modules"]["additionalProperties"]
        self.assertEqual(schema["properties"]["screen_ref"]["description"], "Ours")
        self.config('[packs]\nbuiltin = ["ui"]\n[fields.screen_ref]\ntype = "string"\n'
                    'description = "Team"\n[roles.designer]\ndescription = "Team UX"\n')
        schema = self.ok("schema")["properties"]["modules"]["additionalProperties"]
        self.assertEqual(schema["properties"]["screen_ref"]["description"], "Team")
        data = self.ok("create", "reviews", "--non-interactive", "--description",
                       "Customer reviews of books: ratings and moderation.", "--keywords",
                       "review, rating, stars, comment, moderation", "--tag", "ui")
        doc = (self.root / "modules/reviews/roles/designer.md").read_text()
        self.assertIn("modules/reviews/roles/designer.md", data["files"])
        self.assertEqual(doc, "# Reviews — designer\n\n## UX invariants\n")

    def test_the_engine_tree(self):
        root = builtin_packs_root()  # imported before the patch: the engine's own tree
        self.assertEqual(root, Path(__file__).resolve().parents[1] / "modsys/defaults/packs")
        self.assertEqual(sorted(p.name for p in root.iterdir() if (p / "pack.toml").is_file()),
                         ["core", "qa", "ui"])


class ReservedIdsTest(FakeBuiltins):  # P4B-AC-007
    def test_packs_new_refuses_a_builtin_id(self):
        for enabled in ((), ("core", "ui", "qa")):
            self.enable(*enabled)
            for pack_id in ("core", "ui", "qa"):
                with self.subTest(enabled=enabled, pack=pack_id):
                    err = self.refused("packs", "new", pack_id, "--skill", "x-y")
                    self.assertEqual(err, f"modsys: error: pack id '{pack_id}' is reserved for "
                                          f"the engine's built-in pack — enable it: [packs] "
                                          f"builtin = [\"{pack_id}\"]\n")
                    self.assertFalse((self.root / ".modsys/packs" / pack_id).exists())

    def test_a_repo_copy_replaces_the_builtin_pack(self):
        copy = self.root / ".modsys/packs/ui"
        shutil.copytree(self.tree / "ui", copy)
        (copy / "pack.toml").write_text((copy / "pack.toml").read_text().replace(
            'description = "UX rules"', 'description = "Our UX rules"'))
        for enabled in (("ui",), ()):
            with self.subTest(enabled=enabled):
                self.enable(*enabled)
                rows = [r for r in self.ok("packs", "list") if r["id"] == "ui"]
                self.assertEqual([(r["builtin"], r["dir"], r["roles"]) for r in rows],
                                 [(False, ".modsys/packs/ui", ["designer"])])

    def test_a_repo_core_pack_declares_what_is_synced(self):
        d = self.repo_pack("core", '[skills.notes]\npath = "skills/notes"\n')
        (d / "skills/notes").mkdir(parents=True)
        (d / "skills/notes/SKILL.md").write_text(SKILL.format(sid="notes", pack="team core"))
        self.enable("core")
        data = self.ok("packs", "sync", "--agent", "claude")
        self.assertEqual([(r["skill"], r["pack"], r["status"]) for r in data["skills"]],
                         [("notes", "core", "created")])


class BuiltinMachineryTest(FakeBuiltins):  # P4B-AC-008 (mechanics; the shipped packs: Task 7)
    def sync(self, code=0) -> list[tuple]:
        data = self.ok("packs", "sync", "--agent", "claude", "--agent", "codex", code=code)
        return [(r["agent"], r["skill"], r["status"], r["source"]) for r in data["skills"]]

    def change_the_engine(self) -> None:
        """The engine's tree after an upgrade: `notes` changed, same engine version."""
        new = Path(self._tmp.name) / "builtins-2"
        shutil.copytree(self.tree, new)
        md = new / "core/skills/notes/SKILL.md"
        md.write_text(md.read_text() + "\n5. A new step upstream.\n")
        self.tree = new

    def test_sync_from_a_builtin_pack_and_an_engine_upgrade(self):
        self.enable("core", "ui", "qa")
        rows = self.sync()
        self.assertEqual([r[2] for r in rows], ["created"] * 8)
        marker = json.loads((self.root / ".claude/skills/notes/.modsys-managed").read_text())
        self.assertEqual((marker["pack"], marker["version"], marker["source"]),
                         ("core", __version__, "pack"))
        for sid, pack in SKILLS.items():
            self.assertEqual((self.root / ".agents/skills" / sid / "SKILL.md").read_bytes(),
                             (self.tree / pack / "skills" / sid / "SKILL.md").read_bytes())
        self.assertEqual([r[2] for r in self.sync_check()], ["unchanged"] * 8)
        self.change_the_engine()
        self.assertEqual([(r[0], r[1]) for r in self.sync() if r[2] == "updated"],
                         [("claude", "notes"), ("codex", "notes")])

    def sync_check(self) -> list[tuple]:
        data = self.ok("packs", "sync", "--check", "--agent", "claude", "--agent", "codex")
        return [(r["agent"], r["skill"], r["status"]) for r in data["skills"]]

    def test_eject_a_builtin_skill_and_ms063(self):
        self.enable("core")
        init_git(self.root)
        self.sync()
        data = self.ok("eject", "notes")
        self.assertEqual((data["pack"], data["version"]), ("core", __version__))
        copy = self.root / ".modsys/overrides/skills/notes"
        record = json.loads((copy / ".modsys-ejected").read_text())
        self.assertEqual((record["pack"], record["version"]), ("core", __version__))
        (copy / "SKILL.md").write_text((copy / "SKILL.md").read_text() + "\nOurs.\n")
        self.assertEqual([r for r in self.sync() if r[1] == "notes"],
                         [("claude", "notes", "updated", "ejected"),
                          ("codex", "notes", "updated", "ejected")])
        self.change_the_engine()
        lint = self.ok("lint", "--fail-on", "never")
        self.assertEqual([f["message"] for f in lint["findings"] if f["code"] == "MS063"],
                         [f"ejected skill 'notes' is behind pack 'core' (ejected from "
                          f"{__version__}, pack is now {__version__}) — review: modsys eject "
                          f"notes --diff"])
        diff = self.ok("eject", "notes", "--diff")
        self.assertTrue(diff["behind"])
        self.assertIn("-5. A new step upstream.", diff["diff"])

    def test_the_agents_md_block_and_templates_list(self):
        self.enable("core", "ui", "qa")
        self.ok("agents-md", "--target", "AGENTS.md")
        text = (self.root / "AGENTS.md").read_text()
        for sid, pack in SKILLS.items():
            self.assertIn(f"- `{sid}` — The {sid} skill of the {pack} pack.", text)
        rows = {r["template"]: (r["source"], r["path"]) for r in self.ok("templates", "list")}
        self.assertEqual(rows["roles/designer.md"],
                         ("role-template:ui", str(self.tree / "ui/roles/designer.md")))
        self.assertEqual(rows["roles/qa_acceptance.md"],
                         ("role-template:qa", str(self.tree / "qa/roles/qa_acceptance.md")))


class BuiltinContractTest(FakeBuiltins):  # P4B-AC-024 (packs list with built-in packs)
    def test_one_envelope(self):
        self.enable("core", "ui", "qa")
        code, env, err = run_json("packs", "list", *self.R)
        self.assertEqual((code, err, set(env)), (0, "", {"schema", "data"}))
        self.assertEqual(env["schema"], "modsys.packs/1")
        self.assertEqual({k for row in env["data"] for k in row},
                         {"id", "version", "priority", "builtin", "dir", "description", "roles",
                          "skills"})


if __name__ == "__main__":
    unittest.main()
