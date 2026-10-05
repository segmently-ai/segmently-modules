"""P8.4 Task 4: routing inside the skills with more than one scenario (D1) and their argument
keys (D4, SI-P84-11, SI-P84-12): P84-AC-025, AC-026, AC-027 and AC-030. The routing audit
(AC-024, ruled by the controller) found one such skill: `qa-acceptance-baseline` routes `create`
and `refresh`, with `exit-codes` as its rare-branch file; the nine other audited skills keep
their steps inline, and the three wrapped skills (D3) belong to Task 2."""
import hashlib
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from modsys.config import builtin_packs_root, core_defaults
from modsys.skills import file_hashes, front_matter, read_front_matter, sha256_file
from tests.helpers import copy_fixture, run_json
from tests.plugin_helpers import copy_engine, run_tool
from tests.test_budgets import SPLIT_DECISIONS, decision_key
from tests.test_builtin_skills import (PACK_SKILLS, command_guard, commands, route, route_files,
                                       section, skill_dirs, skill_files, uses)

ENGINE = Path(__file__).resolve().parents[1]
BASELINE_ID = "qa-acceptance-baseline"
BASELINE = builtin_packs_root() / "qa/skills" / BASELINE_ID
# skill -> (its scenarios, its rare-branch files): the audit's one `route` row
# P8.8 (D10): a third scenario, `block`; the shared method files are named by the steps
ROUTED = {BASELINE_ID: (["create", "refresh", "block"], ["exit-codes", "method", "techniques"])}
WRAPPED = {"module-discover", "module-scout", "module-research"}  # D3: Task 2 pins their keys
SINGLE = {  # one scenario: steps and `## Exit codes` inline, no keys, references as before
    "module-adopt": [], "module-init": ["references/phases.md"],
    "module-lint": ["references/lint-codes.md"],
    "module-roles": []}
# P8.7 (X4): the writing skills keep their steps and `## Exit codes` inline, no keys, and point
# into references/ by step — a scenario (a child, an already-split module) or a step's detail
STEP_ROUTED = {
    "module-sync": [("session", ["references/session.md"]),
                    ("placement", ["references/placement.md"]),
                    ("report", ["references/report.md"])],
    "module-create": [("analyse", ["references/analyse.md"]), ("child", ["references/child.md"]),
                      ("fill", ["references/fill.md"])],
    "module-split": [("already-split", ["references/already-split.md"]),
                     ("shapes", ["references/shapes.md"]), ("check", ["references/check.md"])]}
# P8.8 (D8, D9): qa-acceptance points into references/ by step the same way
STEP_ROUTED["qa-acceptance"] = [("method", ["references/method.md"]),
                                 ("techniques", ["references/techniques.md"]),
                                 ("output", ["references/output.md"])]
# P8.9 (D11, D12): designer — one skill, its routes and their shared files named by the steps
STEP_ROUTED["designer"] = [("prototype", ["references/prototype.md"]),
                           ("rework-audit", ["references/rework-audit.md"]),
                           ("review", ["references/review.md"]),
                           ("flow-patterns", ["references/flow-patterns.md"]),
                           ("checklist", ["references/checklist.md"]),
                           ("artifacts", ["references/artifacts.md"])]
STEP_ROUTED_EXTRA = {"module-sync": ["references/choose.md"]}  # named by step 4, not a route
LEAD = ("the scenario named by the invocation (`$scenario`) when one is given, else by the "
        "user's words", "read it, then follow it")
IF_LINE = "If a `modsys` command exits 1 or 2, read `references/exit-codes.md`."
HINT_LINE, ARGUMENTS_LINE = 'argument-hint: "[module] [scenario] [block]"', "arguments: module scenario block"
ROUTE_FILES = sorted(f"references/{n}.md" for n in ["create", "refresh", "block", "exit-codes", "method",
                                                     "techniques"])
STEP_6 = "Write the doc. Follow the scenario's file (the Route above)."  # step 5 until P8.8
SPLIT_SIGNAL = core_defaults()["budgets"]["skill_split_signal"]  # MS068's default, read from the engine
DESCRIPTION_SHA = "2a0efce95123748f"  # sha256[:16] of the description: unchanged
# old sentences rewritten on purpose — P8.4 moved every one; P8.8 (D10) rewrote Gate 1's content,
# the requirement form, the criterion fields and the in-place edit (blocks, not tiers)
REPLACED: list[str] = [
    "**Gate 1 — understanding.** Present: what the module does and why, its main flows, its "
    "functional blocks with a risk each, the rules its docs state, the edge cases you found, and "
    "anything the docs and the code disagree on.",
    "list its requirements, each traced to a doc line or a code file — **Gate 2**: wait for the "
    "user to confirm the list;",
    "write its criteria: **Given** / **When** / **Then** with an observable result;",
    "P0 for critical and high risk, P1 for medium, P2 for low;",
    "use boundary values, decision tables and state transitions where the requirement has "
    "limits, combinations or states — **Gate 3**: wait for the user to confirm the criteria.",
    "It exists: edit it in place, section by section (P0, P1, P2, Retired)."]
# the sentences that are new, per file: the Route, the "if" line, step 5's pointer and each
# route file's lead line (the cross-pointer is an "if" line: read the other route only when
# step 1's state contradicts the words)
ADDED = {
    "SKILL.md": [
        "The entry is also written for a doc that is on disk and that the registry does not "
        "list, and a new doc is never written over it.",  # P8.5 D2 (SI-P85-5)
        "**Route.** Take the scenario named by the invocation (`$scenario`) when one is given, "
        "else by the user's words, and its file below: read it, then follow it — its steps are "
        "step 6.",  # step 5 until P8.8
        "**create** — the module has no acceptance baseline yet (\"write\", \"create\", "
        "\"start\" one) → `references/create.md`",
        "**refresh** — the module changed and its baseline must catch up (\"refresh\", "
        "\"update\" it — new, changed or retired behaviour) → `references/refresh.md`",
        IF_LINE,
        # P8.5 D2 (SI-P85-3, SI-P85-6, fix round I-2): the labels and the dry run's statuses
        "A `child role:qa_acceptance` row with `exists: true` is a split child's own doc: "
        "refresh it the same way.",
        "A `parent baseline role:qa_acceptance` row is the parent's doc, not this module's.",
        # P8.5 final review I-2: the antecedent names the rows; the parent's does not count
        "Without a `role:qa_acceptance` or `child role:qa_acceptance` row with `exists: true` "
        "(a `parent baseline` row does not count), run `modsys roles add qa_acceptance <module> "
        "--dry-run --json`, which writes nothing, and read its status.",
        "Status `registered` means the module's `roles/qa_acceptance.md` is on disk and the "
        "registry does not list it: that file is the doc to refresh, so read it, note the "
        "highest `AC-NNN` in it, take the refresh route and never write a new doc over it.",
        "Status `exists` means the registry lists a doc that is on disk: refresh it, so read it "
        "and note the highest `AC-NNN` in it.",
        "Status `created` means there is no doc: take the create route.",
        "Status `missing` means the registry lists a path with no file: the create route "
        "writes the doc at that path and adds no second registry entry.",
        "Follow the scenario's file (the Route above)."],
    # P8.5 D2 (SI-P85-4): both lead sentences key on "the doc to refresh step 1 names"
    "references/create.md": [
        "Step 6 of `qa-acceptance-baseline` — write the doc — when step 1 found no doc to "
        "refresh: no `role:qa_acceptance` row with `exists: true`, and the dry run said "
        "`created` or `missing` (when it names a doc to refresh, follow `references/refresh.md` "
        "instead).",
        # P8.5 final review M-2: a `missing` doc is written where the registry points
        "When step 1's dry run said `missing`, write the doc at the `path` it reported and skip "
        "`registry set`: the registry lists it already."],
    "references/refresh.md": [
        # P8.5 final review M-3: the lead names the child's own row too
        "Step 6 of `qa-acceptance-baseline` — write the doc — when step 1 names the doc to "
        "refresh (a `role:qa_acceptance` or `child role:qa_acceptance` row with `exists: true`, "
        "or the doc its dry run reported as `registered` or `exists`) and you noted its highest "
        "`AC-NNN` (when step 1 names no doc to refresh, follow `references/create.md` instead).",
        "The doc is not in the registry (step 1's dry run said `registered`): after Gate 3, "
        "run `modsys roles add qa_acceptance <module> --json`.",
        "It adds the registry entry, status `registered`, and never writes the file."],
    "references/exit-codes.md": []}
# the body of `qa-acceptance-baseline/SKILL.md` after its front matter as shipped before the
# Route (cc7f2f8; Task 3 left it unchanged)
OLD_BODY = """
# qa-acceptance-baseline

Write down, for one module, the behaviour that must keep working — as criteria with ids that
never change, so task-level criteria (`qa-acceptance`) and tests can point at them.

## When to use

- A module has no acceptance baseline yet, and the user wants one.
- A module changed and its baseline must catch up (new behaviour, changed behaviour, retired
  behaviour).

## When not to use

- The criteria are for one task, not the whole module: use `qa-acceptance`.
- You only need to know how the module is tested today: use `module-scout` with the `qa` role.
- The module's other docs are out of date: use `module-sync` first — the baseline is built
  from them.

## Scope

Writes: the module's `qa_acceptance` doc, and its entry in the module's registry
`context_files` when the doc is new. It never edits code or another doc, never edits a
`*.legacy.md` file, and never commits.

If `modsys` is not found, tell the user how to install it — the `modsys` plugin for Claude Code, `uv tool install git+ssh://git@github.com/<owner>/<repo>.git`, or `pipx install git+ssh://git@github.com/<owner>/<repo>.git` — and stop until it runs.

## Steps

1. Load the module.

   ```bash
   modsys show <module> --all-roles --json
   modsys show <module> --role qa_acceptance --json
   modsys code-map files <module> --json
   ```

   Exit 2 "unknown role 'qa_acceptance'": the `qa` pack is not enabled — tell the user
   (`[packs] builtin` in the team config) and stop. A `role:qa_acceptance` row with
   `exists: true` is the doc to refresh; read it and note the highest `AC-NNN` in it.

2. Read every doc of the module fully and skim its code files for the interfaces the docs name
   (entry points, commands, messages, limits).

3. **Gate 1 — understanding.** Present: what the module does and why, its main flows, its
   functional blocks with a risk each, the rules its docs state, the edge cases you found, and
   anything the docs and the code disagree on. Wait for "ok" or corrections.

4. For each functional block:

   - list its requirements, each traced to a doc line or a code file — **Gate 2**: wait for
     the user to confirm the list;
   - write its criteria: **Given** / **When** / **Then** with an observable result; P0 for
     critical and high risk, P1 for medium, P2 for low; use boundary values, decision tables
     and state transitions where the requirement has limits, combinations or states —
     **Gate 3**: wait for the user to confirm the criteria.

   For a large module, batch the criteria of several blocks into one Gate 3; never skip Gate 2.

5. Ids, when refreshing: an unchanged criterion keeps its id and text; a changed one keeps its
   id and is edited in place; a new one takes the next id after the highest existing
   `AC-NNN` — continue the numbering, never renumber and never reuse an id; a criterion that
   no longer applies moves to the "Retired" section with its id and the reason.

6. Write the doc.

   - It exists: edit it in place, section by section (P0, P1, P2, Retired).
   - It does not: start from the file of the `roles/qa_acceptance.md` row of
     `modsys templates list --json`, fill it, save it next to the module's other role docs,
     and add it to the module's `context_files`:

     ```bash
     modsys registry set <module> context_files '<the object with roles.qa_acceptance added>' --dry-run
     modsys registry set <module> context_files '<the object with roles.qa_acceptance added>' --json
     ```

     Build the object from `show --all-roles`: `universal` is the universal row, each
     `role:<role>` row is `roles.<role>`; add `roles.qa_acceptance`. Check the dry run's diff
     changes nothing else.

7. Check it.

   ```bash
   modsys lint --json
   modsys show <module> --role qa_acceptance --json
   ```

   No finding for the doc; the `role:qa_acceptance` row exists. Report the criteria added,
   changed and retired per priority, and ask the user to review and commit.

## Gates

Three, never skipped: Gate 1 (understanding), Gate 2 (each block's requirements), Gate 3 (the
criteria, per block or per batch). Nothing is written before Gate 3 of the last block.

## Exit codes

`0` ok · `1` from `lint` = findings: fix the ones the new doc caused · `2` = a usage or config
error, or a refused write: read stderr (an unknown role means the `qa` pack is not enabled).
"""
_PLACEHOLDER = re.compile(r"\$(?:\{|[A-Za-z0-9_]+)")
_FORBIDDEN = re.compile(r"\$(?:ARGUMENTS\b|[0-9]|\{)")


def flat(text: str) -> str:
    return " ".join(text.split())


def body(text: str) -> str:
    """A skill file without its front matter."""
    return text.split("\n---\n", 1)[1] if text.startswith("---\n") else text


def front_lines(text: str) -> list[str]:
    """The raw lines of a `SKILL.md` front matter."""
    return text.split("\n---\n", 1)[0].splitlines()[1:]


def units(text: str) -> list[str]:
    """The normalized sentences of a skill text (P84-AC-026): every line of a fenced block is one;
    headings and fence lines are dropped, list markers and step numbers cut, whitespace
    collapsed; prose is cut at blank lines and list items, then after `.`, `;`, `!` or `?` and a
    space."""
    out, prose, fenced = [], [], False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("```"):
            fenced = not fenced
            prose.append("")
        elif fenced:
            out += [flat(s)] if s else []
        elif s.startswith("#"):
            prose.append("")
        elif re.match(r"(?:\d+\.|-) ", s):  # a list item or step starts a paragraph
            prose += ["", s.split(" ", 1)[1]]
        else:
            prose.append(s)
    for paragraph in re.split(r"\n\s*\n", "\n".join(prose)):
        out += [u for u in re.split(r"(?<=[.;!?])\s+", flat(paragraph)) if u]
    return out


def lost(old: str, new: dict[str, str]) -> list[str]:
    """Each old sentence that is neither in the new `SKILL.md` nor in exactly one of the new
    `references/` files (a sentence a Route line replaces excepted), with where it is."""
    found = {name: " ".join(units(body(text))) for name, text in new.items()}
    out = []
    for unit in units(old):
        if unit in REPLACED or unit in found["SKILL.md"]:
            continue
        where = [name for name, text in found.items() if unit in text]
        if len(where) != 1:
            out.append(f"{unit} — in {', '.join(where) or 'no file'}")
    return out


def declared(text: str) -> list[str]:
    """The names an `arguments:` front-matter key declares (`a`, `"a"`, `[a, b]`)."""
    value = (front_matter(text) or {}).get("arguments", "")
    return [n for n in re.split(r"[\s,\[\]\"']+", value) if n]


def placeholder_problems(files: dict[str, str]) -> list[str]:
    """SI-P84-12 over one skill: each declared name used as `$<name>` in `SKILL.md`, no other
    `$`-placeholder there, none at all in `references/`, never `$ARGUMENTS`, `$0`…`$9` or `${`,
    and an `argument-hint` written as a double-quoted string."""
    skill = files["SKILL.md"]
    names = declared(skill)
    out = [f"SKILL.md: ${n} is declared but never used" for n in names if f"${n}" not in skill]
    out += [f"SKILL.md: {p} is not a declared argument" for p in _PLACEHOLDER.findall(skill)
            if p[1:] not in names]
    for name, text in files.items():
        out += [f"{name}: {p}" for p in _FORBIDDEN.findall(text)]
        if name != "SKILL.md":
            out += [f"{name}: {p} in a reference" for p in _PLACEHOLDER.findall(text)]
    hints = [line for line in front_lines(skill) if line.startswith("argument-hint:")]
    out += [f"SKILL.md: {h} is not a double-quoted string" for h in hints
            if not re.fullmatch(r'argument-hint: "[^"\n]*"', h)]
    return out


class RouteShapeTest(unittest.TestCase):  # P84-AC-025 (the routed row)
    def setUp(self):
        self.text = (BASELINE / "SKILL.md").read_text("utf-8")
        self.files = skill_files(BASELINE)
        self.head = section(self.text, "## Steps").split("\n1. ", 1)[0]

    def test_the_front_matter_adds_the_keys(self):  # P8.8 D10: [module] [scenario] (+ [block])
        lines = front_lines(self.text)
        self.assertEqual(lines[0], f"name: {BASELINE_ID}")
        self.assertEqual(lines[2:], [HINT_LINE, ARGUMENTS_LINE])
        meta = read_front_matter(BASELINE / "SKILL.md")
        self.assertEqual(set(meta), {"name", "description", "argument-hint", "arguments"})
        self.assertEqual((meta["argument-hint"], meta["arguments"]),
                         ("[module] [scenario] [block]", "module scenario block"))
        self.assertEqual(hashlib.sha256(meta["description"].encode()).hexdigest()[:16],
                         DESCRIPTION_SHA)

    def test_the_sections_it_keeps(self):
        for heading in ("## When to use", "## When not to use", "## Scope", "## Steps",
                        "## Gates"):
            self.assertEqual(self.text.count(f"\n{heading}\n"), 1, heading)
        self.assertNotIn("\n## Exit codes\n", self.text)  # behind the "if" line now
        self.assertTrue(section(self.text, "## Scope").strip().startswith("Writes"))
        self.assertIn("Three, never skipped", section(self.text, "## Gates"))

    def test_the_route_lead_in_and_one_line_per_scenario(self):
        self.assertTrue(self.head.strip().startswith("**Route.**"), self.head)
        for phrase in LEAD:
            self.assertIn(phrase, flat(self.head))
        self.assertEqual(self.text.count("$scenario"), 1)
        self.assertEqual(flat(self.head).count("$scenario"), 1)
        scenarios, _ = ROUTED[BASELINE_ID]
        lines = route(self.text)
        self.assertEqual(lines, [(s, [f"references/{s}.md"]) for s in scenarios])
        for word, names in lines:  # the key word is the file's stem: `/<skill> <stem>` picks it
            self.assertEqual([Path(n).stem for n in names], [word])
            self.assertEqual(flat(self.head).count(f"`references/{word}.md`"), 1)

    def test_every_named_file_exists_and_no_other_file_ships(self):
        scenarios, rare = ROUTED[BASELINE_ID]
        wanted = sorted(f"references/{s}.md" for s in scenarios + rare)
        named = sorted({n for text in self.files.values()
                        for n in re.findall(r"`(references/[^`\s]+)`", text)})
        self.assertEqual(named, wanted)
        self.assertEqual(sorted(self.files), ["SKILL.md", *wanted])
        self.assertTrue(all((BASELINE / n).is_file() for n in named))

    def test_the_rare_branch_sits_behind_an_if_line(self):
        self.assertEqual(flat(self.text).count(IF_LINE), 1)
        self.assertIn(IF_LINE, flat(self.head))  # read before any command runs
        exits = flat(self.files["references/exit-codes.md"])
        for needle in ("Exit 2 \"unknown role 'qa_acceptance'\": the `qa` pack is not enabled — "
                       "tell the user (`[packs] builtin` in the team config) and stop.",
                       "`0` ok · `1` from `lint` = findings: fix the ones the new doc caused"):
            self.assertIn(needle, exits)
            self.assertNotIn(needle, flat(self.text))

    def test_the_shared_steps_stay_inline_and_step_6_defers(self):  # step 5 until P8.8
        steps = section(self.text, "## Steps")
        self.assertEqual(re.findall(r"^(\d)\. ", steps, re.M), ["1", "2", "3", "4", "5", "6", "7"])
        self.assertIn(f"6. {STEP_6}", flat(steps))
        for needle in ("1. Load the module.", "**Gate 1 — understanding.**", "**Gate 2**",
                       "**Gate 3**", "**Final confirmation**", "7. Check it.",
                       "ask the user to review and commit"):
            self.assertIn(needle, flat(steps))
        for scenario in ROUTED[BASELINE_ID][0]:
            text = self.files[f"references/{scenario}.md"]
            self.assertTrue(text.startswith(f"# {scenario}: "), text[:40])
            self.assertIn("Step 6 of `qa-acceptance-baseline` — write the doc —", flat(text))

    def test_the_cross_pointers_are_if_lines(self):  # controller ruling Q3
        create, refresh = (flat(self.files[f"references/{s}.md"]) for s in ("create", "refresh"))
        self.assertIn("(when it names a doc to refresh, follow `references/refresh.md` "
                      "instead)", create)
        self.assertIn("(when step 1 names no doc to refresh, follow `references/create.md` "
                      "instead)", refresh)
        self.assertEqual((create.count("references/"), refresh.count("references/")), (1, 1))
        self.assertNotIn("references/", self.files["references/exit-codes.md"])

    def test_every_file_fits(self):
        for name, text in self.files.items():
            with self.subTest(file=name):
                self.assertLessEqual(len(text.splitlines()), 250)
        self.assertEqual(oversize(self.files, SPLIT_SIGNAL), [])


def oversize(files: dict, signal: int) -> list[str]:
    """The baseline skill's files over `signal` that `SPLIT_DECISIONS` does not record (SI-P85-11)."""
    return [name for name, text in files.items()
            if len(text) > signal and decision_key("qa", BASELINE_ID, name) not in SPLIT_DECISIONS]


class SingleScenarioTest(unittest.TestCase):  # P84-AC-025 (the single row), SI-P84-11
    def test_the_audit_covers_every_shipped_skill(self):
        self.assertEqual(sorted(skill_dirs()), sorted([*ROUTED, *WRAPPED, *SINGLE, *STEP_ROUTED]))

    def test_the_writing_skills_route_by_step(self):  # P8.7 X4
        dirs = skill_dirs()
        for sid, routes in STEP_ROUTED.items():
            directory = dirs[sid][1]
            text = (directory / "SKILL.md").read_text("utf-8")
            with self.subTest(skill=sid):
                self.assertEqual(route(text), routes)
                self.assertNotIn("**Route.**", text)
                self.assertTrue(section(text, "## Exit codes").strip())
                files = sorted(["SKILL.md", *(f for _, fs in routes for f in fs),
                                *STEP_ROUTED_EXTRA.get(sid, [])])
                self.assertEqual(sorted(skill_files(directory)), files)
                self.assertEqual(set(read_front_matter(directory / "SKILL.md")),
                                 {"name", "description"})
                for _, (name,) in routes:  # every route file is named again by its step
                    self.assertGreaterEqual(section(text, "## Steps").count(f"`{name}`"), 2, name)

    def test_no_route_exit_codes_inline_references_as_before(self):
        dirs = skill_dirs()
        for sid, refs in SINGLE.items():
            directory = dirs[sid][1]
            text = (directory / "SKILL.md").read_text("utf-8")
            with self.subTest(skill=sid):
                self.assertEqual(route(text), [])
                self.assertNotIn("**Route.**", text)
                self.assertTrue(section(text, "## Exit codes").strip())
                self.assertEqual(sorted(skill_files(directory)), ["SKILL.md", *refs])
                self.assertEqual(set(read_front_matter(directory / "SKILL.md")),
                                 {"name", "description"})


class RoutingLosesNoRuleTest(unittest.TestCase):  # P84-AC-026
    def setUp(self):
        self.files = skill_files(BASELINE)

    def test_every_old_sentence_has_exactly_one_home(self):
        self.assertGreater(len(units(OLD_BODY)), 40)
        self.assertEqual(lost(OLD_BODY, self.files), [])

    def test_the_route_text_stays(self):  # P8.8: the new text is pinned by test_p88_qa_skills
        for name, sentences in ADDED.items():
            have = set(units(body(self.files[name])))
            self.assertEqual([u for u in sentences if u not in have], [], name)

    def test_the_comparison_can_fail(self):
        dropped = dict(self.files)
        dropped["references/refresh.md"] = dropped["references/refresh.md"].replace(
            "never renumber and never reuse an id;", "")
        twice = dict(self.files)
        twice["references/refresh.md"] += "\nCheck the dry run's diff changes nothing else.\n"
        self.assertEqual([p.split(" — in ")[1] for p in lost(OLD_BODY, dropped)], ["no file"])
        self.assertEqual([p.split(" — in ")[1] for p in lost(OLD_BODY, twice)],
                         ["references/create.md, references/refresh.md"])

    def test_phrases_verbs_and_commands(self):
        _, _, verbs, says = PACK_SKILLS[BASELINE_ID]
        text = flat("\n".join(self.files.values()))
        self.assertEqual([p for p in says if p not in text], [])
        steps = "\n".join([section(self.files["SKILL.md"], "## Steps"),
                           *route_files(BASELINE).values()])
        self.assertEqual([v for v in verbs if not uses(commands(steps), v)], [])
        self.assertTrue(uses(commands(steps), ("registry", "set")))  # create's two commands
        self.assertEqual(command_guard(self.files), [])


class ArgumentKeysTest(unittest.TestCase):  # P84-AC-027, SI-P84-12
    def test_routed_skills_declare_scenario_and_use_it_once(self):  # + module, block (P8.8)
        dirs = skill_dirs()
        for sid in ROUTED:
            text = (dirs[sid][1] / "SKILL.md").read_text("utf-8")
            with self.subTest(skill=sid):
                lines = front_lines(text)
                self.assertIn(HINT_LINE, lines)
                self.assertIn(ARGUMENTS_LINE, lines)
                self.assertEqual(declared(text), ["module", "scenario", "block"])
                for name in ("module", "scenario", "block"):
                    self.assertEqual(text.count(f"${name}"), 1, name)
                self.assertEqual(sorted(_PLACEHOLDER.findall(text)),
                                 ["$block", "$module", "$scenario"])

    def test_single_skills_have_neither_key_nor_a_placeholder(self):
        dirs = skill_dirs()
        for sid in SINGLE:
            files = skill_files(dirs[sid][1])
            with self.subTest(skill=sid):
                self.assertFalse([line for line in front_lines(files["SKILL.md"])
                                  if line.startswith(("argument-hint:", "arguments:"))])
                self.assertEqual([p for text in files.values()
                                  for p in _PLACEHOLDER.findall(text)], [])

    def test_every_shipped_skill_passes_the_placeholder_scan(self):
        for sid, (_, directory) in skill_dirs().items():
            with self.subTest(skill=sid):
                self.assertEqual(placeholder_problems(skill_files(directory)), [])

    def test_the_scan_can_fail(self):
        skill = ("---\nname: stock-check\ndescription: Checks the shelves.\n"
                 "argument-hint: [scenario]\narguments: [scenario, depth]\n---\n\n"
                 "Pick by `$scenario`, then `$shelf`, `$ARGUMENTS`, `$0` and `${x}`.\n")
        problems = placeholder_problems({"SKILL.md": skill,
                                         "references/restock.md": "Use `$scenario`.\n"})
        self.assertEqual(problems, [
            "SKILL.md: $depth is declared but never used",
            "SKILL.md: $shelf is not a declared argument",
            "SKILL.md: $ARGUMENTS is not a declared argument",
            "SKILL.md: $0 is not a declared argument", "SKILL.md: ${ is not a declared argument",
            "SKILL.md: $ARGUMENTS", "SKILL.md: $0", "SKILL.md: ${",
            "references/restock.md: $scenario in a reference",
            "SKILL.md: argument-hint: [scenario] is not a double-quoted string"])


class ReferencesCarriedTest(unittest.TestCase):  # P84-AC-030 (+ AC-002's ruled row)
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        self.R = ("--root", str(self.root))
        (self.root / ".modsys/config.toml").write_text('[packs]\nbuiltin = ["qa"]\n')
        self.routes = sorted(p.relative_to(BASELINE).as_posix()
                             for p in (BASELINE / "references").glob("*.md"))

    def tearDown(self):
        self._tmp.cleanup()

    def ok(self, *argv, code=0) -> dict:
        got, env, err = run_json(*argv, *self.R)
        self.assertEqual((got, err), (code, ""), env)
        return env["data"]

    def sync(self, code=0) -> dict:
        data = self.ok("packs", "sync", "--agent", "claude", "--agent", "codex", code=code)
        return {(r["agent"], r["skill"]): r for r in data["skills"]}

    def copies(self) -> list[Path]:
        return [self.root / d / BASELINE_ID for d in (".claude/skills", ".agents/skills")]

    def test_packs_sync_carries_every_route_to_both_agents(self):
        self.assertEqual(self.routes, ROUTE_FILES)
        rows = self.sync()
        for agent in ("claude", "codex"):
            self.assertEqual(rows[(agent, BASELINE_ID)]["status"], "created")
            self.assertEqual(rows[(agent, BASELINE_ID)]["files"], ["SKILL.md", *self.routes])
        for dest in self.copies():
            marker = json.loads((dest / ".modsys-managed").read_text())
            for rel in ["SKILL.md", *self.routes]:
                with self.subTest(copy=dest.parent.name, file=rel):
                    self.assertEqual((dest / rel).read_bytes(), (BASELINE / rel).read_bytes())
                    self.assertEqual(marker["files"][rel], sha256_file(BASELINE / rel))
        data = self.ok("packs", "sync", "--check", "--agent", "claude", "--agent", "codex")
        self.assertEqual({r["status"] for r in data["skills"]}, {"unchanged"})

    def test_the_codex_copy_keeps_the_keys_and_the_placeholder(self):  # AC-002, ruled row
        self.sync()
        text = (self.root / ".agents/skills" / BASELINE_ID / "SKILL.md").read_text("utf-8")
        self.assertEqual(text, (BASELINE / "SKILL.md").read_text("utf-8"))
        self.assertIn(ARGUMENTS_LINE, front_lines(text))
        self.assertIn("$scenario", text)

    def test_eject_and_eject_diff_carry_the_routes(self):
        self.ok("eject", BASELINE_ID)
        ejected = self.root / ".modsys/overrides/skills" / BASELINE_ID
        for rel in self.routes:
            self.assertEqual((ejected / rel).read_bytes(), (BASELINE / rel).read_bytes())
        data = self.ok("eject", BASELINE_ID, "--diff")
        self.assertEqual([f for f in data["files"] if f["path"].startswith("references/")],
                         [{"path": rel, "status": "same"} for rel in self.routes])
        (ejected / "references/refresh.md").write_text("# refresh: ours\n", encoding="utf-8")
        data = self.ok("eject", BASELINE_ID, "--diff")
        self.assertIn({"path": "references/refresh.md", "status": "changed"}, data["files"])
        self.assertIn("--- upstream/references/refresh.md\n+++ ejected/references/refresh.md\n",
                      data["diff"])

    def test_a_route_the_pack_drops_is_deleted_from_the_copies(self):
        tree = Path(self._tmp.name) / "builtins"
        shutil.copytree(builtin_packs_root(), tree)
        with mock.patch("modsys.config.builtin_packs_root", side_effect=lambda: tree):
            self.sync()
            (tree / "qa/skills" / BASELINE_ID / "references/refresh.md").unlink()
            rows = self.sync()
        for agent, dest in zip(("claude", "codex"), self.copies()):
            with self.subTest(agent=agent):
                self.assertEqual((rows[(agent, BASELINE_ID)]["status"],
                                  rows[(agent, BASELINE_ID)]["files"]),
                                 ("updated", ["references/refresh.md"]))
                self.assertFalse((dest / "references/refresh.md").exists())
                self.assertTrue((dest / "references/create.md").is_file())
                marker = json.loads((dest / ".modsys-managed").read_text())
                self.assertNotIn("references/refresh.md", marker["files"])

    def test_an_edited_route_in_a_copy_is_a_conflict(self):
        self.sync()
        edited = self.root / ".claude/skills" / BASELINE_ID / "references/create.md"
        edited.write_text("# create: edited by hand\n", encoding="utf-8")
        rows = self.sync(code=1)
        self.assertEqual(rows[("claude", BASELINE_ID)]["status"], "conflict")
        self.assertIn("references/create.md (locally edited)",
                      rows[("claude", BASELINE_ID)]["reason"])
        self.assertEqual(rows[("codex", BASELINE_ID)]["status"], "unchanged")
        self.assertEqual(edited.read_text(), "# create: edited by hand\n")


class PluginCarriesRoutesTest(unittest.TestCase):  # P84-AC-030 (the builder)
    def test_the_qa_plugin_ships_every_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            engine = copy_engine(base / "engine")
            proc = run_tool(engine, "build_plugins", "--out", str(base / "out"))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            built = base / "out/modsys-qa/skills" / BASELINE_ID
            self.assertEqual(file_hashes(built), file_hashes(BASELINE))
            self.assertEqual(sorted(p.relative_to(built).as_posix()
                                    for p in (built / "references").iterdir()),
                             ROUTE_FILES)


class RoutingDocsTest(unittest.TestCase):  # P84-AC-025 (the docs name the routed skill)
    def test_docs_skills_explains_the_route(self):
        text = flat((ENGINE / "docs/skills.md").read_text("utf-8"))
        part = text.split("## Skills with more than one scenario", 1)[1].split(" ## ", 1)[0]
        for needle in ("a **Route** at the head of its steps",
                       "`/qa-acceptance-baseline <module> refresh`",
                       '`argument-hint: "[module] [scenario] [block]"` and '
                       '`arguments: module scenario block`',
                       "`qa-acceptance-baseline` routes `create`, `refresh` and `block`",
                       "`references/exit-codes.md`", "keep their steps inline",
                       "`packs sync`, `eject` and the plugins carry `references/`"):
            self.assertIn(needle, part)

    def test_the_changelog_names_it(self):
        text = flat((ENGINE / "CHANGELOG.md").read_text("utf-8"))
        unreleased = text.split("## [Unreleased]", 1)[1].split(" ## [", 1)[0]
        self.assertIn("`qa-acceptance-baseline` routes its three scenarios", unreleased)


if __name__ == "__main__":
    unittest.main()
