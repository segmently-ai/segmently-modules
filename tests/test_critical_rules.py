"""`show` and `discover` return `rules`: the titles of a module doc's critical-rules section
(`[lint] critical_rules_heading`, "Critical Rules" by default) with the doc and line, a child's
parent's first; the `MODULE.md` template carries the section, and the create / sync / discover
skill texts say how it is written and read."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from segmently_modules.critical_rules import critical_rules
from tests.helpers import make_repo, run, run_json

ENGINE = Path(__file__).resolve().parents[1]
SKILLS = ENGINE / "segmently_modules/defaults/packs/core/skills"

PARENT_DOC = """# Shop

## Usage

- not a rule

## ⚠️ Critical rules

### 1. Writes to nested fields use dot-notation

**Why**: merge keeps stale keys.

```
### not a heading (code)
```

### 2. Prices are integers in cents

## Other

### Not a rule either
"""

CHILD_DOC = """# Shop / till

## Critical Rules

- **Never** open the drawer without a receipt.
  - an indented detail, not a rule
- Close the shift before midnight.

## Notes
"""


class Parser(unittest.TestCase):
    def doc(self, text: str) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = Path(tmp.name) / "MODULE.md"
        p.write_text(text, encoding="utf-8")
        return p

    def test_headings_inside_the_section_any_case_any_decoration(self):
        rules = critical_rules(self.doc(PARENT_DOC), "Critical Rules")
        self.assertEqual(rules, [
            {"line": 9, "title": "1. Writes to nested fields use dot-notation"},
            {"line": 17, "title": "2. Prices are integers in cents"}])

    def test_top_level_items_when_the_section_has_no_heading(self):
        rules = critical_rules(self.doc(CHILD_DOC), "critical rules")
        self.assertEqual([r["title"] for r in rules],
                         ["Never open the drawer without a receipt.", "Close the shift before midnight."])
        self.assertEqual([r["line"] for r in rules], [5, 7])

    def test_no_section_missing_file_blank_heading(self):
        self.assertEqual(critical_rules(self.doc("# x\n\n## Usage\n- a\n"), "Critical Rules"), [])
        self.assertEqual(critical_rules(Path("/nonexistent/MODULE.md"), "Critical Rules"), [])
        self.assertEqual(critical_rules(self.doc(PARENT_DOC), "  "), [])

    def test_long_title_is_cut(self):
        long = "x" * 300
        rules = critical_rules(self.doc(f"## Critical Rules\n\n### {long}\n"), "Critical Rules")
        self.assertEqual(len(rules[0]["title"]), 160)
        self.assertTrue(rules[0]["title"].endswith("…"))


class ShowAndDiscover(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = make_repo(tmp.name, {"shop": ["shelf"], "shop/till": ["till"], "stock": ["stock"]},
                              files=["src/shop/till.py"])
        (self.root / "modules/shop/MODULE.md").write_text(PARENT_DOC, encoding="utf-8")
        (self.root / "modules/shop/submodules/till/MODULE.md").write_text(CHILD_DOC, encoding="utf-8")
        cfg = self.root / ".segmently-modules/config.toml"
        cfg.write_text('[[code_map]]\nid = "shop"\nglobs = ["src/shop/**"]\nmodule = "shop"\n',
                       encoding="utf-8")
        self.R = ("--root", str(self.root))

    def test_show_child_lists_parent_rules_then_its_own(self):
        _, env, _ = run_json("show", "shop/till", *self.R)
        rules = env["data"]["rules"]
        self.assertEqual([(r["doc"], r["line"]) for r in rules],
                         [("modules/shop/MODULE.md", 9), ("modules/shop/MODULE.md", 17),
                          ("modules/shop/submodules/till/MODULE.md", 5),
                          ("modules/shop/submodules/till/MODULE.md", 7)])

    def test_show_module_without_section_and_text_lines(self):
        _, env, _ = run_json("show", "stock", *self.R)
        self.assertEqual(env["data"]["rules"], [])
        code, out, _ = run("show", "shop", *self.R)
        self.assertEqual(code, 0)
        self.assertIn("  rule  modules/shop/MODULE.md:9  1. Writes to nested fields use dot-notation", out)

    def test_configured_heading(self):
        (self.root / ".segmently-modules/config.toml").write_text(
            '[lint]\ncritical_rules_heading = "Other"\n', encoding="utf-8")
        _, env, _ = run_json("show", "shop", *self.R)
        self.assertEqual([r["title"] for r in env["data"]["rules"]], ["Not a rule either"])

    def test_discover_rows_carry_rules(self):
        code, env, _ = run_json("discover", "--task", "the till and the stock", "--match", "lexical",
                                "--files", "src/shop/till.py", *self.R)
        self.assertEqual(code, 0)
        rows = {m["module"]: m for m in env["data"]["modules"]}
        self.assertEqual(rows["shop"]["usage"], "modify")
        self.assertEqual(rows["shop"]["rules"][0]["line"], 9)
        self.assertEqual(rows["stock"]["rules"], [])  # a reference row has the key too
        code, out, _ = run("discover", "--files", "src/shop/till.py", *self.R)
        self.assertIn("rule   modules/shop/MODULE.md:17  2. Prices are integers in cents", out)


class TextsSayIt(unittest.TestCase):
    def test_template_and_skills(self):
        tpl = (ENGINE / "segmently_modules/defaults/templates/MODULE.md").read_text(encoding="utf-8")
        self.assertIn("## Critical Rules", tpl)
        fill = (SKILLS / "module-create/references/fill.md").read_text(encoding="utf-8")
        self.assertIn("under `## Critical Rules`", fill)
        place = (SKILLS / "module-sync/references/placement.md").read_text(encoding="utf-8")
        self.assertIn("each its own `###` under the critical-rules heading", place)
        disc = " ".join((SKILLS / "module-discover/SKILL.md").read_text(encoding="utf-8").split())
        self.assertIn("Every `rules` title `discover` or `show` returns", disc)
        cfg = (ENGINE / "segmently_modules/defaults/config.toml").read_text(encoding="utf-8")
        self.assertIn('critical_rules_heading = "Critical Rules"', cfg)


if __name__ == "__main__":
    unittest.main()
