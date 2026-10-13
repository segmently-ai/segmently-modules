"""Proposals queue: propose during a run, apply once under the lock."""
import json
import os
import tempfile
import unittest

from segmently_modules.store import file_sha256
from tests.helpers import copy_fixture, run, run_json


class ProposalsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        self.R = ("--root", str(self.root))
        self.queue = self.root / ".segmently-modules" / "proposals"

    def tearDown(self):
        self._tmp.cleanup()

    def propose(self, *argv, run_id="r1", agent="planner"):
        return run_json("propose", *argv, "--run-id", run_id, "--agent", agent, *self.R)

    def reg(self):
        return json.loads((self.root / "modules" / "registry.json").read_text())["modules"]

    def test_propose_queues_without_touching_the_registry(self):
        before = (self.root / "modules" / "registry.json").read_bytes()
        code, env, _ = self.propose("--module", "catalog", "--op", "set", "--field", "status",
                                    "--value", '"draft"', "--reason", "not shipped yet")
        self.assertEqual((code, env["schema"]), (0, "segmently-modules.propose/1"))
        doc = json.loads((self.queue / "r1-planner.json").read_text())
        self.assertEqual(doc["schema"], "segmently-modules.proposal/1")
        self.assertEqual(len(doc["items"][0]["base_sha256"]), 64)
        self.assertEqual((self.root / "modules" / "registry.json").read_bytes(), before)
        _, env, _ = run_json("proposals", "list", *self.R)
        self.assertEqual([(r["file"], r["items"]) for r in env["data"]], [("r1-planner.json", 1)])

    def test_apply_then_reapply_is_idempotent(self):
        self.propose("--module", "catalog", "--op", "set", "--field", "status",
                     "--value", '"draft"', "--reason", "r")
        code, env, _ = run_json("proposals", "apply", *self.R)
        self.assertEqual((code, env["data"]["summary"]), (0, {"applied": 1, "noop": 0, "rejected": 0}))
        self.assertEqual(self.reg()["catalog"]["status"], "draft")
        done = json.loads((self.queue / "done" / "r1-planner.json").read_text())
        self.assertEqual(done["results"][0]["status"], "applied")
        self.assertFalse((self.queue / "r1-planner.json").exists())
        _, env, _ = run_json("proposals", "apply", *self.R)
        self.assertEqual(env["data"]["summary"], {"applied": 0, "noop": 0, "rejected": 0})

    def test_stale_base_rejects_one_item_others_apply(self):
        self.propose("--module", "catalog", "--op", "set", "--field", "status",
                     "--value", '"draft"', "--reason", "r")
        self.propose("--module", "checkout", "--op", "append", "--field", "keywords",
                     "--value", '"basket"', "--reason", "r")
        run("registry", "set", "catalog", "description", '"Changed by a human."', *self.R)
        code, env, _ = run_json("proposals", "apply", *self.R)
        results = env["data"]["files"][0]["results"]
        self.assertEqual(code, 1)
        self.assertEqual([r["status"] for r in results], ["rejected", "applied"])
        self.assertIn("changed since the proposal was made", results[0]["reason"])
        self.assertEqual(self.reg()["catalog"]["status"], "active")
        self.assertIn("basket", self.reg()["checkout"]["keywords"])

    def test_items_of_one_run_share_one_base(self):
        self.propose("--module", "catalog", "--op", "append", "--field", "keywords",
                     "--value", '"ebook"', "--reason", "r")
        self.propose("--module", "catalog", "--op", "set", "--field", "status",
                     "--value", '"draft"', "--reason", "r")
        _, env, _ = run_json("proposals", "apply", *self.R)
        self.assertEqual(env["data"]["summary"]["applied"], 2)

    def test_appends_from_two_runs_merge(self):
        self.propose("--module", "catalog", "--op", "append", "--field", "keywords",
                     "--value", '"ebook"', "--reason", "r", run_id="r1")
        self.propose("--module", "catalog", "--op", "append", "--field", "keywords",
                     "--value", '"audiobook"', "--reason", "r", run_id="r2")
        run("proposals", "apply", *self.R)
        self.assertEqual(self.reg()["catalog"]["keywords"][-2:], ["ebook", "audiobook"])

    def test_doc_append_and_doc_write(self):
        dev = "modules/catalog/roles/developer.md"
        self.propose("--module", "catalog", "--op", "doc_append", "--doc", dev,
                     "--value", "## Gotchas\n\nISBNs may carry a checksum X.", "--reason", "r")
        self.propose("--module", "catalog", "--op", "doc_write",
                     "--doc", "modules/catalog/roles/po.md", "--value", "# Catalog — po",
                     "--reason", "new role doc")
        run("proposals", "apply", *self.R)
        self.assertTrue((self.root / dev).read_text().endswith("checksum X.\n"))
        self.assertEqual((self.root / "modules/catalog/roles/po.md").read_text(), "# Catalog — po\n")
        self.propose("--module", "catalog", "--op", "doc_append", "--doc", dev,
                     "--value", "## Gotchas\n\nISBNs may carry a checksum X.", "--reason", "r",
                     run_id="r2")
        _, env, _ = run_json("proposals", "apply", *self.R)
        self.assertEqual(env["data"]["summary"]["noop"], 1)

    def test_doc_write_stale_base_rejected(self):
        dev = "modules/catalog/roles/developer.md"
        self.propose("--module", "catalog", "--op", "doc_write", "--doc", dev,
                     "--value", "# rewritten", "--reason", "r")
        (self.root / dev).write_text("# edited meanwhile\n")
        _, env, _ = run_json("proposals", "apply", *self.R)
        self.assertEqual(env["data"]["files"][0]["results"][0]["status"], "rejected")
        self.assertEqual((self.root / dev).read_text(), "# edited meanwhile\n")

    def test_refused_at_propose_time(self):
        (self.root / "modules/catalog/MODULE.legacy.md").write_text("# frozen\n")
        cases = [(("--module", "catalog", "--op", "doc_write", "--doc",
                   "modules/checkout/MODULE.md", "--value", "x"), "outside module 'catalog'"),
                 (("--module", "catalog", "--op", "doc_write", "--doc",
                   "modules/catalog/../checkout/MODULE.md", "--value", "x"), "outside module"),
                 (("--module", "catalog", "--op", "doc_append", "--doc",
                   "modules/catalog/MODULE.legacy.md", "--value", "x"), "frozen legacy snapshot"),
                 (("--module", "catalog", "--op", "set", "--field", "keywords",
                   "--value", '"book"'), "does not match field 'keywords'"),
                 (("--module", "nope", "--op", "set", "--field", "status",
                   "--value", '"draft"'), "unknown module 'nope'")]
        for argv, needle in cases:
            with self.subTest(needle=needle):
                code, out, err = run("propose", *argv, "--reason", "r", "--run-id", "r1", *self.R)
                self.assertEqual((code, out), (2, ""))
                self.assertIn(needle, err)
        self.assertFalse((self.queue / "r1-cli.json").exists())
        code, _, err = run("propose", "--module", "catalog", "--op", "set", "--field", "status",
                           "--value", '"draft"', "--reason", "r", "--run-id", "../x", *self.R)
        self.assertEqual(code, 2)
        self.assertIn("may only contain", err)

    def test_reject_and_dry_run(self):
        self.propose("--module", "catalog", "--op", "set", "--field", "status",
                     "--value", '"draft"', "--reason", "r")
        code, env, _ = run_json("proposals", "apply", "--dry-run", *self.R)
        self.assertEqual((code, env["data"]["summary"]["applied"]), (0, 1))
        self.assertEqual(self.reg()["catalog"]["status"], "active")
        self.assertTrue((self.queue / "r1-planner.json").exists())
        code, _, err = run("proposals", "reject", "--run-id", "r1", *self.R)
        self.assertEqual(code, 2)
        self.assertIn("--reason", err)
        run("proposals", "reject", "--run-id", "r1", "--reason", "wrong module", *self.R)
        done = json.loads((self.queue / "done" / "r1-planner.json").read_text())
        self.assertEqual(done["rejected_reason"], "wrong module")
        self.assertEqual(run_json("proposals", "list", *self.R)[1]["data"], [])

    def test_value_file_for_doc_ops(self):
        text = self.root / "note.md"
        text.write_text("## Note\n\nFrom a file.\n")
        self.propose("--module", "payments/refunds", "--op", "doc_append",
                     "--doc", "modules/payments/submodules/refunds/MODULE.md",
                     "--value-file", str(text), "--reason", "r")
        run("proposals", "apply", *self.R)
        self.assertIn("From a file.", (self.root / "modules/payments/submodules/refunds/MODULE.md")
                      .read_text())

    def test_apply_in_per_module_layout(self):
        run("index", "split", *self.R)
        (self.root / ".segmently-modules" / "config.toml").write_text(
            '[paths]\nregistry_layout = "per-module"\n', encoding="utf-8")
        self.propose("--module", "checkout", "--op", "set", "--field", "status",
                     "--value", '"draft"', "--reason", "r")
        run("proposals", "apply", *self.R)
        entry = json.loads((self.root / "modules/checkout/module.json").read_text())
        self.assertEqual(entry["status"], "draft")


class ProposalsGapTest(unittest.TestCase):  # AC-015, AC-016
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        self.R = ("--root", str(self.root))
        self.queue = self.root / ".segmently-modules" / "proposals"

    def tearDown(self):
        self._tmp.cleanup()

    def test_two_agents_same_run_two_files(self):
        for agent, kw in (("planner", '"ebook"'), ("builder", '"audiobook"')):
            run("propose", "--module", "catalog", "--op", "append", "--field", "keywords",
                "--value", kw, "--reason", "r", "--run-id", "r1", "--agent", agent, *self.R)
        self.assertEqual(sorted(p.name for p in self.queue.glob("*.json")),
                         ["r1-builder.json", "r1-planner.json"])
        _, env, _ = run_json("proposals", "apply", *self.R)
        self.assertEqual(env["data"]["summary"]["applied"], 2)

    def test_malformed_queue_file_is_exit_2_naming_it(self):
        self.queue.mkdir(parents=True)
        for text, needle in (("{", "not a valid proposal file"),
                             ('{"schema": "x"}', "not a segmently-modules.proposal/1 file")):
            with self.subTest(needle=needle):
                (self.queue / "bad.json").write_text(text, encoding="utf-8")
                code, out, err = run("proposals", "apply", *self.R)
                self.assertEqual((code, out), (2, ""))
                self.assertIn("bad.json", err)
                self.assertIn(needle, err)

    def test_apply_time_revalidates_hand_crafted_module(self):
        # A hand-written queue item ("module": "..") must be refused at APPLY time too, not
        # only at propose time (F1) — check_doc_path alone is not enough; entry_for must run
        # for every op. The item carries the target's REAL current hash as base_sha256, so this
        # probes the actual exploit (a valid base hash used to be enough to get the write
        # applied) rather than being masked by an incidental base-hash mismatch.
        self.queue.mkdir(parents=True)
        target = self.root / "modules/checkout/MODULE.md"
        before = target.read_bytes()
        item = {"id": "1", "op": "doc_write", "module": "..", "doc": "modules/checkout/MODULE.md",
                "value": "# hacked", "base_sha256": file_sha256(target)}
        bad = {"schema": "segmently-modules.proposal/1", "run_id": "r1", "agent": "planner",
               "created_at": "2026-01-01T00:00:00Z", "items": [item]}
        (self.queue / "r1-planner.json").write_text(json.dumps(bad), encoding="utf-8")
        code, env, _ = run_json("proposals", "apply", *self.R)
        self.assertEqual(code, 1)
        result = env["data"]["files"][0]["results"][0]
        self.assertEqual(result["status"], "rejected")
        self.assertIn("invalid item", result["reason"])
        self.assertEqual(target.read_bytes(), before)

    def test_propose_refuses_bad_doc_paths(self):
        (self.root / "modules/catalog/MODULE.legacy.md").write_text("# frozen\n")
        cases = [(("--module", "catalog", "--op", "doc_write", "--doc",
                   "modules/catalog/module.json", "--value", "x"), "registry entry"),
                 (("--module", "catalog", "--op", "doc_write", "--doc", "modules/catalog",
                   "--value", "x"), "must be a file"),
                 (("--module", "catalog", "--op", "doc_write", "--doc",
                   "modules/catalog/notes.txt", "--value", "x"), "not a markdown doc"),
                 (("--module", "catalog", "--op", "doc_write", "--doc",
                   "modules/catalog/MODULE.LEGACY.MD", "--value", "x"), "frozen legacy snapshot"),
                 (("--module", "payments", "--op", "doc_write", "--doc",
                   "modules/payments/submodules/refunds/MODULE.md", "--value", "x"),
                  "outside module"),
                 (("--module", "payments", "--op", "doc_append", "--doc",
                   "modules/payments/SUBMODULES/refunds/MODULE.md", "--value", "x"),
                  "outside module")]  # case-variant "SUBMODULES" must be caught too
        for argv, needle in cases:
            with self.subTest(needle=needle):
                code, out, err = run("propose", *argv, "--reason", "r", "--run-id", "r1", *self.R)
                self.assertEqual((code, out), (2, ""))
                self.assertIn(needle, err)
        self.assertEqual(list(self.queue.glob("*.json")), [])

    def test_doc_conflict_key_is_case_insensitive(self):
        # Two case-variant paths to the same doc must still conflict — the run that appended
        # applies, the run that would silently overwrite it (dropping the append) is rejected.
        dev = "modules/catalog/roles/developer.md"
        run("propose", "--module", "catalog", "--op", "doc_append", "--doc", dev,
            "--value", "## Note\n\nFrom run a.", "--reason", "r", "--run-id", "a",
            "--agent", "planner", *self.R)
        run("propose", "--module", "catalog", "--op", "doc_write",
            "--doc", "modules/catalog/roles/Developer.md", "--value", "# rewritten",
            "--reason", "r", "--run-id", "b", "--agent", "planner", *self.R)
        code, env, _ = run_json("proposals", "apply", *self.R)
        self.assertEqual(code, 1)
        by_file = {f["file"]: f["results"][0] for f in env["data"]["files"]}
        self.assertEqual(by_file["a-planner.json"]["status"], "applied")
        self.assertEqual(by_file["b-planner.json"]["status"], "rejected")
        self.assertIn("conflicts with", by_file["b-planner.json"]["reason"])
        self.assertIn("From run a.", (self.root / dev).read_text())

    def test_case_variant_doc_ops_in_one_apply_keep_every_edit(self):
        # Doc paths are case-insensitive for the engine (as for conflict tracking): two
        # case-variant spellings of one doc are ONE pending write, landing on the first spelling
        # seen. Before the fix each spelling re-read the original from disk, so on a
        # case-insensitive filesystem the later write clobbered the earlier edit.
        dev = "modules/catalog/roles/developer.md"
        variant = "modules/catalog/roles/Developer.md"
        cases = [("doc_append", "## First\n\nFrom item one.", "From item one."),
                 ("doc_write", "# Rewritten by item one", "# Rewritten by item one")]
        for op, value, needle in cases:
            with self.subTest(first_op=op):
                run("propose", "--module", "catalog", "--op", op, "--doc", dev,
                    "--value", value, "--reason", "r", "--run-id", op, *self.R)
                run("propose", "--module", "catalog", "--op", "doc_append", "--doc", variant,
                    "--value", f"## Second ({op})\n\nFrom item two.", "--reason", "r",
                    "--run-id", op, *self.R)
                code, env, _ = run_json("proposals", "apply", *self.R)
                self.assertEqual((code, env["data"]["summary"]),
                                 (0, {"applied": 2, "noop": 0, "rejected": 0}))
                text = (self.root / dev).read_text()
                self.assertIn(needle, text)
                self.assertIn(f"## Second ({op})", text)
                if (self.root / variant).exists() and os.path.samefile(self.root / dev,
                                                                      self.root / variant):
                    self.assertEqual((self.root / variant).read_text(), text)

    def test_two_agents_one_run_different_fields_both_apply(self):
        run("propose", "--module", "catalog", "--op", "set", "--field", "status",
            "--value", '"draft"', "--reason", "r", "--run-id", "r1", "--agent", "planner", *self.R)
        run("propose", "--module", "catalog", "--op", "set", "--field", "description",
            "--value", '"New copy."', "--reason", "r", "--run-id", "r1", "--agent", "builder",
            *self.R)
        code, env, _ = run_json("proposals", "apply", *self.R)
        self.assertEqual((code, env["data"]["summary"]),
                         (0, {"applied": 2, "noop": 0, "rejected": 0}))

    def test_order_independence_across_two_runs(self):
        def apply_pair(id_a, id_b):
            tmp = tempfile.TemporaryDirectory()
            root = copy_fixture(tmp.name)
            R = ("--root", str(root))
            run("propose", "--module", "catalog", "--op", "append", "--field", "keywords",
                "--value", '"ebook"', "--reason", "r", "--run-id", id_a, "--agent", "planner", *R)
            run("propose", "--module", "catalog", "--op", "set", "--field", "status",
                "--value", '"draft"', "--reason", "r", "--run-id", id_b, "--agent", "planner", *R)
            _, env, _ = run_json("proposals", "apply", *R)
            tmp.cleanup()
            return env["data"]["summary"]

        self.assertEqual(apply_pair("a", "b"), {"applied": 2, "noop": 0, "rejected": 0})
        self.assertEqual(apply_pair("z", "b"), {"applied": 2, "noop": 0, "rejected": 0})

    def test_same_field_conflict_first_applies_second_rejected(self):
        run("propose", "--module", "catalog", "--op", "set", "--field", "status",
            "--value", '"draft"', "--reason", "r", "--run-id", "a", "--agent", "planner", *self.R)
        run("propose", "--module", "catalog", "--op", "set", "--field", "status",
            "--value", '"planned"', "--reason", "r", "--run-id", "b", "--agent", "planner",
            *self.R)
        code, env, _ = run_json("proposals", "apply", *self.R)
        self.assertEqual(code, 1)
        by_file = {f["file"]: f["results"][0] for f in env["data"]["files"]}
        self.assertEqual(by_file["a-planner.json"]["status"], "applied")
        self.assertEqual(by_file["b-planner.json"]["status"], "rejected")
        self.assertIn("conflicts with a-planner.json", by_file["b-planner.json"]["reason"])
        reg = json.loads((self.root / "modules" / "registry.json").read_text())
        self.assertEqual(reg["modules"]["catalog"]["status"], "draft")

    def test_reapply_after_crash_reports_noop(self):
        run("propose", "--module", "catalog", "--op", "set", "--field", "status",
            "--value", '"draft"', "--reason", "r", "--run-id", "r1", "--agent", "planner", *self.R)
        run("proposals", "apply", *self.R)
        done = json.loads((self.queue / "done" / "r1-planner.json").read_text())
        replay = {k: v for k, v in done.items() if k not in ("results", "processed_at")}
        (self.queue / "r1-planner.json").write_text(json.dumps(replay), encoding="utf-8")
        code, env, _ = run_json("proposals", "apply", *self.R)
        self.assertEqual((code, env["data"]["summary"]),
                         (0, {"applied": 0, "noop": 1, "rejected": 0}))


if __name__ == "__main__":
    unittest.main()
