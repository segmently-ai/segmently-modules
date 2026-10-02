"""P8.1 task 5: the text of the four skills that find modules (S3 layer 2, S5, S9, SI-P81-10).
The shared "choose modules" step — `modsys catalog`, the work order of `modsys choose` answered
by the user's own agent, `modsys choose --apply`, the keyword half, the merge — is word for word
the same in module-discover, module-sync, module-scout and module-research; module-discover goes
from the candidates to the code (F6a, F6b); module-sync picks the child, searches the docs that
describe the change and adds a keyword only for a new public name (F10, F13, F15). Sizes and
descriptions are pinned by `test_budgets` and `test_builtin_skills` (P81-AC-040)."""
import io
import json
import tempfile
import unittest
from unittest import mock

from modsys.config import builtin_packs_root
from tests.helpers import SPLIT_FIXTURE, copy_fixture, run
from tests.test_builtin_skills import argv, commands, section, uses

SKILLS = ("module-discover", "module-sync", "module-scout", "module-research")
MODE = "The mode:"  # the shared text starts here …
KEYWORD = "- By keyword (`lexical`, `hybrid`):"  # … the skill's own keyword half sits here …
HYBRID = "- `hybrid`: merge the lists"  # … and the shared merge follows
HYBRID_END = "else modsys has no agent to ask."


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
        '`modsys choose --task "<the text, verbatim, any language>" --json`',
        "a subagent (`model: <search.claude_model>`)",
        "`codex exec -m <search.codex_model> -c model_reasoning_effort=<reasoning> "
        "--output-schema <schema file> -`",
        "`low`, `medium`, `high` for `quick`, `standard`, `deep`",
        "answer it in this session",
        "`quick` the cards only",
        "`standard` also the INDEX or the main doc's head of up to 3 candidates",
        "`deep` also their docs and code",
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
                for verb in (("catalog",), ("choose", "--task"), ("choose", "--apply")):
                    self.assertTrue(uses(cmds, verb), verb)

    def test_no_command_passes_match(self):  # the CLI refuses it without the user's agent
        for skill in SKILLS:
            with self.subTest(skill=skill):
                self.assertEqual([c for c in commands(text(skill)) if "--match" in argv(c)], [])

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


class DiscoverTest(unittest.TestCase):  # P81-AC-041 (F6a, F6b)
    ORDER = [
        "modsys catalog --json",
        "1–3 short English queries",  # F6a: the registry's language, domain terms, identifiers
        "the domain terms and code identifiers",
        '"only lexical"',
        "else `hybrid`",
        "- By meaning (`semantic`, `hybrid`):",
        "`modsys choose --apply - --json`",
        "- By keyword (`lexical`, `hybrid`): `modsys discover --task-file <file> --json`",
        HYBRID,
        "Verify each candidate",
        "the child the task is in",
        "modsys code-map files <candidate> --json",  # F6b: from the candidates to the code
        "inside these files first",
        "only when they give nothing",
        "modsys discover --files <found files> --task-file <file> --json",
        "on a split parent `children` (name the one the change is in)",
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
        "joins the modules to update",
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
        self.assertIn(f'{KEYWORD} `modsys discover --task "<', body)


class ScoutAndResearchTest(unittest.TestCase):  # P81-AC-043
    START, END = "No module named? Choose the candidates.", "Never widen the list on your own."

    def test_the_same_search_for_a_topic_without_modules(self):
        parts = {s: between(text(s), self.START, self.END)
                 for s in ("module-scout", "module-research")}
        self.assertTrue(all(parts.values()), parts)
        self.assertEqual(parts["module-scout"], parts["module-research"])
        self.assertIn("else `hybrid`", parts["module-scout"])
        self.assertIn(f'{KEYWORD} `modsys context --task "<', parts["module-scout"])

    def test_it_is_part_of_the_steps(self):
        for skill in ("module-scout", "module-research"):
            with self.subTest(skill=skill):
                self.assertIn(self.START, flat(section(text(skill), "## Steps")))


if __name__ == "__main__":
    unittest.main()
