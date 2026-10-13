"""Which modules own code: MS054 (info) an active module that maps no code file — drift never
fires for it — unless `[coverage] doc_only` names it (a planned module never counts); MS056 a
`doc_only` name that is no module; `next` lists the MS054 modules in one `no-code`
item and a role item lists the modules without the doc. A `[[code_map]]` rule `shared = true`
routes files that other modules own too, on purpose: MS053 leaves its overlaps alone."""
import json
import tempfile
import unittest

from tests.helpers import init_git, make_repo, mutate_registry, run, run_json

RULE = '[[code_map]]\nid = "src"\npattern = "src/{module}/**"\n'
MODULES = {"shop": ["book"], "theory": ["idea"], "later": ["plan"]}


class Repo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.n = 0

    def tearDown(self):
        self._tmp.cleanup()

    def repo(self, config: str = RULE, files=("src/shop/a.py", "src/later/b.py"), git=True):
        self.n += 1
        root = make_repo(f"{self._tmp.name}/{self.n}", MODULES, config, files)
        mutate_registry(root, lambda d: d["modules"]["later"].update(status="planned"))
        if git:
            init_git(root)
        return root

    def findings(self, root, *codes) -> list[tuple]:
        code, env, err = run_json("lint", "--fail-on", "never", "--root", str(root))
        self.assertEqual((code, err), (0, ""))
        return [(f["code"], f["severity"], f["module"], f["message"])
                for f in env["data"]["findings"] if f["code"] in codes]


class OwnershipLintTest(Repo):
    def test_an_active_module_without_code(self):
        root = self.repo(files=("src/shop/a.py",))  # `later` is planned: never reported
        self.assertEqual(self.findings(root, "MS054", "MS056"), [
            ("MS054", "info", "theory", "active module maps no code file — map its code (segmently-modules "
             "code-map add), list it in [coverage] doc_only when it owns no code on purpose, or "
             "retire it")])

    def test_doc_only_silences_it_and_a_stale_name_is_a_warning(self):
        root = self.repo(RULE + '\n[coverage]\ndoc_only = ["theory", "gone", "shop/child"]\n')
        self.assertEqual(self.findings(root, "MS054", "MS056"), [
            ("MS056", "warning", "*", "[coverage] doc_only names 'gone', which is not a registry "
                                      "module"),
            ("MS056", "warning", "*", "[coverage] doc_only names 'shop/child' — it takes "
                                      "top-level modules (a module counts its children's code)")])

    def test_a_code_pointer_or_a_child_counts_docs_never_do(self):
        root = self.repo(RULE + '\n[fields.file_paths]\ntype = "string[]"\nkind = '
                                '"code_pointer"\ndescription = "Key files"\n',
                         files=("src/shop/a.py", "lib/theory.py"))
        mutate_registry(root, lambda d: d["modules"]["theory"].update(
            file_paths=["lib/theory.py"]))
        self.assertEqual([m for _c, _s, m, _ in self.findings(root, "MS054")], [])

    def test_no_rule_or_no_git_no_finding(self):
        self.assertEqual(self.findings(self.repo(config=""), "MS054"), [])
        with tempfile.TemporaryDirectory() as tmp:
            self._tmp, old = tempfile.TemporaryDirectory(dir=tmp), self._tmp
            try:
                self.assertEqual(self.findings(self.repo(git=False), "MS054"), [])
            finally:
                self._tmp.cleanup()
                self._tmp = old


class NextTest(Repo):
    def items(self, root, *argv) -> list[dict]:
        code, env, err = run_json("next", *argv, "--root", str(root))
        self.assertEqual((code, err), (0, ""))
        return env["data"]["items"]

    def test_the_no_code_item_lists_the_modules(self):
        root = self.repo()
        item = next(i for i in self.items(root) if i["kind"] == "no-code")
        self.assertEqual((item["summary"], item["command"], item["modules"]),
                         ("1 active module(s) map no code file, so drift never fires for them: "
                          "theory", "segmently-modules lint", ["theory"]))

    def test_a_role_item_lists_the_modules_without_the_doc(self):
        root = self.repo()
        roles = [i for i in self.items(root) if i["kind"] == "role"]
        dev = next(i for i in roles if i["summary"].startswith("developer:"))
        self.assertEqual(dev["summary"], "developer: no doc in 3 module(s): later, shop, theory")
        self.assertEqual(dev["modules"], ["later", "shop", "theory"])
        code, out, _err = run("next", "--root", str(root))
        self.assertIn("developer: no doc in 3 module(s): later, shop, theory\n", out)


class SharedRuleTest(Repo):
    def overlap(self, shared: str) -> list:
        config = ('[[code_map]]\nid = "feature"\nmodule = "theory"\nglobs = ["src/shop/eval/**"]\n'
                  + shared + RULE)
        root = self.repo(config, files=("src/shop/a.py", "src/shop/eval/e.py", "src/later/b.py"))
        return [m for _c, _s, _m, m in self.findings(root, "MS053")]

    def test_shared_silences_the_overlap_and_both_modules_keep_the_file(self):
        self.assertEqual(len(self.overlap("")), 1)
        self.assertEqual(self.overlap("shared = true\n"), [])
        root = make_repo(f"{self._tmp.name}/x", MODULES, '[[code_map]]\nid = "feature"\nmodule = '
                         '"theory"\nglobs = ["src/shop/eval/**"]\nshared = true\n' + RULE,
                         ("src/shop/eval/e.py",))
        init_git(root)
        for target in ("theory", "shop"):
            code, env, _err = run_json("code-map", "files", target, "--root", str(root))
            self.assertEqual(code, 0)
            self.assertIn("src/shop/eval/e.py", [f["path"] for f in env["data"]["files"]])

    def test_exclusive_and_shared_together_are_refused(self):
        root = self.repo('[[code_map]]\nid = "x"\nmodule = "theory"\nglobs = ["src/**"]\n'
                         'exclusive = true\nshared = true\n')
        code, out, err = run("lint", "--root", str(root))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("code_map.x: exclusive takes its files from the other rules and shared "
                      "shares them — set one of the two", err)

    def test_code_map_add_shared(self):
        root = self.repo()
        code, env, err = run_json("code-map", "add", "evals", "--glob", "src/shop/eval/**",
                                  "--module", "theory", "--shared", "--root", str(root))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(env["data"]["block"], '[[code_map]]\nid = "evals"\nmodule = "theory"\n'
                                               'globs = ["src/shop/eval/**"]\nshared = true\n')
        code, _out, err = run("code-map", "list", "--shared", "--root", str(root))
        self.assertEqual(code, 2)
        self.assertIn("--shared and --dry-run apply to code-map add", err)


class BaseTest(Repo):
    def test_ci_and_next_name_the_commit_and_a_base_that_moved_on(self):
        from tests.helpers import git
        root = self.repo()
        head = git(root, "rev-parse", "HEAD").strip()
        code, env, _err = run_json("ci", "--base", "HEAD", "--fail-on", "never", "--root",
                                   str(root))
        self.assertEqual((env["data"]["base_commit"], env["data"]["notes"][1:]), (head, []))
        git(root, "checkout", "-q", "-b", "target")
        (root / "src/shop/c.py").write_text("c = 1\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "target moves on")
        git(root, "checkout", "-q", "main")
        code, env, _err = run_json("ci", "--base", "target", "--fail-on", "never", "--root",
                                   str(root))
        note = ("--base target ({}) is not an ancestor of HEAD: the drift also counts what target "
                "changed that HEAD lacks — on a branch, pass its merge base: git merge-base "
                "target HEAD ({})")
        tip = git(root, "rev-parse", "target").strip()
        self.assertEqual(env["data"]["notes"], [note.format(tip[:12], head[:12])])
        data = json.loads(run("next", "--base", "target", "--json", "--root", str(root))[1])
        self.assertEqual(data["data"]["base"], {"ref": "target", "commit": tip,
                                                "notes": [note.format(tip[:12], head[:12])]})
        code, out, _err = run("next", "--base", "target", "--root", str(root))
        self.assertIn(f"base target at {tip[:12]}\nnote: --base target", out)
        code, out, _err = run("ci", "--base", "target", "--root", str(root))
        self.assertIn(f"since target at {tip[:12]}", out)

    def test_a_shallow_clone_says_to_fetch_the_history(self):
        from tests.helpers import git
        root = self.repo()
        git(root, "checkout", "-q", "-b", "target")
        (root / "src/shop/c.py").write_text("c = 1\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "target moves on")
        git(root, "checkout", "-q", "main")
        (root / "src/shop/d.py").write_text("d = 1\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "main moves on")
        clone = root.parent / "clone"
        git(root.parent, "clone", "-q", "--depth", "1", "--no-single-branch",
            f"file://{root}", str(clone))
        code, env, err = run_json("ci", "--base", "origin/target", "--fail-on", "never",
                                  "--root", str(clone))
        self.assertEqual((code, err), (0, ""))
        self.assertIn("this clone is shallow: fetch the history first (git fetch --unshallow; "
                      "in CI a full checkout) to find the merge base", env["data"]["notes"][-1])

    def test_a_failed_step_names_the_severity_it_fails_at(self):
        root = self.repo('[lint]\nlink_severity = "warning"\n' + RULE)
        (root / "modules/shop/MODULE.md").write_text("# shop\n\n[x](gone.md)\n", encoding="utf-8")
        code, out, _err = run("ci", "--base", "HEAD", "--root", str(root))
        self.assertEqual(code, 1)
        self.assertIn("lint      failed       0 error(s), 1 warning(s), 1 info — fails at "
                      "warning\n", out)


if __name__ == "__main__":
    unittest.main()
