"""P8.5 Task 2: a baseline doc on disk with no registry row is refreshed, never overwritten
(D2): P85-AC-008 … AC-012 and the text pins of AC-013. The engine is not changed: the skill's
step 1 detects the case with `roles add qa_acceptance <module> --dry-run --json` (status
`registered`) and the refresh route registers the doc after Gate 3."""
import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

from modsys.config import builtin_packs_root
from tests.helpers import (SPLIT_FIXTURE, changelog_since_first_release, copy_fixture, init_git,
                           mutate_registry, run)
from tests.test_builtin_skills import commands, section, skill_files, uses

ENGINE = Path(__file__).resolve().parents[1]
BASELINE = builtin_packs_root() / "qa/skills/qa-acceptance-baseline"
CONFIG = '[packs]\nbuiltin = ["core", "qa"]\n'
DOC = "# Catalog baseline\n\n## P0\n\n### AC-001: A listed book shows its author\n"
CATALOG_DOC = "modules/catalog/roles/qa_acceptance.md"
CHILD_DOC = "modules/orders/submodules/refunds/roles/qa_acceptance.md"


def flat(text: str) -> str:
    return " ".join(text.split())


def unreleased_sections(log: str) -> dict[str, str]:
    """The `### ` sections of `[Unreleased]`, heading -> body (moved here from the retired P8.4
    module in P8.6)."""
    text = changelog_since_first_release(log)
    parts = re.split(r"^### (.+)\n", text, flags=re.M)
    return dict(zip(parts[1::2], parts[2::2]))


def entries(body: str) -> list[str]:
    """The flat entries of one changelog section."""
    return [flat(e) for e in re.split(r"^- ", body, flags=re.M)[1:]]


def tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        h.update(p.relative_to(root).as_posix().encode())
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Fixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = copy_fixture(self._tmp.name)
        (self.root / ".modsys").mkdir(exist_ok=True)
        (self.root / ".modsys/config.toml").write_text(CONFIG, encoding="utf-8")
        (self.root / CATALOG_DOC).parent.mkdir(parents=True, exist_ok=True)
        (self.root / CATALOG_DOC).write_text(DOC, encoding="utf-8")
        self.R = ("--root", str(self.root))

    def ok(self, *argv, root=None) -> dict:
        code, out, err = run(*argv, "--root", str(root or self.root), "--json")
        self.assertEqual((code, err), (0, ""), argv)
        return json.loads(out)["data"]

    def registry(self, root=None) -> bytes:
        return (root or self.root).joinpath("modules/registry.json").read_bytes()

    def labels(self, module="catalog", root=None) -> list[str]:
        data = self.ok("show", module, "--role", "qa_acceptance", root=root)
        return [row["label"] for row in data["read"]]

    def dry_run(self, module="catalog", root=None) -> list[dict]:
        return self.ok("roles", "add", "qa_acceptance", module, "--dry-run", root=root)["results"]


class EngineReportsTest(Fixture):  # P85-AC-008 (PRE-004)
    def test_what_the_four_read_commands_say_about_the_unlisted_doc(self):
        before = tree_hash(self.root)
        self.assertEqual(self.labels(), ["universal"])  # no `role:qa_acceptance` row
        roles = {r["label"] for r in self.ok("show", "catalog", "--all-roles")["read"]}
        self.assertNotIn("role:qa_acceptance", roles)
        self.assertEqual(self.dry_run(), [{"module": "catalog", "status": "registered",
                                           "path": CATALOG_DOC}])
        lint = self.ok("lint")
        self.assertEqual((lint["findings"], lint["failed"]), ([], False))
        row = next(r for r in self.ok("roles", "list")["roles"] if r["name"] == "qa_acceptance")
        self.assertIn("catalog", row["missing"])  # SI-P85-7: `missing`, though the file exists
        self.assertNotIn("catalog", row["docs"])
        self.assertEqual(tree_hash(self.root), before)

    def test_the_twin_without_the_file_reports_created(self):
        (self.root / CATALOG_DOC).unlink()
        before = tree_hash(self.root)
        self.assertEqual(self.dry_run(), [{"module": "catalog", "status": "created",
                                           "path": CATALOG_DOC}])
        self.assertEqual(tree_hash(self.root), before)


class SkillCommandsTest(Fixture):  # P85-AC-011
    def test_the_commands_register_the_doc_and_never_write_over_it(self):
        init_git(self.root)  # `code-map files` needs a work tree
        doc = self.root / CATALOG_DOC
        doc_sha, registry_before = sha(doc), json.loads(self.registry())
        twin_dir = tempfile.TemporaryDirectory()
        self.addCleanup(twin_dir.cleanup)
        twin = copy_fixture(twin_dir.name)
        (twin / ".modsys").mkdir(exist_ok=True)
        (twin / ".modsys/config.toml").write_text(CONFIG, encoding="utf-8")
        (twin / CATALOG_DOC).parent.mkdir(parents=True, exist_ok=True)
        (twin / CATALOG_DOC).write_text(DOC, encoding="utf-8")

        def unchanged():
            self.assertEqual(sha(doc), doc_sha)

        # step 1, then the dry run: nothing is written
        self.ok("show", "catalog", "--all-roles"); unchanged()
        self.assertNotIn("role:qa_acceptance", self.labels()); unchanged()
        self.ok("code-map", "files", "catalog"); unchanged()
        before = tree_hash(self.root)
        self.assertEqual(self.dry_run()[0]["status"], "registered")
        self.assertEqual(tree_hash(self.root), before)
        # the refresh route's registration, after Gate 3
        done = self.ok("roles", "add", "qa_acceptance", "catalog")
        self.assertEqual(done["results"], [{"module": "catalog", "status": "registered",
                                            "path": CATALOG_DOC}])
        unchanged()
        expected = json.loads(json.dumps(registry_before))
        expected["modules"]["catalog"]["context_files"]["roles"]["qa_acceptance"] = CATALOG_DOC
        self.assertEqual(json.loads(self.registry()), expected)
        # the create route's `registry set` on a twin writes the same bytes
        files = json.loads(json.dumps(registry_before["modules"]["catalog"]["context_files"]))
        files["roles"]["qa_acceptance"] = CATALOG_DOC
        self.ok("registry", "set", "catalog", "context_files", json.dumps(files), root=twin)
        self.assertEqual(self.registry(), self.registry(twin))
        # step 6
        self.assertEqual(self.ok("lint")["findings"], []); unchanged()
        self.assertIn("role:qa_acceptance", self.labels())
        row = next(r for r in self.ok("show", "catalog", "--role", "qa_acceptance")["read"]
                   if r["label"] == "role:qa_acceptance")
        self.assertIs(row["exists"], True)
        self.assertEqual(self.dry_run()[0]["status"], "exists")
        listed = next(r for r in self.ok("roles", "list")["roles"] if r["name"] == "qa_acceptance")
        self.assertIn("catalog", listed["docs"])
        self.assertNotIn("catalog", listed["missing"])
        unchanged()


class SplitChildTest(unittest.TestCase):  # P85-AC-012
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = copy_fixture(self._tmp.name, SPLIT_FIXTURE)
        (self.root / ".modsys").mkdir(exist_ok=True)
        (self.root / ".modsys/config.toml").write_text(CONFIG, encoding="utf-8")
        for rel, text in (("modules/orders/roles/qa_acceptance.md", "# Orders baseline\n"),
                          (CHILD_DOC, "# Refunds baseline\n")):
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text(text, encoding="utf-8")
        mutate_registry(self.root, lambda d: d["modules"]["orders"]["context_files"]["roles"]
                        .update(qa_acceptance="modules/orders/roles/qa_acceptance.md"))

    def ok(self, *argv) -> dict:
        code, out, err = run(*argv, "--root", str(self.root), "--json")
        self.assertEqual((code, err), (0, ""), argv)
        return json.loads(out)["data"]

    def test_the_childs_own_doc_is_reported_and_registered_on_the_child_only(self):
        rows = self.ok("show", "orders/refunds", "--role", "qa_acceptance")["read"]
        self.assertIn("parent baseline role:qa_acceptance", [r["label"] for r in rows])
        self.assertNotIn("role:qa_acceptance", [r["label"] for r in rows])
        self.assertEqual(self.ok("roles", "add", "qa_acceptance", "orders/refunds",
                                 "--dry-run")["results"],
                         [{"module": "orders/refunds", "status": "registered",
                           "path": CHILD_DOC}])
        parent = self.root / "modules/orders/roles/qa_acceptance.md"
        child = self.root / CHILD_DOC
        shas = sha(parent), sha(child)
        before = json.loads((self.root / "modules/registry.json").read_text())
        self.ok("roles", "add", "qa_acceptance", "orders/refunds")
        after = json.loads((self.root / "modules/registry.json").read_text())
        self.assertEqual((sha(parent), sha(child)), shas)
        orders_before = before["modules"]["orders"]
        orders_after = after["modules"]["orders"]
        self.assertEqual(orders_after["submodules"]["refunds"]["context_files"]["roles"],
                         {"qa_acceptance": CHILD_DOC})
        self.assertEqual(orders_after["context_files"], orders_before["context_files"])
        for name in ("checkout", "invoices"):
            self.assertEqual(orders_after["submodules"][name], orders_before["submodules"][name])
        rows = self.ok("show", "orders/refunds", "--role", "qa_acceptance")["read"]
        self.assertIn("child role:qa_acceptance", [r["label"] for r in rows])


class SplitChildOwnDocTest(SplitChildTest):  # fix round I-2
    def test_a_child_with_its_own_registered_doc_is_shown_as_child_role(self):
        self.ok("roles", "add", "qa_acceptance", "orders/refunds")
        rows = self.ok("show", "orders/refunds", "--role", "qa_acceptance")["read"]
        own = [r for r in rows if r["label"] == "child role:qa_acceptance"]
        self.assertEqual([(r["path"], r["exists"]) for r in own], [(CHILD_DOC, True)])
        self.assertIn("child role:qa_acceptance", SkillTextTest.step1_text())
        self.assertEqual(self.ok("roles", "add", "qa_acceptance", "orders/refunds",
                                 "--dry-run")["results"][0]["status"], "exists")


class SkillTextTest(unittest.TestCase):  # P85-AC-009, AC-010, AC-013 (the pins)
    @staticmethod
    def step1_text() -> str:
        skill = skill_files(BASELINE)["SKILL.md"]
        return section(skill, "## Steps").split("\n1. ", 1)[1].split("\n2. ", 1)[0]

    def setUp(self):
        self.files = skill_files(BASELINE)
        self.skill = self.files["SKILL.md"]
        self.step1 = section(self.skill, "## Steps").split("\n1. ", 1)[1].split("\n2. ", 1)[0]

    def test_step_1_keeps_the_old_sentence_once_and_names_the_labels_and_statuses(self):
        old = ("A `role:qa_acceptance` row with `exists: true` is the doc to refresh; read it "
               "and note the highest `AC-NNN` in it.")
        self.assertEqual(flat(self.skill).count(old), 1)
        line = flat(self.step1)
        for needle in (
                "A `child role:qa_acceptance` row with `exists: true` is a split child's own doc",
                "A `parent baseline role:qa_acceptance` row is the parent's doc, not this "
                "module's",
                "`modsys roles add qa_acceptance <module> --dry-run --json`",
                # each status of the dry run has a meaning
                "Status `registered` means the module's `roles/qa_acceptance.md` is on disk and "
                "the registry does not list it: that file is the doc to refresh, so read it, "
                "note the highest `AC-NNN` in it, take the refresh route and never write a new "
                "doc over it",
                "Status `exists` means the registry lists a doc that is on disk: refresh it, so "
                "read it and note the highest `AC-NNN` in it",
                "Status `created` means there is no doc: take the create route",
                "Status `missing` means the registry lists a path with no file: the create "
                "route writes the doc at that path and adds no second registry entry"):
            self.assertIn(needle, line)
        self.assertTrue(uses(commands(self.step1), ("roles", "add", "--dry-run")))

    def test_the_dry_run_condition_names_the_rows(self):  # final review I-2 (F31, split child)
        line = flat(self.step1)
        self.assertEqual(line.count(
            "Without a `role:qa_acceptance` or `child role:qa_acceptance` row with `exists: true` "
            "(a `parent baseline` row does not count), run `modsys roles add qa_acceptance "
            "<module> --dry-run --json`, which writes nothing, and read its status."), 1)
        self.assertEqual(line.count("a `parent baseline` row does not count"), 1)
        self.assertNotIn("Without one of those rows", line)

    def test_create_writes_a_missing_doc_at_the_registered_path(self):  # final review M-2
        create = flat(self.files["references/create.md"])
        sentence = ("When step 1's dry run said `missing`, write the doc at the `path` it reported "
                    "and skip `registry set`: the registry lists it already.")
        self.assertEqual(create.count(sentence), 1)
        self.assertLess(create.index(sentence),
                        create.index("save it next to the module's other role docs"))
        # the dry run reports that `path`: the registered one, wherever it points
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            (root / ".modsys").mkdir(exist_ok=True)
            (root / ".modsys/config.toml").write_text(CONFIG, encoding="utf-8")
            where = "modules/catalog/docs/baseline.md"
            mutate_registry(root, lambda d: d["modules"]["catalog"]["context_files"]
                            .setdefault("roles", {}).update(qa_acceptance=where))
            code, out, err = run("roles", "add", "qa_acceptance", "catalog", "--dry-run",
                                 "--json", "--root", str(root))
            self.assertEqual((code, err), (0, ""))
            row = json.loads(out)["data"]["results"][0]
            self.assertEqual((row["status"], row["path"]), ("missing", where))
            self.assertFalse((root / where).exists())

    def test_refresh_names_the_childs_own_row(self):  # final review M-3
        refresh = flat(self.files["references/refresh.md"])
        lead = refresh.split("1. ", 1)[0]
        self.assertIn("(a `role:qa_acceptance` or `child role:qa_acceptance` row with "
                      "`exists: true`, or the doc its dry run reported as `registered` or "
                      "`exists`)", lead)
        self.assertTrue(all(len(line) <= 100 for line in
                            self.files["references/refresh.md"].splitlines()))

    def test_the_scope_keeps_its_sentence_and_adds_one(self):
        scope = flat(section(self.skill, "## Scope"))
        self.assertIn("Writes: the module's `qa_acceptance` doc, and its entry in the module's "
                      "registry `context_files` when the doc is new.", scope)
        self.assertIn("The entry is also written for a doc that is on disk and that the registry "
                      "does not list, and a new doc is never written over it.", scope)

    def test_refresh_registers_after_gate_3_and_create_keeps_registry_set(self):
        refresh, create = flat(self.files["references/refresh.md"]), flat(
            self.files["references/create.md"])
        self.assertEqual(refresh.count("`modsys roles add qa_acceptance <module> --json`"), 1)
        self.assertIn("after Gate 3", refresh)
        self.assertLess(refresh.index("`modsys roles add"),
                        refresh.index("It exists: edit it in place, block by block"))
        self.assertNotIn("roles add", create)
        self.assertEqual(create.count("modsys registry set <module> context_files"), 2)
        self.assertIn("Check the dry run's diff changes nothing else.", create)
        for name in ("create", "refresh"):
            text = self.files[f"references/{name}.md"]
            self.assertEqual(len(re.findall(r"references/[a-z-]+\.md", text)), 1)
            self.assertNotIn("there is no doc to refresh", text)
        self.assertEqual(self.files["references/exit-codes.md"].count("references/"), 0)

    def test_what_stays_byte_identical(self):
        flat_skill = flat(self.skill)
        for needle in ("If a `modsys` command exits 1 or 2, read `references/exit-codes.md`.",
                       "6. Write the doc. Follow the scenario's file (the Route above).",  # P8.8: step 5 assembles
                       "Three, never skipped: Gate 1 (understanding), Gate 2 (each block's "
                       "requirements), Gate 3 (the criteria, per block or per batch). Nothing is "
                       "written before Gate 3 of the last block."):
            self.assertEqual(flat_skill.count(needle), 1)
        self.assertEqual(self.skill.count("$scenario"), 1)


class ChangelogTest(unittest.TestCase):  # SI-P85-8 (final review M-8): Task 2's one entry
    ENTRY = ("`qa-acceptance-baseline`: a `roles/qa_acceptance.md` on disk that the registry does "
             "not list is the doc to refresh.")

    def test_one_changed_entry(self):
        log = (ENGINE / "CHANGELOG.md").read_text(encoding="utf-8")
        found = [(head, entry) for head, body in unreleased_sections(log).items()
                 for entry in entries(body) if self.ENTRY in entry]
        self.assertEqual([head for head, _ in found], ["Changed"])
        for needle in ("`roles add qa_acceptance <module> --dry-run --json`", "after Gate 3",
                       "never writes a new doc over it"):
            self.assertIn(needle, found[0][1])
