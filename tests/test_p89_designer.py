"""P8.9 (D11, D12): the `ui` pack's skill is `designer` again — the job of the original it was
written from: prototype (a brief and standalone mocks from the team's tokens, a self-check, an
approval gate before any code), rework-audit (the as-is trace, dead ends, preserve list,
mapping) and review (screenshots of the running app are evidence, a tier, thirteen categories
with the flow patterns, the review file always written, PASS or BLOCKED). The team's settings
are a `[ui]` table the skill reads (owner: no engine schema); `designer-review` is gone (owner:
no alias). C2 of the fast mode: the contract's phrases must be there, the removed rules gone."""

import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from segmently_modules._toml import tomllib
from segmently_modules.config import builtin_packs_root, core_defaults
from segmently_modules.skills import file_hashes, read_front_matter
from tests.helpers import changelog_since_first_release, copy_fixture, run_json
from tests.plugin_helpers import copy_engine, run_tool
from tests.test_builtin_skills import section, skill_files

ENGINE = Path(__file__).resolve().parents[1]
UI = builtin_packs_root() / "ui"
SKILL = UI / "skills/designer"
REFERENCES = ["artifacts.md", "checklist.md", "flow-patterns.md", "prototype.md", "review.md",
              "rework-audit.md"]
UI_KEYS = ["rules", "tokens", "capture", "sizes", "schemes", "checker", "artifacts"]
TEMPLATE_HEADINGS = ["## Surface map", "## UX invariants", "## Interaction states",
                     "## Layout and accessibility", "## Visual patterns", "## Key flows",
                     "## Tokens and colour schemes", "## Anti-patterns", "## Design checker"]
BUDGETS = core_defaults()["budgets"]
OLD = "designer" + "-review"  # the retired name, never shipped again


def flat(text: str) -> str:
    return " ".join(text.split())


def every() -> str:
    return flat("\n".join(skill_files(SKILL).values()))


def ref(name: str) -> str:
    return flat((SKILL / "references" / name).read_text("utf-8"))


class NameTest(unittest.TestCase):  # D11, owner: `designer`, no alias
    def test_the_pack_declares_designer_only(self):
        pack = tomllib.loads((UI / "pack.toml").read_text("utf-8"))
        self.assertEqual(pack["skills"], {"designer": {"path": "skills/designer",
                                                       "reads_roles": ["designer"]}})
        self.assertEqual(sorted(p.name for p in (UI / "skills").iterdir()), ["designer"])
        self.assertEqual(read_front_matter(SKILL / "SKILL.md")["name"], "designer")

    def test_the_old_name_is_gone_from_what_ships(self):
        roots = [ENGINE / d for d in ("segmently_modules", "tools", "docs", "evals")] + [ENGINE / "README.md"]
        found = []
        for root in roots:
            for path in [root] if root.is_file() else sorted(root.rglob("*")):
                if path.is_file() and path.suffix in (".md", ".py", ".toml", ".yaml", ".json",
                                                      ".sh"):
                    if OLD in path.read_text("utf-8", errors="replace"):
                        found.append(path.relative_to(ENGINE).as_posix())
        self.assertEqual(found, [])

    def test_the_description_names_the_three_routes(self):  # X3: the trigger changed
        text = read_front_matter(SKILL / "SKILL.md")["description"]
        for needle in ("Prototype", "rework-audit", "review", "standalone HTML mocks",
                       "waits for approval before any code", "screenshots of the running app",
                       "PASS or BLOCKED", "mockup", "prototype"):
            self.assertIn(needle, text)


class PrototypeTest(unittest.TestCase):  # D11 prototype
    def test_the_route_and_its_gate(self):
        text = ref("prototype.md")
        for needle in ("give your recommended answer", "**Mock required:**",
                       "**Skip the mock**", "say in the conversation that the mock was skipped",
                       "`<artifacts>/<feature>/DESIGN_BRIEF.md`", "the flow patterns applied",
                       "component inventory", "two or three mocks that each commit to a "
                       "different primary axis", "Squint test", "`<screen>-<state>-v<N>-<axis>.html`",
                       "One SELF-CONTAINED HTML file per screen and state",
                       "No build step, no CDN, no external request",
                       "MOCK — throwaway prototype, never copy into production code",
                       "label every value with its source token",
                       "A value that maps to no token fails the brief",
                       "A mock is never shown to the user with an open blocking finding",
                       "Checker self-check", "`file://`",
                       "implementation must not start before the mock is approved",
                       "never port mock markup or its CSS", "RENDERED value"):
            self.assertIn(needle, text)
        steps = flat(section((SKILL / "SKILL.md").read_text("utf-8"), "## Steps"))
        self.assertIn("**wait for the approval: implementation does not start before it**", steps)

    def test_the_brief_template(self):
        text = ref("artifacts.md")
        for needle in ("# Design Brief:", "**Track:** new | rework", "**Surface kind:**",
                       "## Flow patterns applied", "## Component inventory", "## States covered",
                       "## Responsive behaviour", "## Mockups", "## Checker self-check",
                       "## Out of scope", "## Open questions", "# As-is Audit:",
                       "# Design Review:", "Not tracked: `screenshots/`"):
            self.assertIn(needle, text)


class ReworkAuditTest(unittest.TestCase):  # D11 rework-audit
    def test_the_five_parts(self):
        text = ref("rework-audit.md")
        for needle in ("## A — As-is path trace", "Walk it in the running app",
                       "| Stacked modal levels | ? | 1 at most |", "## B — Friction and dead-end "
                       "inventory", "`D1`", "A **dead end** =", "## C — Preserve list",
                       "## D — Mapping, not demolition", "| Today | Target | Reuse |",
                       "## E — Live check of the current build", "`F1`",
                       "state the cost and wait for the user's go",
                       "`<artifacts>/<feature>/AS_IS_AUDIT.md`"):
            self.assertIn(needle, text)


class ReviewTest(unittest.TestCase):  # D11 review, D12 evidence
    def test_screenshots_are_the_evidence(self):
        text = ref("review.md")
        for needle in ("**Screenshots of the running app are mandatory — reading the code alone "
                       "is not a design review.**", "`[ui] capture`", "`[ui] sizes`",
                       "`[ui] schemes`", "never work out a route by guessing",
                       "ask the user for exactly these screenshots", "WAIT",
                       "**degraded — no screenshots**",
                       "`<artifacts>/<feature>/screenshots/review-<screen>-<size>[-<theme>].png`"):
            self.assertIn(needle, text)
        gates = flat(section((SKILL / "SKILL.md").read_text("utf-8"), "## Gates"))
        self.assertIn("Reading code alone is not a design review", gates)

    def test_the_tiers(self):
        text = ref("review.md")
        for needle in ("**1 · checker only**", "**2 · checklist + checker**",
                       "**3 · two-reviewer critique + checklist**",
                       "**Money, verdicts and counts always get tier 3**",
                       "isolated from each other", "the review says **degraded**",
                       "A's findings go to categories 3, 6, 7, 11 and 12, B's to 5, 8, 9 and 13"):
            self.assertIn(needle, text)

    def test_the_review_is_always_written(self):
        text = ref("review.md")
        for needle in ("## 5. Write the review — always", "for every tier and every verdict",
                       "**Must fix**", "**Should fix**", "**Could improve**",
                       "**What works well**", "`PASS`", "`BLOCKED: N must-fix`",
                       "`## Re-review <date>`", "Only the user can waive a Must fix, in writing",
                       "End the turn, in the conversation, with: `Review tier: 1 | 2 | 3 — <why>`"):
            self.assertIn(needle, text)

    def test_thirteen_categories_and_the_checker_rules(self):
        raw = (SKILL / "references/checklist.md").read_text("utf-8")
        self.assertEqual(re.findall(r"^## (\d+)\. ", raw, re.M), [str(n) for n in range(1, 14)])
        text = flat(raw)
        for needle in ("**Token drift:**", "A violated invariant is automatically a **Must fix**",
                       "**FP-6 no dead ends:**", "Modal over modal is a **Must fix**",
                       "never install a tool and never guess one", "**blocking class**",
                       "→ **Must fix**", "**taste class**", "→ **Should fix**",
                       "only with a recorded reason", "**A source scan is not the rendered truth.**",
                       "4.5:1"):
            self.assertIn(needle, text)

    def test_the_eleven_flow_patterns(self):
        raw = (SKILL / "references/flow-patterns.md").read_text("utf-8")
        self.assertEqual(re.findall(r"^### (FP-\d+) · ", raw, re.M),
                         [f"FP-{n}" for n in range(1, 12)])
        text = flat(raw)
        self.assertEqual(text.count("**Rule:**"), 11)
        self.assertEqual(text.count("**Anti-pattern:**"), 11)
        self.assertIn("**Must fix** when it brings back a dead end (FP-6), a fake-done state "
                      "(FP-7) or modal over modal (FP-3, FP-4)", text)


class ContextTest(unittest.TestCase):  # D11: the context the host skill loaded, made generic
    def test_settings_modules_and_docs(self):
        steps = flat(section((SKILL / "SKILL.md").read_text("utf-8"), "## Steps"))
        for key in UI_KEYS:
            self.assertIn(f"| `{key}` |", steps)
        for needle in ("`.segmently-modules/config.toml`", "`.segmently-modules/config.user.toml`",
                       "each file whole, never only its first lines",  # C5: a table at the end
                       "`sed -n '/^\\[ui\\]/,/^\\[/p' <file>`",
                       "(default `.design`)", "**Modules** (at most 10)",
                       "its own designer doc plus the parent's (the baseline)",
                       "the first 50 lines of the module's main doc",
                       "note that the module needs a designer doc",
                       "which surfaces change and how to reach them",
                       "resume from the next missing artifact"):
            self.assertIn(needle, steps)

    def test_the_removed_rules_are_gone(self):
        text = every()
        for gone in ("Result: PASS", "Result: FAIL", "Nit", "Should-fix", "Must-fix",
                     "only at a path the user names", "the review stays in the conversation",
                     "cannot be told from the code"):
            self.assertNotIn(gone, text)

    def test_sizes(self):
        for name, text in skill_files(SKILL).items():
            with self.subTest(file=name):
                self.assertLessEqual(len(text), BUDGETS["skill_split_signal"])
                self.assertLessEqual(len(text.splitlines()), 250)
        self.assertEqual(sorted(p.name for p in (SKILL / "references").iterdir()), REFERENCES)


class RoleTemplateTest(unittest.TestCase):  # D12: the designer role template
    def test_the_sections(self):
        text = (UI / "roles/designer.md").read_text("utf-8")
        self.assertEqual(re.findall(r"^## .+$", text, re.M), TEMPLATE_HEADINGS)
        for needle in ("**Why:**", "| Surface | Route or entry | Entry selector | Purpose |",
                       "`[ui] rules`", "`[ui] checker`"):
            self.assertIn(needle, text)

    def test_create_renders_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(Path(tmp))
            (root / ".segmently-modules/config.toml").write_text('[packs]\nbuiltin = ["ui"]\n')
            code, env, err = run_json("create", "reviews", "--non-interactive", "--description",
                                      "Customer reviews of books: ratings and moderation.",
                                      "--keywords", "review, rating, stars, comment, moderation",
                                      "--tag", "ui", "--root", str(root))
            self.assertEqual((code, err), (0, ""), env)
            doc = (root / "modules/reviews/roles/designer.md").read_text("utf-8")
        self.assertEqual(re.findall(r"^## .+$", doc, re.M), TEMPLATE_HEADINGS)
        self.assertNotIn("${", doc)


class UiTableTest(unittest.TestCase):  # owner: `[ui]` in the team config, no engine schema
    def test_the_engine_accepts_the_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(Path(tmp))
            (root / ".segmently-modules/config.toml").write_text(
                '[packs]\nbuiltin = ["ui"]\n\n[ui]\nrules = ["docs/design.md"]\n'
                'capture = "npm run shot --"\nsizes = ["1280x800"]\nschemes = ["light", "dark"]\n'
                'artifacts = ".design"\n')
            for argv in (("lint",), ("show", "catalog", "--role", "designer")):
                code, env, err = run_json(*argv, "--root", str(root))
                with self.subTest(verb=argv[0]):
                    self.assertIn(code, (0, 1), env)
                    self.assertEqual(err, "")
                    self.assertNotIn("[ui]", json.dumps(env))

    def test_the_docs_name_every_key(self):
        config = flat((ENGINE / "docs/configuration.md").read_text("utf-8"))
        part = config.split("## `[ui]`", 1)[1].split(" ## ", 1)[0]
        for key in UI_KEYS:
            self.assertIn(f"| `{key}` |", part)
        self.assertIn("checks none of its keys", part)


class SyncRenameTest(unittest.TestCase):  # an installed copy of the old skill is removed
    def test_packs_sync_moves_the_copies(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = copy_fixture(base / "repo")
            (root / ".segmently-modules/config.toml").write_text('[packs]\nbuiltin = ["ui"]\n')
            old = base / "builtins"
            shutil.copytree(builtin_packs_root(), old)
            (old / "ui/skills/designer").rename(old / "ui/skills" / OLD)
            front = old / "ui/skills" / OLD / "SKILL.md"
            front.write_text(front.read_text("utf-8").replace("name: designer\n", f"name: {OLD}\n",
                                                              1), encoding="utf-8")
            pack = old / "ui/pack.toml"
            pack.write_text(pack.read_text("utf-8").replace(
                '[skills.designer]\npath = "skills/designer"',
                f'[skills.{OLD}]\npath = "skills/{OLD}"'), encoding="utf-8")
            argv = ("packs", "sync", "--agent", "claude", "--agent", "codex", "--root", str(root))
            with mock.patch("segmently_modules.config.builtin_packs_root", side_effect=lambda: old):
                self.assertEqual(run_json(*argv)[0], 0)
            self.assertTrue((root / ".claude/skills" / OLD / "SKILL.md").is_file())
            code, env, err = run_json(*argv)
            self.assertEqual((code, err), (0, ""), env)
            rows = {(r["agent"], r["skill"]): r["status"] for r in env["data"]["skills"]}
            for agent, folder in (("claude", ".claude/skills"), ("codex", ".agents/skills")):
                with self.subTest(agent=agent):
                    self.assertEqual(rows[(agent, OLD)], "removed")
                    self.assertEqual(rows[(agent, "designer")], "created")
                    self.assertFalse((root / folder / OLD).exists())
                    copy = root / folder / "designer"
                    self.assertEqual(sorted(p.relative_to(copy).as_posix()
                                            for p in copy.rglob("*.md")),
                                     ["SKILL.md", *(f"references/{n}" for n in REFERENCES)])


class PluginTest(unittest.TestCase):  # the segmently-modules-ui plugin ships the skill and its routes
    def test_the_ui_plugin(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            engine = copy_engine(base / "engine")
            proc = run_tool(engine, "build_plugins", "--out", str(base / "out"))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            skills = base / "out/segmently-modules-ui/skills"
            self.assertEqual(sorted(p.name for p in skills.iterdir()), ["designer"])
            self.assertEqual(file_hashes(skills / "designer"), file_hashes(SKILL))
            manifest = json.loads((base / "out/segmently-modules-ui/.claude-plugin/plugin.json").read_text())
            self.assertIn("designer skill: prototypes, audits and reviews UI work",
                          manifest["description"])


class DocsTest(unittest.TestCase):
    def test_skills_doc_and_changelog(self):
        skills = flat((ENGINE / "docs/skills.md").read_text("utf-8"))
        for needle in ("| `ui` | the `designer` role (`roles/designer.md`) | `designer` |",
                       "**prototype**", "**rework-audit**", "**review**", "[ui]"):
            self.assertIn(needle, skills)
        log = (ENGINE / "CHANGELOG.md").read_text("utf-8")
        unreleased = flat(changelog_since_first_release(log))
        self.assertIn(f"The `ui` pack's skill is **`designer`** (it was `{OLD}`; `packs sync` "
                      "removes the old copy)", unreleased)


if __name__ == "__main__":
    unittest.main()
