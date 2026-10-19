"""The rules index written by an agent the engine starts (2026-10-18, after four trial runs in which the
agent running module-discover never wrote a doc nobody asked it to): `rules --build` gives each doc
one writer and checks what it did — an `Indexed:` line, every change inside the critical-rules
section, no backup files — only with SEGMENTLY_MODULES_ALLOW_INDEX_WRITER=1 in the environment. Under
`[rules] index = "discover"`, `discover --files`, `rules <module>` and `show` name the docs without an
index and the command that indexes them in the background, which module-discover offers the user
after its report; they write nothing themselves (2026-10-19: two readers told not to edit the
repository killed a writer the engine had started)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from segmently_modules import index_build
from tests.helpers import make_repo, mutate_registry, run, run_json

FAKE = r'''
import json, os, sys, time
from pathlib import Path
time.sleep(float(os.environ.get("FAKE_SLEEP", "0")))
order = json.loads(Path(os.environ["SEGMENTLY_MODULES_WORK_ORDER"]).read_text())
stdin = sys.stdin.read()
if order.get("role") == "extra":                  # an other doc's writer: a JSON list, no edit
    assert "you change nothing" in stdin
    if os.environ.get("FAKE_EXTRA") == "edit":
        (Path(order["root"]) / order["doc"]).write_text("rewritten\n")
    print(json.dumps([{"line": 3, "rule": "Never refund twice."}] if order["doc"].endswith("extra.md") else []))
    sys.exit(0)
assert "Build or refresh" in stdin                # the procedure arrives on stdin
if os.environ.get("FAKE_STDIN"):
    Path(os.environ["FAKE_STDIN"]).write_text(stdin)
doc = Path(order["root"]) / order["doc"]
mode = os.environ.get("FAKE_MODE", "good")
if mode == "fail":
    sys.exit(3)
if mode == "nologin":  # what `claude -p --output-format json` does when its login is gone
    print("Ignoring 9 permissions.allow entries from .claude/settings.json: not trusted", file=sys.stderr)
    print(json.dumps({"type": "result", "is_error": True, "result": "Not logged in · Please run /login"}))
    sys.exit(1)
if mode == "stderr":
    print("a warning first\nthe real reason last", file=sys.stderr)
    sys.exit(4)
text = doc.read_text()
line = "" if mode == "noline" else f"Indexed: every rule of this doc, {order['today']}.\n\n"
text += f"\n## Critical Rules\n\n{line}- Never charge twice — `MODULE.md:1`\n"
if mode == "outside":
    text = text.replace("# shop\n", "# shop, rewritten\n", 1)
doc.write_text(text)
if mode == "stray":
    Path(str(doc) + "-e").write_text("backup")
if mode == "other":
    (Path(order["root"]) / "modules/cart/MODULE.md").write_text("# cart, touched\n")
print("1 entry, no contradictions")
'''


def index_build_ws(root):
    from segmently_modules.workspace import Workspace
    return Workspace.load(root)


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cache = mock.patch.dict(os.environ, {"XDG_CACHE_HOME": str(Path(tmp.name) / "cache")})
        cache.start()  # the lock and last.json of a build: never the user's own cache
        self.addCleanup(cache.stop)
        self.root = make_repo(tmp.name, {"shop": ["shop", "checkout"], "cart": ["cart"]},
                              config='[rules]\nindex = "discover"\n', files=["src/shop/pay.py"])
        with open(self.root / ".segmently-modules/config.toml", "a", encoding="utf-8") as f:
            f.write('\n[[code_map]]\nid = "src"\npattern = "src/{module}/**"\n')
        fake = Path(tmp.name) / "fake_writer.py"
        fake.write_text(FAKE, encoding="utf-8")
        self.env = {index_build.ENV_ALLOW: "1", index_build.ENV_COMMAND: json.dumps([sys.executable, str(fake)])}
        self.R = ("--root", str(self.root))
        self.doc = self.root / "modules/shop/MODULE.md"

    def build(self, mode="good", *names):
        with mock.patch.dict(os.environ, {**self.env, "FAKE_MODE": mode}):
            return run_json("rules", "--build", *(names or ("shop",)), *self.R)


class BuildTest(Base):
    def test_a_writer_indexes_the_doc(self):
        code, env, err = self.build()
        self.assertEqual(code, 0, err)
        self.assertEqual([(r["doc"], r["status"], r["added"]) for r in env["data"]["docs"]],
                         [("modules/shop/MODULE.md", "built", 1)])
        self.assertIn("Indexed: every rule of this doc", self.doc.read_text())
        self.assertEqual(run_json("rules", "--missing", "shop", *self.R)[1]["data"]["modules"], [])

    def test_a_change_outside_the_section_is_undone(self):
        before = self.doc.read_text()
        _, env, _ = self.build("outside")
        r = env["data"]["docs"][0]
        self.assertEqual(r["status"], "refused: it changed the doc outside the critical-rules section (line 1)")
        self.assertEqual(self.doc.read_text(), before)
        self.assertIn("shop, rewritten", Path(r["refused_text"]).read_text())  # what the writer left, kept to look at

    def test_no_indexed_line_or_a_failed_writer_leaves_the_doc_as_it_was(self):
        before = self.doc.read_text()
        for mode, status in (("noline", "failed: no Indexed: line"), ("fail", "failed: the writer exited 3")):
            _, env, _ = self.build(mode)
            self.assertEqual(env["data"]["docs"][0]["status"], status)
            self.assertEqual(self.doc.read_text(), before)

    def test_a_failure_names_the_writers_own_reason_not_the_first_warning(self):
        for mode, status in (("nologin", "failed: the writer exited 1 (Not logged in · Please run /login)"),
                             ("stderr", "failed: the writer exited 4 (the real reason last)")):
            _, env, _ = self.build(mode)
            self.assertEqual(env["data"]["docs"][0]["status"], status)

    def test_a_backup_next_to_the_doc_is_removed_and_another_files_change_is_reported(self):
        _, env, _ = self.build("stray")
        self.assertEqual(env["data"]["docs"][0]["removed"], ["modules/shop/MODULE.md-e"])
        self.assertFalse((self.root / "modules/shop/MODULE.md-e").exists())
        self.doc.write_text("# shop\n")
        _, env, _ = self.build("other")
        self.assertEqual(env["data"]["other_changes"], ["modules/cart/MODULE.md"])

    def test_refused_without_the_permission_or_a_writer(self):
        with mock.patch.dict(os.environ, {index_build.ENV_COMMAND: self.env[index_build.ENV_COMMAND]}, clear=False):
            os.environ.pop(index_build.ENV_ALLOW, None)
            code, _, err = run("rules", "--build", "shop", *self.R)
        self.assertEqual(code, 2)
        self.assertIn(index_build.ENV_ALLOW, err)
        with mock.patch.dict(os.environ, {index_build.ENV_ALLOW: "1", "CLAUDECODE": ""}):
            os.environ.pop(index_build.ENV_COMMAND, None)
            code, _, err = run("rules", "--build", "shop", *self.R)
        self.assertEqual(code, 2)
        self.assertIn("no writer", err)
        with mock.patch.dict(os.environ, {index_build.ENV_ALLOW: "yes"}):
            self.assertEqual(run("rules", "--build", "shop", *self.R)[0], 2)

    def test_the_claude_default_may_edit_only_its_doc(self):
        with mock.patch.dict(os.environ, {"CLAUDECODE": "1"}):
            os.environ.pop(index_build.ENV_COMMAND, None)
            argv = index_build._fill(index_build.writer_command(), {"doc_rule": "//r/modules/shop/MODULE.md",
                                                                     "claude_model": "sonnet"})
        self.assertEqual(argv[:4], ["claude", "-p", "--model", "sonnet"])
        self.assertIn("Edit(//r/modules/shop/MODULE.md)", argv)
        self.assertNotIn("Write", " ".join(argv))

    def test_the_prompt_names_the_section_the_engine_reads(self):
        heading = "Critical Rules"
        self.assertIn("no critical-rules section: add `## Critical Rules` at the end",
                      index_build.where("# shop\n\nText.\n", heading))
        doc = "# shop\n\n## Wallet\n\n### Critical rules when modifying\n\n- Do x\n\n### Debugging\n\nSteps.\n"
        self.assertIn("`### Critical rules when modifying`, lines 5–8: put the index inside it",
                      index_build.where(doc, heading))
        self.doc.write_text(doc)
        seen = self.root.parent / "stdin.txt"
        with mock.patch.dict(os.environ, {**self.env, "FAKE_MODE": "good", "FAKE_STDIN": str(seen)}):
            _, env, _ = run_json("rules", "--build", "shop", *self.R)
        self.assertIn("`### Critical rules when modifying`, lines 5–8", seen.read_text())
        # the fake writer appends a second section: refused, since the reader would never see it
        self.assertTrue(env["data"]["docs"][0]["status"].startswith("refused"), env["data"]["docs"][0])

    def other_docs(self):
        def extra(reg):
            reg["modules"]["shop"]["context_files"]["supplementary"] = ["modules/shop/extra.md", "modules/cart/MODULE.md"]
        mutate_registry(self.root, extra)
        (self.root / "modules/shop/extra.md").write_text("# Extra\n\nNever refund twice.\n", encoding="utf-8")
        (self.root / "modules/shop/memo.md").write_text("# Memo\n\nSome history.\n", encoding="utf-8")
        (self.root / "modules/shop/old.legacy.md").write_text("# old\n", encoding="utf-8")
        self.doc.write_text("# shop\n\nRead [the memo](memo.md) first; not `old.legacy.md`, not [cart](../cart/MODULE.md).\n",
                            encoding="utf-8")

    def test_the_module_doc_takes_the_rules_of_its_other_docs(self):  # c02, 2026-10-19
        self.other_docs()
        seen = self.root.parent / "stdin.txt"
        with mock.patch.dict(os.environ, {**self.env, "FAKE_MODE": "good", "FAKE_STDIN": str(seen)}):
            _, env, _ = run_json("rules", "--build", "shop", *self.R)
        self.assertIn("Its 2 other doc(s) (modules/shop/extra.md, modules/shop/memo.md) are read by writers of their own",
                      seen.read_text())  # another module's own doc and a frozen copy are never among them
        r = env["data"]["docs"][0]
        self.assertEqual((r["status"], r["extras"], r["extras_failed"], r["extras_added"]),
                         ("built", ["modules/shop/extra.md", "modules/shop/memo.md"], [], 1))
        self.assertEqual([(x["doc"], x["status"], x["rules"]) for x in env["data"]["extras"]],
                         [("modules/shop/extra.md", "listed", [{"line": 3, "rule": "Never refund twice."}]),
                          ("modules/shop/memo.md", "listed", [])])
        self.assertIn("- Never refund twice. (`modules/shop/extra.md:3`)", self.doc.read_text())
        rules = run_json("rules", "shop", *self.R)[1]["data"]["modules"][0]["rules"]
        self.assertIn("Never refund twice. (`modules/shop/extra.md:3`)", [x["text"] for x in rules])  # a reader gets it
        self.assertEqual(index_build.other_docs(index_build_ws(self.root), {"doc": "modules/shop/roles/qa.md",
                                                                           "target": "shop", "role": "qa"}, ""), [])

    def test_an_other_docs_writer_that_edits_is_refused_and_undone(self):
        self.other_docs()
        with mock.patch.dict(os.environ, {**self.env, "FAKE_MODE": "good", "FAKE_EXTRA": "edit"}):
            _, env, _ = run_json("rules", "--build", "shop", *self.R)
        self.assertEqual((self.root / "modules/shop/extra.md").read_text(), "# Extra\n\nNever refund twice.\n")
        listed = {x["doc"]: x["status"] for x in env["data"]["extras"]}
        self.assertEqual(listed["modules/shop/extra.md"], "refused: it changed modules/shop/extra.md")
        r = env["data"]["docs"][0]
        self.assertEqual((r["status"], r["extras_added"]), ("built", 0))
        self.assertIn("modules/shop/extra.md", r["extras_failed"])

    def test_a_break_before_a_new_section_is_free_but_not_under_text(self):
        old = "# shop\n\nText.\n"
        new = old + "\n---\n\n## Critical Rules\n\nIndexed: every rule of this doc, 2026-10-18.\n\n- Never x\n"
        self.assertIsNone(index_build.outside_line(old, new, "Critical Rules"))
        under = "# shop\n\nText.\n---\n\n## Critical Rules\n\n- Never x\n"   # "Text." becomes a heading
        self.assertEqual(index_build.outside_line("# shop\n\nText.\n", under, "Critical Rules"), 4)

    def test_a_bad_command_is_refused(self):
        for bad in ('["claude", "{nope}"]', '["{root}"]', '"claude"'):
            with mock.patch.dict(os.environ, {index_build.ENV_COMMAND: bad}):
                with self.assertRaises(Exception):
                    index_build.writer_command()


class DiscoverTest(Base):
    def discover(self, extra=()):
        return run_json("discover", "--files", "src/shop/pay.py", *extra, *self.R)

    def wait_built(self):
        deadline = time.time() + 30
        while time.time() < deadline and (index_build.running(self.root) or "Indexed:" not in self.doc.read_text()):
            time.sleep(0.2)
        self.assertIn("Indexed:", self.doc.read_text())

    def test_discover_files_offers_the_build_and_writes_nothing(self):
        before = self.doc.read_text()
        with mock.patch.dict(os.environ, {**self.env, "FAKE_MODE": "good"}):
            _, env, _ = self.discover()
        rb = env["data"]["rules_build"]
        self.assertEqual((rb["status"], rb["docs"], rb["build"]),
                         ("missing", ["modules/shop/MODULE.md"], "segmently-modules rules --build shop --background"))
        time.sleep(0.5)
        self.assertFalse(index_build.running(self.root))
        self.assertEqual(self.doc.read_text(), before)

    def test_discovers_text_ends_with_the_rules_command_and_the_offer(self):
        with mock.patch.dict(os.environ, {**self.env, "FAKE_MODE": "good"}):
            code, out, _ = run("discover", "--files", "src/shop/pay.py", *self.R)
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[-2:], [
            "rules: segmently-modules rules shop > <temp file>, then read the file to the end",
            "rules index: 1 doc(s) without one; their rules are only in their text: read each to the end — "
            "modules/shop/MODULE.md. After your report, ask the user whether to index them: "
            "segmently-modules rules --build shop --background"])

    def test_the_offered_command_builds_in_the_background(self):
        with mock.patch.dict(os.environ, {**self.env, "FAKE_MODE": "good", "FAKE_SLEEP": "2"}):
            code, env, err = run_json("rules", "--build", "shop", "--background", *self.R)
        self.assertEqual(code, 0, err)
        self.assertEqual((env["data"]["status"], env["data"]["docs"]), ("started", ["modules/shop/MODULE.md"]))
        self.assertEqual(index_build.running(self.root)["docs"], ["modules/shop/MODULE.md"])  # at once, not later
        with mock.patch.dict(os.environ, self.env):
            self.assertEqual(self.discover()[1]["data"]["rules_build"]["status"], "running")
        self.wait_built()
        last = json.loads((index_build.state_dir(self.root) / "last.json").read_text())
        self.assertEqual(last["summary"]["built"], 1)
        with mock.patch.dict(os.environ, self.env):
            self.assertEqual(self.discover()[1]["data"]["rules_build"]["status"], "complete")
            code, out, _ = run("rules", "--build", "shop", "--background", *self.R)
        self.assertEqual((code, out.strip()), (0, "nothing to index: every doc of these modules has a rules index"))

    def test_the_background_build_is_refused_as_the_build_is(self):
        os.environ.pop(index_build.ENV_ALLOW, None)
        code, _, err = run("rules", "--build", "shop", "--background", *self.R)
        self.assertEqual(code, 2)
        self.assertIn(index_build.ENV_ALLOW, err)
        self.assertFalse(index_build.running(self.root))
        self.assertEqual(run("rules", "shop", "--background", *self.R)[0], 2)  # --background goes with --build

    def test_the_callers_marks_choose_the_docs_over_the_code_map(self):
        os.environ.pop(index_build.ENV_ALLOW, None)  # not_allowed: the docs are named, nothing starts
        rb = self.discover(("--modify", "cart"))[1]["data"]["rules_build"]
        self.assertEqual(rb["docs"], ["modules/cart/MODULE.md"])  # the code map would give shop's
        rb = self.discover(("--modify", "cart", "--consume", "shop"))[1]["data"]["rules_build"]
        self.assertEqual(rb["docs"], ["modules/cart/MODULE.md", "modules/shop/MODULE.md"])
        self.assertEqual(rb["read"], "segmently-modules rules cart shop > <temp file>, then read the file to the end")
        self.assertEqual(run("discover", "--files", "src/shop/pay.py", "--modify", "nope", *self.R)[0], 2)

    def test_rules_and_show_of_named_modules_offer_it_too(self):
        before = self.doc.read_text()
        with mock.patch.dict(os.environ, {**self.env, "FAKE_MODE": "good"}):
            code, out, _ = run("rules", "shop", *self.R)
            self.assertEqual(code, 0)
            self.assertIn("rules index: 1 doc(s) without one; their rules are only in their text: read each to the "
                          "end — modules/shop/MODULE.md. After your report, ask the user whether to index them: "
                          "segmently-modules rules --build shop --background", out)
            self.assertNotIn("rules_build", run_json("rules", "--files", "src/shop/pay.py", *self.R)[1]["data"])
            code, out, _ = run("show", "shop", *self.R)
            self.assertEqual(code, 0)
            self.assertIn("  index 1 doc(s) without one; read each in full: modules/shop/MODULE.md. After your "
                          "report, ask the user whether to index them: segmently-modules rules --build shop "
                          "--background", out)
        time.sleep(0.5)
        self.assertFalse(index_build.running(self.root))
        self.assertEqual(self.doc.read_text(), before)
        with mock.patch.dict(os.environ, {**self.env, "FAKE_MODE": "good"}):
            run("rules", "--build", "shop", *self.R)
            self.assertEqual(run_json("rules", "shop", *self.R)[1]["data"]["rules_build"]["status"], "complete")
            self.assertNotIn("rules_build", run_json("show", "shop", *self.R)[1]["data"])  # nothing missing now

    def test_what_discover_says_when_it_does_not_build(self):
        os.environ.pop(index_build.ENV_ALLOW, None)
        self.assertEqual(self.discover()[1]["data"]["rules_build"]["status"], "not_allowed")
        with mock.patch.dict(os.environ, {**self.env, "SEGMENTLY_MODULES_RUN_ID": "r1"}):
            self.assertEqual(self.discover()[1]["data"]["rules_build"]["status"], "skipped")
        with mock.patch.dict(os.environ, {**self.env, "SEGMENTLY_MODULES_WORK_ORDER": "/x"}):
            self.assertEqual(self.discover()[1]["data"]["rules_build"]["status"], "skipped")
        self.assertFalse(index_build.running(self.root))
        self.assertNotIn("Indexed:", self.doc.read_text())

    def test_only_with_the_setting_and_never_on_a_branch_review_or_a_task_alone(self):
        (self.root / ".segmently-modules/config.toml").write_text(
            '[[code_map]]\nid = "src"\npattern = "src/{module}/**"\n', encoding="utf-8")
        with mock.patch.dict(os.environ, self.env):
            d = self.discover()[1]["data"]
        self.assertNotIn("rules_build", d)
        self.assertNotIn("rules_setting", d)
        (self.root / ".segmently-modules/config.toml").write_text('[rules]\nindex = "discover"\n', encoding="utf-8")
        with mock.patch.dict(os.environ, self.env):
            d = run_json("discover", "--task", "shop checkout", *self.R)[1]["data"]
        self.assertEqual(d["rules_setting"], "discover")
        self.assertNotIn("rules_build", d)


if __name__ == "__main__":
    unittest.main()
