"""P8.1 task 1: a child's own description in `show` / `context` (F7), `related` of a child (F8),
repeated `--files` (F9), the `init` hint on a populated registry (F1), the `packs sync` note
for a directory git ignores (F14)."""
import tempfile
import unittest
from pathlib import Path

import os
from unittest import mock

from tests.helpers import FIXTURE, SPLIT_FIXTURE, copy_fixture, git, init_git, make_repo, \
    mutate_registry, run, run_json

REFUNDS = "Returned books: refund requests, partial refunds and restocking."
ORDERS = ("Order lifecycle for the bookshop, split into checkout, refunds and invoices. "
          "Start here for anything about a placed order.")
SKILL = "---\nname: api-review\ndescription: Review an API.\n---\n\n# api-review\n"


class SplitRepo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name, SPLIT_FIXTURE)
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()


class ChildDescriptionTest(SplitRepo):
    def test_show_child_has_its_own_description(self):  # P81-AC-001
        code, env, err = run_json("show", "orders/refunds", *self.R)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(env["data"]["description"], REFUNDS)
        code, out, _ = run("show", "orders/refunds", *self.R)
        self.assertEqual(code, 0)
        self.assertIn(REFUNDS, out)
        self.assertNotIn("Start here", out)

    def test_show_parent_keeps_its_description(self):
        _, env, _ = run_json("show", "orders", *self.R)
        self.assertEqual(env["data"]["description"], ORDERS)

    def test_child_without_a_description_falls_back_to_the_parent(self):  # SI-P81-8
        mutate_registry(self.root, lambda d: d["modules"]["orders"]["submodules"]["refunds"]
                        .pop("description"))
        _, env, _ = run_json("show", "orders/refunds", *self.R)
        self.assertEqual(env["data"]["description"], ORDERS)

    def test_context_rows_are_unchanged_for_a_matched_child(self):  # P81-AC-002 / AC-023
        """`context` stays byte-identical to the base: no description key on any row."""
        _, env, _ = run_json("context", "--task", "partial refund for a returned book", *self.R)
        for m in env["data"]["modules"]:
            self.assertNotIn("description", m)
        self.assertIn("orders/refunds", [m["module"] for m in env["data"]["modules"]])
        self.assertEqual(run_json("show", "orders", *self.R)[1]["data"]["description"], ORDERS)

    def test_context_json_matches_the_base_document(self):  # P81-AC-023
        code, env, err = run_json("context", "--task", "book refund", "--root", str(FIXTURE))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(env["data"], CONTEXT_BASE)


CONTEXT_BASE = {
    "task": "book refund", "role": None, "all_roles": False,
    "modules": [
        {"module": "catalog", "score": 3, "keywords": ["book"], "negative": [],
         "read": [{"label": "universal", "path": "modules/catalog/MODULE.md", "exists": True}],
         "code": ["src/catalog/service.py"], "code_globs": []},
        {"module": "payments", "score": 3, "keywords": ["refund"], "negative": [],
         "read": [{"label": "universal (parent INDEX)", "path": "modules/payments/MODULE.md",
                   "exists": True}], "code": [], "code_globs": []},
        {"module": "payments/refunds", "score": 3, "keywords": ["refund"], "negative": [],
         "read": [{"label": "universal (parent INDEX)", "path": "modules/payments/MODULE.md",
                   "exists": True},
                  {"label": "child universal (refunds)",
                   "path": "modules/payments/submodules/refunds/MODULE.md", "exists": True}],
         "code": [], "code_globs": []}],
    "read": [
        {"module": "catalog", "label": "universal", "path": "modules/catalog/MODULE.md",
         "exists": True},
        {"module": "payments", "label": "universal (parent INDEX)",
         "path": "modules/payments/MODULE.md", "exists": True},
        {"module": "payments/refunds", "label": "child universal (refunds)",
         "path": "modules/payments/submodules/refunds/MODULE.md", "exists": True}],
    "near_misses": []}


class FilesRepeatTest(SplitRepo):
    A, B = "src/catalog/service.py", "src/payments/gateway.py"

    def check(self, verb, *flags):
        code, env, err = run_json(*verb, *flags, *self.R)
        self.assertEqual((code, err), (0, ""))
        return env["data"]

    def test_discover_repeated_and_single_occurrence_agree(self):  # P81-AC-003
        repeated = self.check(("discover",), "--files", self.A, "--files", self.B)
        packed = self.check(("discover",), "--files", self.A, self.B)
        self.assertEqual(repeated, packed)
        self.assertEqual([f["path"] for f in repeated["files"]], [self.A, self.B])
        self.assertEqual([m["module"] for m in repeated["modules"]], ["catalog", "payments"])

    def test_sync_repeated(self):
        data = self.check(("sync", "--dry-run"), "--files", self.A, "--files", self.B)
        self.assertEqual(data["changed_files"], [self.A, self.B])
        self.assertEqual([m["module"] for m in data["modules"]], ["catalog", "payments"])
        self.assertEqual(data, self.check(("sync", "--dry-run"), "--files", self.A, self.B)
                         | {"run_id": data["run_id"]})

    def test_sync_instructions_repeated(self):
        data = self.check(("sync-instructions",), "--files", self.A, "--files", self.B)
        self.assertEqual([m["module"] for m in data["modules"]], ["catalog", "payments"])
        self.assertEqual(data, self.check(("sync-instructions",), "--files", self.A, self.B))

    def test_a_single_files_flag_is_unchanged(self):
        data = self.check(("discover",), "--files", self.A)
        self.assertEqual([m["module"] for m in data["modules"]], ["catalog"])


class RelatedChildTest(SplitRepo):
    def test_child_names_itself_and_marks_inherited_edges(self):  # P81-AC-004
        _, env, _ = run_json("related", "orders/checkout", *self.R)
        data = env["data"]
        self.assertEqual(data["module"], "orders/checkout")
        self.assertEqual(data["inherited_from"], "orders")
        self.assertEqual([(e["module"], e["relation"]) for e in data["edges"]],
                         [("payments", "depends-on")])

    def test_child_with_its_own_edges_reports_them_alone(self):
        mutate_registry(self.root, lambda d: d["modules"]["orders"]["submodules"]["refunds"]
                        .update(related_modules=[{"module": "catalog", "relation": "complements",
                                                  "description": "Restocked titles"}]))
        _, env, _ = run_json("related", "orders/refunds", *self.R)
        data = env["data"]
        self.assertEqual(data["module"], "orders/refunds")
        self.assertNotIn("inherited_from", data)
        self.assertEqual([e["module"] for e in data["edges"]], ["catalog"])

    def test_text_names_the_child_and_the_inheritance(self):
        _, out, _ = run("related", "orders/checkout", *self.R)
        self.assertEqual(out.splitlines()[:3], ["module: orders/checkout",
                                                "edges inherited from orders",
                                                "forward edges — 1:"])
        mutate_registry(self.root, lambda d: d["modules"]["orders"]["submodules"]["refunds"]
                        .update(related_modules=[{"module": "catalog", "relation": "complements",
                                                  "description": "Restocked titles"}]))
        _, out, _ = run("related", "orders/refunds", *self.R)
        self.assertEqual(out.splitlines()[:2], ["module: orders/refunds", "forward edges — 1:"])
        self.assertNotIn("inherited", out)

    def test_top_level_text_is_the_base_text(self):
        _, out, _ = run("related", "orders", *self.R)
        self.assertTrue(out.startswith("forward edges — 1:\n"))
        self.assertNotIn("module:", out)

    def test_parent_output_is_unchanged(self):
        _, env, _ = run_json("related", "orders", *self.R)
        self.assertEqual(sorted(env["data"]), ["edges", "module", "reverse"])
        self.assertEqual(env["data"]["module"], "orders")

    def test_unsplit_module_has_no_inherited_from(self):
        _, env, _ = run_json("related", "payments", *self.R)
        self.assertNotIn("inherited_from", env["data"])
        self.assertEqual([r["from"] for r in env["data"]["reverse"]], ["orders"])


class InitHintTest(unittest.TestCase):
    def test_populated_registry_hints_next(self):  # P81-AC-008
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp, {"catalog": ["book"]})
            code, out, err = run("init", "--root", str(root))
            self.assertEqual((code, err), (0, ""))
            self.assertIn("next: segmently-modules next\n", out)
            self.assertNotIn("segmently-modules create NAME", out)

    def test_empty_registry_keeps_the_first_module_hint(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, _ = run("init", "--root", tmp)
            self.assertEqual(code, 0)
            self.assertIn("next: segmently-modules create NAME", out)
            code, out, _ = run("init", "--root", tmp)  # re-init of the still empty registry
            self.assertIn("next: segmently-modules create NAME", out)


class IgnoredTargetNoteTest(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull,
                                           "GIT_CONFIG_NOSYSTEM": "1"})
        env.start()
        self.addCleanup(env.stop)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        self.R = ("--root", str(self.root))
        d = self.root / ".segmently-modules/packs/team"
        (d / "skills/api-review").mkdir(parents=True)
        (d / "pack.toml").write_text('id = "team"\nversion = "9.0.0"\npriority = 50\n'
                                     '[skills.api-review]\npath = "skills/api-review"\n')
        (d / "skills/api-review/SKILL.md").write_text(SKILL)
        init_git(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_ignored_directory_is_named_once_and_files_are_written(self):  # P81-AC-009
        (self.root / ".gitignore").write_text(".agents/\n")
        code, out, err = run("packs", "sync", "--agent", "codex", *self.R)
        self.assertEqual((code, err), (0, ""))
        notes = [line for line in out.splitlines() if line.startswith("note:")]
        self.assertEqual(len(notes), 1)
        self.assertIn(".agents/skills", notes[0])
        self.assertIn("ignore", notes[0])
        self.assertTrue((self.root / ".agents/skills/api-review/SKILL.md").exists())

    def test_json_notes_carry_it(self):
        (self.root / ".gitignore").write_text(".agents/\n")
        code, env, _ = run_json("packs", "sync", "--agent", "codex", *self.R)
        self.assertEqual(code, 0)
        self.assertEqual(len([n for n in env["data"]["notes"] if ".agents/skills" in n]), 1)

    def test_not_ignored_directory_has_no_note(self):
        code, out, _ = run("packs", "sync", "--agent", "codex", *self.R)
        self.assertEqual(code, 0)
        self.assertNotIn("note:", out)
        self.assertTrue((self.root / ".agents/skills/api-review/SKILL.md").exists())

    def test_outside_a_git_repository_there_is_no_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            (root / ".gitignore").write_text(".agents/\n")
            d = root / ".segmently-modules/packs/team"
            (d / "skills/api-review").mkdir(parents=True)
            (d / "pack.toml").write_text('id = "team"\nversion = "9.0.0"\npriority = 50\n'
                                         '[skills.api-review]\npath = "skills/api-review"\n')
            (d / "skills/api-review/SKILL.md").write_text(SKILL)
            code, out, _ = run("packs", "sync", "--agent", "codex", "--root", str(root))
            self.assertEqual(code, 0)
            self.assertNotIn("note:", out)


if __name__ == "__main__":
    unittest.main()
