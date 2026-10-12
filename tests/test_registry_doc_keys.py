"""`modsys registry OP TARGET context_files.<key> [VALUE]`: one doc key of a module's
`context_files` — a supplementary doc registered in one command, without rewriting universal and
roles. `universal` is one path (set / unset); `roles` belongs to `roles add` / `roles skip`; a new
path must exist on disk (lint MS004)."""
import json
import tempfile
import unittest

from tests.helpers import copy_fixture, run, run_json

KEY = "context_files.supplementary"


class DocKeyTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        for name in ("history.md", "api.md"):
            (self.root / "modules/catalog" / name).write_text(f"# {name}\n", encoding="utf-8")
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def reg(self, *argv) -> dict:
        code, env, err = run_json("registry", *argv, *self.R)
        self.assertEqual((code, err), (0, ""))
        return env["data"]

    def refused(self, *argv) -> str:
        before = (self.root / "modules/registry.json").read_bytes()
        code, out, err = run("registry", *argv, *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertEqual((self.root / "modules/registry.json").read_bytes(), before)
        return err

    def cf(self, target: str = "catalog") -> dict:
        data = json.loads((self.root / "modules/registry.json").read_text(encoding="utf-8"))
        parent, _, child = target.partition("/")
        entry = data["modules"][parent]
        return (entry["submodules"][child] if child else entry)["context_files"]

    def test_append_remove_and_the_rest_stays(self):
        before = self.cf()
        self.assertTrue(self.reg("append", "catalog", KEY, '"modules/catalog/history.md"')
                        ["changed"])
        self.assertFalse(self.reg("append", "catalog", KEY, '"modules/catalog/history.md"')
                         ["changed"])
        self.reg("append", "catalog", KEY, '"modules/catalog/api.md"')
        self.assertEqual(self.cf(), {**before, "supplementary": ["modules/catalog/history.md",
                                                                 "modules/catalog/api.md"]})
        self.reg("remove", "catalog", KEY, '"modules/catalog/history.md"')
        self.assertEqual(self.cf()["supplementary"], ["modules/catalog/api.md"])
        self.reg("remove", "catalog", KEY, '"modules/catalog/api.md"')
        self.assertEqual(self.cf(), before)  # the key goes with its last path
        code, _env, err = run_json("lint", *self.R)
        self.assertEqual((code, err), (0, ""))

    def test_set_unset_a_single_path_and_a_child(self):
        self.reg("set", "catalog", "context_files.history", '"modules/catalog/history.md"')
        self.assertEqual(self.cf()["history"], "modules/catalog/history.md")
        self.reg("append", "catalog", "context_files.history", '"modules/catalog/api.md"')
        self.assertEqual(self.cf()["history"], ["modules/catalog/history.md",
                                                "modules/catalog/api.md"])
        self.reg("unset", "catalog", "context_files.history")
        self.assertNotIn("history", self.cf())
        self.reg("append", "payments/refunds", KEY, '"modules/catalog/api.md"')
        self.assertEqual(self.cf("payments/refunds")[KEY.split(".")[1]], ["modules/catalog/api.md"])

    def test_a_dry_run_shows_the_diff(self):
        data = self.reg("append", "catalog", KEY, '"modules/catalog/history.md"', "--dry-run")
        self.assertTrue(data["changed"])
        self.assertIn('+        "supplementary": [', data["diff"])
        self.assertNotIn("supplementary", self.cf())

    def test_refusals(self):
        for argv, why in (
                (("append", "catalog", KEY, '"modules/catalog/nope.md"'),
                 "context_files.supplementary: modules/catalog/nope.md is missing on disk "
                 "(lint MS004) — write the doc first"),
                (("set", "catalog", "context_files.roles", '{"qa": false}'),
                 "role docs are written by modsys roles add ROLE TARGET"),
                (("append", "catalog", "context_files.universal", '"modules/catalog/api.md"'),
                 "context_files.universal is one path; use set"),
                (("set", "catalog", "context_files.universal", '["modules/catalog/api.md"]'),
                 "context_files.universal takes a doc path, got"),
                (("set", "catalog", KEY, '["modules/catalog/api.md", "modules/catalog/api.md"]'),
                 "takes a doc path or a list of distinct doc paths"),
                (("append", "catalog", KEY, '5'), "append context_files.supplementary takes one "
                                                  "doc path, got 5"),
                (("set", "catalog", "context_files.", '"modules/catalog/api.md"'),
                 "'context_files.' names no key")):
            with self.subTest(argv=argv):
                self.assertIn(why, self.refused(*argv))


if __name__ == "__main__":
    unittest.main()
