"""`init finish` (D4, gate 7): the staging docs moved, the registry written through its writer,
the code-map rules and the agents' block — never a commit; its refusals; `--open-pr` against a
local bare remote and a `gh` stand-in."""
import json
import os
import shutil
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from modsys.config import builtin_packs_root
from tests.helpers import git, run, run_json
from tests.init_helpers import (IDENTITY, SIX, WORK, bare_remote, executor, gh_shim, ok,
                                protected_sha, shop, state, text)


def verified(base: Path, name: str = "shop", **kw) -> Path:
    root = shop(base, name=name, **kw)
    for argv in (("fanout",), ("run", "--executor", executor()), ("reconcile",),
                 ("eval-tasks", "--executor", executor()), ("verify",)):
        ok(root, "init", *argv)
    return root


class FinishRepo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.template = verified(Path(cls._tmp.name).resolve(), name="template")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(dir=self._tmp.name)).resolve()
        self.root = self.base / "shop"
        shutil.copytree(self.template, self.root, symlinks=True)

    def finish(self, *flags: str, code: int = 0):
        return ok(self.root, "init", "finish", *flags, code=code)

    def refused(self, *flags: str) -> str:
        before = protected_sha(self.root)
        code, out, err = run("init", "finish", *flags, "--json", "--root", str(self.root))
        self.assertEqual((code, out), (2, ""), err)
        self.assertEqual(protected_sha(self.root), before)
        return err


class FinishTest(FinishRepo):  # P5B-AC-023 (SI-18)
    def test_gate_7(self):
        team = "# The team's notes\n\nKeep them.\n"
        (self.root / "CLAUDE.md").write_text(team)
        head = git(self.root, "rev-parse", "HEAD")
        staged = json.loads((self.root / WORK / "staging/registry.json").read_text())
        data = self.finish()
        self.assertEqual(set(data), {"action", "moved", "registry", "agents_md", "code_map",
                                     "git_add", "forced", "pr", "next"})
        self.assertEqual((data["forced"], data["pr"], data["registry"]),
                         (False, None, "modules/registry.json"))
        for m in SIX:
            base = self.root / WORK / "staging" / m
            for rel in ["MODULE.md", *(f"roles/{r}.md" for r in ("architect", "developer", "po",
                                                                 "qa"))]:
                self.assertEqual((self.root / "modules" / m / rel).read_bytes(),
                                 (base / rel).read_bytes())
                self.assertIn(f"modules/{m}/{rel}", data["moved"])
        registry = json.loads((self.root / "modules/registry.json").read_text())
        self.assertEqual(registry, staged)
        claude = (self.root / "CLAUDE.md").read_text()
        self.assertTrue(claude.startswith(team))
        self.assertEqual(data["agents_md"], [{"path": "CLAUDE.md", "status": "added"}])
        pack = tomllib.loads((builtin_packs_root() / "core/pack.toml").read_text())
        for skill in pack["skills"]:
            self.assertIn(f"- `{skill}` — ", claude)
        self.assertFalse((self.root / "AGENTS.md").exists())
        config = tomllib.loads((self.root / ".modsys/config.toml").read_text())
        rules = {r["id"]: r for r in config["code_map"]}
        self.assertEqual(data["code_map"], [f"init-{m}" for m in SIX])
        self.assertEqual(rules["init-cart"], {"id": "init-cart", "module": "cart",
                                              "globs": ["packages/cart/**"]})
        s = state(self.root)
        self.assertEqual((s["phases"]["finish"]["status"], s["phase"]), ("done", "finished"))
        self.assertEqual(git(self.root, "rev-parse", "HEAD"), head)  # never a commit
        status = {line[3:] for line in git(self.root, "status", "--porcelain",
                                           "--untracked-files=all").splitlines()}
        self.assertEqual(status, set(data["git_add"]))
        out = text(self.root, "init", "status")[1]
        self.assertIn("next: init is finished", out)

    def test_afterwards(self):
        self.finish()
        self.assertEqual(run("lint", "--fail-on", "warning", "--root", str(self.root))[0], 0)
        self.assertEqual([r["module"] for r in ok(self.root, "list")], SIX)
        files = ok(self.root, "code-map", "files", "cart")["files"]
        self.assertEqual([f["path"] for f in files if "code_map:init-cart" in f["via"]],
                         ["packages/cart/package.json", "packages/cart/src/index.ts",
                          "packages/cart/src/lines.ts"])
        coverage = ok(self.root, "coverage")
        self.assertEqual(coverage["unmapped"], ["README.md", "package.json", "tools/report.js",
                                                "tools/seed.py"])

    def test_the_per_module_layout_and_agents_md(self):
        single = [r["module"] for r in (self.finish(), ok(self.root, "list"))[1]]
        root = shop(self.base, name="per", config="")
        shutil.rmtree(root / ".modsys/init")
        (root / ".modsys/config.toml").unlink()
        (root / "modules/registry.json").unlink()
        ok(root, "init", "map", "--layout", "per-module")
        doc = json.loads((root / WORK / "proposal.json").read_text())
        for c in doc["candidates"]:
            c["include"] = c["name"] != "tools"
        (root / WORK / "proposal.json").write_text(json.dumps(doc))
        for argv in (("confirm",), ("fanout",), ("run", "--executor", executor()),
                     ("reconcile",), ("verify",)):
            ok(root, "init", *argv)
        data = ok(root, "init", "finish", "--agents-md", "AGENTS.md")
        self.assertEqual(data["agents_md"], [{"path": "AGENTS.md", "status": "created"}])
        for m in SIX:
            entry = json.loads((root / f"modules/{m}/module.json").read_text())
            self.assertEqual(entry["name"], m)
        index = json.loads((root / "modules/registry.json").read_text())
        self.assertEqual(sorted(index["modules"]), SIX)
        self.assertEqual([r["module"] for r in ok(root, "list")], single)
        self.assertEqual(run("lint", "--fail-on", "warning", "--root", str(root))[0], 0)

    def test_no_instruction_file(self):
        data = self.finish()
        self.assertEqual(data["agents_md"], [])
        self.assertIn("--agents-md CLAUDE.md", data["next"])

    def test_a_module_created_by_hand_is_never_moved(self):  # P5B-AC-051 (finish)
        root = shop(self.base, name="kept")
        ok(root, "create", "catalog", "--non-interactive", "--description",
           "Book titles, authors and ISBN lookups for the shop.", "--keywords",
           "catalog, isbn, author, title, shelf")
        docs = {p: p.read_bytes() for p in (root / "modules/catalog").rglob("*") if p.is_file()}
        entry = json.loads((root / "modules/registry.json").read_text())["modules"]["catalog"]
        for argv in (("fanout",), ("run", "--executor", executor()), ("reconcile",),
                     ("verify",)):
            ok(root, "init", *argv)
        data = ok(root, "init", "finish")
        self.assertFalse([p for p in data["moved"] if p.startswith("modules/catalog/")])
        self.assertNotIn("init-catalog", data["code_map"])
        self.assertEqual({p: p.read_bytes() for p in (root / "modules/catalog").rglob("*")
                          if p.is_file()}, docs)
        self.assertEqual(json.loads((root / "modules/registry.json").read_text())["modules"]
                         ["catalog"], entry)


class RefusalsTest(FinishRepo):  # P5B-AC-024 (SI-16, SI-18)
    def test_verify_not_passed_and_force(self):
        (self.root / WORK / "verify.json").unlink()
        s = state(self.root)
        s["phases"]["verify"]["status"] = "pending"
        (self.root / WORK / "state.json").write_text(json.dumps(s))
        self.assertIn("verify has not passed — run modsys init verify", self.refused())
        data = self.finish("--force")
        self.assertTrue(data["forced"])
        self.assertEqual(state(self.root)["forced"]["reason"], "verify not passed")

    def test_the_staging_changed_since_verify(self):
        registry = self.root / WORK / "staging/registry.json"
        registry.write_text(registry.read_text().replace('"basket"', '"trolley"'))
        self.assertIn("staging changed since verify — run modsys init verify", self.refused())
        self.assertEqual(self.finish("--force")["forced"], True)
        self.assertEqual(state(self.root)["forced"]["reason"], "staging changed since verify")

    def test_what_force_never_overrides(self):
        (self.root / "modules/cart").mkdir()
        (self.root / "modules/cart/MODULE.md").write_text("# by hand\n")
        for flags in ((), ("--force",)):
            self.assertIn("modules/cart/ exists", self.refused(*flags))
        shutil.rmtree(self.root / "modules/cart")
        self.assertIn("outside the repository root", self.refused("--agents-md", "../x.md"))
        ok(self.root, "create", "wishlist", "--non-interactive", "--description",
           "The books a reader wants to buy later.", "--keywords",
           "wishlist, wish, later, save, want")
        for flags in ((), ("--force",)):
            self.assertIn("the registry changed since init reconcile (wishlist)",
                          self.refused(*flags))

    def test_before_reconcile_and_after_finish(self):
        s = state(self.root)
        s["phases"]["reconcile"]["status"] = "pending"
        (self.root / WORK / "state.json").write_text(json.dumps(s))
        for flags in ((), ("--force",)):
            self.assertIn("modsys init reconcile", self.refused(*flags))
        self.setUp()
        self.finish()
        for flags in ((), ("--force",)):
            self.assertIn("already finished", self.refused(*flags))


class OpenPrTest(FinishRepo):  # P5B-AC-025 (SI-20)
    def setUp(self):
        super().setUp()
        self.remote = bare_remote(self.root, self.base / "remote.git")
        self.log = self.base / "gh.jsonl"
        self.bin = self.base / "bin"
        gh_shim(self.bin, self.log)
        self.env = {**IDENTITY, "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}"}

    def open_pr(self, *flags: str, code: int = 0) -> tuple[int, dict | None, str]:
        with mock.patch.dict(os.environ, self.env):
            got, env, err = run_json("init", "finish", "--open-pr", *flags, "--root",
                                     str(self.root))
        self.assertEqual(got, code, err)
        return got, env["data"] if env else None, err

    def calls(self) -> list[dict]:
        return [json.loads(l) for l in self.log.read_text().splitlines()] \
            if self.log.exists() else []

    def test_one_commit_and_its_pr(self):
        base = git(self.root, "rev-parse", "HEAD").strip()
        _, data, err = self.open_pr()
        self.assertEqual((data["pr"], err), ("https://example.invalid/bookshop/pull/1", ""))
        self.assertEqual(git(self.root, "branch", "--show-current").strip(), "modsys/init")
        self.assertEqual(git(self.root, "rev-list", "--count", f"{base}..HEAD").strip(), "1")
        committed = git(self.root, "show", "--name-only", "--format=", "HEAD").split()
        self.assertEqual(sorted(committed), data["git_add"])
        self.assertEqual(git(self.remote, "rev-parse", "modsys/init"),
                         git(self.root, "rev-parse", "HEAD"))
        (call,) = self.calls()
        argv = call["argv"]
        self.assertEqual(argv[:6], ["pr", "create", "--base", "main", "--head", "modsys/init"])
        for needle in ("## Verify", "- lint: 0 error(s), 0 warning(s)",
                       "- routing: hit rate 1.0 (30/30, top 3; threshold 0.8)",
                       "| cart | 5 | 5 |", "## Judgement items (init reconcile)",
                       "- duplicate `formatPrice`: packages/catalog/src/books.ts:14"):
            self.assertIn(needle, call["body"])
        self.assertEqual(git(self.root, "status", "--porcelain"), "")
        self.assertEqual(state(self.root)["pr"], "https://example.invalid/bookshop/pull/1")

    def test_the_base_branch_and_no_tasks(self):
        (self.root / WORK / "routing-tasks.json").unlink()
        ok(self.root, "init", "verify")
        _, data, _ = self.open_pr("--base", "develop", "--branch", "init/docs")
        (call,) = self.calls()
        self.assertEqual(call["argv"][2:6], ["--base", "develop", "--head", "init/docs"])
        self.assertIn("- routing: not measured", call["body"])

    def refused_pr(self, *flags: str, env=None) -> str:
        before = (protected_sha(self.root), git(self.root, "branch", "--list"))
        with mock.patch.dict(os.environ, env or self.env):
            code, out, err = run("init", "finish", "--open-pr", *flags, "--root", str(self.root))
        self.assertEqual((code, out), (2, ""), err)
        self.assertEqual((protected_sha(self.root), git(self.root, "branch", "--list")), before)
        return err

    def test_the_refusals(self):
        (self.root / "notes.txt").write_text("n\n")
        self.assertIn("working tree not clean (notes.txt)", self.refused_pr())
        (self.root / "notes.txt").unlink()
        (self.root / "README.md").write_text("changed\n")
        self.assertIn("working tree not clean (README.md)", self.refused_pr())
        git(self.root, "checkout", "-q", "--", "README.md")
        self.assertIn("gh is not installed (needed for --open-pr)",
                      self.refused_pr(env={**IDENTITY, "PATH": "/usr/bin:/bin"}))
        for flag in ("--base", "--branch"):
            self.assertIn("expected one argument", self.refused_pr(flag, "-x"))  # argparse
            self.assertIn("may not start with '-'", self.refused_pr(f"{flag}=-x"))
        git(self.root, "branch", "modsys/init")
        self.assertIn("branch modsys/init exists", self.refused_pr())
        git(self.root, "branch", "-D", "modsys/init")
        git(self.root, "remote", "remove", "origin")
        self.assertIn("no git remote 'origin'", self.refused_pr())

    def test_a_failed_push_or_gh_leaves_it_pending(self):
        shutil.rmtree(self.remote)
        _, data, err = self.open_pr(code=1)
        self.assertEqual(data["pr"], "pending")
        self.assertIn("modsys: the pull request is pending: git push failed", err)
        s = state(self.root)
        self.assertEqual((s["pr"], s["open_pr"]["committed"], s["open_pr"]["pushed"]),
                         ("pending", True, False))
        self.assertEqual(git(self.root, "branch", "--show-current").strip(), "modsys/init")
        self.assertEqual(self.calls(), [])
        self.setUp()
        gh_shim(self.bin, self.log, code=1)
        _, data, err = self.open_pr(code=1)
        self.assertIn("gh pr create failed", err)
        s = state(self.root)
        self.assertEqual((s["pr"], s["open_pr"]["pushed"]), ("pending", True))


if __name__ == "__main__":
    unittest.main()
