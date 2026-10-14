"""What the plugins are for and the one-prompt installs (owner 2026-10-14, by the pattern of the
support plugins): an AI coding agent is an excellent worker with amnesia and a memory of limited
size, and the notes solve both — written for any part of the project, found before a task,
updated after it, kept per role. One text (`PURPOSE` and `install_prompts` in
tools/build_plugins.py) reaches the core plugin's README, the publish repository's README
section and the npm README; the engine's README says the purpose at length and carries the very
same prompts, pinned like its other install lines."""
from __future__ import annotations

import re
import unittest

from tests.plugin_helpers import ENGINE, load_tool

PLUGINS_REPO = "segmently-ai/segmently-modules-plugins"
README = (ENGINE / "README.md").read_text(encoding="utf-8")


class PurposeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = load_tool("build_plugins")

    def test_the_engine_readme_opens_with_it(self):
        head = README.split("\n## What it is for\n", 1)[1].split("\n## ", 1)[0]
        self.assertTrue(README.startswith("# Segmently Modules\n\n## What it is for\n"))
        for needle in ("An AI coding agent is an excellent worker with amnesia and a memory of "
                       "limited size", "1. **It writes the notes for starting work on any part "
                       "of the project** — a specific page or a",
                       "2. **It finds the notes a task needs before the work starts**",
                       "3. **It brings the notes up to date when the work is done**",
                       "4. **It keeps the notes per role**", "its memory is limited"):
            self.assertIn(needle, " ".join(head.split()))

    def test_the_core_plugin_readme_carries_it_and_the_others_do_not(self):
        build = self.build
        core = build.readme(build.CORE, ["module-scout"], [], "9.1.0")
        self.assertIn(f"## What it is for\n\n{build.PURPOSE}\n## What it holds\n", core)
        self.assertIn(build.RELOAD_NOTE, core)
        self.assertIn("Notes for AI coding agents, excellent workers with amnesia",
                      build.PLUGINS[build.CORE]["description"])
        self.assertIn("`npm install -g @segmently/modules`", core)
        for name in build.PLUGINS:
            if name != build.CORE:
                with self.subTest(plugin=name):
                    self.assertNotIn(build.PURPOSE, build.readme(name, ["designer"], [], "9.1.0"))

    def test_the_marketplace_and_npm_say_it(self):
        self.assertIn("notes for AI coding agents", load_tool("publish").DESCRIPTION["stable"])
        npm = load_tool("build_npm").readme("9.1.0", "Code-structure-centric context layer for "
                                                     "AI coding agents").decode("utf-8")
        self.assertIn(self.build.PURPOSE, npm)
        self.assertIn("This package is the command line: code-structure-centric", npm)


class PromptsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = load_tool("build_plugins")
        cls.release = load_tool("release")

    def test_the_engine_readme_holds_the_prompts_verbatim(self):
        pinned = set(re.findall(r"segmently-modules\.git@v(\d+\.\d+\.\d+)", README))
        self.assertEqual(len(pinned), 1, pinned)  # the release moves every pin at once
        cli = f"git+https://github.com/segmently-ai/segmently-modules.git@v{pinned.pop()}"
        blocks = re.findall(r"```text\n(.*?)```", README, re.S)
        for agent, text in self.build.install_prompts(cli).items():
            with self.subTest(agent=agent):
                self.assertIn(text, blocks)

    def test_each_prompt_sets_up_and_stops(self):
        for agent, text in self.build.install_prompts("git+x").items():
            with self.subTest(agent=agent):
                self.assertTrue(text.startswith(f"Set up Segmently Modules for {agent} on this "
                                                f"machine, then stop and give me the two next "
                                                f"steps."))
                self.assertIn("git --version and python3 --version", text)
                self.assertIn("Python must be 3.9 or newer", text)
                # the owner, 2026-10-14: the end is one explicit message — reload, then the request
                self.assertIn("Do not try to reload or restart anything yourself and do not start "
                              f"another {agent} process. End with one separate message to me that "
                              "holds only the text below, word for word:\n\nSetup is done. Two "
                              "steps for you:\n1. ", text)
                self.assertIn("\n2. Then paste this request:\n" + self.build.FIRST_REQUEST + "\n",
                              text)
                self.assertTrue(text.endswith(self.build.FIRST_REQUEST + "\n"))
                self.assertIn("Use the module-assistant skill", text)
                for way_in in ("adopt it with the module-adopt skill",  # the owner: name what runs
                               "run segmently-modules setup, then map the code into modules and "
                               "write their notes with the module-init skill",
                               "run segmently-modules setup, then the module-create skill",
                               "adds the Segmently Modules section to CLAUDE.md and AGENTS.md"):
                    self.assertIn(way_in, text)
                self.assertIn(PLUGINS_REPO, text)
                self.assertIn("segmently-modules@segmently-modules", text)
        claude, codex = (self.build.install_prompts("git+x")[a] for a in ("Claude Code", "Codex"))
        self.assertIn(f"claude plugin marketplace add {PLUGINS_REPO}#stable --scope user", claude)
        self.assertIn(f"codex plugin marketplace add {PLUGINS_REPO} --ref stable", codex)
        self.assertIn("npm install -g @segmently/modules", codex)
        self.assertIn("uv tool install git+x instead", codex)
        self.assertNotIn("npm install", claude)  # the Claude Code plugin carries the CLI
        self.assertIn("Claude Code picks a newly installed plugin up only after /reload-plugins, "
                      "which only I can type, or in a new session", claude)  # the owner, 2026-10-14
        self.assertIn("1. Type /reload-plugins in this chat (or restart Claude Code in the "
                      "repository you want to work on).", claude)
        self.assertIn("Codex picks a newly installed plugin up only in a new session", codex)
        self.assertIn("1. Restart Codex in the repository you want to work on.", codex)

    def test_the_readme_separates_the_purpose_and_names_the_reload(self):
        flat = " ".join(README.split())
        self.assertLess(README.index("## What it is for"), README.index("## Install with one prompt"))
        self.assertLess(README.index("## Install with one prompt"), README.index("## Install by hand"))
        for text in (self.build.PROMPTS_INTRO, self.build.RELOAD_NOTE,
                     "**What goes into `CLAUDE.md`.** " + self.build.INSTRUCTIONS_NOTE,
                     "Codex picks the plugin up in a new session."):
            with self.subTest(text=text[:40]):
                self.assertIn(text, flat)

    def test_the_publish_readme_section_carries_both(self):
        for channel, version, cli in (
                ("stable", "9.1.0",
                 "git+https://github.com/segmently-ai/segmently-modules.git@v9.1.0"),
                ("dev", "9.1.0-dev.h1234abcd",
                 "git+https://github.com/segmently-ai/segmently-modules.git")):
            with self.subTest(channel=channel):
                section = self.release.readme_section(PLUGINS_REPO, channel, version)
                self.assertTrue(section.startswith("## Segmently Modules\n\n### What it is for\n\n"
                                                   + self.build.PURPOSE))
                self.assertIn(f"### Install with one prompt\n\n{self.build.PROMPTS_INTRO}\n", section)
                self.assertIn(f"```\n\n{self.build.INSTRUCTIONS_NOTE}\n\n### Install by hand", section)
                self.assertTrue(section.endswith(f"\n\n{self.build.RELOAD_NOTE}\n"))
                for agent, text in self.build.install_prompts(cli).items():
                    self.assertIn(f"**{agent}**\n\n```text\n{text}```\n", section)
                self.assertLess(section.index("### Install with one prompt"),
                                section.index("### Install by hand"))


if __name__ == "__main__":
    unittest.main()
