"""`show` returns `rules`: the rules of a module doc's critical-rules section (`[lint]
critical_rules_heading`, "Critical Rules" by default) with the doc and line, a child's parent's
first; `discover` counts them; `rules` gives them whole for the modules named and the modules the
files map to, a child's parent added; lint MS018 flags a context_files with no universal doc. The
`MODULE.md` template carries the section, and the create / sync / discover skill texts say how it
is written and read."""
from __future__ import annotations

import json
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
        self.assertEqual([(r["line"], r["title"]) for r in rules], [
            (9, "1. Writes to nested fields use dot-notation"), (17, "2. Prices are integers in cents")])
        self.assertTrue(rules[0]["text"].startswith(  # the whole rule: its words, then its body
            "1. Writes to nested fields use dot-notation\n\n**Why**: merge keeps stale keys."))
        self.assertIn("### not a heading (code)", rules[0]["text"])  # code inside a rule is its text
        self.assertEqual(rules[1]["text"], "2. Prices are integers in cents")

    def test_top_level_items_when_the_section_has_no_heading(self):
        rules = critical_rules(self.doc(CHILD_DOC), "critical rules")
        self.assertEqual([r["title"] for r in rules],
                         ["Never open the drawer without a receipt.", "Close the shift before midnight."])
        self.assertEqual([r["line"] for r in rules], [5, 7])
        self.assertEqual([r["text"] for r in rules], [
            "**Never** open the drawer without a receipt.\n  - an indented detail, not a rule",
            "Close the shift before midnight."])

    def test_no_section_missing_file_blank_heading(self):
        self.assertEqual(critical_rules(self.doc("# x\n\n## Usage\n- a\n"), "Critical Rules"), [])
        self.assertEqual(critical_rules(Path("/nonexistent/MODULE.md"), "Critical Rules"), [])
        self.assertEqual(critical_rules(self.doc(PARENT_DOC), "  "), [])

    def test_long_title_is_cut(self):
        long = "x" * 300
        rules = critical_rules(self.doc(f"## Critical Rules\n\n### {long}\n"), "Critical Rules")
        self.assertEqual(len(rules[0]["title"]), 160)
        self.assertTrue(rules[0]["title"].endswith("…"))
        self.assertEqual(rules[0]["text"], long)  # the text is never cut


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

    def test_text_budget_keeps_titles(self):
        (self.root / ".segmently-modules/config.toml").write_text("[budgets]\nrules_text_max = 40\n",
                                                                   encoding="utf-8")
        _, env, _ = run_json("show", "shop", *self.R)
        texts = [r["text"] for r in env["data"]["rules"]]
        self.assertEqual(texts, [None, "2. Prices are integers in cents"])  # the first is past 40

    def test_configured_heading(self):
        (self.root / ".segmently-modules/config.toml").write_text(
            '[lint]\ncritical_rules_heading = "Other"\n', encoding="utf-8")
        _, env, _ = run_json("show", "shop", *self.R)
        self.assertEqual([r["title"] for r in env["data"]["rules"]], ["Not a rule either"])

    def test_discover_rows_count_rules(self):
        code, env, _ = run_json("discover", "--task", "the till and the stock", "--match", "lexical",
                                "--files", "src/shop/till.py", *self.R)
        self.assertEqual(code, 0)
        rows = {m["module"]: m for m in env["data"]["modules"]}
        self.assertEqual(rows["shop"]["usage"], "modify")
        self.assertEqual(rows["shop"]["rule_count"], 2)
        self.assertNotIn("rules", rows["shop"])  # the rules themselves: `show`, `rules`
        self.assertEqual(rows["stock"]["rule_count"], 0)  # a reference row has the key too
        code, out, _ = run("discover", "--files", "src/shop/till.py", *self.R)
        self.assertIn("rules  2 critical rule(s): segmently-modules rules shop", out)
        self.assertNotIn("rules  0", run("discover", "--task", "stock", *self.R)[1])


class RulesVerb(unittest.TestCase):
    setUp = ShowAndDiscover.setUp

    def test_files_map_to_modules_and_a_child_brings_its_parent(self):
        (self.root / ".segmently-modules/config.toml").write_text(
            '[[code_map]]\nid = "till"\nglobs = ["src/shop/**"]\nmodule = "shop/till"\n', encoding="utf-8")
        (self.root / "README.md").write_text("# repo\n", encoding="utf-8")
        code, env, err = run_json("rules", "--files", "src/shop/till.py", "README.md", "src/gone.py",
                                  *self.R)
        self.assertEqual((code, err), (0, ""))
        d = env["data"]
        self.assertEqual([(m["module"], m["via"]) for m in d["modules"]],
                         [("shop", ["parent"]), ("shop/till", ["files"])])
        self.assertEqual(d["modules"][1]["files"], ["src/shop/till.py"])
        self.assertEqual([r["line"] for r in d["modules"][0]["rules"]], [9, 17])
        self.assertEqual(d["modules"][1]["rules"][0]["text"],
                         "**Never** open the drawer without a receipt.\n  - an indented detail, not a rule")
        self.assertEqual(d["files_outside_modules"], ["README.md", "src/gone.py"])
        self.assertEqual(d["missing_files"], ["src/gone.py"])

    def test_named_modules_no_budget_and_text(self):
        (self.root / ".segmently-modules/config.toml").write_text("[budgets]\nrules_text_max = 1\n",
                                                                   encoding="utf-8")
        _, env, _ = run_json("rules", "stock", "shop", *self.R)
        mods = {m["module"]: m for m in env["data"]["modules"]}
        self.assertEqual((mods["stock"]["rules"], mods["shop"]["via"]), ([], ["named"]))
        self.assertTrue(all(r["text"] for r in mods["shop"]["rules"]))  # no budget in `rules`
        code, out, _ = run("rules", "shop", "stock", *self.R)
        self.assertEqual(code, 0)
        self.assertIn("## shop — modules/shop/MODULE.md  (named)\n"
                      "- modules/shop/MODULE.md:9  1. Writes to nested fields use dot-notation\n"
                      "    **Why**: merge keeps stale keys.\n", out)
        self.assertIn("   no rules: the doc has no 'Critical Rules' section", out)
        self.assertTrue(out.rstrip().endswith("2 rule(s) in 2 module(s)"))

    def test_refusals(self):
        for argv, needle in ((("rules",), "give the modules"), (("rules", "nope"), "unknown module 'nope'"),
                             (("rules", "shop/drawer"), "'drawer' is not a submodule of 'shop'")):
            with self.subTest(argv=argv):
                code, _, err = run(*argv, *self.R)
                self.assertEqual(code, 2)
                self.assertIn(needle, err)


class UniversalLint(unittest.TestCase):
    def test_ms018_a_doc_key_in_place_of_universal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp, {"shop": ["shelf"], "shop/till": ["till"]})
            reg = root / "modules/registry.json"
            data = json.loads(reg.read_text(encoding="utf-8"))
            cf = data["modules"]["shop"]["context_files"]
            cf["module_md"] = cf.pop("universal")
            data["modules"]["shop"]["submodules"]["till"]["context_files"].pop("universal")
            reg.write_text(json.dumps(data, indent=2), encoding="utf-8")
            _, env, _ = run_json("lint", "--fail-on", "never", "--root", str(root))
            got = [(f["module"], f["severity"], f["message"]) for f in env["data"]["findings"]
                   if f["code"] == "MS018"]
            self.assertEqual([g[:2] for g in got], [("shop", "warning"), ("shop/till", "warning")])
            self.assertIn("context_files has no 'universal' (other doc keys: module_md)", got[0][2])
            self.assertIn("(other doc keys: none)", got[1][2])


class TextsSayIt(unittest.TestCase):
    def test_template_and_skills(self):
        tpl = (ENGINE / "segmently_modules/defaults/templates/MODULE.md").read_text(encoding="utf-8")
        self.assertIn("## Critical Rules", tpl)
        fill = (SKILLS / "module-create/references/fill.md").read_text(encoding="utf-8")
        self.assertIn("under `## Critical Rules`", fill)
        self.assertIn("one list item per rule with the `doc:line` of its detail", " ".join(fill.split()))
        place = (SKILLS / "module-sync/references/placement.md").read_text(encoding="utf-8")
        self.assertIn("each its own `###` under the critical-rules heading", place)
        self.assertIn("the module's must-know index (`references/rules-index.md`)", place)
        index = " ".join((SKILLS / "module-sync/references/rules-index.md").read_text(encoding="utf-8").split())
        for needle in ("for every role", "Never remove a rule", "a new section: list items",
                       "report both places, never pick one silently"):
            self.assertIn(needle, index)
        sync = (SKILLS / "module-sync/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("`references/rules-index.md`", sync)
        check = " ".join((SKILLS / "module-check/SKILL.md").read_text(encoding="utf-8").split())
        for needle in ("segmently-modules rules <module>… --files <path>…", "`--from-diff <base>..HEAD`",
                       "`Conflicts:`", "at most five", "`Not checked:`", "a fresh agent with no tools"):
            self.assertIn(needle, check)
        prompt = (SKILLS / "module-check/references/prompt.md").read_text(encoding="utf-8")
        self.assertIn("no quote, no conflict", " ".join(prompt.split()))
        disc = " ".join((SKILLS / "module-discover/SKILL.md").read_text(encoding="utf-8").split())
        self.assertIn("`show` returns each kept module's critical rules (`rules`: title, text", disc)
        self.assertIn("`module-check` reads the plan", disc)
        cfg = (ENGINE / "segmently_modules/defaults/config.toml").read_text(encoding="utf-8")
        self.assertIn('critical_rules_heading = "Critical Rules"', cfg)


if __name__ == "__main__":
    unittest.main()
