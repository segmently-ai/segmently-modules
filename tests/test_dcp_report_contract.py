"""module-discover's report contract (DCP-AC-011…017): every `Code:` line starts with a tag —
`edit` (an existing file the change edits, with what changes there in one clause) or `read`
(called or consulted as it is, a consumer, a pattern, an alternative); an existing test is an
`edit` line only when it asserts the changed behaviour, else a module with an `edit` line gets
`Tests: add new — …`; `Likely consequence:` lines under the risks; the search line first under
the title, in the form `references/choose.md` gives; the JSON is `1.1` and each `files[].reason`
starts with the tag. Everything else in `references/report.md` stays byte for byte what it was:
the base file is frozen below and the new one must be the base with exactly these edits.
Formalization eval 2026-10-15: the owner adopted the lite text — the procedure is the model's, the
contract is pinned: step 6 records existing code in the tagged form under the rules of
`references/report.md` (the tags, the tests line and the consequences are defined there, pinned
below), never lists the files the work will create and searches no code for a `reference`
module. Owner rulings 2026-10-16: step 2 gives one score, so the template writes `(score <0–10>)`
(the module heading and the rejected line) and the JSON's `confidence` is `high` when the score
is ≥ 7. Owner ruling 2026-10-18 (c05 pilots: the reader grepped docs and rules by keyword): the
`searched (<terms>)` form of 2026-10-16 is gone — every doc step 5 lists is read to the end with
the file-read tool, never a search in it, a line range or a cut."""
from __future__ import annotations

import difflib
import json
import re
import unittest
from pathlib import Path

from segmently_modules.config import builtin_packs_root
from tests.test_p81_skill_text import between, section, text

ENGINE = Path(__file__).resolve().parents[1]
DISCOVER = builtin_packs_root() / "core/skills/module-discover"
REPORT = DISCOVER / "references/report.md"
CHOOSE = DISCOVER / "references/choose.md"
FROM_DIFF = DISCOVER / "references/from-diff.md"

# `references/report.md` before the tags, byte for byte (DCP-AC-016)
BASE_REPORT = (
    "# The report (step 8) and the JSON (step 9)\n"
    "\n"
    "## Report\n"
    "\n"
    "Shown in the conversation, in this shape. Modules in usage order — `modify`, `consume`,\n"
    "`reference` — and by score within each.\n"
    "\n"
    "```markdown\n"
    "## Discovery: <task, one line>\n"
    "\n"
    "### <module>[/<child>] — usage: modify | consume | reference (score <average>)\n"
    "Why: <what the task needs from it; \"named by the user\" when it was>\n"
    "Docs:\n"
    "- `<path>` (<role>): <a rule, constraint, contract or pitfall that bears on the task>\n"
    "- `<path>` (<role>): read, nothing for this task\n"
    "Docs to update: `<path>`, …\n"
    "Code:\n"
    "- `<file>:<line>` — `<symbol>` — <why: what the task touches there>\n"
    "Risks / unknowns: <open questions, a doc the code contradicts, an assumption the plan must check>\n"
    "\n"
    "### Rejected\n"
    "- <module> — <reason> (score <average>, or \"off-topic by its description\")\n"
    "\n"
    "### Files outside every module\n"
    "- `<file>` — needs `module-create` or a `[[code_map]]` rule\n"
    "\n"
    "### Missing files\n"
    "- `<file>`\n"
    "```\n"
    "\n"
    "- Every doc step 5 read is on a `Docs:` line: an extract, or \"read, nothing for this task\". An\n"
    "  extract is short — a quote or a close paraphrase — and says what it means for this task.\n"
    "- A `reference` module has its main doc's lines and no `Code:` line.\n"
    "- `Code:` holds existing code only. A file the work will create is never listed: where new code\n"
    "  goes is the plan's decision.\n"
    "- An empty section says \"none\"; it is never left out.\n"
    "\n"
    "## JSON (`discovery-results.json`)\n"
    "\n"
    "Only when the user asks, at the path the user names — the shape a planning pipeline reads:\n"
    "\n"
    "```json\n"
    "{\n"
    "  \"version\": \"1.0\",\n"
    "  \"task\": \"<the task, verbatim>\",\n"
    "  \"modules\": [\n"
    "    {\n"
    "      \"name\": \"<module>[/<child>]\",\n"
    "      \"score\": 7.5,\n"
    "      \"confidence\": \"high | medium | user_specified\",\n"
    "      \"usage_type\": \"MODIFY | EXTEND | READ-ONLY\",\n"
    "      \"documentation\": {\"module_md\": \"<main doc>\", \"<role>_md\": \"<role doc>\"},\n"
    "      \"files\": [{\"path\": \"<file>\", \"offset\": 42, \"limit\": 30, \"reason\": \"<symbol> — <why>\"}]\n"
    "    }\n"
    "  ],\n"
    "  \"files_outside_modules\": [{\"path\": \"<file>\", \"offset\": 1, \"limit\": 30, \"reason\": \"<why>\"}],\n"
    "  \"summary\": \"<two or three sentences: the modules, the main risks>\"\n"
    "}\n"
    "```\n"
    "\n"
    "`usage_type`: `modify` → `MODIFY` (`EXTEND` when the task adds new code on the module's patterns),\n"
    "`consume` and `reference` → `READ-ONLY`. `confidence`: `user_specified` for a module the user\n"
    "named, else `high` (average ≥ 7) or `medium`. `documentation` holds every doc step 5 read for the\n"
    "module, one key per role (`developer_md`, `qa_md`, …). `files[].offset` is the touch point's line.\n"
)

# the base lines this task replaces, and the lines after which it inserts
TITLE = "## Discovery: <task, one line>"
OLD_CODE = "- `<file>:<line>` — `<symbol>` — <why: what the task touches there>"
RISKS = ("Risks / unknowns: <open questions, a doc the code contradicts, an assumption the plan "
         "must check>")
CODE_RULE_END = "  goes is the plan's decision."
OLD_VERSION = '  "version": "1.0",'
OLD_FILES = ('      "files": [{"path": "<file>", "offset": 42, "limit": 30, '
             '"reason": "<symbol> — <why>"}]')
JSON_END = ("module, one key per role (`developer_md`, `qa_md`, …). `files[].offset` is the touch "
            "point's line.")

# the new lines (R-2): the search line, the two tagged code lines, the tests line, the consequence
SEARCH = ("Search: <lexical | by meaning | hybrid> — <the setting or the user's words> — "
          "lexical <sure | unsure: reason | not run>")
EDIT = "- `edit` — `<file>:<line>` — `<symbol>` — <what changes there, one clause>"
READ = ("- `read` — `<file>:<line>` — `<symbol>` — <why it was read: called as is / alternative "
        "/ pattern to follow>")
TESTS = "Tests: add new — <what to cover>"
CONSEQUENCE = ("Likely consequence: <what the implementation will probably also need> — <the "
               "existing file it would touch, or \"a new file: the plan decides where\">")
RULES = [
    "- Every `Code:` line starts with its tag. `edit`: an existing file the change edits; its why",
    "  says what changes there, in one clause, never \"relevant\" or \"related\". `read`: a file called",
    "  or consulted as it is, a consumer, a pattern to follow, or an alternative — a file offered",
    "  with \"or\", \"either\" or \"could also\" is never `edit`, and its why says \"alternative\". Only",
    "  the `edit` lines are the files to change; the `read` lines are evidence.",
    "- `Tests:` one line per module with an `edit` line. An existing test file is `edit` only when",
    "  its assertion names the symbol or value the task changes, and this line then reads",
    "  `Tests: edit the lines above`; otherwise `Tests: add new — <what to cover>`, with no path.",
    "- `Likely consequence:` lines, none or more, under `Risks / unknowns`: what the implementation",
    "  will probably also need (an environment variable to read, an export to add, an import path a",
    "  test runner resolves) and the existing file it would touch, or \"a new file: the plan decides",
    "  where\". A consequence never enters `Code:` and never names a new path.",
    "- `Search:` is the first line under the title, in the form `references/choose.md` gives.",
    # 2026-10-19 (owner): discover writes nothing; after the report it asks to index the docs without one
    "- The closing question only when an `index:` line says `not indexed` (`references/rules.md`):",
    "  every such doc, once; on a yes run `rules_build`'s `build`, never without it.",
]
MISSING_FILE = "- `<file>`"
QUESTION = ("Index the rules of <doc>, … now? A writer per doc, in the background, edits only their "
            "critical-rules sections; the next reader gets the index instead of reading them again.")
NEW_VERSION = '  "version": "1.1",'
NEW_FILES = [
    '      "files": [{"path": "<file>", "offset": 42, "limit": 30, '
    '"reason": "edit — <symbol> — <what changes there>"},',
    '                {"path": "<file>", "offset": 7, "limit": 30, '
    '"reason": "read — <symbol> — <why it was read>"}]',
]
JSON_REASON = "`files[].reason` starts with the tag of its `Code:` line: `edit — ` or `read — `."

# owner rulings 2026-10-16: one score (step 2), and a doc only searched says so
OLD_HEADING = "### <module>[/<child>] — usage: modify | consume | reference (score <average>)"
NEW_HEADING = "### <module>[/<child>] — usage: modify | consume | reference (score <0–10>)"
OLD_REJECTED = "- <module> — <reason> (score <average>, or \"off-topic by its description\")"
NEW_REJECTED = "- <module> — <reason> (score <0–10>, or \"off-topic by its description\")"
OLD_CONFIDENCE = ("named, else `high` (average ≥ 7) or `medium`. `documentation` holds every doc "
                  "step 5 read for the")
NEW_CONFIDENCE = ("named, else `high` when the score is ≥ 7, otherwise `medium`. `documentation` "
                  "holds every doc step 5 read for the")
OLD_DOCS_RULE = "- Every doc step 5 read is on a `Docs:` line: an extract, or \"read, nothing for this task\". An"
NEW_DOCS_RULE = ["- Every doc step 5 lists is read to the end — the whole file with your file-read tool, never a",
                 "  search in it, a line range or a cut — and is on a `Docs:` line: an extract, or \"read, nothing",
                 "  for this task\". An"]  # owner ruling 2026-10-18: no `searched` form
NOTHING = "- `<path>` (<role>): read, nothing for this task"
DOCS_RULE_END = ("  extract is short — a quote or a close paraphrase — and says what it means for "
                 "this task.")
# reference benchmark 2026-10-17 (owner: both levers): a rule is quoted in the doc's own words, never softened
NEW_EXTRACT = ["  extract is short and says what it means for this task. A rule — a never / must / do not / always",
               "  statement, a ❌ line — is quoted in the doc's own words with its `doc:line`, never softened into an",
               "  option or a question."]
# the rules index in discover (2026-10-18): a modify module's `Rules:` block after `Why:`, and its rule
WHY = "Why: <what the task needs from it; \"named by the user\" when it was>"
RULES_BLOCK = ["Rules:", "- `<doc>:<line>` (<role>) — <the rule's first line, verbatim>",
               "- index: <complete (<date>) | building in the background — <doc>, … | not indexed — <doc>, … | incomplete — <doc>, …>"]
RULES_BULLET = ["- `Rules:` only for a `modify` module (`references/rules.md`): each rule",
                "  `rules <module>` gives (`references/rules.md`), verbatim, in its order, then the `index:` line.",
                "  A `consume` or `reference` module: no `Rules:` lines."]
REPLACED = {OLD_CODE: [EDIT, READ, TESTS], OLD_VERSION: [NEW_VERSION], OLD_FILES: NEW_FILES,
            OLD_HEADING: [NEW_HEADING], OLD_REJECTED: [NEW_REJECTED],
            OLD_CONFIDENCE: [NEW_CONFIDENCE], OLD_DOCS_RULE: RULES_BULLET + NEW_DOCS_RULE,
            DOCS_RULE_END: NEW_EXTRACT}

# step 6 (R-3), in order, as the lite text says it: the form, under report.md's rules (RULES above);
# task 3's compact-list sentence stays (test_dcp_code_lists)
STEP6 = [
    "Record existing code only, as `<edit | read> — file:line — symbol — why` under the rules of "
    "`references/report.md`;",
    "the files the work will create are the plan's decision and are never listed.",
    "No code search for a `reference` module.",
]
STEP8 = ("8. **Report** in the conversation, in the shape of `references/report.md` (the search "
         "line first, every section there, the rejected candidates included, every `Code:` line "
         "tagged `edit` or `read`).")
FROM_DIFF_LINE = ("the changed files are its `Code:` lines, each `edit` (`edit — file:line — symbol "
                  "— why` where a hunk shows it), a file the branch added too; no search line, no "
                  "`Tests:` line, no `Likely consequence:` line, no scores, no rejected list "
                  "(nothing was chosen).")  # task-2 review M-3
STEP7 = ("segmently-modules discover --files <edit files> --task-file <file> --match lexical "
         "--modify <modify> --consume <consume> --json")  # task-2 review M-4: the owners and docs to update of the
# files the change edits; 2026-10-18: + the step 4 marks, which choose the docs the engine indexes under "discover"
TAGGED = re.compile(r"^- `(edit|read)` — `<file>:<line>` — `<symbol>` — <[^<>]+>$")
MODES = ("lexical", "by meaning", "hybrid", "<lexical | by meaning | hybrid>")


def flat(s: str) -> str:
    return " ".join(s.split())


def report() -> str:
    return REPORT.read_bytes().decode("utf-8")


def template() -> list[str]:
    """The lines of the report's markdown block."""
    block = re.search(r"```markdown\n(.*?)\n```", report(), re.S)
    return block.group(1).split("\n")


def json_block(source: str) -> dict:
    return json.loads(re.search(r"```json\n(.*?)\n```", source, re.S).group(1))


def expected_report() -> str:
    """The base with exactly this task's edits: nothing else may differ."""
    out = []
    for line in BASE_REPORT.split("\n"):
        if line in REPLACED:
            out += REPLACED[line]
            continue
        out.append(line)
        if line == TITLE:
            out += ["", SEARCH]
        elif line == WHY:
            out += RULES_BLOCK
        elif line == RISKS:
            out.append(CONSEQUENCE)
        elif line == CODE_RULE_END:
            out += RULES
        elif line == JSON_END:
            out.append(JSON_REASON)
        elif line == MISSING_FILE:
            out += ["", QUESTION]
    return "\n".join(out)


class RestUnchangedTest(unittest.TestCase):  # DCP-AC-016
    def test_the_anchors_are_base_lines_once(self):
        lines = BASE_REPORT.split("\n")
        for anchor in (TITLE, OLD_CODE, RISKS, CODE_RULE_END, OLD_VERSION, OLD_FILES, JSON_END,
                       *REPLACED, NOTHING, DOCS_RULE_END):
            with self.subTest(anchor=anchor):
                self.assertEqual(lines.count(anchor), 1)

    def test_the_report_is_the_base_with_these_edits_only(self):
        self.assertEqual(report(), expected_report())

    def test_only_the_listed_lines_change(self):
        base, new = BASE_REPORT.split("\n"), report().split("\n")
        removed, added = [], []
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, base, new,
                                                          autojunk=False).get_opcodes():
            if op != "equal":
                removed += base[i1:i2]
                added += new[j1:j2]
        self.assertEqual(removed, [OLD_HEADING, OLD_CODE, OLD_REJECTED, OLD_DOCS_RULE, DOCS_RULE_END,
                                   OLD_VERSION, OLD_FILES, OLD_CONFIDENCE])  # every other base line kept
        allowed = {"", SEARCH, EDIT, READ, TESTS, CONSEQUENCE, NEW_VERSION, JSON_REASON, QUESTION,
                   *RULES, *NEW_FILES, NEW_HEADING, NEW_REJECTED, NEW_CONFIDENCE,
                   *NEW_DOCS_RULE, *NEW_EXTRACT, *RULES_BLOCK, *RULES_BULLET}
        self.assertEqual([line for line in added if line not in allowed], [])

    def test_the_sections_are_the_base_sections(self):
        heads = [line for line in report().split("\n") if line.startswith("#")]
        base = [line for line in BASE_REPORT.split("\n") if line.startswith("#")]
        self.assertEqual(heads, [NEW_HEADING if line == OLD_HEADING else line for line in base])


class TaggedCodeLineTest(unittest.TestCase):  # DCP-AC-011 (the template and the step-6 wording)
    def test_every_code_line_of_the_template_is_tagged(self):
        lines = template()
        start = lines.index("Code:") + 1
        code = []
        for line in lines[start:]:
            if not line.startswith("- "):
                break
            code.append(line)
        self.assertEqual(code, [EDIT, READ])
        for line in code:
            self.assertRegex(line, TAGGED)
        self.assertNotIn(OLD_CODE, report())

    def test_the_rule_and_step_6_name_the_form(self):
        self.assertIn("Every `Code:` line starts with its tag.", flat(report()))
        step6 = self.step6()
        at = [step6.find(s) for s in STEP6]
        self.assertNotIn(-1, at, [s for s, i in zip(STEP6, at) if i < 0])
        self.assertEqual(at, sorted(at))
        self.assertNotIn("(what the task does there: changes, calls, extends)", step6)

    def test_step_8_and_the_change_only_scenario(self):
        steps = flat(section(text("module-discover"), "## Steps"))
        self.assertEqual(steps.count(STEP8), 1)
        diff = flat(FROM_DIFF.read_text(encoding="utf-8"))
        self.assertEqual(diff.count(FROM_DIFF_LINE), 1)
        self.assertNotIn("`file:line — symbol — why`", diff)

    def test_step_7_takes_the_edit_files(self):  # task-2 review M-4
        steps = section(text("module-discover"), "## Steps")
        step7 = between(steps, "7. **Owners and docs to update.**", "8. **Report**")
        self.assertEqual(step7.count(STEP7), 1)
        self.assertNotIn("<touch-point files>", steps)

    @staticmethod
    def step6() -> str:
        return between(section(text("module-discover"), "## Steps"),
                       "6. **Code touch points.**", "7. **Owners and docs to update.**")


class EditOnlyExistingTest(unittest.TestCase):  # DCP-AC-012, DCP-AC-014 (the wording)
    def test_edit_is_an_existing_file_the_change_edits(self):
        body = flat(report())
        self.assertIn("`edit`: an existing file the change edits;", body)
        self.assertIn("a file offered with \"or\", \"either\" or \"could also\" is never `edit`, "
                      "and its why says \"alternative\".", body)
        self.assertIn("alternative", READ)
        self.assertIn("`Code:` holds existing code only.", body)  # the base rule stays

    def test_one_reason_per_edit_line(self):
        self.assertTrue(EDIT.endswith("<what changes there, one clause>"))
        self.assertIn("its why says what changes there, in one clause, never \"relevant\" or "
                      "\"related\".", flat(report()))


class TestsLineTest(unittest.TestCase):  # DCP-AC-013 (the wording)
    def test_the_tests_line_follows_the_code_lines(self):
        lines = template()
        at = lines.index(TESTS)
        self.assertEqual(lines[at - 2:at + 2], [EDIT, READ, TESTS, RISKS])

    def test_an_existing_test_only_when_it_asserts_the_change(self):
        body = flat(report())
        self.assertIn("An existing test file is `edit` only when its assertion names the symbol or "
                      "value the task changes, and this line then reads `Tests: edit the lines "
                      "above`; otherwise `Tests: add new — <what to cover>`, with no path.", body)
        self.assertIn("`Tests:` one line per module with an `edit` line.", body)


class ConsequenceTest(unittest.TestCase):  # DCP-AC-015 (the wording)
    def test_the_consequence_line_under_the_risks(self):
        lines = template()
        self.assertEqual(lines[lines.index(RISKS) + 1], CONSEQUENCE)
        self.assertEqual(lines[lines.index(RISKS) + 2], "")

    def test_it_never_enters_code(self):
        body = flat(report())
        self.assertIn("A consequence never enters `Code:` and never names a new path.", body)
        self.assertIn("`Likely consequence:` lines, none or more, under `Risks / unknowns`", body)
        self.assertIn("A file the work will create is never listed", body)  # the base rule stays


class SearchLineTest(unittest.TestCase):  # R-1: the report's line is choose.md's form
    def test_the_first_line_under_the_title(self):
        lines = template()
        self.assertEqual(lines[:3], [TITLE, "", SEARCH])

    def test_the_same_form_as_choose_md(self):
        choose = flat(CHOOSE.read_bytes().decode("utf-8"))
        form = re.search(r"chosen: `(Search: [^`]+)`", choose).group(1)
        self.assertEqual(form, SEARCH)

    def test_every_search_line_has_three_parts(self):  # task-1 review M4
        sources = {"report.md": next(ln for ln in template() if ln.startswith("Search: ")),
                   "choose.md": CHOOSE.read_text(encoding="utf-8"),
                   "docs/skills.md": (ENGINE / "docs/skills.md").read_text(encoding="utf-8")}
        for name, source in sources.items():
            lines = re.findall(r"`(Search: [^`]+)`", flat(source)) or [source]
            for line in lines:
                with self.subTest(source=name, line=line):
                    parts = line[len("Search: "):].split(" — ")
                    self.assertEqual(len(parts), 3)
                    self.assertIn(parts[0], MODES)
                    self.assertTrue(parts[2].startswith("lexical "))


class JsonTest(unittest.TestCase):  # DCP-AC-017
    def test_version_and_tagged_reasons(self):
        doc = json_block(report())
        self.assertEqual(doc["version"], "1.1")
        reasons = [f["reason"] for m in doc["modules"] for f in m["files"]]
        self.assertEqual([r.split(" — ", 1)[0] for r in reasons], ["edit", "read"])
        for r in reasons:
            self.assertTrue(r.startswith(("edit — ", "read — ")), r)
        self.assertIn(JSON_REASON, report())

    def test_every_other_key_is_unchanged(self):
        base, new = json_block(BASE_REPORT), json_block(report())

        def keys(node, path=""):
            if isinstance(node, dict):
                return [k for key, value in node.items()
                        for k in [f"{path}.{key}", *keys(value, f"{path}.{key}")]]
            if isinstance(node, list):
                return [k for item in node for k in keys(item, f"{path}[]")]
            return []
        self.assertEqual(sorted(set(keys(new))), sorted(set(keys(base))))
        self.assertEqual(keys(new["modules"][0]["files"][0]), keys(base["modules"][0]["files"][0]))
        for key in ("task", "files_outside_modules", "summary"):
            self.assertEqual(new[key], base[key])
        module, old = new["modules"][0], base["modules"][0]
        self.assertEqual({k: v for k, v in module.items() if k != "files"},
                         {k: v for k, v in old.items() if k != "files"})
        self.assertEqual(new["modules"][0]["files"][0]["path"], old["files"][0]["path"])


class ReadWholeTest(unittest.TestCase):  # owner ruling 2026-10-18: no `searched` form, docs read whole
    def test_the_template_has_no_searched_form(self):
        lines = template()
        self.assertEqual(lines[lines.index(NOTHING) + 1], "Docs to update: `<path>`, …")
        self.assertNotIn("searched", report())

    def test_every_doc_is_read_to_the_end(self):
        body = flat(report())
        self.assertEqual(body.count(flat("\n".join(NEW_DOCS_RULE))), 1)
        rules = flat((DISCOVER / "references/rules.md").read_text("utf-8"))  # the rules too, of any module
        self.assertIn("This holds for every rule you read, of any module and at any step", rules)


class OneScoreTest(unittest.TestCase):  # owner ruling 2026-10-16: step 2 gives one score
    def test_the_heading_and_the_rejected_line(self):
        lines = template()
        self.assertIn(NEW_HEADING, lines)
        self.assertIn(NEW_REJECTED, lines)
        self.assertNotIn("average", report())

    def test_the_json_confidence(self):
        self.assertIn("`confidence`: `user_specified` for a module the user named, else `high` "
                      "when the score is ≥ 7, otherwise `medium`.", flat(report()))


class DocsTest(unittest.TestCase):  # R-6: the docs show the tagged shape, the changelog says so
    def test_skills_doc(self):
        doc = flat((ENGINE / "docs/skills.md").read_text(encoding="utf-8"))
        row = next(line for line in (ENGINE / "docs/skills.md").read_text(encoding="utf-8")
                   .split("\n") if line.startswith("| `module-discover` |"))
        for phrase in ("the modules (each scored 0–10 by how much the task needs it and kept at "
                       "5 or more; one hop of forward links; usage modify / consume / reference)",
                       # the lite text (formalization eval 2026-10-15)
                       "each tagged `edit` (an existing file the change edits) or `read`",
                       "`<edit | read> — file:line — symbol — why`",
                       "`Tests: add new — …`", "`Likely consequence:`",
                       "`version` `1.1`"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, row)
        self.assertNotIn("(`file:line — symbol — why`, never", row)
        self.assertNotIn("four questions", row)
        self.assertIn("e.g. `Search: lexical — when_unsure, chooser skipped — lexical sure`", doc)
        self.assertNotIn("chooser skipped (when_unsure, lexical sure)", doc)

    def test_changelog(self):
        log = (ENGINE / "CHANGELOG.md").read_text(encoding="utf-8")
        unreleased = flat(log.split("## [Unreleased]", 1)[1].split("\n## [", 1)[0])
        for phrase in ("module-discover's report tags every `Code:` line `edit`",
                       "`Tests: add new — <what to cover>`", "`Likely consequence:`",
                       "`Search: …`", "`discovery-results.json` is `version` `1.1`"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, unreleased)
        self.assertIn("### Changed", unreleased)


if __name__ == "__main__":
    unittest.main()
