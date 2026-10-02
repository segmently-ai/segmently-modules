"""P8.1 task 5: the text of the four skills that find modules (S3 layer 2, S5, S9, SI-P81-10).
The shared "choose modules" step — `modsys catalog`, the work order of `modsys choose` answered
by the user's own agent, `modsys choose --apply`, the keyword half, the merge — is word for word
the same in module-discover, module-sync, module-scout and module-research; module-discover goes
from the candidates to the code (F6a, F6b); module-sync picks the child, searches the docs that
describe the change and adds a keyword only for a new public name (F10, F13, F15). Sizes and
descriptions are pinned by `test_budgets` and `test_builtin_skills` (P81-AC-040). Every task text
goes to modsys through a file (final review M-6), and every `match` / `context` / `discover`
given a task in a shipped skill, reference or template runs `--match lexical` (final review
I-1): a team's `[match] mode` never reaches them."""
import io
import json
import tempfile
import unittest
from unittest import mock

from modsys.config import builtin_packs_root
from modsys.packs_cmd import scaffold_files
from tests.helpers import SPLIT_FIXTURE, copy_fixture, init_git, run, run_json
from tests.test_builtin_skills import argv, commands, section, uses

SKILLS = ("module-discover", "module-sync", "module-scout", "module-research")
MODE = "The mode:"  # the shared text starts here …
KEYWORD = "- By keyword (`lexical`, `hybrid`):"  # … the skill's own keyword half sits here …
HYBRID = "- `hybrid`: merge the lists"  # … and the shared merge follows
HYBRID_END = "only when `match.semantic` is true."


def text(skill: str) -> str:
    return (builtin_packs_root() / "core/skills" / skill / "SKILL.md").read_bytes().decode(
        "utf-8")


def flat(s: str) -> str:
    return " ".join(s.split())


def between(s: str, start: str, end: str) -> str:
    """The flat text from `start` up to `end` (excluded); '' when either is missing."""
    s = flat(s)
    if start not in s:
        return ""
    rest = s[s.index(start):]
    return rest[:rest.index(end)] if end in rest else ""


def in_order(body: str, phrases: list[str]) -> list[int]:
    """The position of each phrase in `body`, each searched after the previous one (-1: not
    found there)."""
    out, at = [], 0
    for p in phrases:
        i = body.find(p, at)
        out.append(i)
        at = i + len(p) if i >= 0 else at
    return out


class SharedStepTest(unittest.TestCase):  # P81-AC-074, SI-P81-10
    PHRASES = [
        "modsys catalog --json", "read `match` and `search`.",
        '"only lexical"', '"search deep"', '"use opus"',  # the user's words win
        "else `hybrid`",  # the skills' default mode
        "- By meaning (`semantic`, `hybrid`):", KEYWORD, HYBRID,
        "`modsys choose --task-file <the text, verbatim, in a file> --json`",  # final review
        # M-6: a file, so a task's apostrophes, backticks or `$` reach modsys as written
        "Answer it whole (never a preview)",  # final review M-3: a long order is saved whole
        "a subagent (`model: <search.claude_model>`)",
        "`codex exec -m <search.codex_model> -c model_reasoning_effort=<reasoning> "
        "--output-schema <schema file> -`",
        "`low`, `medium`, `high` for `quick`, `standard`, `deep`",
        "answer it in this session",
        "`quick` the cards only",
        "`standard` also the INDEX or the main doc's head of up to 3 candidates",
        "`deep` also their docs and code",
        "at the depth its rules set (or the user's)",  # review M-2
        "`modsys choose --apply - --json`",
        "Pass `--match semantic` or `--match hybrid` only when `match.semantic` is true",
    ]

    def test_every_skill_says_it(self):
        for skill in SKILLS:
            with self.subTest(skill=skill):
                body = flat(text(skill))
                self.assertEqual([p for p in self.PHRASES if p not in body], [])

    def test_word_for_word_the_same(self):
        for start, end in ((MODE, KEYWORD), (HYBRID, HYBRID_END)):
            parts = {s: between(text(s), start, end) for s in SKILLS}
            with self.subTest(part=start):
                self.assertTrue(all(parts.values()), parts)
                self.assertEqual(len(set(parts.values())), 1, parts)

    def test_said_once_and_in_order(self):
        for skill in SKILLS:
            with self.subTest(skill=skill):
                body = flat(text(skill))
                for p in ("modsys catalog --json", MODE, "modsys choose --task",
                          "modsys choose --apply", KEYWORD, HYBRID):
                    self.assertEqual(body.count(p), 1, p)
                self.assertNotIn(-1, in_order(body, ["modsys catalog --json", MODE,
                                                     "modsys choose --task",
                                                     "modsys choose --apply", KEYWORD, HYBRID]))

    def test_the_steps_run_the_verbs(self):
        for skill in SKILLS:
            with self.subTest(skill=skill):
                cmds = commands(section(text(skill), "## Steps"))
                for verb in (("catalog",), ("choose", "--task-file"), ("choose", "--apply")):
                    self.assertTrue(uses(cmds, verb), verb)

    def test_keyword_commands_are_lexical(self):  # review I-1: `[match] mode` never leaks in
        for skill in SKILLS:
            with self.subTest(skill=skill):
                body = flat(text(skill))
                self.assertNotIn("has no agent to ask", body)
                keyword = [argv(c) for c in commands(text(skill))
                           if argv(c)[:1] in (["discover"], ["context"])]
                self.assertTrue(keyword)
                for a in keyword:
                    self.assertIn("--match", a, a)
                for a in (argv(c) for c in commands(text(skill))):
                    if "--match" in a:  # never semantic or hybrid: the skill is the agent
                        self.assertEqual(a[a.index("--match") + 1], "lexical", a)

    def test_every_task_text_goes_through_a_file(self):  # final review M-6, deferred 3
        for skill in SKILLS:
            with self.subTest(skill=skill):
                for a in (argv(c) for c in commands(text(skill))):
                    self.assertNotIn("--task", a, a)
                self.assertTrue(any("--task-file" in argv(c) for c in commands(text(skill))))

    def test_the_keys_it_names_are_printed(self):  # the text and the engine agree
        with tempfile.TemporaryDirectory() as tmp:
            R = ("--root", str(copy_fixture(tmp, SPLIT_FIXTURE)))
            code, out, err = run("catalog", "--json", *R)
            self.assertEqual((code, err), (0, ""))
            catalog = json.loads(out)["data"]
            self.assertEqual(sorted(catalog["match"]), ["mode", "semantic"])
            self.assertEqual(sorted(catalog["search"]), ["claude_model", "codex_model", "effort"])
            self.assertIn(catalog["search"]["effort"], ("quick", "standard", "deep"))
            code, out, err = run("choose", "--task", "a partial refund", "--json", *R)
            self.assertEqual((code, err), (0, ""))
            order = json.loads(out)["data"]
            self.assertEqual(order["search"], catalog["search"])
            self.assertEqual(order["answer_schema"]["type"], "object")
            answer = {"picks": [{"module": "orders/refunds", "confidence": 0.8, "reason": "r"}],
                      "none": False}
            with mock.patch("sys.stdin", io.StringIO(json.dumps(answer))):
                code, out, err = run("choose", "--apply", "-", "--json", *R)
            self.assertEqual((code, err), (0, ""))
            pick = json.loads(out)["data"]["picks"][0]
            self.assertEqual(pick["module"], "orders/refunds")
            self.assertTrue(pick["read"])


class EveryShippedTextIsLexicalTest(unittest.TestCase):  # final review I-1 (and 5 D-4)
    """A `match`, a `context` or a `discover` given a task, anywhere the engine ships text an
    agent follows (every pack's skills and references, the templates, the skill `packs new`
    scaffolds), passes `--match lexical`: under a committed `[match] mode = "semantic"` none of
    them exits 2 for want of an agent command, and none starts the user's agent for a keyword
    check. And none takes its task as a quoted `--task` argument (M-6): always `--task-file`."""

    def shipped(self) -> dict[str, str]:
        root = builtin_packs_root().parent
        out = {p.relative_to(root).as_posix(): p.read_bytes().decode("utf-8")
               for p in sorted(root.rglob("*.md"))}
        for roles in (["reviewer", "auditor"], []):  # what `packs new` writes, with roles or none
            for path, body in scaffold_files("team", roles, ["api-review"], None, None).items():
                out[f"packs new ({len(roles)} roles): {path}"] = body
        return out

    def test_every_keyword_command_is_lexical(self):
        found = set()
        for name, body in self.shipped().items():
            for a in (argv(c) for c in commands(body)):
                if a[:1] in (["match"], ["context"]) or (
                        a[:1] == ["discover"] and {"--task", "--task-file"} & set(a)):
                    found.add(name)
                    with self.subTest(file=name, argv=a):
                        self.assertIn("--match", a)
                        self.assertEqual(a[a.index("--match") + 1], "lexical")
        for name in ("templates/agents-md.md", "packs/core/skills/module-create/SKILL.md",
                     "packs/qa/skills/qa-acceptance/SKILL.md",
                     "packs/core/skills/module-discover/SKILL.md",
                     "packs new (2 roles): skills/api-review/SKILL.md",
                     "packs new (0 roles): skills/api-review/SKILL.md"):
            self.assertIn(name, found)  # the scan reaches what the reviews named

    def test_no_task_is_a_quoted_argument(self):  # final review M-6
        for name, body in self.shipped().items():
            for a in (argv(c) for c in commands(body)):
                with self.subTest(file=name, argv=a):
                    self.assertNotIn("--task", a)

    def test_the_scan_sees_a_missing_flag(self):
        for body in ('`modsys context --task "<t>" --role <r>`',
                     "```bash\nmodsys match x --json\n```",
                     "`modsys discover --task-file <f> --match hybrid --json`"):
            a = argv(commands(body)[0])
            self.assertFalse("--match" in a and a[a.index("--match") + 1] == "lexical", body)


class OtherKeysTest(unittest.TestCase):  # review M-9: the keys the steps read, next to the text
    def test_children_submodules_near_misses_and_code_map_via(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp, SPLIT_FIXTURE)
            init_git(root)
            R = ("--root", str(root))
            found = run_json("discover", "--files", "src/orders/service.py", "--match",
                             "lexical", *R)[1]["data"]
            row = {m["module"]: m for m in found["modules"]}["orders"]
            self.assertEqual(row["usage"], "modify")
            self.assertEqual(sorted(row["children"][1]), ["description", "doc", "module"])
            shown = run_json("show", "orders", *R)[1]["data"]
            self.assertIn("refunds", shown["submodules"])
            near = run_json("context", "--task", "refundz", "--match", "lexical", *R)[1]["data"]
            self.assertEqual((near["modules"], near["near_misses"][0]["module"]),
                             ([], "orders/refunds"))
            child = run_json("code-map", "files", "orders/refunds", *R)[1]["data"]["files"]
            self.assertEqual({tuple(f["via"]) for f in child}, {("docs",)})  # no code: parent's
            parent = run_json("code-map", "files", "orders", *R)[1]["data"]["files"]
            self.assertIn("src/orders/service.py",
                          [f["path"] for f in parent if f["via"] != ["docs"]])


class DiscoverTest(unittest.TestCase):  # P81-AC-041 (F6a, F6b)
    ORDER = [
        "modsys catalog --json",
        "1–3 short English queries",  # F6a: the registry's language, domain terms, identifiers
        "(step 4 uses it too)",  # review M-4
        "the domain terms and code identifiers",
        '"only lexical"',
        "else `hybrid`",
        "- By meaning (`semantic`, `hybrid`):",
        "`modsys choose --apply - --json`",
        "- By keyword (`lexical`, `hybrid`): "
        "`modsys discover --task-file <file> --match lexical --json`",
        HYBRID,
        "Verify each candidate",
        "the child the task is in",
        "modsys code-map files <candidate> --json",  # F6b: from the candidates to the code
        "its code is the files whose `via` is not `docs`",  # review I-2: a doc is not code
        "(a child without code: its parent's)",
        "Grep the terms of `<file>` inside that code first",
        "only when it gives nothing",
        "modsys discover --files <found files> --task-file <file> --match lexical --json",
        "on a split parent `children` (name the one the change is in and add its `doc` to the "
        "docs to update)",  # review M-3
        "every `modify` row with its code at file:line",
    ]

    def test_the_steps_in_order(self):
        body = flat(section(text("module-discover"), "## Steps"))
        found = in_order(body, self.ORDER)
        self.assertEqual([p for p, i in zip(self.ORDER, found) if i < 0], [])


class SyncTest(unittest.TestCase):  # P81-AC-042 (F10, F13, F15)
    ORDER = [
        "modsys sync-instructions --from-diff <base>..HEAD --json",
        "`children` on a split parent: pick the child the change is in",  # F10
        "modsys catalog --json",  # F13: the docs that describe the change, in the mode
        "The text: a summary of the change with its identifiers",
        "joins the modules to update, with the docs the search listed",  # review M-6
        "modsys registry append <module> keywords",
        "only for a new public name a future task would search by",  # F15
        "never a keyword per task",
    ]

    def test_the_steps_in_order(self):
        body = flat(section(text("module-sync"), "## Steps"))
        found = in_order(body, self.ORDER)
        self.assertEqual([p for p, i in zip(self.ORDER, found) if i < 0], [])

    def test_the_keyword_half_is_discover(self):
        body = flat(text("module-sync"))
        self.assertIn(f'{KEYWORD} `modsys discover --task-file <', body)


class ScoutAndResearchTest(unittest.TestCase):  # P81-AC-043
    START, END = "No module named? Choose the candidates.", "never widen the list on your own."

    def test_the_same_search_for_a_topic_without_modules(self):
        parts = {s: between(text(s), self.START, self.END)
                 for s in ("module-scout", "module-research")}
        self.assertTrue(all(parts.values()), parts)
        self.assertEqual(parts["module-scout"], parts["module-research"])
        self.assertIn("else `hybrid`", parts["module-scout"])
        self.assertIn(f'{KEYWORD} `modsys context --task-file <', parts["module-scout"])
        self.assertIn("Keep the top 3;", parts["module-scout"])  # review M-7

    def test_scout_keeps_the_retry_rule(self):  # review M-8
        exits = section(text("module-scout"), "## Exit codes")
        self.assertIn("do not retry the same command", flat(exits))

    def test_it_is_part_of_the_steps(self):
        for skill in ("module-scout", "module-research"):
            with self.subTest(skill=skill):
                self.assertIn(self.START, flat(section(text(skill), "## Steps")))


if __name__ == "__main__":
    unittest.main()
