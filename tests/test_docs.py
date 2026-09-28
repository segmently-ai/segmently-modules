"""The user docs stay true to the engine: every config key and lint code is documented, and
every `modsys …` command in a doc's code blocks uses a real verb and real flags."""
import re
import shlex
import unittest
from pathlib import Path

from modsys.changes import CODE_MAP_SCHEMA
from modsys.cli import build_parser
from modsys.config import LAYER_SCHEMA, PACK_META_KEYS, ROLE_SCHEMA
from modsys.fields import CORE_FIELDS, DECLARATION_KEYS
from modsys.hooks import HOOK_SCHEMA

ENGINE = Path(__file__).resolve().parents[1]
CONFIG_DOC = ENGINE / "docs" / "configuration.md"
USER_DOCS = [ENGINE / "README.md", ENGINE / "docs" / "configuration.md",
             ENGINE / "docs" / "cli-contract.md", ENGINE / "docs" / "writing-a-pack.md",
             ENGINE / "docs" / "skills.md", ENGINE / "docs" / "init.md"]  # P5b D12: + init.md
_FENCE = re.compile(r"^([ \t]*)(`{3,})[^\n]*\n(.*?)^\1\2\s*$", re.M | re.S)


def verbs() -> dict:
    return build_parser()._subparsers._group_actions[0].choices


def commands(text: str) -> list[list[str]]:
    """`modsys VERB …` command lines from the fenced code blocks (continuations joined)."""
    out = []
    for block in _FENCE.finditer(text):
        for line in block.group(3).replace("\\\n", " ").splitlines():
            line = line.strip()
            if line.startswith("modsys ") and not line.startswith("modsys -"):
                out.append(shlex.split(line.split(" #")[0].split("<<")[0]))
    return out


class ConfigDocTest(unittest.TestCase):
    def test_every_config_key_is_documented(self):
        doc = CONFIG_DOC.read_text(encoding="utf-8")
        keys = {k for schema in LAYER_SCHEMA.values() for k in schema}
        keys |= set(ROLE_SCHEMA) | set(CODE_MAP_SCHEMA) | set(HOOK_SCHEMA)
        keys |= (DECLARATION_KEYS - {"owner"}) | (PACK_META_KEYS) | set(CORE_FIELDS)
        missing = sorted(k for k in keys if f"`{k}`" not in doc)
        self.assertEqual(missing, [])
        for section in LAYER_SCHEMA:
            self.assertIn(f"## `[{section}]`", doc)

    def test_every_lint_code_is_in_the_table(self):
        source = "".join((ENGINE / "modsys" / f).read_text(encoding="utf-8")
                         for f in ("lint.py", "rules.py"))
        emitted = set(re.findall(r"MS\d{3}", source))
        documented = set(re.findall(r"^\| (MS\d{3}) \|", CONFIG_DOC.read_text(encoding="utf-8"),
                                    re.M))
        self.assertEqual(emitted, documented)

    def test_a_ci_gate_is_pointed_to_modsys_ci_not_a_separate_plain_lint(self):  # M-7
        doc = CONFIG_DOC.read_text(encoding="utf-8")
        self.assertNotIn("a CI gate must also run plain `modsys lint --fail-on warning`", doc)
        self.assertNotIn("run plain\n`modsys lint --fail-on warning` too", doc)
        self.assertIn("modsys ci", doc)


class CommandsInDocsTest(unittest.TestCase):
    def test_commands_use_real_verbs_and_flags(self):
        choices = verbs()
        seen = 0
        for doc in USER_DOCS:
            for argv in commands(doc.read_text(encoding="utf-8")):
                with self.subTest(doc=doc.name, argv=argv):
                    self.assertIn(argv[1], choices)
                    flags = {s for a in choices[argv[1]]._actions for s in a.option_strings}
                    used = {a.split("=")[0] for a in argv[2:] if a.startswith("--")}
                    self.assertEqual(used - flags, set())
                    seen += 1
        self.assertGreaterEqual(seen, 15)

    def test_readme_walks_through_init_coverage_and_the_gate(self):
        used = {argv[1] for argv in commands((ENGINE / "README.md").read_text(encoding="utf-8"))}
        self.assertTrue({"init", "create", "registry", "lint", "coverage", "context", "propose",
                         "sync", "index"} <= used)


if __name__ == "__main__":
    unittest.main()
