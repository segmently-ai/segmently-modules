"""Golden headless contract: malformed config, packs, registry or docs never produce a
traceback. Errors are exit 2 with `segmently-modules: error: …` on stderr and nothing on stdout;
malformed registry entries are lint's job to report, read verbs tolerate them."""
import json
import os
import tempfile
import unittest
from unittest import mock

from tests.helpers import copy_fixture, mutate_registry, run

VERBS = [("schema",), ("match", "book listing"), ("show", "catalog"), ("related", "catalog"),
         ("list",), ("lint", "--fail-on", "never")]
REGISTRY_VERBS = [v for v in VERBS if v[0] != "schema"]  # schema never reads the registry

CONFIG_CASES = [
    '[match]\ntop = "8"\n',
    'match = 5\n',
    '[registry]\nstatuses = "active"\n',
    '[registry]\nstub_pattern = "("\n',
    '[roles]\ndesigner = true\n',
    '[roles.designer]\norder = "50"\n',
    '[fields]\nx = "string"\n',
    '[fields.x]\ntype = 5\n',
    '[fields.x]\ntyp = "string"\n',
    '[fields.x]\ntype = "string"\nkind = "code-pointer"\n',
    '[match]\ntop = -1\n',
]

REGISTRY_CASES = [
    lambda d: d["modules"]["catalog"].update(related_modules=["checkout"]),
    lambda d: d["modules"]["catalog"].update(context_files=["modules/catalog/MODULE.md"]),
    lambda d: d["modules"]["catalog"]["context_files"].update(roles=["x"]),
    lambda d: d["modules"].update(checkout="oops"),
    lambda d: d["modules"]["catalog"].update(keywords=["book", 5]),
    lambda d: d["modules"]["payments"].update(submodules=["refunds"]),
    lambda d: d["modules"]["catalog"].update(description=5),
]


def run_verb(verb, root, *extra):
    return run(*verb, "--root", str(root), *extra)


class ContractTest(unittest.TestCase):
    def assertUsageError(self, code, out, err):
        self.assertEqual(code, 2, err)
        self.assertEqual(out, "")
        self.assertTrue(err.startswith("segmently-modules: error:"), err)
        self.assertNotIn("Traceback", err)

    def test_invalid_config_layers_are_usage_errors(self):
        for text in CONFIG_CASES:
            with tempfile.TemporaryDirectory() as tmp:
                root = copy_fixture(tmp)
                (root / ".segmently-modules" / "config.toml").write_text(text, encoding="utf-8")
                for verb in VERBS:
                    with self.subTest(config=text, verb=verb[0]):
                        code, out, err = run_verb(verb, root, "--json")
                        self.assertUsageError(code, out, err)
                        if text.startswith("[fields"):
                            self.assertTrue("field 'x'" in err or "[fields.x]" in err, err)
                        else:
                            self.assertIn("config.toml", err)

    def test_invalid_pack_meta_is_usage_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            pack = root / ".segmently-modules" / "packs" / "bad" / "pack.toml"
            pack.parent.mkdir(parents=True)
            pack.write_text('id = "bad"\npriority = "high"\n', encoding="utf-8")
            for verb in VERBS:
                with self.subTest(verb=verb[0]):
                    code, out, err = run_verb(verb, root, "--json")
                    self.assertUsageError(code, out, err)
                    self.assertIn("pack.toml", err)

    def test_malformed_registry_entries_are_lint_findings(self):
        for n, mutation in enumerate(REGISTRY_CASES):
            with tempfile.TemporaryDirectory() as tmp:
                root = copy_fixture(tmp)
                mutate_registry(root, mutation)
                with self.subTest(case=n, verb="lint"):
                    code, out, err = run_verb(("lint", "--fail-on", "never"), root, "--json")
                    self.assertEqual(code, 0, err)
                    env = json.loads(out)
                    self.assertEqual(env["schema"], "segmently-modules.lint/1")
                    self.assertIn("MS013", {f["code"] for f in env["data"]["findings"]})
                for verb in VERBS[:-1]:
                    for extra in (("--json",), ()):
                        with self.subTest(case=n, verb=verb[0], extra=extra):
                            code, _, err = run_verb(verb, root, *extra)
                            self.assertIn(code, (0, 1, 2))
                            self.assertNotIn("internal error", err)
                            self.assertNotIn("Traceback", err)

    def test_read_verbs_on_non_object_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            mutate_registry(root, lambda d: (
                d["modules"].update(checkout="oops"),
                d["modules"]["payments"]["submodules"].update(refunds=5),
                d["modules"]["catalog"]["related_modules"][0].pop("relation")))
            for verb, label in [(("show", "checkout"), "checkout"),
                                (("related", "checkout"), "checkout"),
                                (("show", "payments/refunds"), "payments/refunds")]:
                with self.subTest(verb=verb):
                    code, out, err = run_verb(verb, root, "--json")
                    self.assertUsageError(code, out, err)
                    self.assertIn(f"registry entry '{label}' is not an object", err)
            code, out, err = run_verb(("list",), root, "--json")
            self.assertEqual(code, 0, err)
            rows = {r["module"]: r for r in json.loads(out)["data"]}
            self.assertEqual(rows["checkout"], {"module": "checkout", "status": None,
                                                "description": "", "children": ""})
            for verb in (("list",), ("related", "catalog"), ("show", "payments")):
                with self.subTest(verb=verb, mode="text"):
                    code, _, err = run_verb(verb, root)
                    self.assertEqual((code, err), (0, ""))

    def test_non_utf8_registry_is_usage_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            (root / "modules" / "registry.json").write_bytes(b'{"modules": {"\xff": {}}}')
            for verb in REGISTRY_VERBS:
                with self.subTest(verb=verb[0]):
                    code, out, err = run_verb(verb, root, "--json")
                    self.assertUsageError(code, out, err)
                    self.assertIn("not valid UTF-8", err)

    def test_non_utf8_docs_are_tolerated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            (root / "modules" / "catalog" / "MODULE.md").write_bytes(b"\xff\xfe# x\n")
            (root / "modules" / "ghost").mkdir()  # unregistered dir: read by the stub check
            (root / "modules" / "ghost" / "MODULE.md").write_bytes(b"\xff\xfe# x\n")
            code, out, err = run_verb(("lint", "--fail-on", "never"), root, "--json")
            self.assertEqual(code, 0, err)
            self.assertIn("MS014", {f["code"] for f in json.loads(out)["data"]["findings"]})
            self.assertNotIn("internal error", err)
            code, _, err = run_verb(("show", "catalog"), root, "--json")
            self.assertEqual(code, 0, err)
            self.assertNotIn("internal error", err)
            code, out, err = run_verb(("show", "ghost"), root, "--json")
            self.assertUsageError(code, out, err)
            self.assertIn("unknown module", err)

    def test_negative_top_is_usage_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            code, out, err = run_verb(("match", "book listing", "--top", "-1"), root, "--json")
        self.assertUsageError(code, out, err)
        self.assertIn("--top must be >= 0", err)

    def test_unexpected_exception_is_exit_2_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            with mock.patch("segmently_modules.query.list_modules", side_effect=RuntimeError("boom")):
                with mock.patch.dict(os.environ):
                    os.environ.pop("SEGMENTLY_MODULES_DEBUG", None)
                    code, out, err = run("list", "--root", str(root))
                self.assertEqual((code, out), (2, ""))
                self.assertIn("internal error: RuntimeError: boom", err)
                self.assertNotIn("Traceback", err)
                with mock.patch.dict(os.environ, {"SEGMENTLY_MODULES_DEBUG": "1"}):
                    with self.assertRaises(RuntimeError):
                        run("list", "--root", str(root))


if __name__ == "__main__":
    unittest.main()
