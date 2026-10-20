"""The task context file (plan 2026-10-20, §8): module-discover saves its judgements through `task-context save`
and the engine fills the rest — each doc's role and hash, every rule of those docs verbatim (a rule outside a
section quoted from the doc's own line), the docs to update, the files outside every module; later phases `add`
to it (never removing, a revision a writer may pin), read their slice with `show` (the main doc's part always),
see whether it is still fresh with `check`, `refresh` a stale module, and `export` the old 1.1 JSON."""
from __future__ import annotations

import datetime
import json
import tempfile
import os
import unittest
from unittest import mock
from pathlib import Path

from tests.helpers import git, init_git, make_repo, mutate_registry, run, run_json

MODULE_DOC = ("# shop\n\nThe shop module.\n\n## Critical Rules\n\n"
              "- Never charge a card twice — `src/shop/pay.py:1`\n"
              "- Always store amounts in cents\n\n"
              "## Notes\n\nRefunds go through the ledger, never straight to the card.\n")
QA_DOC = "# shop qa\n\n## Critical Rules\n\n- Every payment test uses the sandbox key\n"
DEV_DOC = "# shop developer\n\nUse the money helpers.\n"


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        cache = mock.patch.dict(os.environ, {"XDG_CACHE_HOME": str(self.tmp / "cache")})  # never the user's cache
        cache.start()
        self.addCleanup(cache.stop)
        self.root = make_repo(tmp.name, {"shop": ["shop", "checkout"], "cart": ["cart"]},
                              config='[packs]\nbuiltin = ["ui"]\n\n',  # the role designer
                              files=["src/shop/pay.py", "src/cart/cart.py", "tools/x.py"])
        with open(self.root / ".segmently-modules/config.toml", "a", encoding="utf-8") as f:
            f.write('[[code_map]]\nid = "src"\npattern = "src/{module}/**"\n')

        def roles(reg):
            reg["modules"]["shop"]["context_files"].update(
                {"roles": {"developer": "modules/shop/roles/developer.md", "qa": "modules/shop/roles/qa.md",
                           "designer": "modules/shop/roles/designer.md"},
                 "supplementary": ["modules/shop/memo.md"]})
        mutate_registry(self.root, roles)
        (self.root / "modules/shop/roles").mkdir()
        self.write("modules/shop/MODULE.md", MODULE_DOC)
        self.write("modules/shop/roles/qa.md", QA_DOC)
        self.write("modules/shop/roles/developer.md", DEV_DOC)
        self.write("modules/shop/roles/designer.md", "# shop designer\n")
        self.write("modules/shop/memo.md", "# memo\n")
        init_git(self.root)
        self.R = ("--root", str(self.root))

    def write(self, rel: str, text: str) -> None:
        (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.root / rel).write_text(text, encoding="utf-8")

    def input(self, data: dict, name: str = "in.json") -> str:
        path = self.tmp / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return str(path)

    def judgements(self, **extra) -> dict:
        data = {"task": "Refund a paid order to the card",
                "search": {"mode": "lexical", "lexical": "sure", "reason": None},
                "modules": [{"module": "shop", "usage": "modify", "score": 8, "why": "refunds live here",
                             "files": [{"path": "src/shop/pay.py", "line": 1, "tag": "edit", "symbol": "pay",
                                        "why": "add the refund call"},
                                       {"path": "tools/x.py", "line": 1, "tag": "read", "symbol": "x",
                                        "why": "pattern to follow"}],
                             "tests": "add new — a refund is never charged twice", "risks": ["the ledger API"],
                             "consequences": [{"text": "an export to add", "file": "src/shop/gone.py"}]},
                            {"module": "cart", "usage": "reference", "score": 5, "why": "the cart shape"}],
                "docs": [{"path": "modules/shop/roles/qa.md",
                          "extracts": [{"text": "payment tests use the sandbox key",
                                        "ref": "modules/shop/roles/qa.md:5"}]},
                         {"path": "modules/shop/roles/developer.md", "nothing": True}],
                "rules": [{"ref": "modules/shop/MODULE.md:7", "applies": "a refund is a charge"},
                          {"ref": "modules/shop/MODULE.md:12", "applies": "refunds go through the ledger",
                           "text": "Refunds go through the ledger"}],
                "rejected": [{"module": "search", "score": 2, "why": "off-topic by its description"}],
                "summary": "shop changes; cart is read"}
        data.update(extra)
        return data

    def save(self, data=None, *extra):
        code, env, err = run_json("task-context", "save", "--from", self.input(data or self.judgements()),
                                  *extra, *self.R)
        self.assertEqual(code, 0, err)
        return self.root / env["data"]["path"] if not Path(env["data"]["path"]).is_absolute() \
            else Path(env["data"]["path"])

    def load(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))


class SaveTest(Base):
    def test_the_engine_fills_docs_roles_and_hashes(self):
        data = self.load(self.save())
        self.assertEqual(data["schema"], "segmently-modules.task-context/1")
        self.assertEqual((data["revision"], data["head"]), (1, git(self.root, "rev-parse", "HEAD").strip()))
        docs = {d["path"]: d for d in data["docs"]}
        self.assertEqual({p: d["role"] for p, d in docs.items()},
                         {"modules/shop/MODULE.md": "module", "modules/shop/roles/developer.md": "developer",
                          "modules/shop/roles/qa.md": "qa", "modules/shop/roles/designer.md": "designer",
                          "modules/shop/memo.md": "extras", "modules/cart/MODULE.md": "module"})
        self.assertEqual(docs["modules/cart/MODULE.md"]["module"], "cart")  # a reference module: its main doc only
        self.assertEqual(len(docs["modules/shop/MODULE.md"]["sha256"]), 64)
        self.assertTrue(all(d["read"] == "whole" for d in docs.values()))
        self.assertEqual(docs["modules/shop/roles/qa.md"]["extracts"],
                         [{"text": "payment tests use the sandbox key", "ref": "modules/shop/roles/qa.md:5",
                           "phase": "discover"}])
        self.assertTrue(docs["modules/shop/roles/developer.md"]["nothing"])
        self.assertEqual(data["phases"][0]["phase"], "discover")
        self.assertEqual(data["phases"][0]["actor"], "module-discover")

    def test_rules_are_verbatim_from_the_docs(self):
        data = self.load(self.save())
        rules = {r["id"]: r for r in data["rules"]}
        self.assertEqual(set(rules), {"modules/shop/MODULE.md:7", "modules/shop/MODULE.md:8",
                                      "modules/shop/roles/qa.md:5", "modules/shop/MODULE.md:12"})
        section = rules["modules/shop/MODULE.md:7"]
        self.assertEqual((section["text"], section["source"], section["role"], section["applies"]),
                         ("Never charge a card twice — `src/shop/pay.py:1`", "section", "module", "a refund is a charge"))
        self.assertIsNone(rules["modules/shop/MODULE.md:8"]["applies"])  # every rule kept, only one marked
        self.assertEqual(rules["modules/shop/roles/qa.md:5"]["role"], "qa")
        body = rules["modules/shop/MODULE.md:12"]
        self.assertEqual((body["source"], body["quote"], body["text"]),
                         ("doc", "Refunds go through the ledger, never straight to the card.",
                          "Refunds go through the ledger"))

    def test_a_ref_past_the_end_or_to_no_doc_is_refused(self):
        for ref in ("modules/shop/MODULE.md:99", "modules/shop/none.md:1", "modules/shop/MODULE.md"):
            with self.subTest(ref=ref):
                code, _, err = run("task-context", "save", "--from",
                                   self.input(self.judgements(rules=[{"ref": ref}])), *self.R)
                self.assertEqual(code, 2, err)

    def test_docs_to_update_outside_and_missing(self):
        data = self.load(self.save())
        shop, cart = data["modules"]
        self.assertEqual(shop["docs_to_update"], ["modules/shop/MODULE.md", "modules/shop/roles/developer.md",
                                                  "modules/shop/roles/qa.md"])
        self.assertEqual(cart["docs_to_update"], [])
        self.assertEqual(data["files_outside_modules"], ["tools/x.py"])
        self.assertEqual(data["missing_files"], ["src/shop/gone.py"])
        self.assertEqual(shop["files"][0], {"path": "src/shop/pay.py", "line": 1, "tag": "edit", "symbol": "pay",
                                            "why": "add the refund call"})

    def test_the_default_path_is_outside_the_repository(self):  # 2026-10-20: a session told not to edit the repository
        cache = self.tmp / "cache"                                  # skipped a save into it (setUp points the cache here)
        if True:
            path = self.save()
            today = datetime.date.today().isoformat()
            self.assertEqual(path.parent.parent, cache / "segmently-modules")
            self.assertTrue(path.parent.name.startswith("tasks-"))
            self.assertEqual(path.name, f"{today}-refund-a-paid-order-to-the.json")
            self.assertFalse((path.parent / ".gitignore").exists())
            self.assertEqual(git(self.root, "status", "--porcelain"), "")
            self.assertNotEqual(self.save(), path)  # another run's file is never replaced
            code, out, _ = run("task-context", "save", "--from", self.input(self.judgements()), *self.R)
            self.assertTrue(out.strip().endswith(f"{today}-refund-a-paid-order-to-the-3.json"))
            code, env, _ = run_json("task-context", "list", *self.R)
            self.assertEqual(code, 0)
            self.assertEqual(len(env["data"]["files"]), 3)
            self.assertEqual(env["data"]["files"][0]["phases"], ["discover"])

    def test_out_and_save_dir(self):
        out = self.root / "specs/7/discovery-results.json"
        self.assertEqual(self.save(None, "--out", str(out)), out)
        self.assertFalse((out.parent / ".gitignore").exists())
        with open(self.root / ".segmently-modules/config.toml", "a", encoding="utf-8") as f:
            f.write('\n[discover]\nsave_dir = "work/ctx"\n')
        path = self.save()
        self.assertEqual(path.parent, self.root / "work/ctx")
        self.assertEqual((path.parent / ".gitignore").read_text(), "*\n")  # inside the repository: kept out of git

    def test_bad_input_is_refused(self):
        for bad in ({"modules": []}, self.judgements(module=[]),
                    self.judgements(modules=[{"module": "shop", "usage": "edit"}]),
                    self.judgements(modules=[{"module": "nope", "usage": "modify"}])):
            with self.subTest(bad=list(bad)):
                code, out, err = run("task-context", "save", "--from", self.input(bad), *self.R)
                self.assertEqual((code, out), (2, ""))
        code, _, err = run("task-context", "save", "--from", self.input(self.judgements(
            modules=[{"module": "nope", "usage": "modify"}])), *self.R)
        self.assertIn("unknown module 'nope'", err)

    def test_the_settings(self):
        cfg = self.root / ".segmently-modules/config.toml"
        for bad, msg in (('save = "sometimes"', "[discover] save: expected one of always, ask, off"),
                         ('save_dir = 3', "[discover] save_dir: expected a directory")):
            with self.subTest(bad=bad):
                cfg.write_text(f"[discover]\n{bad}\n", encoding="utf-8")
                code, _, err = run("catalog", "--settings", *self.R)
                self.assertEqual(code, 2)
                self.assertIn(msg, err)
        cfg.write_text('[discover]\nsave = "ask"\n', encoding="utf-8")
        self.assertIn('save = "ask"', run("catalog", "--settings", *self.R)[1])


class AddTest(Base):
    def add(self, path, patch, *extra):
        return run_json("task-context", "add", str(path), "--phase", "grooming", "--from", self.input(patch, "p.json"),
                        *extra, *self.R)

    def test_add_appends_and_keeps_history(self):
        path = self.save()
        code, env, err = self.add(path, {
            "modules": [{"module": "shop", "usage": "extend", "why": "refunds live here",
                         "files": [{"path": "src/shop/pay.py", "line": 1, "tag": "edit", "symbol": "pay",
                                    "why": "add the refund call"},
                                   {"path": "src/cart/cart.py", "line": 1, "tag": "read"}],
                         "risks": ["the ledger API", "a second risk"]},
                        {"module": "cart", "usage": "consume"}],
            "docs": [{"path": "modules/shop/roles/designer.md", "extracts": [{"text": "no new screen"}]}],
            "rules": [{"ref": "modules/shop/MODULE.md:8", "applies": "refund amounts"}],
            "notes": [{"text": "settled: refunds are partial too", "refs": ["modules/shop/MODULE.md:7"]}],
            "summary": "new summary"}, "--actor", "grooming")
        self.assertEqual(code, 0, err)
        self.assertEqual(env["data"]["revision"], 2)
        data = self.load(path)
        shop, cart = data["modules"]
        self.assertEqual([f["path"] for f in shop["files"]], ["src/shop/pay.py", "tools/x.py", "src/cart/cart.py"])
        self.assertEqual(shop["risks"], ["the ledger API", "a second risk"])
        self.assertEqual((shop["usage"], shop["history"]), ("extend", [{"phase": "grooming", "field": "usage",
                                                                        "old": "modify"}]))
        self.assertEqual(cart["history"], [{"phase": "grooming", "field": "usage", "old": "reference"}])
        self.assertEqual(cart["docs_to_update"], [])  # consumed: nothing to update
        designer = next(d for d in data["docs"] if d["path"] == "modules/shop/roles/designer.md")
        self.assertEqual(designer["extracts"], [{"text": "no new screen", "ref": None, "phase": "grooming"}])
        rule = next(r for r in data["rules"] if r["id"] == "modules/shop/MODULE.md:8")
        self.assertEqual((rule["applies"], rule["phase"]), ("refund amounts", "grooming"))
        self.assertEqual(data["notes"][-1]["phase"], "grooming")
        self.assertEqual(data["summary"], "new summary")
        self.assertEqual([(p["phase"], p["actor"], p["revision"]) for p in data["phases"]],
                         [("discover", "module-discover", 1), ("grooming", "grooming", 2)])

    def test_one_way_is_kept_and_replaced_with_history(self):  # a pipeline's size verdict reads it (2026-10-20)
        path = self.save()
        one = {"kind": "schema", "reason": "a stored field is renamed"}
        self.assertEqual(self.add(path, {"modules": [{"module": "shop", "one_way": one}]})[0], 0)
        shop = self.load(path)["modules"][0]
        self.assertEqual((shop["one_way"], shop["history"][-1]["field"]), (one, "one_way"))
        code, _, err = self.add(path, {"modules": [{"module": "shop", "one_way": {"kind": "schema"}}]})
        self.assertEqual(code, 2, err)
        self.assertIn("one_way", err)

    def test_a_new_module_is_filled_as_on_save(self):
        path = self.save(self.judgements(modules=[{"module": "cart", "usage": "reference"}]))
        self.assertEqual(self.add(path, {"modules": [{"module": "shop", "usage": "modify"}]})[0], 0)
        data = self.load(path)
        self.assertIn("modules/shop/roles/qa.md", {d["path"] for d in data["docs"]})
        self.assertIn("modules/shop/MODULE.md:8", {r["id"] for r in data["rules"]})

    def test_a_usage_raised_from_reference_fills_the_role_docs(self):
        path = self.save(self.judgements(modules=[{"module": "shop", "usage": "reference"}], docs=[],
                                         rules=[{"ref": "modules/shop/MODULE.md:7"}]))
        data = self.load(path)
        self.assertEqual({d["path"] for d in data["docs"]}, {"modules/shop/MODULE.md"})
        self.assertNotIn("modules/shop/roles/qa.md:5", {r["id"] for r in data["rules"]})
        self.assertEqual(self.add(path, {"modules": [{"module": "shop", "usage": "modify"}]})[0], 0)
        data = self.load(path)
        self.assertIn("modules/shop/roles/qa.md", {d["path"] for d in data["docs"]})
        self.assertIn("modules/shop/roles/qa.md:5", {r["id"] for r in data["rules"]})
        self.assertEqual(data["modules"][0]["docs_to_update"][0], "modules/shop/MODULE.md")
        self.assertEqual(next(r for r in data["rules"] if r["id"] == "modules/shop/MODULE.md:7")["applies"], "")

    def test_base_revision(self):
        path = self.save()
        code, _, err = self.add(path, {"notes": [{"text": "x"}]}, "--base-revision", "5")
        self.assertEqual(code, 2)
        self.assertIn("revision is 1, not 5: read it again", err)
        self.assertEqual(self.add(path, {"notes": [{"text": "x"}]}, "--base-revision", "1")[0], 0)
        self.assertEqual(self.load(path)["revision"], 2)

    def test_another_task_or_a_foreign_file_is_refused(self):
        path = self.save()
        self.assertEqual(self.add(path, {"task": "something else"})[0], 2)
        other = self.tmp / "other.json"
        other.write_text('{"version": "1.1"}', encoding="utf-8")
        code, _, err = self.add(other, {"notes": []})
        self.assertEqual(code, 2)
        self.assertIn("not a task context file", err)


class ShowTest(Base):
    def show(self, path, *extra):
        code, env, err = run_json("task-context", "show", str(path), *extra, *self.R)
        self.assertEqual(code, 0, err)
        return env["data"]

    def test_a_role_keeps_the_module_docs(self):
        path = self.save()
        view = self.show(path, "--role", "qa")
        self.assertEqual({d["path"] for d in view["docs"]},
                         {"modules/shop/MODULE.md", "modules/shop/roles/qa.md", "modules/cart/MODULE.md"})
        self.assertEqual({r["id"] for r in view["rules"]}, {"modules/shop/MODULE.md:7", "modules/shop/MODULE.md:12"})
        view = self.show(path, "--role", "developer,designer", "--module", "shop")
        self.assertEqual([m["module"] for m in view["modules"]], ["shop"])
        self.assertEqual({d["role"] for d in view["docs"]}, {"module", "developer", "designer"})
        self.assertEqual(len(self.show(path)["docs"]), 6)  # no role: everything

    def test_all_rules(self):
        view = self.show(self.save(), "--all-rules", "--role", "qa")
        self.assertEqual({r["id"] for r in view["rules"]},
                         {"modules/shop/MODULE.md:7", "modules/shop/MODULE.md:8", "modules/shop/MODULE.md:12",
                          "modules/shop/roles/qa.md:5"})

    def test_for_a_skill_takes_its_pack_roles(self):
        view = self.show(self.save(), "--for", "designer")  # the ui pack: reads_roles = ["designer"]
        self.assertEqual({d["role"] for d in view["docs"]}, {"module", "designer"})
        code, _, err = run("task-context", "show", str(self.save()), "--for", "no-such-skill", *self.R)
        self.assertEqual(code, 2)

    def test_the_text_is_in_the_reports_order(self):
        code, out, err = run("task-context", "show", str(self.save()), "--role", "qa", *self.R)
        self.assertEqual(code, 0, err)
        order = ["### shop — usage: modify (score 8)", "Why: refunds live here", "Rules:",
                 "- `modules/shop/MODULE.md:7` (module) — Never charge a card twice", "applies: a refund is a charge",
                 "Docs:", "- `modules/shop/roles/qa.md` (qa): payment tests use the sandbox key", "Code:",
                 "- `edit` — `src/shop/pay.py:1` — `pay` — add the refund call", "Tests: add new",
                 "Risks / unknowns: the ledger API", "Likely consequence: an export to add — src/shop/gone.py",
                 "Docs to update:", "### cart — usage: reference", "### Rejected", "- search — off-topic",
                 "### Files outside every module", "- `tools/x.py`", "### Missing files", "- `src/shop/gone.py`"]
        at = [out.find(p) for p in order]
        self.assertNotIn(-1, at, [p for p, i in zip(order, at) if i < 0])
        self.assertEqual(at, sorted(at))
        self.assertNotIn("(developer)", out)  # its docs to update are named, its doc is not shown


class CheckRefreshTest(Base):
    def check(self, path):
        return run_json("task-context", "check", str(path), *self.R)

    def test_fresh_then_stale_doc_code_and_module(self):
        path = self.save()
        code, env, err = self.check(path)
        self.assertEqual((code, env["data"]["fresh"]), (0, True), err)
        self.write("modules/shop/roles/qa.md", QA_DOC + "- A new rule\n")
        code, env, _ = self.check(path)
        self.assertEqual(code, 1)
        self.assertEqual(env["data"]["docs"], [{"path": "modules/shop/roles/qa.md", "module": "shop",
                                                "state": "changed"}])
        self.assertEqual(env["data"]["code"], [])
        self.write("src/shop/pay.py", "x = 2\n")
        self.assertEqual(self.check(path)[1]["data"]["code"], ["src/shop/pay.py"])
        git(self.root, "commit", "-qam", "change")
        self.assertEqual(self.check(path)[1]["data"]["code"], ["src/shop/pay.py"])  # committed since head too
        mutate_registry(self.root, lambda reg: reg["modules"].pop("cart"))
        self.assertEqual(self.check(path)[1]["data"]["modules"], [{"module": "cart", "state": "gone"}])
        code, out, _ = run("task-context", "check", str(path), *self.R)
        self.assertEqual(code, 1)
        self.assertIn("stale: 1 doc(s), 1 code file(s), 1 module(s)", out)

    def test_refresh_marks_stale_extracts(self):
        path = self.save()
        self.write("modules/shop/roles/qa.md", "# shop qa\n\nnew line\n\n## Critical Rules\n\n"
                                               "- Every payment test uses the sandbox key\n")
        code, env, err = run_json("task-context", "refresh", str(path), "--module", "shop", *self.R)
        self.assertEqual(code, 0, err)
        self.assertEqual((env["data"]["revision"], env["data"]["changed_docs"]), (2, ["modules/shop/roles/qa.md"]))
        data = self.load(path)
        qa = next(d for d in data["docs"] if d["path"] == "modules/shop/roles/qa.md")
        self.assertTrue(qa["extracts"][0]["stale"])
        rules = {r["id"]: r for r in data["rules"]}
        self.assertTrue(rules["modules/shop/roles/qa.md:5"]["stale"])  # the rule moved to line 7
        self.assertEqual(rules["modules/shop/roles/qa.md:7"]["text"], "Every payment test uses the sandbox key")
        self.assertEqual(data["phases"][-1]["phase"], "refresh")
        self.assertEqual(self.check(path)[0], 0)
        self.assertEqual(run("task-context", "refresh", str(path), "--module", "nope", *self.R)[0], 2)


class ExportTest(Base):
    def test_the_old_json(self):
        code, out, err = run("task-context", "export", str(self.save()), "--format", "discovery-1.1", *self.R)
        self.assertEqual(code, 0, err)
        doc = json.loads(out)
        self.assertEqual(list(doc), ["version", "task", "modules", "files_outside_modules", "summary"])
        self.assertEqual(doc["version"], "1.1")
        shop = doc["modules"][0]
        self.assertEqual(list(shop), ["name", "score", "confidence", "usage_type", "documentation", "files"])
        self.assertEqual((shop["usage_type"], shop["confidence"]), ("MODIFY", "high"))
        self.assertEqual(doc["modules"][1]["usage_type"], "READ-ONLY")
        self.assertEqual(shop["documentation"]["module_md"], "modules/shop/MODULE.md")
        self.assertEqual(shop["documentation"]["qa_md"], "modules/shop/roles/qa.md")
        self.assertEqual(shop["files"][0], {"path": "src/shop/pay.py", "offset": 1, "limit": 30,
                                            "reason": "edit — pay — add the refund call"})
        self.assertEqual(doc["files_outside_modules"][0]["path"], "tools/x.py")
        self.assertEqual(run("task-context", "export", str(self.save()), "--format", "2.0", *self.R)[0], 2)


if __name__ == "__main__":
    unittest.main()
