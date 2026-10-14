import tempfile
import unittest

from tests.helpers import FIXTURE, copy_fixture, mutate_registry, run, run_json


def codes(env):
    return {(f["code"], f["severity"]) for f in env["data"]["findings"]}


CASES = [
    ("MS001", "error", lambda d: d["modules"]["catalog"].pop("status")),
    ("MS003", "error", lambda d: d["modules"]["checkout"].update(status="wip")),
    ("MS004", "error", lambda d: d["modules"]["checkout"]["context_files"].update(
        universal="modules/checkout/NOPE.md")),
    ("MS006", "error", lambda d: d["modules"]["catalog"]["related_modules"][0].update(
        relation="uses")),
    ("MS010", "error", lambda d: d["modules"]["checkout"]["related_modules"][0].update(
        module="payments/nochild")),
    ("MS011", "error", lambda d: d["modules"]["catalog"].update(depends_on_modules=["checkout"])),
    ("MS012", "warning", lambda d: d["modules"]["payments"].update(owner_team="books")),
    ("MS013", "error", lambda d: d["modules"]["catalog"].update(keywords="catalog")),
    # AC-025 remaining codes (appended so CASES[1] / CASES[6] indices stay stable)
    ("MS002", "error", lambda d: d["modules"]["checkout"].update(name="cart")),
    ("MS004", "error", lambda d: d["modules"]["checkout"]["context_files"]["roles"].update(
        developer=["modules/checkout/roles/developer.md", 5])),
    ("MS007", "error", lambda d: d["modules"]["catalog"]["related_modules"][0].pop("description")),
    ("MS008", "error", lambda d: d["modules"]["catalog"]["related_modules"][0].pop("module")),
    ("MS009", "error", lambda d: d["modules"]["catalog"]["related_modules"][0].update(module="nope")),
]


def lint_codes(root):
    _, env, _ = run_json("lint", "--root", str(root), "--fail-on", "never")
    return codes(env)


class LintGapTest(unittest.TestCase):  # AC-025 … AC-029
    def test_whitelisted_and_stub_dirs_are_not_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            (root / ".segmently-modules" / "config.toml").write_text('[registry]\ndir_whitelist = ["scratch"]\n')
            (root / "modules" / "scratch").mkdir()
            self.assertNotIn(("MS014", "error"), lint_codes(root))  # legacy-search stub too

    def test_doc_budget_boundaries(self):  # AC-026
        cases = [("modules/checkout/MODULE.md", 600, None),
                 ("modules/checkout/MODULE.md", 1000, ("MS030", "warning")),
                 ("modules/checkout/roles/developer.md", 600, None),
                 ("modules/checkout/roles/developer.md", 601, ("MS032", "warning"))]
        for rel, lines, expected in cases:
            with self.subTest(rel=rel, lines=lines), tempfile.TemporaryDirectory() as tmp:
                root = copy_fixture(tmp)
                (root / rel).write_text("line\n" * lines)
                got = {c for c in lint_codes(root) if c[0] in ("MS030", "MS031", "MS032")}
                self.assertEqual(got, {expected} if expected else set())

    def test_keyword_budget_boundaries(self):  # AC-026
        many = [f"kw{i}" for i in range(41)]
        cases = [(lambda d: d["modules"]["catalog"].update(keywords=many[:40]), set()),
                 (lambda d: d["modules"]["catalog"].update(keywords=many), {("MS020", "info")}),
                 (lambda d: d["modules"]["payments"].update(keywords=many), set())]  # split parent
        for mutation, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as tmp:
                root = copy_fixture(tmp)
                mutate_registry(root, mutation)
                self.assertEqual({c for c in lint_codes(root) if c[0] == "MS020"}, expected)

    def test_keyword_shared_threshold(self):  # AC-026 (threshold N-1 vs N)
        for holders, expected in [(("catalog",), set()),
                                  (("catalog", "payments"), {("MS021", "info")})]:
            with self.subTest(holders=holders), tempfile.TemporaryDirectory() as tmp:
                root = copy_fixture(tmp)
                (root / ".segmently-modules" / "config.toml").write_text("[budgets]\nkeyword_shared_warn = 3\n")
                mutate_registry(root, lambda d: [d["modules"][m]["keywords"].append("order")
                                                 for m in holders])
                self.assertEqual({c for c in lint_codes(root) if c[0] == "MS021"}, expected)

    def test_component_table_variants(self):  # AC-027
        extra = ("| Anchor | `src/catalog/service.py#L10` | ok |\n"
                 "| Glob | `src/**/*.py` | ignored |\n"
                 "| Url | `https://example.com/x` | ignored |\n"
                 "| Symbol | `BookRepository` | ignored |\n"
                 "\n## Other\n\n| Name | Path |\n|---|---|\n| Nope | `src/nope/x.py` |\n")
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            with (root / "modules" / "catalog" / "MODULE.md").open("a") as fh:
                fh.write(extra)
            self.assertNotIn(("MS040", "warning"), lint_codes(root))
            (root / ".segmently-modules" / "config.toml").write_text(
                '[lint]\ncomponent_table_heading = "Other"\n')
            self.assertIn(("MS040", "warning"), lint_codes(root))

    def test_fail_on_matrix(self):  # AC-028
        mutations = {
            "info": lambda d: d["modules"]["catalog"].update(keywords=[f"kw{i}" for i in range(41)]),
            "warning": CASES[6][2],   # MS012
            "error": CASES[1][2],     # MS003
        }
        expected = {("info", "error"): 0, ("info", "warning"): 0, ("info", "never"): 0,
                    ("warning", "error"): 0, ("warning", "warning"): 1, ("warning", "never"): 0,
                    ("error", "error"): 1, ("error", "warning"): 1, ("error", "never"): 0}
        for (scenario, fail_on), exit_code in expected.items():
            with self.subTest(scenario=scenario, fail_on=fail_on), \
                    tempfile.TemporaryDirectory() as tmp:
                root = copy_fixture(tmp)
                mutate_registry(root, mutations[scenario])
                code, env, _ = run_json("lint", "--root", str(root), "--fail-on", fail_on)
                self.assertEqual(code, exit_code)
                self.assertEqual(env["data"]["failed"], exit_code == 1)

    def test_invalid_fail_on_config(self):  # AC-029
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            (root / ".segmently-modules" / "config.toml").write_text('[lint]\nfail_on = "sometimes"\n')
            code, out, err = run("lint", "--root", str(root))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("never", err)


class LintTest(unittest.TestCase):
    def test_clean_fixture(self):
        code, env, _ = run_json("lint", "--root", str(FIXTURE))
        self.assertEqual(code, 0)
        self.assertEqual(env["data"]["summary"]["error"], 0)
        self.assertEqual(env["data"]["summary"]["warning"], 0)

    def test_registry_mutations(self):
        for code_, severity, mutation in CASES:
            with self.subTest(code_), tempfile.TemporaryDirectory() as tmp:
                root = copy_fixture(tmp)
                mutate_registry(root, mutation)
                _, env, _ = run_json("lint", "--root", str(root), "--fail-on", "never")
                self.assertIn((code_, severity), codes(env))

    def test_fail_on_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            mutate_registry(root, CASES[6][2])  # MS012 warning only
            self.assertEqual(run("lint", "--root", str(root))[0], 0)
            self.assertEqual(run("lint", "--root", str(root), "--fail-on", "warning")[0], 1)

    def test_disk_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            (root / "modules" / "orphan").mkdir()
            (root / "modules" / "orphan" / "MODULE.md").write_text("# Orphan\n")
            (root / "modules" / "checkout" / "MODULE.md").write_text("line\n" * 1001)
            (root / "modules" / "payments" / "MODULE.md").write_text("line\n" * 601)
            with (root / "modules" / "catalog" / "MODULE.md").open("a") as fh:
                fh.write("| Ghost | `src/catalog/missing.py:12` | gone |\n")
            _, env, _ = run_json("lint", "--root", str(root), "--fail-on", "never")
        got = codes(env)
        for expected in [("MS014", "error"), ("MS031", "error"), ("MS030", "warning"),
                         ("MS040", "warning")]:
            self.assertIn(expected, got)


class LintAdditionsTest(unittest.TestCase):  # MS015, MS022, MS040 alias/placeholder skip
    def test_unconfigured_role_is_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            mutate_registry(root, lambda d: d["modules"]["catalog"]["context_files"]["roles"].update(
                security="modules/catalog/roles/qa.md"))
            self.assertIn(("MS015", "warning"), lint_codes(root))

    def test_empty_keyword_is_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            mutate_registry(root, lambda d: d["modules"]["catalog"].update(keywords=["catalog", " "]))
            self.assertIn(("MS022", "warning"), lint_codes(root))

    def test_a_generic_keyword_is_info_unless_the_module_is_named_by_it(self):  # MS023
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            mutate_registry(root, lambda d: (
                d["modules"]["catalog"].update(keywords=["catalog", "book", "Searches", "users"]),
                d["modules"]["checkout"].update(keywords=["cart", "checkout", "order"])))
            _, env, _ = run_json("lint", "--root", str(root), "--fail-on", "never")
            rows = [(f["code"], f["severity"], f["module"], f["message"].split("'")[1])
                    for f in env["data"]["findings"] if f["code"] == "MS023"]
            self.assertEqual(rows, [("MS023", "info", "catalog", "Searches"),
                                    ("MS023", "info", "catalog", "users")])
            mutate_registry(root, lambda d: d["modules"]["catalog"].update(
                keywords=["catalog", "book", "catalogs"]))  # no generic word left
            self.assertNotIn(("MS023", "info"), lint_codes(root))

    def test_a_component_path_with_a_space_or_a_hash(self):  # MS040, 0.3.0
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            (root / "src/catalog/Custom cells").mkdir(parents=True)
            (root / "src/catalog/Custom cells/Row.py").write_text("x = 1\n")
            (root / "src/catalog/v#1.json").write_text("{}\n")
            with (root / "modules" / "catalog" / "MODULE.md").open("a") as fh:
                fh.write("| Row | `src/catalog/Custom cells/Row.py` | a |\n"
                         "| V1 | `src/catalog/v#1.json` | b |\n")
            self.assertNotIn(("MS040", "warning"), lint_codes(root))
            with (root / "modules" / "catalog" / "MODULE.md").open("a") as fh:
                fh.write("| Gone | `src/catalog/v#2.json` | c |\n")  # missing: cut at `#`
            _, env, _ = run_json("lint", "--root", str(root), "--fail-on", "never")
            found = [f["message"] for f in env["data"]["findings"] if f["code"] == "MS040"]
            self.assertEqual(len(found), 1, found)
            self.assertIn("src/catalog/v", found[0])

    def test_component_aliases_and_placeholders_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            with (root / "modules" / "catalog" / "MODULE.md").open("a") as fh:
                fh.write("| Alias | `@app/catalog/x.ts` | a |\n| Ph | `src/<name>/x.py` | p |\n")
            self.assertNotIn(("MS040", "warning"), lint_codes(root))


if __name__ == "__main__":
    unittest.main()
