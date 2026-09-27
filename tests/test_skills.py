"""The pack skills model (D3): `[skills.<id>]` shape errors, the Agent Skills name rule,
shadowing between packs, and the stdlib-only `SKILL.md` front-matter reader."""
import tempfile
import unittest
from pathlib import Path

from modsys.skills import (SKILL_KEYS, front_matter, pack_skills, read_front_matter,
                           source_problem)
from tests.helpers import copy_fixture, run, run_json

ENGINE = Path(__file__).resolve().parents[1]
GOOD = "---\nname: api-review\ndescription: Reviews API changes.\n---\n\n# api-review\n"


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def pack(root: Path, pack_id: str, body: str, priority: int = 50) -> Path:
    toml = root / ".modsys/packs" / pack_id / "pack.toml"
    write(toml, f'id = "{pack_id}"\nversion = "0.1.0"\npriority = {priority}\n{body}')
    return toml


class SkillsModelTest(unittest.TestCase):  # P4A-AC-007
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def listing(self, body: str) -> tuple[int, str, str]:
        pack(self.root, "team", body)
        code, out, err = run("list", "--json", *self.R)
        return code, out, err

    def test_a_valid_declaration_loads(self):
        code, _, err = self.listing('[skills.api-review]\npath = "skills/api-review"\n'
                                    'reads_roles = ["reviewer"]\n')
        self.assertEqual((code, err), (0, ""))

    def test_shape_errors_are_config_errors(self):
        cases = [("skills = 5\n", "skills must be a table of [skills.<id>] tables"),
                 ('[skills]\napi-review = "x"\n', "skills.api-review must be a table"),
                 ("[skills.api-review]\nreads_roles = []\n", "[skills.api-review] path is missing"),
                 ("[skills.api-review]\npath = 3\n", "[skills.api-review] path: expected a string"),
                 ('[skills.api-review]\npath = "s"\nreads_roles = "reviewer"\n',
                  "[skills.api-review] reads_roles: expected a list of strings")]
        for body, needle in cases:
            with self.subTest(needle=needle):
                code, out, err = self.listing(body)
                self.assertEqual((code, out), (2, ""))
                self.assertIn(".modsys/packs/team/pack.toml: ", err)
                self.assertIn(needle, err)
                self.assertNotIn("Traceback", err)

    def test_the_agent_skills_name_rule(self):
        for sid, code in [("a", 0), ("a" * 64, 0), ("api-review-2", 0), ("a" * 65, 2),
                          ("Api-review", 2), ("api_review", 2), ("-api", 2), ("api-", 2),
                          ("api--review", 2)]:
            with self.subTest(sid=sid):
                got, out, err = self.listing(f'[skills."{sid}"]\npath = "skills/x"\n')
                self.assertEqual(got, code, err)
                if code:
                    self.assertEqual(out, "")
                    self.assertIn(f"skill id {sid!r}: 1–64 characters: lowercase letters and "
                                  f"digits, words joined by single hyphens", err)

    def test_the_higher_precedence_pack_wins_a_shared_id(self):
        pack(self.root, "a", '[skills.api-review]\npath = "skills/api-review"\n', priority=10)
        pack(self.root, "b", '[skills.api-review]\npath = "skills/api-review"\n', priority=50)
        code, env, err = run_json("packs", "list", *self.R)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual([(r["id"], [s["id"] for s in r["skills"]]) for r in env["data"]],
                         [("a", ["api-review"]), ("b", ["api-review"]), ("bookshop", [])])
        self.assertEqual(pack_skills(self.root / ".modsys")["api-review"].pack, "a")
        self.assertEqual(run("list", *self.R)[0], 0)  # other verbs keep working

    def test_the_skill_keys_are_documented(self):
        doc = (ENGINE / "docs" / "configuration.md").read_text(encoding="utf-8")
        self.assertEqual([k for k in SKILL_KEYS if f"`{k}`" not in doc], [])


class FrontMatterTest(unittest.TestCase):  # P4A-AC-008
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.skill = Path(self._tmp.name) / "api-review"

    def tearDown(self):
        self._tmp.cleanup()

    def loadable(self, text: str | bytes) -> str | None:
        self.skill.mkdir(exist_ok=True)
        data = text if isinstance(text, bytes) else text.encode("utf-8")
        (self.skill / "SKILL.md").write_bytes(data)
        return source_problem(self.skill, "api-review")

    def test_the_reader_table(self):
        rows = [(GOOD, "api-review", "Reviews API changes."),
                ("---\nname: \"api-review\"\ndescription: 'Checks: routes, errors'\n---\n",
                 "api-review", "Checks: routes, errors"),
                ("---\nname: api-review\ndescription: >\n  Reviews API\n  changes.\n---\n",
                 "api-review", "Reviews API changes."),
                ("---\nname: api-review\ndescription: |\n  Reviews API\n  changes.\n---\n",
                 "api-review", "Reviews API\nchanges."),
                ("---\nname: api-review\nmetadata:\n  author: x\ndescription: Reviews.\n---\n",
                 "api-review", "Reviews."),
                ("﻿---\r\nname: api-review\r\ndescription: Reviews.\r\n---\r\n",
                 "api-review", "Reviews.")]
        for text, name, description in rows:
            with self.subTest(text=text):
                meta = front_matter(text)
                self.assertEqual((meta["name"], meta["description"]), (name, description))
                self.assertIsNone(self.loadable(text))
        self.assertEqual(front_matter(rows[4][0])["metadata"], "")

    def test_what_is_not_front_matter(self):
        for text in ("name: api-review\ndescription: Reviews.\n",
                     "# api-review\n---\nname: api-review\n---\n",
                     "---\nname: api-review\ndescription: Reviews.\n"):
            with self.subTest(text=text):
                self.assertIsNone(front_matter(text))
                self.assertEqual(self.loadable(text), "SKILL.md has no front matter (a --- block "
                                                      "at the top, closed by a --- line)")

    def test_description_length_boundary(self):
        for n, problem in [(1024, None), (1025, "SKILL.md description has 1025 characters "
                                                "(max 1024)")]:
            with self.subTest(n=n):
                self.assertEqual(self.loadable(f"---\nname: api-review\ndescription: "
                                               f"{'d' * n}\n---\n"), problem)

    def test_name_and_description_problems(self):
        rows = [("---\nname: api-review\ndescription:\n---\n",
                 "SKILL.md front matter has no description"),
                ("---\nname: api-review\n---\n", "SKILL.md front matter has no description"),
                ("---\ndescription: Reviews.\n---\n", "SKILL.md front matter has no name"),
                ("---\nname: other-name\ndescription: Reviews.\n---\n",
                 "SKILL.md name 'other-name' is not the skill id 'api-review'"),
                (b"---\nname: api-review\ndescription: \xff\n---\n",
                 "SKILL.md has no front matter (a --- block at the top, closed by a --- line)")]
        for text, problem in rows:
            with self.subTest(text=text):
                self.assertEqual(self.loadable(text), problem)

    def test_front_matter_other_tools_write(self):  # Review Focus
        text = ("--- \nname: api-review   \nlicense: MIT\nallowed-tools:\n- Read\n- Grep\n"
                "metadata:\n  version: '2'\n  tags: [a, b]\n"
                "description: \"Reviews API changes.\"  # set by the pack\n---  \n\n# body\n")
        meta = front_matter(text)
        self.assertEqual((meta["name"], meta["description"], meta["license"]),
                         ("api-review", "Reviews API changes.", "MIT"))
        self.assertIsNone(self.loadable(text))

    def test_reader_details(self):  # PR rulings: comments, continuation, chomping, quotes
        meta = front_matter("---\n# a comment\nname: api-review # trailing\n"
                            "description: Reviews API\n  changes and\n  errors.\n"
                            "one: |-\n  kept\n\n  lines\n"
                            "two: >+\n  folded\n  text\n\n  second\n"
                            "three: \"tab\\tquote \\\"q\\\"\"\n"
                            "four: 'it''s'\n---\n")
        self.assertEqual(meta, {"name": "api-review",
                                "description": "Reviews API changes and errors.",
                                "one": "kept\n\nlines", "two": "folded text\nsecond",
                                "three": 'tab\tquote "q"', "four": "it's"})
        self.assertIsNone(read_front_matter(self.skill / "missing.md"))


if __name__ == "__main__":
    unittest.main()
