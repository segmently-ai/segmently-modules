"""`segmently-modules sync-instructions` (D4): per module a change touches — or per named module — the docs
to update, the drift findings, the field `sync_hint`s of every layer and the queued proposals;
the core fields' hints; the verb in the contract (25 verbs)."""
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from segmently_modules.cli import build_parser
from segmently_modules.fields import CORE_FIELDS
from tests.helpers import copy_fixture, git, init_git, mutate_registry, run, run_json
from tests.test_cli_contract import GOLDEN

ENGINE = Path(__file__).resolve().parents[1]
CATALOG_DOCS = ["modules/catalog/MODULE.md", "modules/catalog/roles/developer.md",
                "modules/catalog/roles/qa.md"]
HAND_EDITED = {"description", "status", "keywords", "context_files", "related_modules",
               "submodules", "negative_keywords", "required_combinations"}


class SyncInstructionsRepo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        self.R = ("--root", str(self.root))
        init_git(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def ok(self, *argv) -> dict:
        code, env, err = run_json("sync-instructions", *argv, *self.R)
        self.assertEqual((code, err), (0, ""), env)
        self.assertEqual(set(env), {"schema", "data"})
        self.assertEqual(env["schema"], "segmently-modules.sync-instructions/1")
        return env["data"]

    def refused(self, *argv) -> str:
        code, out, err = run("sync-instructions", *argv, "--json", *self.R)
        self.assertEqual((code, out), (2, ""))
        return err

    def commit(self, message: str = "change") -> None:
        git(self.root, "add", "--", ".")
        git(self.root, "commit", "-q", "-m", message)

    def change_catalog_code(self) -> None:
        path = self.root / "src/catalog/service.py"
        path.write_text(path.read_text() + "\nLIMIT = 10\n")
        self.commit()


class ModesTest(SyncInstructionsRepo):  # P4B-AC-011
    def test_from_diff(self):
        self.change_catalog_code()
        data = self.ok("--from-diff", "HEAD~1..HEAD")
        self.assertEqual(data["files_outside_modules"], [])
        [row] = data["modules"]
        self.assertEqual((row["module"], row["usage"], row["docs_to_update"],
                          row["proposals_pending"]), ("catalog", "modify", CATALOG_DOCS, 0))
        self.assertEqual(row["drift"], [{"code": "MS050", "severity": "warning", "path": None,
                                         "message": "code changed (1 file(s)) but none of its "
                                                    "docs"}])
        self.assertEqual(sorted(row), ["docs_to_update", "drift", "fields", "module",
                                       "proposals_pending", "usage"])
        discover = run_json("discover", "--from-diff", "HEAD~1..HEAD", *self.R)[1]["data"]
        self.assertEqual([(m["module"], m["docs_to_update"]) for m in discover["modules"]],
                         [(r["module"], r["docs_to_update"]) for r in data["modules"]])

    def test_files(self):
        (self.root / "other.txt").write_text("x\n")
        data = self.ok("--files", "src/catalog/service.py", "other.txt")
        self.assertEqual(([m["module"] for m in data["modules"]], data["files_outside_modules"]),
                         (["catalog"], ["other.txt"]))
        discover = run_json("discover", "--files", "src/catalog/service.py", "other.txt",
                            *self.R)[1]["data"]
        self.assertEqual(data["modules"][0]["docs_to_update"],
                         discover["modules"][0]["docs_to_update"])

    def test_named_modules(self):
        legacy = self.root / "modules/catalog/MODULE.legacy.md"
        legacy.write_text("# Catalog (before the split)\n")
        mutate_registry(self.root, lambda d: d["modules"]["catalog"]["context_files"].update(
            history="modules/catalog/MODULE.legacy.md"))
        data = self.ok("--module", "catalog", "--module", "payments/refunds")
        self.assertEqual([(m["module"], m["usage"], m["drift"]) for m in data["modules"]],
                         [("catalog", "modify", []), ("payments/refunds", "modify", [])])
        self.assertEqual(data["modules"][0]["docs_to_update"],
                         CATALOG_DOCS + ["modules/catalog/roles/designer.md"])
        self.assertEqual(data["modules"][1]["docs_to_update"], [
            "modules/payments/MODULE.md", "modules/payments/submodules/refunds/MODULE.md",
            "modules/payments/submodules/refunds/roles/developer.md",
            "modules/payments/roles/developer.md"])
        self.assertEqual(data["files_outside_modules"], [])

    def test_no_change_and_the_text(self):
        self.assertEqual(self.ok("--from-diff", "HEAD..HEAD"),
                         {"modules": [], "files_outside_modules": []})
        self.assertEqual(run("sync-instructions", "--from-diff", "HEAD..HEAD", *self.R),
                         (0, "nothing to sync\n", ""))
        self.change_catalog_code()
        lines = run("sync-instructions", "--from-diff", "HEAD~1..HEAD", *self.R)[1].splitlines()
        self.assertEqual(lines[:5], ["catalog  modify",
                                     "  update  modules/catalog/MODULE.md",
                                     "  update  modules/catalog/roles/developer.md",
                                     "  update  modules/catalog/roles/qa.md",
                                     "  drift   MS050 code changed (1 file(s)) but none of its "
                                     "docs"])
        self.assertIn(f"  field   keywords — {CORE_FIELDS['keywords'].sync_hint}", lines)

    def test_the_queued_and_outside_lines(self):  # fix wave P-a
        code, _, err = run("propose", "--run-id", "r1", "--module", "catalog", "--op", "append",
                           "--field", "keywords", "--value", '"shelf"', "--reason", "new words",
                           *self.R)
        self.assertEqual((code, err), (0, ""))
        (self.root / "other.txt").write_text("x\n")
        code, out, err = run("sync-instructions", "--files", "src/catalog/service.py",
                             "other.txt", *self.R)
        self.assertEqual((code, err), (0, ""))
        lines = out.splitlines()
        self.assertEqual(lines[0], "catalog  modify")
        self.assertIn("  queued  1 proposal item(s) — segmently-modules proposals list", lines)
        self.assertEqual(lines[-1], "outside   other.txt")
        row = next(line for line in (ENGINE / "docs/cli-contract.md").read_text(
            encoding="utf-8").splitlines() if line.startswith("| `sync-instructions` |"))
        text = row.split("Text:", 1)[1]
        for kind in ("`  queued  <n> proposal item(s) — segmently-modules proposals list`",
                     "`outside   <path>`"):
            self.assertIn(kind, text)

    def test_usage_errors(self):
        for argv, needle in [((), "one of the arguments --from-diff --files --module is "
                                  "required"),
                             (("--module", "catalog", "--files", "x.py"),
                              "not allowed with argument"),
                             (("--module", "nosuch"), "segmently-modules: error: unknown module 'nosuch'")]:
            with self.subTest(argv=argv):
                self.assertIn(needle, self.refused(*argv))

    def test_outside_a_work_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            argv = ("--from-diff", "HEAD~1..HEAD", "--json", "--root", str(root))
            ours = run("sync-instructions", *argv)
            theirs = run("discover", *argv)
            self.assertEqual((ours[0], ours[1]), (2, ""))
            self.assertEqual(ours[2], theirs[2])
            self.assertIn("segmently-modules: error: git diff --name-only HEAD~1..HEAD failed", ours[2])


class ContentTest(SyncInstructionsRepo):  # P4B-AC-012
    def fields(self, data: dict) -> dict[str, list]:
        return {m["module"]: [f["name"] for f in m["fields"]] for m in data["modules"]}

    def test_field_hints_of_every_layer_by_scope(self):
        team = self.root / ".segmently-modules/packs/team"
        team.mkdir(parents=True)
        (team / "pack.toml").write_text(
            'id = "team"\nversion = "0.1.0"\n[fields.owner_team]\ntype = "string"\n'
            'description = "Owning team"\nsync_hint = "Set it when the owning team changes."\n')
        (self.root / ".segmently-modules/config.toml").write_text(
            '[fields.review_notes]\ntype = "string"\nscope = ["submodule"]\n'
            'sync_hint = "Note what reviewers must re-check."\n'
            '[fields.plain]\ntype = "string"\n'
            '[fields.keywords]\nsync_hint = "Team words."\n')
        data = self.ok("--module", "catalog", "--module", "payments/refunds")
        core_top = [n for n, d in CORE_FIELDS.items() if d.sync_hint and "module" in d.scope]
        core_child = [n for n, d in CORE_FIELDS.items() if d.sync_hint and "submodule" in d.scope]
        self.assertEqual(self.fields(data), {"catalog": core_top + ["owner_team"],
                                             "payments/refunds": core_child + ["review_notes"]})
        catalog = {f["name"]: f for f in data["modules"][0]["fields"]}
        self.assertEqual(catalog["owner_team"], {"name": "owner_team", "type": ["string"],
                                                 "description": "Owning team",
                                                 "sync_hint": "Set it when the owning team "
                                                              "changes."})
        self.assertEqual(catalog["keywords"]["sync_hint"], "Team words.")
        self.assertEqual(catalog["keywords"]["type"], ["string[]"])

    def test_a_core_field_takes_only_a_sync_hint(self):
        (self.root / ".segmently-modules/config.toml").write_text(
            '[fields.keywords]\ntype = "string"\nsync_hint = "x"\n')
        self.assertIn("field 'keywords' (owner config) is a core field; it cannot be "
                      "redeclared (a layer may set its sync_hint only)",
                      self.refused("--module", "catalog"))

    def test_queued_proposals_count_per_module(self):
        for run_id in ("r1", "r2"):
            code, _, err = run("propose", "--run-id", run_id, "--module", "catalog", "--op",
                               "append", "--field", "keywords", "--value", f'"{run_id}"',
                               "--reason", "new words", *self.R)
            self.assertEqual((code, err), (0, ""))
        data = self.ok("--module", "catalog", "--module", "payments/refunds")
        self.assertEqual([m["proposals_pending"] for m in data["modules"]], [2, 0])

    def test_drift_only_in_its_own_row(self):
        legacy = self.root / "modules/payments/submodules/refunds/MODULE.legacy.md"
        legacy.write_text("# Refunds (frozen)\n")
        self.commit("freeze")
        legacy.write_text("# Refunds (edited by mistake)\n")
        (self.root / "modules/checkout/MODULE.md").write_text("# Checkout\n\nUpdated.\n")
        path = self.root / "src/catalog/service.py"
        path.write_text(path.read_text() + "\nLIMIT = 10\n")
        self.commit()
        data = self.ok("--from-diff", "HEAD~1..HEAD")
        drift = {m["module"]: [(f["code"], f["path"]) for f in m["drift"]]
                 for m in data["modules"]}
        self.assertEqual(drift, {"catalog": [("MS050", None)], "checkout": [],
                                 "payments/refunds": [("MS051", "modules/payments/submodules/"
                                                                "refunds/MODULE.legacy.md")]})
        files = self.ok("--files", "modules/payments/submodules/refunds/MODULE.legacy.md")
        self.assertEqual(files["modules"][0]["drift"], [])  # a file list: no MS051


class CoreHintsTest(unittest.TestCase):  # P4B-AC-013
    def test_every_hand_edited_core_field_has_a_hint(self):
        for name, fdef in CORE_FIELDS.items():
            with self.subTest(field=name):
                if name in HAND_EDITED:
                    self.assertTrue(1 <= len(fdef.sync_hint) <= 200, fdef.sync_hint)
                    self.assertTrue(fdef.sync_hint[0].isupper() and fdef.sync_hint[-1] == ".")
                else:
                    self.assertEqual(fdef.sync_hint, "")
        self.assertEqual(set(CORE_FIELDS) - HAND_EDITED, {"name"})

    def test_the_docs_table_equals_the_engine(self):
        text = (ENGINE / "docs/configuration.md").read_text(encoding="utf-8")
        table = text.split("| Core field | `sync_hint` |", 1)[1].split("\n\n", 1)[0]
        rows = dict(re.findall(r"^\| `(\w+)` \| (.+) \|$", table, re.M))
        self.assertEqual(rows, {n: d.sync_hint for n, d in CORE_FIELDS.items() if d.sync_hint})


class ContractTest(SyncInstructionsRepo):  # P4B-AC-024, P4B-AC-023 (25 verbs)
    def test_garbage_config_interrupt_and_internal_error(self):
        (self.root / ".segmently-modules/config.toml").write_text("[packs]\nbuiltin = 5\n")
        err = self.refused("--module", "catalog")
        self.assertTrue(err.startswith("segmently-modules: error: "), err)
        self.assertIn(".segmently-modules/config.toml: [packs] builtin", err)
        (self.root / ".segmently-modules/config.toml").unlink()
        with mock.patch("segmently_modules.sync_instructions_cmd.build", side_effect=KeyboardInterrupt):
            self.assertEqual(run("sync-instructions", "--module", "catalog", *self.R),
                             (130, "", "segmently-modules: interrupted\n"))
        with mock.patch("segmently_modules.sync_instructions_cmd.build", side_effect=ValueError("boom")):
            code, out, err = run("sync-instructions", "--module", "catalog", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("segmently-modules: internal error: ValueError: boom"), err)
        self.assertNotIn("Traceback", err)

    def test_twenty_five_verbs_everywhere(self):
        parser = set(build_parser()._subparsers._group_actions[0].choices)
        contract = set(re.findall(r"^\| `([a-z-]+)", (ENGINE / "docs/cli-contract.md").read_text(
            encoding="utf-8"), re.M))
        self.assertEqual((parser, {argv[0] for argv, _ in GOLDEN}),
                         (contract, contract))  # the count: 26 (P5a, test_adopt)
        self.assertIn("sync-instructions", parser)


if __name__ == "__main__":
    unittest.main()
