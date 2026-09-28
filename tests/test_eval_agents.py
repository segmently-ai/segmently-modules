"""E-B blind-agent fixtures: the prompts keep their placeholders and rules, the rubric its
PASS line, and the `adopter` persona's repository builder makes the repository it describes."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from tests.helpers import git, run, run_json

AGENTS = Path(__file__).resolve().parents[1] / "evals" / "adoption" / "agents"
BROWNFIELD_SHA256 = "89d72954459985c3018f749dd281e5bbf3aaa2d570a60b38c399220b6ff2c89e"


class AgentFixturesTest(unittest.TestCase):
    def read(self, name: str) -> str:
        return (AGENTS / name).read_text(encoding="utf-8")

    def test_prompts_carry_placeholders_rules_and_the_log_format(self):
        for name, goals in (("greenfield.md", 5), ("brownfield.md", 6)):  # P5b D11: + 5, 6
            with self.subTest(prompt=name):
                text = self.read(name)
                for needle in ("{WORKDIR}", "{VENV}", "{DOCS}", "source peek", "--help",
                               "FRICTION.md", "## Log", "## Summary", "blocker", "major",
                               "minor", f"{goals}. "):
                    self.assertIn(needle, text)
                self.assertNotIn(f"{goals + 1}. ", text)

    def test_brownfield_pins_the_public_repository(self):
        text = self.read("brownfield.md")
        self.assertIn("https://github.com/nsidnev/fastapi-realworld-example-app", text)
        self.assertIn("checkout -q 029eb77", text)
        self.assertIn("at least 80 %", text)

    def test_the_pack_author_prompt_and_its_rubric(self):  # P4A-AC-025 (fixtures)
        text = self.read("pack-author.md")
        for needle in ("{WORKDIR}", "{VENV}", "{DOCS}", "tests/fixtures/bookshop", "CLAUDE.md",
                       "AGENTS.md", "source peek", "--help", "about 35 commands", "FRICTION.md",
                       "## Log", "## Summary", "blocker", "major", "minor", "5. "):
            self.assertIn(needle, text)
        self.assertNotIn("6. ", text)
        rubric = " ".join(self.read("rubric.md").split())
        self.assertIn("## pack-author", rubric)
        self.assertIn("**PASS (pack-author)** = all 5 goal steps verified, 0 source peeks, "
                      "0 blockers, commands ≤ 35.", rubric)
        for check in ("modsys packs sync --check --agent claude --agent codex",
                      "no MS060–MS065 error", "modsys show … --role <role>",
                      ".modsys/overrides/skills/<skill>/", "exactly one `<!-- modsys:begin` line"):
            self.assertIn(check, rubric)

    def test_the_adopter_prompt_and_its_rubric(self):  # P5A-AC-040 (fixtures)
        text = self.read("adopter.md")
        for needle in ("{WORKDIR}", "{VENV}", "{DOCS}", "adopter_repo.py", "source peek",
                       "--help", "about 35 commands", "FRICTION.md", "## Log", "## Summary",
                       "blocker", "major", "minor", "4. ", "without rewriting it",
                       "`modsys lint` clean"):
            self.assertIn(needle, text)
        self.assertNotIn("5. ", text)
        rubric = " ".join(self.read("rubric.md").split())
        self.assertIn("## adopter", rubric)
        self.assertIn("**PASS (adopter)** = all 4 goal steps verified, 0 source peeks, "
                      "0 blockers, commands ≤ 35.", rubric)
        for check in ("git diff --quiet <the first commit> -- modules",
                      "git ls-files --error-unmatch .modsys/config.toml",
                      "modsys lint --fail-on warning", "modsys show inventory --json",
                      "`src/inventory/` under `code`"):
            self.assertIn(check, rubric)
        self.assertIn("whether it used `modsys init map`", rubric)

    def test_the_brownfield_prompt_is_pinned(self):  # P5B-AC-036: D11's goal steps 5 and 6
        import hashlib
        text = " ".join(self.read("brownfield.md").split())
        for needle in ("5. The registry is lint-clean: `modsys lint --fail-on warning` exits 0",
                       "6. Measure the routing: write a tasks file yourself",
                       "whether you used `modsys init`", "about 45 commands"):
            self.assertIn(needle, text)
        rubric = " ".join(self.read("rubric.md").split())
        for needle in ("(greenfield: 5, brownfield: 6)", "PASS needs 6/6",
                       "`modsys eval routing --tasks <file>` or `modsys init verify`"):
            self.assertIn(needle, rubric)
        self.assertEqual(hashlib.sha256((AGENTS / "brownfield.md").read_bytes()).hexdigest(),
                         BROWNFIELD_SHA256)

    def test_rubric_pass_line(self):
        text = " ".join(self.read("rubric.md").split())
        self.assertIn("**PASS** = all goal steps done, 0 source peeks, 0 blockers, commands ≤ 40 "
                      "(greenfield) or ≤ 45 (brownfield), and — brownfield — the coverage "
                      "reported and ≥ 0.8.", text)



class AdopterRepoTest(unittest.TestCase):  # P5A-AC-040: the builder, checked by commands
    def build(self, dest: Path) -> Path:
        spec = importlib.util.spec_from_file_location("adopter_repo", AGENTS / "adopter_repo.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.build(dest)

    def test_the_repository_and_the_goal_steps_by_config_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.build(Path(tmp) / "warehouse")
            again = self.build(Path(tmp) / "again")
            self.assertEqual(git(root, "rev-parse", "HEAD"), git(again, "rev-parse", "HEAD"))
            self.assertFalse((root / ".modsys").exists())
            raw = json.loads((root / "modules/registry.json").read_text())
            self.assertEqual((raw["last_modified"], sorted(raw["modules"])),
                             ("2026-02-01T09:30:00Z", ["inventory", "loyalty", "orders",
                                                       "shipping"]))
            self.assertEqual(raw["modules"]["inventory"]["stock_paths"], ["src/inventory/"])
            self.assertIn("archivist", raw["modules"]["inventory"]["context_files"]["roles"])
            R = ("--root", str(root))
            before = {p: p.read_bytes() for p in (root / "modules").rglob("*") if p.is_file()}
            lint = run_json("lint", "--fail-on", "never", *R)[1]["data"]
            self.assertEqual(sorted({f["code"] for f in lint["findings"]}),
                             ["MS012", "MS014", "MS015"])
            self.assertEqual(run("adopt", *R)[0], 0)
            self.assertEqual({p: p.read_bytes() for p in (root / "modules").rglob("*")
                              if p.is_file()}, before)
            self.assertEqual(run("lint", "--fail-on", "warning", *R)[0], 0)
            self.assertEqual(run_json("show", "inventory", *R)[1]["data"]["code"],
                             ["src/inventory/"])
            self.assertEqual(sorted(r["module"] for r in run_json("list", *R)[1]["data"]),
                             ["inventory", "loyalty", "orders", "shipping"])


if __name__ == "__main__":
    unittest.main()
