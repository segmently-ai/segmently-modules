"""Field-level writers: `modsys registry set|append|remove|unset`."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import modsys
from modsys.fields import load_field_defs
from modsys.writers import apply_field_op, entry_sha256
from tests.helpers import FIXTURE, copy_fixture, run, run_json


class RegistryVerbTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        self.path = self.root / "modules" / "registry.json"
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def reg(self):
        return json.loads(self.path.read_text(encoding="utf-8"))["modules"]

    def test_set_status_and_lint_stays_clean(self):
        code, env, _ = run_json("registry", "set", "catalog", "status", '"draft"', *self.R)
        self.assertEqual((code, env["schema"], env["data"]["changed"]), (0, "modsys.registry/1", True))
        self.assertEqual(self.reg()["catalog"]["status"], "draft")
        self.assertEqual(run("lint", *self.R)[0], 0)

    def test_type_mismatch_is_exit_2_and_file_unchanged(self):
        before = self.path.read_bytes()
        code, out, err = run("registry", "set", "catalog", "keywords", '"book"', *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("does not match field 'keywords' type string[]", err)
        self.assertEqual(self.path.read_bytes(), before)

    def test_append_dedupes_and_remove_drops(self):
        self.assertFalse(run_json("registry", "append", "catalog", "keywords", '"book"',
                                  *self.R)[1]["data"]["changed"])
        run("registry", "append", "catalog", "keywords", '"ebook"', *self.R)
        self.assertEqual(self.reg()["catalog"]["keywords"][-1], "ebook")
        run("registry", "remove", "catalog", "keywords", '"isbn"', *self.R)
        self.assertNotIn("isbn", self.reg()["catalog"]["keywords"])

    def test_unset_optional_and_refuse_required(self):
        run("registry", "unset", "catalog", "file_paths", *self.R)
        self.assertNotIn("file_paths", self.reg()["catalog"])
        code, _, err = run("registry", "unset", "catalog", "status", *self.R)
        self.assertEqual(code, 2)
        self.assertIn("required on module entries", err)

    def test_refusals_name_the_reason(self):
        cases = [(("set", "catalog", "owner_team", '"x"'), "unknown field 'owner_team'"),
                 (("set", "catalog", "depends_on_modules", '["checkout"]'), "deprecated"),
                 (("set", "payments/refunds", "status", '"draft"'), "not allowed on submodule"),
                 (("set", "catalog", "name", '"books"'), "structural"),
                 (("set", "nope", "status", '"draft"'), "unknown module 'nope'"),
                 (("set", "payments/nope", "keywords", '[]'), "not a submodule of 'payments'"),
                 (("set", "catalog", "status", "draft"), "not valid JSON"),
                 (("unset", "catalog", "file_paths", '"x"'), "unset takes no value"),
                 (("append", "catalog", "keywords"), "needs a JSON value")]
        for argv, needle in cases:
            with self.subTest(argv=argv):
                code, out, err = run("registry", *argv, *self.R)
                self.assertEqual((code, out), (2, ""))
                self.assertIn(needle, err)

    def test_submodule_field(self):
        run("registry", "append", "payments/refunds", "keywords", '"chargeback"', *self.R)
        self.assertIn("chargeback", self.reg()["payments"]["submodules"]["refunds"]["keywords"])

    def test_dry_run_prints_diff_and_writes_nothing(self):
        before = self.path.read_bytes()
        code, out, _ = run("registry", "set", "catalog", "status", '"draft"', "--dry-run", *self.R)
        self.assertEqual(code, 0)
        self.assertIn('-      "status": "active",', out)
        self.assertIn('+      "status": "draft",', out)
        self.assertEqual(self.path.read_bytes(), before)


class ApplyFieldOpTest(unittest.TestCase):
    def test_entry_hash_changes_only_with_the_entry(self):
        raw = json.loads((FIXTURE / "modules" / "registry.json").read_text(encoding="utf-8"))
        fields = load_field_defs({})
        h_catalog, h_checkout = entry_sha256(raw, "catalog"), entry_sha256(raw, "checkout")
        apply_field_op(raw, fields, "set", "checkout", "status", "draft",
                       vocab={"statuses": ["active", "draft"], "relations": []})
        self.assertEqual(entry_sha256(raw, "catalog"), h_catalog)
        self.assertNotEqual(entry_sha256(raw, "checkout"), h_checkout)


class ConcurrentWritersTest(unittest.TestCase):  # AC-005
    def test_two_concurrent_cli_writers_lose_nothing(self):
        engine = str(Path(modsys.__file__).resolve().parents[1])
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            env = {**os.environ, "PYTHONPATH": engine}
            procs = [subprocess.Popen([sys.executable, "-m", "modsys", "registry", "append",
                                       "catalog", "keywords", f'"{kw}"', "--root", str(root)],
                                      env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                     for kw in ("x1", "x2")]
            codes = [p.wait(timeout=30) for p in procs]
            for p in procs:
                p.stderr.close()
            keywords = json.loads((root / "modules/registry.json").read_text())[
                "modules"]["catalog"]["keywords"]
        self.assertEqual(codes, [0, 0])
        self.assertEqual((keywords.count("x1"), keywords.count("x2")), (1, 1))


if __name__ == "__main__":
    unittest.main()
