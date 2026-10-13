"""`[packs] builtin_delivery` as a table — the built-in skills' delivery per agent, e.g.
`{ claude = "plugin", codex = "repo" }`: Claude Code gets them from the plugin, Codex as copies,
and a repository pack's skills are copied for both. An agent the table leaves out takes the value
of an agent that reads the same directory, else "repo"."""
from tests.helpers import run, run_json
from tests.test_builtin_delivery import AGENTS, BUILTIN, DeliveryRepo

MIXED = '{ claude = "plugin", codex = "repo" }'


class TableValuesTest(DeliveryRepo):
    def test_values_that_are_refused(self):
        for value, why in (('{ claude = "both" }',
                            "claude: expected one of repo, plugin, got 'both'"),
                           ("{ claude = 5 }", "claude: expected one of repo, plugin, got 5"),
                           ('{ vim = "plugin" }', "unknown agent 'vim'"),
                           ('{ codex = "repo", cursor = "plugin" }',
                            "codex and cursor read the same directory (.agents/skills) and need "
                            "the same delivery"),
                           ("5", "expected a string or a table, got 5")):
            with self.subTest(value=value):
                self.config(value)
                code, out, err = run("packs", "sync", "--agent", "claude", *self.R)
                self.assertEqual((code, out), (2, ""))
                self.assertIn(f".segmently-modules/config.toml: [packs] builtin_delivery: {why}", err)

    def test_a_string_still_means_every_agent(self):
        self.config('"plugin"')
        data = self.sync(*AGENTS)
        self.assertEqual(self.rows(data), [("claude", "api-review", "created"),
                                           ("codex", "api-review", "created")])


class MixedSyncTest(DeliveryRepo):
    def test_claude_from_the_plugin_codex_as_copies(self):
        self.config(MIXED)
        data = self.sync(*AGENTS)
        self.assertEqual(self.rows(data),
                         [("claude", "api-review", "created")]
                         + [("codex", s, "created") for s in sorted(BUILTIN + ["api-review"])])
        self.assertEqual(sorted(p.name for p in (self.root / ".claude/skills").iterdir()),
                         ["api-review"])
        self.assertEqual(sorted(r["name"] for r in data["agent_files"]),
                         ["module-discover-agent", "module-research-agent", "module-scout-agent"])
        notes = self.plugin_notes(data)
        self.assertEqual(len(notes), 1, data["notes"])
        self.assertIn("for claude", notes[0])
        check, _env, _err = run_json("packs", "sync", *AGENTS, "--check", *self.R)
        self.assertEqual(check, 0)

    def test_copies_made_for_claude_under_repo_are_removed(self):
        self.sync(*AGENTS)
        before = self.files(".agents/skills")
        self.config(MIXED)
        data = self.sync(*AGENTS)
        removed = [s for a, s, st in self.rows(data) if a == "claude" and st == "removed"]
        self.assertEqual(sorted(removed), BUILTIN)
        self.assertEqual({(a, st) for a, s, st in self.rows(data) if a == "codex"},
                         {("codex", "unchanged")})
        self.assertEqual(self.files(".agents/skills"), before)
        self.assertEqual(sorted(p.name for p in (self.root / ".claude/skills").iterdir()),
                         ["api-review"])

    def test_an_agent_left_out_takes_its_directory_or_repo(self):
        self.config('{ claude = "plugin" }')  # codex: not listed, no sibling listed -> repo
        data = self.sync(*AGENTS)
        self.assertIn(("codex", "module-sync", "created"), self.rows(data))
        self.assertNotIn(("claude", "module-sync", "created"), self.rows(data))
        self.config('{ cursor = "plugin" }')  # codex reads cursor's directory -> plugin
        data = self.sync("--agent", "codex")
        self.assertEqual({(s, st) for _a, s, st in self.rows(data)},
                         {("api-review", "unchanged")} | {(s, "removed") for s in BUILTIN})

    def test_bare_sync_and_next_follow_the_table(self):
        self.config(MIXED)
        self.sync(*AGENTS)
        cfg = self.root / ".segmently-modules/config.toml"
        cfg.write_text(cfg.read_text() + 'agents = ["claude", "codex"]\n', encoding="utf-8")
        code, env, err = run_json("packs", "sync", "--check", *self.R)
        self.assertEqual((code, err), (0, ""), env)
        code, env, err = run_json("next", *self.R)
        self.assertEqual((code, err), (0, ""))
        self.assertNotIn("skills", [i["kind"] for i in env["data"]["items"]])


class MixedOtherVerbsTest(DeliveryRepo):
    def test_eject_of_a_built_in_skill_is_refused(self):
        self.config(MIXED)
        code, out, err = run("eject", "module-lint", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn('builtin_delivery gives "plugin" to claude — the plugin provides this '
                      'skill there; eject needs "repo" for every agent', err)
        code, _out, err = run("eject", "api-review", *self.R)  # a repository pack's skill
        self.assertEqual((code, err), (0, ""))

    def test_ms067_only_where_the_plugin_delivers(self):
        self.sync(*AGENTS)
        self.config(MIXED)
        found = self.lint_codes()
        self.assertEqual(found, sorted((f".claude/skills/{s}", "info") for s in BUILTIN))

    def test_the_block_names_who_gets_what(self):
        self.config(MIXED)
        code, _env, err = run_json("agents-md", "--target", "CLAUDE.md", *self.R)
        self.assertEqual((code, err), (0, ""))
        text = (self.root / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("Skills from packs (the segmently-modules plugins provide these skills for claude; "
                      "`segmently-modules packs sync` copies them for the other agents):\n- `designer`", text)
        self.assertIn("Skills from packs (`segmently-modules packs sync` copies them into the agents' skill "
                      "directories):\n- `api-review`", text)
        self.assertEqual(text.count("segmently-modules:begin"), 1)
