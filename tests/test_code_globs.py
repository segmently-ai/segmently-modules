"""`show` / `context` report `code_globs`: the [[code_map]] globs that route files to a target."""
import tempfile
import unittest

from tests.helpers import copy_fixture, run, run_json

RULES = ('[[code_map]]\nid = "src"\npattern = "src/{module}/**"\n'
         '[[code_map]]\nid = "isbn"\nmodule = "catalog"\nglobs = ["lib/isbn.py", "src/catalog/**"]\n'
         '[[code_map]]\nid = "refunds"\nmodule = "payments/refunds"\nglobs = ["billing/refunds/**"]\n'
         '[[code_map]]\nid = "legacy"\nmodule = "checkout"\npattern = "legacy/{module}/cart/**"\n')


class CodeGlobsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def show(self, target):
        code, env, err = run_json("show", target, *self.R)
        self.assertEqual((code, err), (0, ""))
        return env["data"]

    def test_no_code_map_means_no_globs(self):
        data = self.show("catalog")
        self.assertEqual((data["code"], data["code_globs"]), (["src/catalog/service.py"], []))

    def test_globs_per_target(self):
        (self.root / ".modsys" / "config.toml").write_text(RULES, encoding="utf-8")
        catalog = self.show("catalog")
        self.assertEqual(catalog["code"], ["src/catalog/service.py"])  # code pointers, unchanged
        self.assertEqual(catalog["code_globs"], ["src/catalog/**", "lib/isbn.py"])
        self.assertEqual(self.show("checkout")["code_globs"],
                         ["src/checkout/**", "legacy/*/cart/**"])
        self.assertEqual(self.show("payments")["code_globs"], ["src/payments/**"])
        self.assertEqual(self.show("payments/refunds")["code_globs"], ["billing/refunds/**"])

    def test_context_rows_carry_code_globs(self):
        (self.root / ".modsys" / "config.toml").write_text(RULES, encoding="utf-8")
        code, env, _ = run_json("context", "--task", "isbn check digit", *self.R)
        self.assertEqual(code, 0)
        row = env["data"]["modules"][0]
        self.assertEqual((row["module"], row["code"], row["code_globs"]),
                         ("catalog", ["src/catalog/service.py"], ["src/catalog/**", "lib/isbn.py"]))

    def test_text_output_prints_globs_as_code_lines(self):
        (self.root / ".modsys" / "config.toml").write_text(RULES, encoding="utf-8")
        _, out, _ = run("show", "catalog", *self.R)
        self.assertIn("  code  src/catalog/service.py\n  code  src/catalog/**\n"
                      "  code  lib/isbn.py\n", out)
        _, out, _ = run("context", "--task", "isbn", *self.R)
        self.assertIn("lib/isbn.py", out)


if __name__ == "__main__":
    unittest.main()
