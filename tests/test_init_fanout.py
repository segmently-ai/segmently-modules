"""`init fanout` (D1, phase 4): one work item per confirmed module — its files (capped at 200),
neighbours, roles, staging dir and a prompt rendered from the template chain — and the modules
created by hand after gate 3 (D15(d), SI-30)."""
import json
import os
import re
import string
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from modsys.create import engine_templates
from tests.helpers import git, run_json
from tests.init_helpers import ROLES, SIX, WORK, ok, shop, state, text, tree_sha

KEYS = ["module", "parent", "paths", "files", "files_total", "neighbours", "roles",
        "staging_dir", "prompt"]


class FanoutRepo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name).resolve()

    def tearDown(self):
        self._tmp.cleanup()

    def item(self, root: Path, module: str) -> dict:
        return json.loads((root / WORK / "work" / f"{module}.json").read_text())


class WorkItemsTest(FanoutRepo):  # P5B-AC-001
    def test_one_item_per_included_module(self):
        root = shop(self.base)
        data = ok(root, "init", "fanout")
        self.assertEqual((data["items"], data["existing"], data["status"], data["work"]),
                         (SIX, [], "written", f"{WORK}/work/"))
        self.assertEqual(sorted(p.name for p in (root / WORK / "work").iterdir()),
                         [f"{m}.json" for m in SIX])
        cart = self.item(root, "cart")
        self.assertEqual(list(cart), KEYS)
        self.assertEqual({k: cart[k] for k in KEYS if k != "prompt"}, {
            "module": "cart", "parent": None, "paths": ["packages/cart/**"],
            "files": ["packages/cart/package.json", "packages/cart/src/index.ts",
                      "packages/cart/src/lines.ts"], "files_total": 3,
            "neighbours": [{"to": "catalog", "imports": 1}], "roles": ROLES,
            "staging_dir": f"{WORK}/staging/cart"})
        self.assertEqual(self.item(root, "storefront")["neighbours"],
                         [{"to": "cart", "imports": 1}, {"to": "catalog", "imports": 1},
                          {"to": "ui-kit", "imports": 1}])
        self.assertEqual({m: e["status"] for m, e in state(root)["modules"].items()},
                         dict.fromkeys(SIX, "pending"))
        self.assertEqual(state(root)["phases"]["fanout"]["status"], "done")
        self.assertFalse((root / WORK / "staging").exists())

    def test_an_excluded_module_gets_no_item(self):
        root = shop(self.base, exclude=("tools", "storefront"))
        self.assertEqual(ok(root, "init", "fanout")["items"],
                         ["cart", "catalog", "payments", "recommendations", "ui-kit"])
        self.assertFalse((root / WORK / "work/storefront.json").exists())
        self.assertEqual(self.item(root, "cart")["neighbours"], [{"to": "catalog", "imports": 1}])

    def test_the_200_file_cap(self):
        for count in (199, 200, 201):
            with self.subTest(files=count):
                root = self.base / f"r{count}"
                (root / "src/big").mkdir(parents=True)
                for i in range(count):
                    (root / "src/big" / f"f{i:03}.py").write_text("X = 1\n")
                git(root, "init", "-q", "-b", "main")
                ok(root, "init", "map")
                ok(root, "init", "confirm")
                ok(root, "init", "fanout")
                item = self.item(root, "big")
                expected = sorted(f"src/big/f{i:03}.py" for i in range(count))[:200]
                self.assertEqual((item["files"], item["files_total"]), (expected, count))
                note = ("(the first 200 of 201 files, in path order)" if count == 201 else
                        f"({count} files)")
                self.assertIn(note, item["prompt"])

    def test_a_second_fanout_is_byte_identical(self):
        root = shop(self.base)
        ok(root, "init", "fanout")
        first = tree_sha(root / WORK / "work")
        self.assertEqual(ok(root, "init", "fanout")["status"], "unchanged")
        self.assertEqual(tree_sha(root / WORK / "work"), first)
        other = shop(self.base, name="other")
        ok(other, "init", "fanout")
        self.assertEqual(tree_sha(other / WORK / "work"), first)


class ModulePromptTest(FanoutRepo):  # P5B-AC-002 (SI-1)
    def test_the_engine_prompt(self):
        root = shop(self.base)
        ok(root, "init", "fanout")
        prompt = self.item(root, "cart")["prompt"]
        for needle in ("`cart`", "`packages/cart/**`", "(3 files)", "- `packages/cart/src/lines.ts`",
                       "- `catalog` (1 import(s))", f"`{WORK}/staging/cart/`",
                       "### `MODULE.md`", "### `roles/developer.md`", "### `roles/qa.md`",
                       "### `roles/po.md`", "### `roles/architect.md`", "### `entry.json`",
                       "one sentence of 20–200 characters", "at least 5 distinct words",
                       "`related_modules` (optional)", "depends-on, complements",
                       "| Name | Path | Purpose |", "Describe only components that exist",
                       "Never write outside", "# Cart — developer", "## Where the code lives"):
            self.assertIn(needle, prompt)
        flat = " ".join(prompt.split())  # the real-agent findings of G9 / G11 (the keyword
        for needle in (  # forms, the paths the invented check verifies)
                "Routing matches whole words exactly, without stemming",
                "the plural and verb forms of the key nouns (`suggestion`, `suggestions`, "
                "`suggest`)", "a phrase of several words only when developers write exactly "
                "that phrase", "backticks mark a path the check verifies",
                "written from the repository root, not from the package",
                "Never backtick a path that does not exist", "an import specifier such as "
                "`./lines`", "(a sibling doc: `modules/cart/roles/qa.md`; the main doc: "
                "`modules/cart/MODULE.md`)"):
            self.assertIn(needle, flat)
        self.assertNotIn("${", prompt)
        self.assertIn("<one sentence: what the module does, why, when to use it>", prompt)

    def test_the_keywords_bullet(self):  # P6-AC-040 (D15): domain words, every verb form
        root = shop(self.base)
        ok(root, "init", "fanout")
        for module in SIX:
            prompt = self.item(root, module)["prompt"]
            self.assertNotIn("${", prompt)
            flat = " ".join(prompt.split())
            for needle in ("Routing matches whole words exactly, without stemming",
                           "the plural and verb forms of the key nouns (`suggestion`, "
                           "`suggestions`, `suggest`)",
                           "Give the words for what the module handles as a task would name "
                           "them, including the things and actions its `## Purpose` paragraph "
                           "names, even where the code names them differently (a payments "
                           "module: `card`, `decline`, `charge`)",
                           "each key verb in every form tasks use — base, `-s`, `-ed`, `-ing` "
                           "(`charge`, `charges`, `charged`, `charging`)"):
                self.assertIn(needle, flat)
            self.assertNotIn("copy the paragraph", flat)  # SI-25: the words, not the text
        source = (engine_templates() / "init/module_prompt.md").read_text(encoding="utf-8")
        self.assertEqual(set(string.Template(source).get_identifiers()), {  # f1f5e46's set
            "ask_fields", "description_max", "description_min", "docs", "files", "files_note",
            "min_keywords", "module", "module_doc", "modules_dir", "neighbours", "paths",
            "relations", "staging_dir"})

    def test_only_the_keywords_bullet_changed(self):  # P6-AC-041 (D15)
        old_bullet = (  # the bullet at f1f5e46, pinned
            "- `keywords`: at least ${min_keywords} distinct words a developer would type in a "
            "task about this\n  module (domain words, not file names). Routing matches whole "
            "words exactly, without stemming,\n  so give the words in the forms tasks use: "
            "single words, with the plural and verb forms of the\n  key nouns (`suggestion`, "
            "`suggestions`, `suggest`); a phrase of several words only when\n  developers write "
            "exactly that phrase;\n")
        bullet = re.compile(r"^- `keywords`:.*?\n(?=- `related_modules`)", re.S | re.M)
        new = shop(self.base, name="new")
        ok(new, "init", "fanout")
        old = shop(self.base, name="old")
        override = old / ok(old, "templates", "override", "init/module_prompt.md")["file"]
        source = override.read_text(encoding="utf-8")
        self.assertEqual(len(bullet.findall(source)), 1)
        override.write_text(bullet.sub(lambda m: old_bullet, source), encoding="utf-8")
        ok(old, "init", "fanout")
        for module in SIX:
            with self.subTest(module=module):
                a, b = self.item(old, module), self.item(new, module)
                self.assertEqual({k: v for k, v in a.items() if k != "prompt"},
                                 {k: v for k, v in b.items() if k != "prompt"})
                self.assertNotEqual(a["prompt"], b["prompt"])
                self.assertEqual(bullet.sub("", a["prompt"]), bullet.sub("", b["prompt"]))

    def test_a_custom_modules_dir(self):  # final review M-5: the layout init done checks
        root = shop(self.base, config='[paths]\nmodules_dir = "docs/modules"\n'
                                      'module_doc = "README.md"\n')
        ok(root, "init", "fanout")
        prompt = self.item(root, "cart")["prompt"]
        self.assertIn("(a sibling doc: `docs/modules/cart/roles/qa.md`; the main doc: "
                      "`docs/modules/cart/README.md`)", " ".join(prompt.split()))
        self.assertNotIn("`modules/cart/", prompt)
        self.assertNotIn("${", prompt)

    def test_the_placeholder_rule(self):  # P5C-AC-014 (D4): said in words, never with `${`
        root = shop(self.base)
        ok(root, "init", "fanout")
        prompt = self.item(root, "cart")["prompt"]
        self.assertNotIn("${", prompt)
        flat = " ".join(prompt.split())
        for needle in ("Leave no placeholder of these templates behind",
                       "(the title, the description, the module, the role, the files, the "
                       "paths, the docs and the others these templates use)",  # final review M-6
                       "belongs to the code you describe", "is fine",
                       "uses one of these templates' names that way is refused: reword it"):
            self.assertIn(needle, flat)
        source = (engine_templates() / "init/module_prompt.md").read_text(encoding="utf-8")
        self.assertLessEqual({"module", "staging_dir", "paths", "files_note", "neighbours",
                              "files", "docs", "description_min", "description_max",
                              "min_keywords", "relations", "ask_fields", "modules_dir",
                              "module_doc"},
                             set(string.Template(source).get_identifiers()))
        prose = source.split("## Rules", 1)[1]  # the template's own words hold no `${` but
        self.assertEqual(set(re.findall(r"\$\{(\w+)\}", prose)),  # the values it renders
                         {"modules_dir", "module", "module_doc", "staging_dir"})

    def test_the_template_chain(self):
        root = shop(self.base)
        rows = {r["template"]: r for r in ok(root, "templates", "list")}
        for name in ("init/module_prompt.md", "init/routing_prompt.md"):
            self.assertEqual((rows[name]["role"], rows[name]["source"], Path(rows[name]["path"])),
                             (None, "engine", engine_templates() / name))
        pack = root / ".modsys/packs/team"
        (pack / "templates/init").mkdir(parents=True)
        (pack / "pack.toml").write_text('id = "team"\nversion = "9.0.0"\n')
        (pack / "templates/init/module_prompt.md").write_text("Pack prompt for ${module}: "
                                                              "${files_note}\n")
        self.assertEqual(ok(root, "templates", "list")[-2]["source"], "pack:team")
        ok(root, "init", "fanout")
        self.assertEqual(self.item(root, "cart")["prompt"], "Pack prompt for cart: (3 files)\n")
        data = ok(root, "templates", "override", "init/module_prompt.md")
        override = root / data["file"]
        self.assertEqual((data["from"], override.read_text()),
                         ("pack:team", "Pack prompt for ${module}: ${files_note}\n"))
        override.write_text("Team prompt for ${module} ${unknown}\n")
        self.assertEqual(ok(root, "templates", "list")[-2]["source"], "override")
        ok(root, "init", "fanout")
        self.assertEqual(self.item(root, "cart")["prompt"], "Team prompt for cart <unknown>\n")


class ExistingModulesTest(FanoutRepo):  # P5B-AC-051 (D15(d), SI-30)
    DESC = "Book titles, authors and ISBN lookups for the shop."

    def create_catalog(self, root: Path) -> None:
        ok(root, "create", "catalog", "--non-interactive", "--description", self.DESC,
           "--keywords", "catalog, book, isbn, author, title")

    def test_a_module_created_by_hand(self):
        root = shop(self.base)
        self.create_catalog(root)
        docs = tree_sha(root / "modules/catalog")
        data = ok(root, "init", "fanout")
        self.assertEqual(data["existing"], ["catalog"])
        item = self.item(root, "catalog")
        self.assertEqual((item["existing"], item["prompt"]), (True, None))
        self.assertEqual(state(root)["modules"]["catalog"],
                         {"status": "done", "attempts": 0, "error": None, "existing": True})
        self.assertEqual(tree_sha(root / "modules/catalog"), docs)
        out = text(root, "init", "status")[1]
        self.assertIn("catalog                  done  (existing)", out.splitlines())

    def test_an_unregistered_module_directory(self):
        root = shop(self.base)
        (root / "modules/catalog").mkdir(parents=True)
        (root / "modules/catalog/notes.md").write_text("# notes\n")
        before = (root / WORK / "state.json").read_bytes()
        code, env, err = run_json("init", "fanout", "--root", str(root))
        self.assertEqual((code, env), (2, None))
        self.assertIn("modules/catalog/ exist(s) without a registry entry — register it with "
                      "modsys create, or move it away", err)
        self.assertFalse((root / WORK / "work").exists())
        self.assertEqual((root / WORK / "state.json").read_bytes(), before)

    def test_a_registry_module_that_was_not_confirmed(self):
        root = shop(self.base)
        ok(root, "create", "legacy", "--non-interactive", "--description",
           "An old module somebody created by hand.", "--keywords", "old, legacy, archive, "
           "ledger, history")
        ok(root, "init", "fanout")
        self.assertNotIn("legacy", state(root)["modules"])
        self.assertFalse((root / WORK / "work/legacy.json").exists())

    def test_starting_over_is_refused_with_modules_created_by_hand(self):  # M-14
        root = shop(self.base)
        self.create_catalog(root)
        ok(root, "init", "fanout")
        before = (root / WORK / "state.json").read_bytes()
        for flags in (("--restart",), ()):
            with self.subTest(flags=flags):
                code, env, err = run_json("init", "map", *flags, "--root", str(root))
                self.assertEqual((code, env), (2, None))
                self.assertIn("modules/registry.json already has 1 module(s), created by hand "
                              "during init — init map (and --restart) starts only from code "
                              "without modules: continue with modsys init resume", err)
        self.assertEqual((root / WORK / "state.json").read_bytes(), before)


class StaleItemTest(FanoutRepo):  # Task 4 review M2: a failed removal is a named write failure
    def test_a_stale_work_item_that_cannot_be_removed(self):
        root = shop(self.base)
        ok(root, "init", "fanout")
        (root / WORK / "work/zz-gone.json").write_text("{}")
        real = Path.unlink

        def unlink(path, *args, **kwargs):
            if path.name == "zz-gone.json":
                raise PermissionError(13, "Permission denied")
            return real(path, *args, **kwargs)

        with mock.patch.object(Path, "unlink", autospec=True, side_effect=unlink):
            code, env, err = run_json("init", "fanout", "--root", str(root))
        self.assertEqual((code, env), (2, None))
        self.assertIn(f"modsys: error: cannot write {WORK}/work/zz-gone.json: Permission denied",
                      err)
        self.assertNotIn("internal error", err)

    def test_a_work_item_that_cannot_be_read(self):  # follow-up extension: named, not internal
        rows = [("dangling", "No such file or directory"), ("directory", "Is a directory")]
        if os.geteuid() != 0:  # (a root user reads a mode-0 file anyway)
            rows.append(("mode 0", "Permission denied"))
        for kind, reason in rows:
            with self.subTest(kind=kind):
                root = shop(self.base, name=kind.replace(" ", "-"))
                ok(root, "init", "fanout")
                cart = root / WORK / "work/cart.json"
                if kind == "dangling":
                    cart.unlink()
                    cart.symlink_to(self.base / "nowhere.json")
                elif kind == "directory":
                    cart.unlink()
                    cart.mkdir()
                else:
                    cart.chmod(0)
                before = (root / WORK / "state.json").read_bytes()
                code, out, err = text(root, "init", "fanout", "--json")
                self.assertEqual((code, out), (2, ""))
                self.assertEqual(err, f"modsys: error: cannot read {WORK}/work/cart.json: "
                                      f"{reason} — remove it, then run modsys init fanout; "
                                      f"nothing written\n")
                self.assertEqual((root / WORK / "state.json").read_bytes(), before)
                cart.rmdir() if kind == "directory" else cart.unlink()  # the way out it names
                self.assertEqual(ok(root, "init", "fanout")["status"], "written")
                self.assertEqual(self.item(root, "cart")["module"], "cart")


if __name__ == "__main__":
    unittest.main()
