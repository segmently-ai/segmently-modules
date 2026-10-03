"""P8.2 task 1a: the instruction of the choose work order is the template `choose/rules.md`
(D3): the default rules, placeholders, line parsing, the resolution chain, the refusals, the
`templates list|override` row and the packaging (P82-AC-001…008, 012, 013)."""
import json
import os
import shutil
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from modsys.create import engine_templates
from tests.agent_helpers import AgentRepo, picks
from tests.helpers import run, run_json

TASK = "refund payment catalog"
REL = ".modsys/overrides/templates/choose/rules.md"
ENGINE_FILE = Path(__file__).resolve().parents[1] / "modsys/defaults/templates/choose/rules.md"
DEPTH = {
    "quick": "Choose from the cards only; do not open any file.",
    "standard": "Choose from the cards, and also open the INDEX or the head of MODULE.md of up "
                "to 3 candidates before you answer.",
    "deep": "Choose from the cards, and also read the candidates' docs and confirm the choice "
            "in their code before you answer.",
}
NOTES = ["# The rules of the modsys choose work order",
         "The instruction the agent", "modsys templates override choose/rules.md"]
D3_TEXT = """# The rules of the modsys choose work order

The instruction the agent that picks modules by meaning follows: the modsys plugin's
module-chooser agent, `codex exec`, or your own agent command (MODSYS_AGENT_COMMAND).
Every line that starts with "- " is one rule, sent as written; the other lines (these) are
notes for you and are not sent. Placeholders: $max_picks (the most picks the order allows)
and $depth (the sentence for [search] effort). Change the rules in your copy:
modsys templates override choose/rules.md

- Read every card before you choose: the cards are the whole catalog. Never filter them by the task's words — a module may describe the task in other words or in another language.
- Choose the modules this task needs by meaning, in any language the task is written in.
- A card with a parent is one area of a split module: when the task is in that area, pick that child; add the parent only when the task also changes what all its areas share.
- Use only module ids that appear in the cards; never invent one.
- Answer {"picks": [], "none": true} when you are not sure.
- Give at most $max_picks picks, best first, each with a confidence from 0 to 1 and a short reason.
- $depth
- Answer with one JSON object that matches the answer schema, and nothing else.
"""
DEFAULT_RULES = [
    "Read every card before you choose: the cards are the whole catalog. Never filter them by "
    "the task's words — a module may describe the task in other words or in another language.",
    "Choose the modules this task needs by meaning, in any language the task is written in.",
    "A card with a parent is one area of a split module: when the task is in that area, pick "
    "that child; add the parent only when the task also changes what all its areas share.",
    "Use only module ids that appear in the cards; never invent one.",
    'Answer {"picks": [], "none": true} when you are not sure.',
    "Give at most 5 picks, best first, each with a confidence from 0 to 1 and a short reason.",
    DEPTH["standard"],
    "Answer with one JSON object that matches the answer schema, and nothing else.",
]
NO_RULE = 'no rule in choose/rules.md (a rule is a line starting with "- ")'


class Base(AgentRepo, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.task = self.tmp / "t.txt"
        self.task.write_text(TASK, encoding="utf-8")
        self.answer = self.tmp / "a.json"
        self.answer.write_text(json.dumps(picks(("payments", 0.9))), encoding="utf-8")

    def write(self, rel: str, data) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        return path

    def override(self, data) -> Path:
        return self.write(REL, data)

    def pack(self, pid: str, data, priority: int = 50) -> str:
        self.write(f".modsys/packs/{pid}/pack.toml",
                   f'id = "{pid}"\nversion = "0.1.0"\npriority = {priority}\n')
        rel = f".modsys/packs/{pid}/templates/choose/rules.md"
        self.write(rel, data)
        return rel

    def order(self, *extra) -> dict:
        code, env, err = run_json("choose", "--task-file", str(self.task), *extra, *self.R)
        self.assertEqual((code, err), (0, ""))
        return env["data"]

    def rules(self, *extra) -> list[str]:
        return self.order(*extra)["rules"]

    def row(self) -> dict:
        code, env, err = run_json("templates", "list", *self.R)
        self.assertEqual((code, err), (0, ""))
        return {r["template"]: r for r in env["data"]}["choose/rules.md"]


class DefaultRulesTest(Base):
    def test_default_rules_are_the_template_rendered(self):  # P82-AC-001
        self.assertEqual(self.rules(), DEFAULT_RULES)
        code, out, err = run("choose", "--task-file", str(self.task), *self.R)
        self.assertEqual((code, err), (0, ""))
        block = out.split("Rules:\n")[1].split("\n\n")[0].splitlines()
        self.assertEqual(block, [f"- {r}" for r in DEFAULT_RULES])
        for note in NOTES:
            self.assertNotIn(note, out)
            self.assertNotIn(note, json.dumps(self.rules()))

    def test_the_engine_file_is_the_d3_text(self):  # P82-AC-001
        raw = ENGINE_FILE.read_bytes()
        self.assertEqual(raw, D3_TEXT.encode("utf-8"))
        self.assertNotIn(b"\r", raw)
        self.assertTrue(raw.endswith(b"\n"))


class PlaceholdersTest(Base):
    BODY = ("- at most $max_picks\n- ${max_picks} again\n- $depth\n- costs $$5\n"
            "- keep $unknown and ${other}\n")

    def test_placeholders(self):  # P82-AC-002
        self.override(self.BODY)
        for top, want in ((("--top", "1"), 1), (("--top", "3"), 3), ((), 5)):
            with self.subTest(top=top):
                rules = self.rules(*top)
                self.assertEqual(rules[0], f"at most {want}")
                self.assertEqual(rules[1], f"{want} again")
                self.assertEqual(rules[3:], ["costs $5", "keep $unknown and ${other}"])
        for effort, sentence in DEPTH.items():
            with self.subTest(effort=effort):
                self.config(f'[search]\neffort = "{effort}"\n', "config.user.toml")
                order = self.order()
                self.assertEqual(order["rules"][2], sentence)
                self.assertEqual(order["search"]["effort"], effort)

    def test_text_form_prints_the_substituted_rules(self):  # P82-AC-002
        self.override(self.BODY)
        out = run("choose", "--task-file", str(self.task), "--top", "3", *self.R)[1]
        self.assertIn("- at most 3\n- 3 again\n", out)
        self.assertIn("- costs $5\n- keep $unknown and ${other}\n", out)

    def test_no_depth_placeholder_sends_no_depth_sentence(self):  # P82-AC-002
        self.override("- only this\n")
        self.config('[search]\neffort = "deep"\n', "config.user.toml")
        order = self.order()
        self.assertEqual(order["rules"], ["only this"])
        self.assertEqual(order["search"]["effort"], "deep")

    def test_the_semantic_order_says_at_most_five(self):  # P82-AC-002
        self.override(self.BODY)
        self.agent(answer=picks(("payments", 0.9)))
        code, out, err = run("match", TASK, "--match", "semantic", "--top", "2", *self.R)
        self.assertEqual((code, err), (0, ""))
        sent = json.loads(self.calls()[0]["stdin"])
        self.assertEqual(sent["rules"][0], "at most 5")
        self.assertEqual(sent["rules"][2], DEPTH["standard"])


class ParsingTest(Base):
    def test_line_parsing(self):  # P82-AC-003
        body = ("note one\n- a\n-b\n  - c\n-\td\n- \n-   \n-  e\nbetween notes\n- f   \n"
                "- g\r\n- i\n- i\n")
        self.override(body)
        self.assertEqual(self.rules(), ["a", " e", "f", "g", "i", "i"])

    def test_a_crlf_file_sends_no_carriage_return(self):  # P82-AC-003
        self.override("# note\r\n- a\r\n- b   \r\nnote\r\n- c\r\n")
        rules = self.rules()
        self.assertEqual(rules, ["a", "b", "c"])
        self.assertNotIn("\r", json.dumps(rules))

    def test_a_leading_bom_is_ignored(self):  # P82-AC-003
        self.override(b"\xef\xbb\xbf- h\n- x\n")
        self.assertEqual(self.rules(), ["h", "x"])

    def test_notes_are_never_sent(self):  # P82-AC-003
        self.override("# title\n- one\nsome note with $max_picks\n- two\n")
        sent = json.dumps(self.rules())
        self.assertEqual(self.rules(), ["one", "two"])
        self.assertNotIn("title", sent)
        self.assertNotIn("note", sent)


class ResolutionTest(Base):
    def source_of(self, rules_text: str) -> None:
        self.assertEqual(self.rules()[0], rules_text)

    def test_engine_only(self):  # P82-AC-004
        self.assertEqual(self.rules(), DEFAULT_RULES)
        row = self.row()
        self.assertEqual(row["source"], "engine")
        self.assertEqual(Path(row["path"]), engine_templates() / "choose/rules.md")
        self.assertEqual(row["role"], None)

    def test_a_pack_wins_over_the_engine(self):  # P82-AC-004
        rel = self.pack("team", "- from team\n", 10)
        self.source_of("from team")
        self.assertEqual((self.row()["source"], self.row()["path"]), ("pack:team", rel))

    def test_the_first_pack_in_precedence_order_wins(self):  # P82-AC-004
        rel = self.pack("team", "- from team\n", 10)
        self.pack("extra", "- from extra\n", 50)
        self.source_of("from team")
        self.assertEqual((self.row()["source"], self.row()["path"]), ("pack:team", rel))

    def test_an_override_wins_over_a_pack(self):  # P82-AC-004
        self.pack("team", "- from team\n")
        self.override("- from override\n")
        self.source_of("from override")
        self.assertEqual((self.row()["source"], self.row()["path"]), ("override", REL))

    def test_override_only(self):  # P82-AC-004
        self.override("- from override\n")
        self.source_of("from override")
        self.assertEqual(self.row()["source"], "override")

    def test_the_core_pack_has_no_choose_template(self):  # P82-AC-004
        self.config('[packs]\nbuiltin = ["core"]\n')
        self.assertEqual(self.rules(), DEFAULT_RULES)
        self.assertEqual(self.row()["source"], "engine")

    def test_a_role_template_key_never_applies(self):  # P82-AC-004
        self.config('[roles.qa]\ntemplate = "roles/qa.md"\n')
        self.assertEqual(self.rules(), DEFAULT_RULES)
        self.assertEqual(self.row()["source"], "engine")


class BrokenTemplateTest(Base):
    CASES = {"empty": b"", "notes only": b"# title\nonly notes\n-x\n  - y\n- \n",
             "no placeholder lines": b"\n\n"}

    def refuses(self, argv, message: str) -> None:
        code, out, err = run(*argv, *self.R)
        self.assertEqual((code, out), (2, ""), argv)
        self.assertEqual(err, f"modsys: error: {message}\n", argv)
        self.assertNotIn("Traceback", err)

    def verbs(self):
        t = str(self.task)
        return [("choose", "--task-file", t), ("choose", "--task-file", t, "--json"),
                ("choose", "--apply", str(self.answer)),
                ("choose", "--apply", str(self.answer), "--json"),
                ("choose", "--task-file", t, "--run"),
                ("match", TASK, "--match", "hybrid"), ("match", TASK, "--match", "semantic"),
                ("context", "--task", TASK, "--match", "hybrid")]

    def layers(self, data):
        yield "override", REL, lambda: self.override(data)
        yield "pack", ".modsys/packs/team/templates/choose/rules.md", \
            lambda: self.pack("team", data)

    def check(self, data, message_for):
        for layer, rel, make in self.layers(data):
            make()
            for argv in self.verbs():
                with self.subTest(layer=layer, argv=argv):
                    self.agent(answer=picks(("payments", 0.9)))
                    self.refuses(argv, message_for(rel))
            self.assertEqual(self.calls(), [])
            (self.root / rel).unlink()

    def test_no_rule_is_refused(self):  # P82-AC-005
        for name, data in self.CASES.items():
            with self.subTest(case=name):
                self.check(data, lambda rel: f"{rel}: {NO_RULE}")

    def test_non_utf8_is_refused(self):  # P82-AC-005
        self.check(b"- ok\n- \xff\n", lambda rel: f"cannot read {rel}: not valid UTF-8")

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root reads mode 000")
    def test_unreadable_is_refused(self):  # P82-AC-005
        path = self.override("- ok\n")
        path.chmod(0)
        self.addCleanup(path.chmod, 0o644)
        self.agent(answer=picks(("payments", 0.9)))
        for argv in self.verbs():
            self.refuses(argv, f"cannot read {REL}: Permission denied")
        self.assertEqual(self.calls(), [])

    def test_a_broken_pack_does_not_fall_back_to_a_lower_layer(self):  # P82-AC-005
        self.pack("team", b"", 10)
        self.pack("extra", "- from extra\n", 50)
        self.refuses(("choose", "--task-file", str(self.task)),
                     f".modsys/packs/team/templates/choose/rules.md: {NO_RULE}")

    def test_lexical_and_other_verbs_never_read_it(self):  # P82-AC-005
        argvs = [("match", TASK), ("match", TASK, "--match", "lexical"),
                 ("context", "--task", TASK), ("discover", "--task", TASK),
                 ("catalog",), ("show", "payments"), ("lint",), ("list",)]
        before = {a: run(*a, "--json", *self.R) for a in argvs}
        before_list = run("templates", "list", *self.R)
        self.override(b"")
        for a in argvs:
            with self.subTest(argv=a):
                self.assertEqual(run(*a, "--json", *self.R), before[a])
                self.assertEqual(before[a][0] in (0, 1), True)
        code, out, err = run("templates", "list", *self.R)
        self.assertEqual((code, err), (0, ""))
        self.assertNotEqual(out, before_list[1])  # the row names the override now
        self.assertIn("override", out)


class NoEngineFallbackTest(Base):
    def test_a_missing_engine_file_is_refused_not_replaced(self):  # P82-AC-006
        copy = self.tmp / "engine-templates"
        shutil.copytree(engine_templates(), copy)
        (copy / "choose/rules.md").unlink()
        with mock.patch("modsys.create.engine_templates", return_value=copy):
            code, out, err = run("choose", "--task-file", str(self.task), *self.R)
            self.assertEqual((code, out), (2, ""))
            self.assertIn(f"modsys: error: cannot read {copy / 'choose/rules.md'}: ", err)
            self.assertNotIn("Traceback", err)
            code, env, err = run_json("templates", "list", *self.R)
            self.assertEqual((code, err), (0, ""))
            rows = {r["template"]: r for r in env["data"]}
            self.assertEqual((rows["choose/rules.md"]["source"], rows["choose/rules.md"]["path"]),
                             ("engine", str(copy / "choose/rules.md")))
            # a role without an engine file still falls back, as before
            (copy / "roles" / "qa.md").unlink()
            rows = {r["template"]: r for r in run_json("templates", "list", *self.R)[1]["data"]}
            self.assertEqual(rows["roles/qa.md"]["source"], "engine-fallback")
            self.assertEqual(Path(rows["roles/qa.md"]["path"]), copy / "roles" / "_role.md")


class TemplatesListTest(Base):
    def test_the_row_is_last_with_the_same_layout(self):  # P82-AC-007
        rows = run_json("templates", "list", *self.R)[1]["data"]
        self.assertEqual([r["template"] for r in rows][-3:],
                         ["init/module_prompt.md", "init/routing_prompt.md", "choose/rules.md"])
        self.assertEqual(rows[-1], {"template": "choose/rules.md", "role": None,
                                    "source": "engine",
                                    "path": str(engine_templates() / "choose/rules.md")})
        out = run("templates", "list", *self.R)[1].splitlines()
        last = rows[-1]
        self.assertEqual(out[-1], f"{last['template']:<24} {last['source']:<24} {last['path']}")
        self.assertEqual([r["role"] for r in rows if r["role"]],
                         [r["template"][6:-3] for r in rows if r["role"]])


class OverrideTest(Base):
    def tree(self) -> list[str]:
        return sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*"))

    def test_the_override_sequence(self):  # P82-AC-008
        before = self.tree()
        code, out, err = run("templates", "override", "choose/rules.md", "--dry-run", *self.R)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.splitlines()[0],
                         f"would create  {REL}  (a copy of the engine template)")
        self.assertEqual(out.splitlines()[1], "next: edit it — from now on it wins over every "
                         "pack and engine template (modsys templates list)")
        code, env, err = run_json("templates", "override", "choose/rules.md", "--dry-run",
                                  *self.R)
        self.assertEqual(env["data"], {"template": "choose/rules.md", "file": REL,
                                       "from": "engine", "dry_run": True})
        self.assertEqual(self.tree(), before)
        applied_before = run("choose", "--apply", str(self.answer), "--json", *self.R)
        code, out, err = run("templates", "override", "choose/rules.md", *self.R)
        self.assertEqual((code, err), (0, ""))
        copy = self.root / REL
        self.assertEqual(copy.read_bytes(), ENGINE_FILE.read_bytes())
        self.assertEqual(self.row()["source"], "override")
        text = copy.read_text(encoding="utf-8").replace(
            "Choose the modules this task needs by meaning, in any language the task is "
            "written in.", "Pick by meaning only.")
        copy.write_text(text, encoding="utf-8")
        self.assertEqual(self.rules()[1], "Pick by meaning only.")
        self.assertEqual(run("choose", "--apply", str(self.answer), "--json", *self.R),
                         applied_before)
        edited = copy.read_bytes()
        code, out, err = run("templates", "override", "choose/rules.md", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(err, f"modsys: error: {REL} already exists — edit it\n")
        self.assertEqual(copy.read_bytes(), edited)
        code, out, err = run("templates", "override", "choose/nosuch.md", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("unknown template 'choose/nosuch.md' (templates: MODULE.md, ", err)
        self.assertTrue(err.rstrip().endswith(", choose/rules.md)"))

    def test_a_pack_template_is_what_gets_copied(self):  # P82-AC-008
        self.pack("team", "- from team\n", 10)
        code, env, err = run_json("templates", "override", "choose/rules.md", *self.R)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(env["data"]["from"], "pack:team")
        self.assertEqual((self.root / REL).read_bytes(), b"- from team\n")


class DeterminismTest(Base):
    def twice(self) -> None:
        outputs = []
        for tmpdir in (self.tmp, Path(tempfile.mkdtemp(dir=self.tmp))):
            cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                with mock.patch.dict(os.environ, {"TMPDIR": str(tmpdir)}):
                    outputs.append(tuple(run("choose", "--task-file", str(self.task), *form,
                                             *self.R) for form in ((), ("--json",))))
            finally:
                os.chdir(cwd)
        self.assertEqual(outputs[0], outputs[1])
        for code, out, err in outputs[0]:
            self.assertEqual((code, err), (0, ""))
            self.assertNotIn("overrides", out)
            self.assertNotIn("packs/", out)
            self.assertNotIn(str(self.tmp), out)

    def test_engine_override_and_pack_templates(self):  # P82-AC-012
        self.twice()
        self.pack("team", "- from team $max_picks\n")
        self.twice()
        self.override("- from override $depth\n")
        self.twice()


class PackagingTest(unittest.TestCase):
    def test_the_choose_glob_is_package_data(self):  # P82-AC-013
        data = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml")
                             .read_text(encoding="utf-8"))
        self.assertIn("defaults/templates/choose/*.md",
                      data["tool"]["setuptools"]["package-data"]["modsys"])


if __name__ == "__main__":
    unittest.main()
