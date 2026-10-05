"""`[packs] builtin_delivery` (P6 D2): "repo" (the default: `packs sync` copies the built-in
packs' skills) or "plugin" (the modsys plugins provide them) — the values and layers, one
delivery at a time across `packs sync`, `eject`, `agents-md` and lint MS067, and the transitions
between the two."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import modsys
from tests.helpers import copy_fixture, init_git, run, run_json

CORE = ["module-adopt", "module-create", "module-discover", "module-init", "module-lint",
        "module-research", "module-roles", "module-scout", "module-split", "module-sync"]
BUILTIN = sorted(CORE + ["designer", "qa-acceptance", "qa-acceptance-baseline"])
SKILL = "---\nname: api-review\ndescription: Reviews API changes.\n---\n\n# api-review\n"
PLUGINS = "the plugins modsys (core), modsys-qa (qa), modsys-ui (ui)"
REFUSAL = 'builtin_delivery = "plugin" — the plugin provides this skill; eject needs "repo"'
AGENTS = ("--agent", "claude", "--agent", "codex")


class DeliveryRepo(unittest.TestCase):
    """The bookshop fixture in git, the three built-in packs, repository pack `team` with the
    skill `api-review`."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        self.R = ("--root", str(self.root))
        team = self.root / ".modsys/packs/team"
        (team / "skills/api-review").mkdir(parents=True)
        (team / "pack.toml").write_text('id = "team"\nversion = "0.1.0"\n\n[skills.api-review]\n'
                                        'path = "skills/api-review"\n', encoding="utf-8")
        (team / "skills/api-review/SKILL.md").write_text(SKILL, encoding="utf-8")
        init_git(self.root)
        self.config()

    def tearDown(self):
        self._tmp.cleanup()

    def config(self, delivery: str | None = None, builtin=("core", "ui", "qa"),
               user: str | None = None) -> None:
        """`delivery` / `user`: the TOML value of `builtin_delivery` in the team / user config
        (e.g. '"plugin"', '5'); None leaves the key out."""
        text = f"[packs]\nbuiltin = {json.dumps(list(builtin))}\n"
        if delivery is not None:
            text += f"builtin_delivery = {delivery}\n"
        (self.root / ".modsys/config.toml").write_text(text, encoding="utf-8")
        user_path = self.root / ".modsys/config.user.toml"
        if user is None:
            user_path.unlink(missing_ok=True)
        else:
            user_path.write_text(f"[packs]\nbuiltin_delivery = {user}\n", encoding="utf-8")

    def sync(self, *argv: str, code: int = 0) -> dict:
        got, env, err = run_json("packs", "sync", *argv, *self.R)
        self.assertEqual((got, err), (code, ""), env)
        return env["data"]

    def rows(self, data: dict) -> list[tuple]:
        return [(r["agent"], r["skill"], r["status"]) for r in data["skills"]]

    def plugin_notes(self, data: dict) -> list[str]:
        return [n for n in data["notes"] if n.startswith('builtin_delivery = "plugin"')]

    def lint_codes(self, *argv: str) -> list[tuple]:
        code, env, err = run_json("lint", "--fail-on", "never", *argv, *self.R)
        self.assertEqual((code, err), (0, ""))
        return sorted((f["path"], f["severity"]) for f in env["data"]["findings"]
                      if f["code"] == "MS067")

    def files(self, top: str) -> dict:
        base = self.root / top
        return {p.relative_to(base).as_posix(): p.read_bytes()
                for p in sorted(base.rglob("*")) if p.is_file()} if base.exists() else {}


class ValuesAndLayersTest(DeliveryRepo):  # P6-AC-001 (SI-8)
    def test_the_default_and_the_layers(self):
        for team, user, effective in ((None, None, "repo"), ('"repo"', None, "repo"),
                                      ('"plugin"', None, "plugin"),
                                      ('"repo"', '"plugin"', "plugin"),
                                      ('"plugin"', '"repo"', "repo")):
            with self.subTest(team=team, user=user):
                self.config(team, user=user)
                data = self.sync("--dry-run", "--agent", "claude")
                built = {r["skill"] for r in data["skills"]} & set(BUILTIN)
                self.assertEqual(bool(built), effective == "repo")
                self.assertEqual(bool(self.plugin_notes(data)), effective == "plugin")

    def test_values_that_are_refused(self):
        for value, why in (('"Plugin"', "expected one of repo, plugin, got 'Plugin'"),
                           ('""', "expected one of repo, plugin, got ''"),
                           ('"both"', "expected one of repo, plugin, got 'both'"),
                           ("5", "expected a string, got 5"),
                           ("true", "expected a string, got True"),
                           ('["plugin"]', "expected a string, got ['plugin']")):
            for layer in ("team", "user"):
                with self.subTest(value=value, layer=layer):
                    self.config(value if layer == "team" else None,
                                user=value if layer == "user" else None)
                    name = "config.toml" if layer == "team" else "config.user.toml"
                    code, out, err = run("packs", "sync", "--agent", "claude", *self.R)
                    self.assertEqual((code, out), (2, ""))
                    self.assertTrue(err.startswith("modsys: error: "), err)
                    self.assertIn(f".modsys/{name}: [packs] builtin_delivery: {why}", err)

    def test_a_pack_cannot_set_it(self):
        pack = self.root / ".modsys/packs/team/pack.toml"
        pack.write_text(pack.read_text() + '\n[packs]\nbuiltin_delivery = "plugin"\n')
        code, out, err = run("packs", "sync", "--agent", "claude", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn(".modsys/packs/team/pack.toml: [packs] builtin_delivery: a pack cannot "
                      "choose how the built-in skills are delivered — set it in "
                      ".modsys/config.toml (or config.user.toml)", err)


class OneDeliveryTest(DeliveryRepo):  # P6-AC-002
    def test_repo_then_plugin_the_copies_are_removed(self):  # rows 1, 2, 3, 9
        data = self.sync(*AGENTS)  # row 1
        self.assertEqual(self.rows(data), [(a, s, "created") for a in ("claude", "codex")
                                           for s in sorted(BUILTIN + ["api-review"])])
        self.assertEqual(self.plugin_notes(data), [])
        self.assertEqual(self.lint_codes(), [])
        ok_md = run("agents-md", "--target", "CLAUDE.md", *self.R)
        self.assertEqual(ok_md[0], 0)
        for sid in BUILTIN + ["api-review"]:
            self.assertIn(f"- `{sid}` — ", (self.root / "CLAUDE.md").read_text())
        before = self.files(".claude")
        self.assertEqual(self.sync(*AGENTS)["summary"]["unchanged"], 28)  # row 9: repo keeps
        self.config('"plugin"')
        self.assertEqual(self.lint_codes(), sorted(  # row 3, before the sync: 26 infos
            (f"{top}/{s}", "info") for top in (".agents/skills", ".claude/skills")
            for s in BUILTIN))
        # P81-AC-038: the block's wording follows the delivery, so the repo block is stale now
        self.assertEqual(run("agents-md", "--target", "CLAUDE.md", "--check", *self.R)[0], 1)
        self.assertEqual(run("agents-md", "--target", "CLAUDE.md", *self.R)[0], 0)
        self.assertEqual(run("agents-md", "--target", "CLAUDE.md", "--check", *self.R)[0], 0)
        data = self.sync(*AGENTS)  # row 3
        self.assertEqual(self.rows(data), [
            (a, s, "unchanged" if s == "api-review" else "removed") for a in ("claude", "codex")
            for s in sorted(BUILTIN + ["api-review"])])
        self.assertEqual(self.plugin_notes(data), [
            f'builtin_delivery = "plugin": the built-in skills come from {PLUGINS} — packs sync '
            f'copies none of them'])
        for top in (".claude/skills", ".agents/skills"):
            self.assertEqual(sorted(p.name for p in (self.root / top).iterdir()), ["api-review"])
        self.assertEqual(self.files(".claude"), {k: v for k, v in before.items()
                                                 if k.startswith("skills/api-review/")})
        self.assertEqual(self.lint_codes(), [])  # after it: none
        data = self.sync(*AGENTS)  # row 2: plugin, no copies
        self.assertEqual({r["status"] for r in data["skills"]}, {"unchanged"})
        self.assertEqual([r["skill"] for r in data["skills"]], ["api-review", "api-review"])
        self.config()  # row 9 the other way: back to repo recreates them
        self.assertEqual(self.sync(*AGENTS)["summary"]["created"], 26)

    def test_plugin_from_the_start(self):  # row 2
        self.config('"plugin"')
        data = self.sync(*AGENTS)
        self.assertEqual(self.rows(data), [("claude", "api-review", "created"),
                                           ("codex", "api-review", "created")])
        self.assertEqual(len(self.plugin_notes(data)), 1)
        code, out, err = run("packs", "sync", *AGENTS, *self.R)
        self.assertIn(f'note: builtin_delivery = "plugin": the built-in skills come from '
                      f'{PLUGINS} — packs sync copies none of them', out.splitlines())
        self.assertEqual((code, err), (0, ""))
        for argv in (("module-lint",), ("module-lint", "--dry-run")):
            code, out, err = run("eject", *argv, "--json", *self.R)
            self.assertEqual((code, out), (2, ""))
            self.assertIn(REFUSAL, err)
        self.assertFalse((self.root / ".modsys/overrides").exists())
        run("agents-md", "--target", "CLAUDE.md", *self.R)
        plugin_block = (self.root / "CLAUDE.md").read_bytes()
        self.config()  # P81-AC-038: back to repo, the plugin wording is stale; --check writes nothing
        self.assertEqual(run("agents-md", "--target", "CLAUDE.md", "--check", *self.R)[0], 1)
        self.assertEqual((self.root / "CLAUDE.md").read_bytes(), plugin_block)
        self.assertEqual(self.lint_codes(), [])

    def test_an_edited_copy_and_a_hand_written_skill(self):  # rows 4 and 5
        self.sync(*AGENTS)
        edited = self.root / ".claude/skills/module-sync/SKILL.md"
        edited.write_text("# edited by hand\n")
        shutil.rmtree(self.root / ".agents/skills/module-scout")
        mine = self.root / ".agents/skills/module-scout/SKILL.md"
        mine.parent.mkdir()
        mine.write_text("---\nname: module-scout\ndescription: Mine.\n---\n")
        self.config('"plugin"')
        data = self.sync(*AGENTS, code=1)
        rows = {(r["agent"], r["skill"]): r for r in data["skills"]}
        self.assertEqual((rows[("claude", "module-sync")]["status"],
                          rows[("claude", "module-sync")]["reason"]),
                         ("conflict", "SKILL.md (locally edited; not removed)"))
        self.assertNotIn(("codex", "module-scout"), rows)  # no marker: no row, untouched
        self.assertEqual(sum(r["status"] == "removed" for r in rows.values()), 24)
        self.assertEqual(edited.read_text(), "# edited by hand\n")
        self.assertEqual(mine.read_text(), "---\nname: module-scout\ndescription: Mine.\n---\n")
        self.assertEqual(self.lint_codes(), [(".claude/skills/module-sync", "info")])

    def test_an_ejected_built_in_skill(self):  # row 6
        self.assertEqual(run("eject", "module-lint", *self.R)[0], 0)
        self.sync(*AGENTS)
        ejected = self.files(".modsys/overrides")
        copies = {top: self.files(f"{top}/skills/module-lint") for top in (".claude", ".agents")}
        self.config('"plugin"')
        data = self.sync(*AGENTS, code=1)
        rows = [r for r in data["skills"] if r["skill"] == "module-lint"]
        self.assertEqual([(r["agent"], r["status"], r["source"]) for r in rows],
                         [("claude", "conflict", "ejected"), ("codex", "conflict", "ejected")])
        self.assertEqual(rows[0]["reason"], 'ejected to .modsys/overrides/skills/module-lint '
                         'while builtin_delivery = "plugin" (the plugin provides this skill) — '
                         'delete the ejected copy, or set [packs] builtin_delivery = "repo"')
        self.assertEqual(self.files(".modsys/overrides"), ejected)
        self.assertEqual({top: self.files(f"{top}/skills/module-lint")
                          for top in (".claude", ".agents")}, copies)
        code, env, err = run_json("eject", "module-lint", "--diff", *self.R)
        self.assertEqual((code, err, env["data"]["behind"]), (0, "", False))
        self.assertEqual(self.lint_codes(), [(".agents/skills/module-lint", "info"),
                                             (".claude/skills/module-lint", "info")])
        out = run("packs", "sync", *AGENTS, *self.R)[1]
        self.assertIn('  ejected to .modsys/overrides/skills/module-lint while builtin_delivery = '
                      '"plugin" (the plugin provides this skill) — delete the ejected copy, or '
                      'set [packs] builtin_delivery = "repo"', out.splitlines())

    def test_a_repository_pack_with_a_built_in_id(self):  # row 8
        self.config('"plugin"')
        ui = self.root / ".modsys/packs/ui"
        code, env, _ = run_json("packs", "list", *self.R)
        shutil.copytree(next(r["dir"] for r in env["data"] if r["id"] == "ui"), ui)
        data = self.sync(*AGENTS)
        self.assertIn(("claude", "designer", "created"), self.rows(data))
        self.assertEqual(self.plugin_notes(data), [
            'builtin_delivery = "plugin": the built-in skills come from the plugins modsys '
            '(core), modsys-qa (qa) — packs sync copies none of them'])
        self.assertEqual(run("eject", "designer", *self.R)[0], 0)
        run("agents-md", "--target", "CLAUDE.md", *self.R)
        self.assertIn("- `designer` — ", (self.root / "CLAUDE.md").read_text())

    def test_roles_and_templates_are_the_same(self):  # the Then under the table
        outputs = {}
        for delivery in (None, '"plugin"'):
            self.config(delivery)
            outputs[delivery] = [run(*argv, "--json", *self.R)[1] for argv in (
                ("templates", "list"), ("packs", "list"))]
            code, env, err = run_json("create", "reviews", "--non-interactive", "--tag", "ui",
                                      "--tag", "qa", "--dry-run", "--description",
                                      "Customer reviews of books: ratings and comments.",
                                      "--keywords", "review, rating, stars, comment, moderation",
                                      *self.R)
            self.assertEqual((code, err), (0, ""))
            outputs[delivery].append(json.dumps(env["data"], sort_keys=True))
        self.assertEqual(outputs[None], outputs['"plugin"'])
        self.assertIn("roles/designer.md", outputs[None][2])
        self.assertIn("roles/qa_acceptance.md", outputs[None][2])

    def test_the_info_finding_in_ci_and_not_in_lint_changed(self):  # the second Then
        self.sync(*AGENTS)
        self.config('"plugin"')
        code, env, err = run_json("ci", "--fail-on", "warning", *self.R)
        lint = next(s for s in env["data"]["steps"] if s["name"] == "lint")
        self.assertEqual(len([f for f in lint["findings"] if f["code"] == "MS067"]), 26)
        self.assertEqual(lint["status"], "passed")  # info never fails a gate
        code, env, err = run_json("lint", "--changed", "--fail-on", "never", *self.R)
        self.assertNotIn("MS067", {f["code"] for f in env["data"]["findings"]})


class PluginTextsTest(DeliveryRepo):  # final review M-14, M-15 (T-9)
    def test_ms067_names_the_sync_that_removes_it(self):
        self.sync(*AGENTS)
        (self.root / ".modsys/config.toml").write_text(
            '[packs]\nbuiltin = ["core", "ui", "qa"]\nbuiltin_delivery = "plugin"\n'
            'agents = ["claude"]\n', encoding="utf-8")

        def found() -> dict:
            code, env, err = run_json("lint", "--fail-on", "never", *self.R)
            self.assertEqual((code, err), (0, ""))
            return {f["path"]: f["message"] for f in env["data"]["findings"]
                    if f["code"] == "MS067"}

        tail = ("removes it when it is unedited (an edited copy, or the copy of an ejected "
                "skill, stays: a packs sync conflict)")
        messages = found()
        self.assertEqual(len(messages), 26)
        for path, message in messages.items():
            command = ("modsys packs sync" if path.startswith(".claude/")
                       else "modsys packs sync --agent codex")  # [packs] agents leaves it out
            self.assertTrue(message.endswith(f'(the plugin provides it) — {command} {tail}'),
                            message)
        self.sync()  # the bare sync: claude only
        self.assertEqual(sorted({p.split("/")[0] for p in found()}), [".agents"])
        self.sync("--agent", "codex")
        self.assertEqual(found(), {})

    def test_nothing_to_copy_says_where_the_skills_come_from(self):
        shutil.rmtree(self.root / ".modsys/packs/team")
        self.config('"plugin"')
        note = (f'note: builtin_delivery = "plugin": the built-in skills come from {PLUGINS} — '
                'packs sync copies none of them')  # and no Copilot note: nothing is in two places
        code, out, err = run("packs", "sync", "--agent", "claude", *self.R)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.splitlines(), [
            'nothing to copy: the built-in skills come from the modsys plugins '
            '(builtin_delivery = "plugin"); a repository pack\'s skills are copied (add one: '
            'modsys packs new ID --skill NAME)', note,
            "packs sync: 0 created, 0 updated, 0 unchanged, 0 removed, 0 conflict, 0 invalid"])
        # with codex the agent files are the rows (P8.4 D3: written under either delivery)
        code, out, err = run("packs", "sync", *AGENTS, *self.R)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.splitlines(), [
            f"created    codex   .codex/agents/{name}.toml  (core {modsys.__version__})"
            for name in ("module-discover-agent", "module-research-agent", "module-scout-agent")
        ] + [note, "packs sync: 0 created, 0 updated, 0 unchanged, 0 removed, 0 conflict, "
                   "0 invalid; agent files: 3 created, 0 updated, 0 unchanged, 0 removed, "
                   "0 conflict"])


class TransitionsTest(DeliveryRepo):  # P6-AC-026
    def test_repo_plugin_repo(self):
        self.config(builtin=("core",))
        first = self.sync("--agent", "claude")
        self.assertEqual([r["status"] for r in first["skills"]], ["created"] * 11)
        synced = self.files(".claude")
        self.config('"plugin"', builtin=("core",))
        data = self.sync("--agent", "claude")
        self.assertEqual({r["skill"]: r["status"] for r in data["skills"]},
                         {**{s: "removed" for s in CORE}, "api-review": "unchanged"})
        self.config(builtin=("core",))
        data = self.sync("--agent", "claude")
        self.assertEqual({r["skill"]: r["status"] for r in data["skills"]},
                         {**{s: "created" for s in CORE}, "api-review": "unchanged"})
        self.assertEqual(self.files(".claude"), synced)

    def test_an_ejected_skill_across_the_switch(self):
        self.config(builtin=("core",))
        self.assertEqual(run("eject", "module-lint", *self.R)[0], 0)
        self.sync("--agent", "claude")
        self.config('"plugin"', builtin=("core",))
        data = self.sync("--agent", "claude", code=1)
        statuses = {r["skill"]: r["status"] for r in data["skills"]}
        self.assertEqual(statuses, {**{s: "removed" for s in CORE}, "module-lint": "conflict",
                                    "api-review": "unchanged"})
        shutil.rmtree(self.root / ".modsys/overrides/skills/module-lint")
        data = self.sync("--agent", "claude")
        self.assertEqual({r["skill"]: r["status"] for r in data["skills"]},
                         {"module-lint": "removed", "api-review": "unchanged"})
        self.config(builtin=("core",))
        data = self.sync("--agent", "claude")
        lint_row = next(r for r in data["skills"] if r["skill"] == "module-lint")
        self.assertEqual((lint_row["status"], lint_row["source"]), ("created", "pack"))

    def test_enabling_and_disabling_built_in_packs(self):
        self.config('"plugin"', builtin=("core",))
        data = self.sync("--agent", "claude")
        self.assertEqual(self.plugin_notes(data), [
            'builtin_delivery = "plugin": the built-in skills come from the plugins modsys '
            '(core) — packs sync copies none of them'])
        self.config('"plugin"', builtin=("core", "ui"))
        data = self.sync("--agent", "claude")
        self.assertEqual([r["skill"] for r in data["skills"]], ["api-review"])
        self.assertEqual(self.plugin_notes(data), [
            'builtin_delivery = "plugin": the built-in skills come from the plugins modsys '
            '(core), modsys-ui (ui) — packs sync copies none of them'])
        self.config('"plugin"', builtin=())
        data = self.sync("--agent", "claude")
        self.assertEqual(([r["skill"] for r in data["skills"]], self.plugin_notes(data)),
                         (["api-review"], []))


class DeliveryContractTest(DeliveryRepo):  # P6-AC-033 (the D2 rows)
    def test_a_value_of_the_wrong_type_stops_every_verb(self):
        self.config("5")
        for argv in (("packs", "sync", "--agent", "claude"), ("lint",), ("match", "book"),
                     ("eject", "module-lint"), ("agents-md", "--target", "CLAUDE.md")):
            with self.subTest(argv=argv):
                code, out, err = run(*argv, "--json", *self.R)
                self.assertEqual((code, out), (2, ""))
                self.assertTrue(err.startswith("modsys: error: "), err)
                self.assertIn(".modsys/config.toml: [packs] builtin_delivery: expected a "
                              "string, got 5", err)
                self.assertNotIn("Traceback", err)


class AgentsMdGroupsTest(DeliveryRepo):  # P81 fix round 1: lead-in per skill group
    PLUGIN = "(the modsys plugins provide these skills):"
    SYNC = "(`modsys packs sync` copies them into the agents' skill directories):"

    def block(self):
        run("agents-md", "--target", "CLAUDE.md", *self.R)
        return (self.root / "CLAUDE.md").read_text()

    def test_plugin_delivery_splits_builtin_and_repository_skills(self):
        self.config('"plugin"')
        text = self.block()
        head_plugin = f"Skills from packs {self.PLUGIN}\n"
        head_sync = f"Skills from packs {self.SYNC}\n"
        self.assertEqual((text.count(head_plugin), text.count(head_sync)), (1, 1))
        plugin_part, sync_part = text.split(head_sync)
        plugin_part = plugin_part.split(head_plugin)[1]
        for sid in BUILTIN:
            self.assertIn(f"- `{sid}` — ", plugin_part)
            self.assertNotIn(f"- `{sid}` — ", sync_part)
        self.assertIn("- `api-review` — ", sync_part)
        self.assertNotIn("- `api-review` — ", plugin_part)

    def test_an_empty_group_has_no_heading(self):
        self.config('"plugin"', builtin=())
        text = self.block()
        self.assertIn(f"Skills from packs {self.SYNC}\n- `api-review` — ", text)
        self.assertNotIn("plugins provide", text)
        shutil.rmtree(self.root / ".modsys/packs/team")  # no repository skill left
        self.config('"plugin"')
        text = self.block()
        self.assertEqual(text.count("Skills from packs"), 1)
        self.assertIn(f"Skills from packs {self.PLUGIN}\n", text)

    def test_repo_delivery_is_one_group_with_the_old_wording(self):
        self.config()
        text = self.block()
        self.assertEqual(text.count("Skills from packs"), 1)
        self.assertIn(f"Skills from packs {self.SYNC}\n", text)
        for sid in BUILTIN + ["api-review"]:
            self.assertIn(f"- `{sid}` — ", text)


if __name__ == "__main__":
    unittest.main()
