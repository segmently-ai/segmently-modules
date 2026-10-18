"""The rules index written by an agent the engine starts (2026-10-18, after four trial runs in which the
agent running module-discover never wrote a doc nobody asked it to): `rules --build` gives each doc
one writer and checks what it did — an `Indexed:` line, every change inside the critical-rules
section, no backup files — and `discover --files` under `[rules] index = "discover"` starts it in
the background, only with SEGMENTLY_MODULES_ALLOW_INDEX_WRITER=1 in the environment."""
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
from tests.helpers import make_repo, run, run_json

FAKE = r'''
import json, os, sys
from pathlib import Path
order = json.loads(Path(os.environ["SEGMENTLY_MODULES_WORK_ORDER"]).read_text())
assert "Build or refresh" in sys.stdin.read()     # the procedure arrives on stdin
doc = Path(order["root"]) / order["doc"]
mode = os.environ.get("FAKE_MODE", "good")
if mode == "fail":
    sys.exit(3)
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

    def test_a_bad_command_is_refused(self):
        for bad in ('["claude", "{nope}"]', '["{root}"]', '"claude"'):
            with mock.patch.dict(os.environ, {index_build.ENV_COMMAND: bad}):
                with self.assertRaises(Exception):
                    index_build.writer_command()


class DiscoverTest(Base):
    def discover(self, extra=()):
        return run_json("discover", "--files", "src/shop/pay.py", *extra, *self.R)

    def test_discover_files_starts_the_build_in_the_background(self):
        with mock.patch.dict(os.environ, {**self.env, "FAKE_MODE": "good"}):
            _, env, _ = self.discover()
        rb = env["data"]["rules_build"]
        self.assertEqual((rb["status"], rb["docs"]), ("started", ["modules/shop/MODULE.md"]))
        deadline = time.time() + 30
        while time.time() < deadline and "Indexed:" not in self.doc.read_text():
            time.sleep(0.2)
        self.assertIn("Indexed:", self.doc.read_text(), Path(rb["log"]).read_text())
        while time.time() < deadline and index_build.running(self.root):
            time.sleep(0.2)
        last = json.loads((index_build.state_dir(self.root) / "last.json").read_text())
        self.assertEqual(last["summary"]["built"], 1)
        with mock.patch.dict(os.environ, self.env):
            self.assertEqual(self.discover()[1]["data"]["rules_build"]["status"], "complete")

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
