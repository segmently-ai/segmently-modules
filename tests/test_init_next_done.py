"""The sequential driver (D1, driver 2): `init next` claims the next pending module and returns
its work item; `init done MODULE` checks the files written into its staging directory (SI-8)."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.init_fake_executor import write_docs
from tests.init_helpers import ROLES, WORK, ok, shop, state, text


class DriverRepo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.template = shop(Path(cls._tmp.name).resolve(), name="template")
        ok(cls.template, "init", "fanout")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(dir=self._tmp.name))
        self.root = self.base / "shop"
        shutil.copytree(self.template, self.root, symlinks=True)

    def claim(self) -> dict:
        return ok(self.root, "init", "next")


class NextTest(DriverRepo):  # P5B-AC-005 (init next)
    def test_the_first_pending_module_in_name_order(self):
        data = self.claim()
        self.assertEqual(set(data), {"action", "item", "path", "counts"})
        self.assertEqual((data["item"]["module"], data["path"]),
                         ("cart", f"{WORK}/work/cart.json"))
        self.assertEqual(data["counts"], {"pending": 5, "running": 1, "done": 0, "failed": 0})
        self.assertEqual(state(self.root)["modules"]["cart"],
                         {"status": "running", "attempts": 1, "error": None})
        self.assertEqual(self.claim()["item"]["module"], "catalog")

    def test_text_output(self):
        code, out, err = text(self.root, "init", "next")
        self.assertEqual((code, err), (0, ""))
        item = json.loads((self.root / WORK / "work/cart.json").read_text())
        self.assertEqual(out, f"claimed       cart  (work item {WORK}/work/cart.json)\n"
                              + item["prompt"])

    def test_a_symlinked_staging_dir_is_refused(self):  # Task 5 review I1 (Work.clear)
        target = self.base / "elsewhere"
        target.mkdir()
        (target / "keep.md").write_text("keep\n")
        staging = self.root / WORK / "staging"
        staging.mkdir(parents=True, exist_ok=True)
        (staging / "cart").symlink_to(target)
        before = (self.root / WORK / "state.json").read_bytes()
        code, out, err = text(self.root, "init", "next", "--json")
        self.assertEqual((code, out), (2, ""))
        self.assertIn(f"{WORK}/staging/cart is a symlink — remove it (its target is left alone)",
                      err)
        self.assertEqual((target / "keep.md").read_text(), "keep\n")
        self.assertEqual((self.root / WORK / "state.json").read_bytes(), before)


class DoneTest(DriverRepo):  # P5B-AC-005 (init done, the table)
    def setUp(self):
        super().setUp()
        self.claim()
        self.item = json.loads((self.root / WORK / "work/cart.json").read_text())
        self.staging = self.root / self.item["staging_dir"]

    def entry(self, **changes) -> None:
        path = self.staging / "entry.json"
        entry = json.loads(path.read_text())
        entry.update(changes)
        path.write_text(json.dumps({k: v for k, v in entry.items() if v is not None}))

    def outcome(self, change=None) -> tuple[int, list[str]]:
        shutil.rmtree(self.staging, ignore_errors=True)
        write_docs(self.root, self.item)
        if change:
            change()
        before = json.dumps(state(self.root)["modules"]["cart"])
        code, out, err = text(self.root, "init", "done", "cart", "--json")
        data = json.loads(out)["data"]
        lines = err.splitlines()
        if code == 1:
            self.assertEqual(json.dumps(state(self.root)["modules"]["cart"]), before)
            self.assertEqual(lines, [f"modsys: cart: {p}" for p in data["problems"]])
            self.assertEqual(data["status"], "running")
        return code, data["problems"]

    def test_the_table(self):
        twenty = "x" * 20
        rows = [
            (lambda: self.entry(description=twenty), []),
            (lambda: self.entry(description="y" * 200), []),
            (lambda: self.entry(description="y" * 19), ["description must be 20–200 characters"]),
            (lambda: self.entry(description="y" * 201), ["description must be 20–200 characters"]),
            (lambda: self.entry(keywords=["a", "b", "c", "d"]),
             ["at least 5 distinct keywords (a list of non-empty strings)"]),
            (lambda: self.entry(keywords=["a", "b", "c", "d", "d"]),
             ["at least 5 distinct keywords (a list of non-empty strings)"]),
            (lambda: (self.staging / "roles/qa.md").unlink(), ["missing roles/qa.md"]),
            (lambda: (self.staging / "MODULE.md").write_text("  \n\n "), ["MODULE.md is empty"]),
            (lambda: (self.staging / "MODULE.md").write_text("# ${title}\n"),
             ["MODULE.md: unfilled placeholder ${title}"]),
            (lambda: (self.staging / "notes.txt").write_text("n\n"),
             ["unexpected file notes.txt"]),
            (lambda: (self.staging / "entry.json").write_text("{not json"),
             ["entry.json: invalid JSON"]),
            (lambda: (self.staging / "entry.json").write_text("[]"), ["entry.json: not an object"]),
            (lambda: self.entry(status="active"), ["entry.json: unknown key 'status'"]),
            (lambda: self.entry(related_modules=[
                {"module": "nosuch", "relation": "depends-on", "description": "d"},
                {"module": "catalog", "relation": "uses", "description": "d"},
                {"module": "catalog", "relation": "depends-on"}]),
             ["related_modules[0]: 'nosuch' is not a confirmed module",
              "related_modules[1]: relation 'uses' is not in the relations (depends-on, "
              "complements, implemented-in, shares-contract, superseded-by)",
              "related_modules[2]: missing description"]),
        ]
        for change, problems in rows:
            with self.subTest(problems=problems):
                code, got = self.outcome(change)
                self.assertEqual((code, got), (1 if problems else 0, problems))
                if not problems:  # back to running for the next row
                    s = state(self.root)
                    s["modules"]["cart"]["status"] = "running"
                    (self.root / WORK / "state.json").write_text(json.dumps(s))
        code, got = self.outcome(lambda: self.entry(related_modules=[
            {"module": "catalog", "relation": "depends-on", "description": "imports the books"}]))
        self.assertEqual((code, got, state(self.root)["modules"]["cart"]["status"]),
                         (0, [], "done"))

    def test_the_text_of_a_check_with_problems(self):  # Task 5 review M1 (_render_done)
        write_docs(self.root, self.item)
        (self.staging / "roles/qa.md").unlink()
        self.entry(keywords=["one"])
        code, out, err = text(self.root, "init", "done", "cart")
        self.assertEqual((code, out), (1, "not done      cart (2 problem(s) on stderr)\n"))
        self.assertEqual(err.splitlines(), [
            "modsys: cart: missing roles/qa.md",
            "modsys: cart: at least 5 distinct keywords (a list of non-empty strings)"])

    def test_a_failed_item_that_still_has_problems(self):  # Task 5 review M2
        s = state(self.root)
        s["modules"]["cart"].update(status="failed", error="exit 3: gave up")
        (self.root / WORK / "state.json").write_text(json.dumps(s))
        write_docs(self.root, self.item)
        (self.staging / "MODULE.md").write_text("")
        code, out, err = text(self.root, "init", "done", "cart", "--json")
        data = json.loads(out)["data"]
        self.assertEqual((code, data["status"], data["problems"]),
                         (1, "failed", ["MODULE.md is empty"]))
        self.assertEqual(state(self.root)["modules"]["cart"]["status"], "failed")

    def test_a_symlinked_staging_dir_is_one_problem(self):  # M-8: its target is never read
        elsewhere = self.base / "elsewhere"
        shutil.rmtree(self.staging)
        elsewhere.mkdir()
        self.staging.symlink_to(elsewhere)
        write_docs(self.root, self.item, staging=elsewhere)
        code, out, err = text(self.root, "init", "done", "cart", "--json")
        self.assertEqual((code, json.loads(out)["data"]["problems"]),
                         (1, [f"the staging dir {WORK}/staging/cart is a symlink (write the "
                              f"files into a real directory)"]))

    def test_claimed_again_while_it_was_checked(self):  # M-10: the same attempt only
        from modsys.init_work import Work
        write_docs(self.root, self.item)
        real = Work.problems

        def meanwhile(work, module):  # another driver resets and claims it during the check
            found = real(work, module)
            s = state(self.root)
            s["modules"][module]["attempts"] += 1
            (self.root / WORK / "state.json").write_text(json.dumps(s))
            return found

        with mock.patch("modsys.init_work.Work.problems", autospec=True, side_effect=meanwhile):
            code, out, err = text(self.root, "init", "done", "cart", "--json")
        data = json.loads(out)["data"]
        self.assertEqual((code, data["status"]), (1, "running"))
        self.assertEqual(data["problems"], ["changed while it was checked (now running, attempt "
                                            "2): nothing marked — check it again once it is "
                                            "written"])
        self.assertEqual(state(self.root)["modules"]["cart"]["status"], "running")
        self.assertEqual(ok(self.root, "init", "done", "cart")["status"], "done")

    def test_several_problems_at_once_and_a_symlink(self):
        def change():
            (self.staging / "roles/po.md").unlink()
            (self.staging / "roles/po.md").symlink_to(self.staging / "MODULE.md")
            (self.staging / "roles/qa.md").unlink()
            self.entry(description="short", keywords=["one"])
        code, got = self.outcome(change)
        self.assertEqual((code, got), (1, [
            "missing roles/qa.md", "roles/po.md is a symlink (write the file itself)",
            "description must be 20–200 characters",
            "at least 5 distinct keywords (a list of non-empty strings)"]))


class PlaceholderTest(DriverRepo):  # P5C-AC-012, P5C-AC-013 (D4, SI-11)
    ROWS = [  # (text appended to MODULE.md, the problem — None: done)
        ("\n# ${title}\n", "MODULE.md: unfilled placeholder ${title}"),
        ("\n${description}\n", "MODULE.md: unfilled placeholder ${description}"),
        ("\n${role_description}\n", "MODULE.md: unfilled placeholder ${role_description}"),
        ("\n${module} and ${title}\n", "MODULE.md: unfilled placeholder ${module}"),
        ("\n${staging_dir}\n", "MODULE.md: unfilled placeholder ${staging_dir}"),
        ("\nThe ${title\n", "MODULE.md: unfilled placeholder ${title"),
        ("\nCall `${API_URL}` first.\n", None),
        ("\n```bash\necho \"${HOME}\"\n```\n", None),
        ("\nIt logs `Hello ${userName}`.\n", None),
        ("\n${name}, ${keywords} and ${status}\n", None),  # values fill supplies, no template's
        ("\n$title\n", None),
        ("\n${} and ${ title }\n", None),
        ("\n```js\nconst label = `${title}`;\n```\n",  # a template's own name used by code:
         "MODULE.md: unfilled placeholder ${title}"),  # the residual cost (D4)
    ]

    def setUp(self):
        super().setUp()
        self.claim()
        self.item = json.loads((self.root / WORK / "work/cart.json").read_text())
        self.staging = self.root / self.item["staging_dir"]

    def check(self, doc: str, extra: str) -> list[str]:
        """The problems of `init done cart` with `extra` appended to the staging doc `doc`."""
        shutil.rmtree(self.staging, ignore_errors=True)
        write_docs(self.root, self.item)
        path = self.staging / doc
        path.write_text(path.read_text() + extra)
        code, out, err = text(self.root, "init", "done", "cart", "--json")
        problems = json.loads(out)["data"]["problems"]
        self.assertEqual((code, err.splitlines()),
                         (1 if problems else 0, [f"modsys: cart: {p}" for p in problems]))
        if not problems:  # back to running for the next row
            s = state(self.root)
            s["modules"]["cart"]["status"] = "running"
            (self.root / WORK / "state.json").write_text(json.dumps(s))
        return problems

    def test_the_table(self):
        for extra, problem in self.ROWS:
            with self.subTest(text=extra):
                self.assertEqual(self.check("MODULE.md", extra), [problem] if problem else [])

    def test_override(self):  # a team template's own placeholders count; a dropped one does not
        for rel in ("MODULE.md", *(f"roles/{r}.md" for r in ROLES)):
            path = self.root / ok(self.root, "templates", "override", rel)["file"]
            path.write_text(path.read_text().replace("${title}", "${team_field}"))
        self.assertEqual(self.check("MODULE.md", "\n${team_field}\n"),
                         ["MODULE.md: unfilled placeholder ${team_field}"])
        self.assertEqual(self.check("roles/qa.md", "\n${team_field}\n"),
                         ["roles/qa.md: unfilled placeholder ${team_field}"])
        self.assertEqual(self.check("MODULE.md", "\n${title}\n"), [])

    def test_a_pack_template(self):  # only the roles of the module's work item count
        pack = self.root / ".modsys/packs/team"
        (pack / "templates/roles").mkdir(parents=True)
        (pack / "pack.toml").write_text('id = "team"\nversion = "1.0.0"\n')
        (pack / "templates/roles/qa.md").write_text("# ${title} — qa\n\n${pack_hint}\n")
        (pack / "templates/roles/designer.md").write_text("# ${title}\n\n${designer_hint}\n")
        self.assertEqual(self.check("roles/qa.md", "\n${pack_hint}\n"),
                         ["roles/qa.md: unfilled placeholder ${pack_hint}"])
        self.assertEqual(self.check("MODULE.md", "\n${designer_hint}\n"), [])


HINT = " (write paths from the repository root, as in the file list)"


def missing(doc: str, line: int, token: str) -> str:
    return f"{doc}:{line}: path does not exist: {token}{HINT}"


def at_line_12(token: str) -> str:
    """A MODULE.md whose line 12 holds `token`."""
    return "".join(f"Line {n}.\n" for n in range(1, 12)) + f"See {token} here.\n"


def table(name: str, path: str, header: str = "| Name | Path | Purpose |") -> str:
    """A MODULE.md whose components table has one row, at line 20."""
    return ("".join(f"Line {n}.\n" for n in range(1, 18)) + f"{header}\n|---|---|---|\n"
            f"| {name} | {path} | what it does |\n")


class InventedAtDoneTest(DriverRepo):  # P5C-AC-004…007, 021, 022 (D2, SI-1, SI-2, SI-3)
    def setUp(self):
        super().setUp()
        self.claim()
        self.item = json.loads((self.root / WORK / "work/cart.json").read_text())

    def done(self, docs: dict, root: Path | None = None, item: dict | None = None,
             **entry) -> tuple[int, list[str]]:
        """`init done cart` over the fake writer's output with `docs` ({doc: text, bytes or
        None to remove it}) and `entry` (entry.json keys) written over it."""
        root, item = root or self.root, item or self.item
        staging = root / item["staging_dir"]
        shutil.rmtree(staging, ignore_errors=True)
        write_docs(root, item)
        for rel, body in docs.items():
            path = staging / rel
            if body is None:
                path.unlink()
            elif isinstance(body, bytes):
                path.write_bytes(body)
            else:
                path.write_text(body)
        if entry:
            doc = json.loads((staging / "entry.json").read_text())
            (staging / "entry.json").write_text(json.dumps({**doc, **entry}))
        code, out, err = text(root, "init", "done", "cart", "--json")
        data = json.loads(out)["data"]
        self.assertEqual(set(data), {"action", "module", "status", "problems", "message"})
        self.assertEqual((code, err.splitlines()), (1 if data["problems"] else 0,
                                                    [f"modsys: cart: {p}"
                                                     for p in data["problems"]]))
        s = state(root)
        self.assertEqual(s["modules"]["cart"]["status"], "done" if code == 0 else "running")
        s["modules"]["cart"]["status"] = "running"  # back to running for the next row
        (root / WORK / "state.json").write_text(json.dumps(s))
        return code, data["problems"]

    def test_the_path_table(self):  # P5C-AC-004
        outside = self.base / "outside/x.py"  # it exists, but outside the root
        outside.parent.mkdir()
        outside.write_text("x = 1\n")
        for token, problems in (
                ("`packages/cart/src/lines.ts`", []),
                ("`packages/cart/src/lines.ts:12`", []),
                ("`packages/cart/src/lines.ts#L10`", []),
                ("`src/lines.ts`", [missing("MODULE.md", 12, "src/lines.ts")]),
                ("`roles/qa.md`", [missing("MODULE.md", 12, "roles/qa.md")]),
                ("`../outside/x.py`", [missing("MODULE.md", 12, "../outside/x.py")]),
                ("`/etc/hosts`", [missing("MODULE.md", 12, "/etc/hosts")]),
                ("`packages/*/src`, `https://x.org/a/b`, `<module>/x`, `@scope/pkg`, `word`",
                 [])):
            with self.subTest(token=token):
                self.assertEqual(self.done({"MODULE.md": at_line_12(token)}),
                                 (1 if problems else 0, problems))
        skipped = (at_line_12("the code") + "```\n`packages/cart/src/missing.ts`\n```\n"
                   "<!-- `packages/cart/src/missing.ts` -->\n")
        self.assertEqual(self.done({"MODULE.md": skipped}), (0, []))
        self.assertEqual(self.done({"roles/qa.md": "# Cart — qa\n\nSee `src/lines.ts`.\n"}),
                         (1, [missing("roles/qa.md", 3, "src/lines.ts")]))

    def test_existing(self):  # P5C-AC-005 (SI-3): the disk, its own docs, the planned docs
        for token, problems in (
                ("`modules/cart/roles/qa.md`", []),
                ("`modules/catalog/MODULE.md`, `modules/catalog/roles/developer.md`", []),
                ("`modules/catalog/roles/designer.md`",
                 [missing("MODULE.md", 12, "modules/catalog/roles/designer.md")]),
                ("`modules/nosuch/MODULE.md`", [missing("MODULE.md", 12,
                                                        "modules/nosuch/MODULE.md")])):
            with self.subTest(token=token):
                self.assertEqual(self.done({"MODULE.md": at_line_12(token)}),
                                 (1 if problems else 0, problems))
        planned = table("`Cart`", "`modules/catalog/MODULE.md`")  # not written yet: not read
        self.assertEqual(self.done({"MODULE.md": planned}), (0, []))

    def test_created_by_hand_and_a_custom_modules_dir(self):  # P5C-AC-005
        root = shop(self.base, name="by-hand")
        ok(root, "create", "ui-kit", "--non-interactive", "--description",
           "Buttons, text fields and labels shared by the shop.", "--keywords",
           "button, field, form, label, widget")
        ok(root, "init", "fanout")
        item = ok(root, "init", "next")["item"]
        self.assertEqual(self.done({"MODULE.md": at_line_12("`modules/ui-kit/MODULE.md`")},
                                   root, item), (0, []))
        root = shop(self.base, name="docs-dir", config='[paths]\nmodules_dir = "docs/modules"\n')
        ok(root, "init", "fanout")
        item = ok(root, "init", "next")["item"]
        for token, problems in (
                ("`docs/modules/catalog/MODULE.md`, `docs/modules/cart/roles/qa.md`", []),
                ("`modules/catalog/MODULE.md`", [missing("MODULE.md", 12,
                                                         "modules/catalog/MODULE.md")])):
            with self.subTest(token=token):
                self.assertEqual(self.done({"MODULE.md": at_line_12(token)}, root, item),
                                 (1 if problems else 0, problems))

    def test_table(self):  # P5C-AC-006 (the AC's addLine is the fixture's lineTotal)
        lines = "`packages/cart/src/lines.ts`"
        for name, path, header, problems in (
                ("`lineTotal`", lines, None, []),
                ("`lineTotals`", lines, None,
                 ["MODULE.md:20: symbol not found in its row's file: lineTotals"]),
                ("`lineTotal`", "", None, ["MODULE.md:20: no file to check: lineTotal"]),
                ("`lineTotal`", "`packages/cart/src`", None,
                 ["MODULE.md:20: no file to check: lineTotal"]),
                ("`lineTotal`", "`packages/cart/src/nope.ts`", None,
                 [missing("MODULE.md", 20, "packages/cart/src/nope.ts")]),
                ("Adds up a line", lines, None, []),
                ("`anything`", "a function", "| Name | Kind | Purpose |", [])):
            with self.subTest(name=name, path=path):
                doc = table(name, path, header) if header else table(name, path)
                self.assertEqual(self.done({"MODULE.md": doc}), (1 if problems else 0, problems))

    def test_all_at_once(self):  # P5C-AC-007 (SI-1): one answer; a doc it cannot read: skipped
        self.assertEqual(self.done({"roles/qa.md": None,
                                    "MODULE.md": at_line_12("`src/lines.ts`")},
                                   keywords=["a", "b", "c", "d"]),
                         (1, ["missing roles/qa.md", missing("MODULE.md", 12, "src/lines.ts"),
                              "at least 5 distinct keywords (a list of non-empty strings)"]))
        self.assertEqual(self.done({"MODULE.md": " \n\n "}),
                         (1, ["MODULE.md is empty"]))
        code, problems = self.done({"MODULE.md": b"\xff\xfe See `src/lines.ts`.\n"})
        self.assertEqual(code, 1)
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith("MODULE.md: cannot read it as UTF-8 text ("))

    def test_a_source_that_cannot_be_read(self):  # P5C-AC-021: no file to check, no traceback
        src = self.root / "packages/cart/src"
        (src / "blob.ts").write_bytes(b"\0\x01lineTotal\n")
        locked = src / "locked.ts"
        locked.write_text("export const lineTotal = 1;\n")
        locked.chmod(0)
        try:
            paths = ["packages/cart/src/blob.ts", "packages/cart/src"]
            if not os.access(locked, os.R_OK):  # (a root user reads it anyway)
                paths.append("packages/cart/src/locked.ts")
            for path in paths:
                with self.subTest(path=path):
                    self.assertEqual(self.done({"MODULE.md": table("`lineTotal`", f"`{path}`")}),
                                     (1, ["MODULE.md:20: no file to check: lineTotal"]))
        finally:
            locked.chmod(0o644)

    def test_config_dir(self):  # P5C-AC-022: a file in <config_dir>/init/ is on disk (backlog)
        doc = (f"# Cart\n\nIts work item: `{WORK}/work/cart.json`; its staging doc: "
               f"`{WORK}/staging/cart/MODULE.md`.\n")
        self.assertEqual(self.done({"MODULE.md": doc}), (0, []))


if __name__ == "__main__":
    unittest.main()
