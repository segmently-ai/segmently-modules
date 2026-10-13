"""P8.7 (D5–D7; the plan's fast mode, C2): `module-sync`, `module-create` and `module-split` follow
the job and the output contract of the host originals they replace again. sync takes the session's
knowledge first and the change second, prints its findings and proposals, places each item by its
readers and reports its decisions; create analyses existing code and proposes the description and
keywords from it, fills the docs to a minimum, seeds links and shows the module matches; split
refuses below the size signals, keeps a child's role docs to those with content and handles an
already-split module. Pinned here: the contract's phrases, the removed rules, the size of the core
pack, and `create --no-standard-roles` (the child keeps only the role docs that get content)."""
import unittest
from pathlib import Path

from segmently_modules.config import builtin_packs_root, core_defaults
from tests.helpers import copy_fixture, run, run_json

CORE = builtin_packs_root() / "core" / "skills"
WRITING = ("module-sync", "module-create", "module-split")
REFERENCES = {"module-sync": ["choose.md", "placement.md", "report.md", "session.md"],
              "module-create": ["analyse.md", "child.md", "fill.md"],
              "module-split": ["already-split.md", "check.md", "shapes.md"]}


def flat(text: str) -> str:
    return " ".join(text.split())


def skill(name: str) -> str:
    return (CORE / name / "SKILL.md").read_text(encoding="utf-8")


def every_file(name: str) -> str:
    return flat("\n".join([skill(name)] + [(CORE / name / "references" / f).read_text("utf-8")
                                           for f in REFERENCES[name]]))


CONTRACT = {
    "module-sync": [  # D5: session first, diff second
        "The session is the primary source; the change in git confirms it and finds missed modules.",
        "revealed module knowledge", "`<base>` is `HEAD`, and step 3 takes `--module`",
        "segmently-modules sync-instructions --module <module> --module <module> --json",
        "**Plan goal**", "**Decisions** — each choice made, with the alternatives rejected and why.",
        "**Discoveries**", "**Patterns**", "**Gotchas**", "**Dependencies**", "**Critical rules**",
        "homeless discovery: report it, never drop it", "sync from the change alone",
        # C5 run b (sonnet) edited before printing them: the print comes first, said twice
        "Before any edit, print in your reply — the user audits the run from it",
        "**Findings**: each session item (kind · module · fact)", "**Proposal: <module>**",
        "Then apply without waiting.", "Only after that print, write each module's docs",
        "Ask Segmently Modules what to update — always, a session without a code change too.",
        "Interactive mode (the user asked for it)", "`ok / skip / edit`",
        "never hand-edits a role doc another skill owns (it flags it)",
        "never hand-edited — flag it for that skill in the report",
        "only when business behaviour changed", "only when the UI changed",
        "past about 300 lines after the edit, route the excess to them",
        "reconcile the prose with the edges",
        "`segmently-modules roles add <role> <module>/<child> --json` creates and registers it",
        "never copy the area content into the parent's baseline",
        "**Budget watch**", "never a silent trim",
        "every decision you took on your own and every question you asked, with the answer",
        "each split or routing proposal as an action item", "stats",
        "records each decision in the report",
    ],
    "module-create": [  # D6
        "does its code exist? yes → `active`, no → `planned`", "--status <status>",
        "**artifacts**", "does it render a user interface", "`--tag ui`",
        "read the artifacts before anything is created", "**components**", "**imports**",
        "**usage**", "**critical rules**", "**dependencies**, both ways", "**propose**",
        "never generic", "The user corrects them.",
        "at least three components with real paths",
        "at least one right-and-wrong usage example", "real import lines in the developer doc",
        "no template comment (`<!-- … -->`) left", "about 200–300 lines", "Planned:",
        "segmently-modules registry append <name> related_modules",
        "--no-standard-roles", "add the child's row to the parent's routing table",
        "the routing table must list every child",
        'segmently-modules match "<a typical task for it>" --match lexical --json',
        "the typical task ranks the new module first",
        "template comments left (0)",
    ],
    "module-split": [  # D7
        "No MS030 / MS031 for the module: refuse", "go on only when the user explicitly overrides",
        "Three to six children (two only with the reason stated)",
        "every level-two and level-three heading",
        "every section a tool or another module reads from the parent doc",
        "the roles without area content: no doc for them",
        "--no-standard-roles --role <role> --json", "Never split again.",
        "**Add a child**", "**Rebalance**", "**Report sizes**",
        "none of its `*.legacy.md` files is ever overwritten",
        "| Child | Scope | Keywords | Lines |", "Pre-split snapshot: [{module doc}.legacy.md]",
        "Pre-split snapshot: [{role}.legacy.md]",
        "the parent's routing table lists every child, with its line count",
        "holds area content — no template comment", "the roles left unsplit and why",
        "should get a designer doc", "explain any loss over 5 %",
    ],
}
REMOVED = {
    "module-sync": ["Nothing changed yet: use", "A task changed module code and is done",
                    "Use at the end of a task that changed module code"],
    "module-create": ["in the user's own vocabulary", "one question at a time when the user has not"],
    "module-split": ["the user gave no other reason", "receives no section stays as `create` wrote it",
                     "Two to six children", "move sections between children by hand",
                     "level two) ·"],
}


class ContractTest(unittest.TestCase):
    def test_the_contract_phrases(self):
        for name, phrases in CONTRACT.items():
            text = every_file(name)
            with self.subTest(skill=name):
                self.assertEqual([p for p in phrases if p not in text], [])

    def test_the_removed_rules_are_gone(self):
        for name, phrases in REMOVED.items():
            text = every_file(name)
            with self.subTest(skill=name):
                self.assertEqual([p for p in phrases if p in text], [])

    def test_the_references_are_the_named_ones(self):
        for name in WRITING:
            with self.subTest(skill=name):
                self.assertEqual(sorted(p.name for p in (CORE / name / "references").iterdir()),
                                 REFERENCES[name])

    def test_the_core_pack_stays_under_its_signal(self):  # X4: routed, never trimmed
        total = sum(len(p.read_text("utf-8")) for p in CORE.glob("*/SKILL.md"))
        self.assertLessEqual(total, core_defaults()["budgets"]["pack_split_signal"])


class NoStandardRolesTest(unittest.TestCase):  # D6 / D7: a child keeps the docs with content
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = str(copy_fixture(Path(self._tmp.name)))

    def create(self, *extra):
        return run_json("create", "search", "--parent", "catalog", "--non-interactive",
                        "--description", "Search over the catalog by title and author.",
                        "--keywords", "search", *extra, "--root", self.root)

    def test_a_child_gets_only_the_named_roles(self):
        code, env, err = self.create("--no-standard-roles", "--role", "qa")
        self.assertEqual((code, err), (0, ""))
        data = env["data"]
        self.assertEqual(data["files"], ["modules/catalog/submodules/search/MODULE.md",
                                         "modules/catalog/submodules/search/roles/qa.md"])
        self.assertEqual(data["entry"]["context_files"]["roles"],
                         {"qa": "modules/catalog/submodules/search/roles/qa.md"})
        code, env, _ = run_json("roles", "list", "--root", self.root)
        roles = {r["name"]: r for r in env["data"]["roles"]}
        self.assertIn("catalog/search", roles["developer"]["inherited"])
        self.assertIn("catalog/search", roles["qa"]["docs"])
        code, env, _ = run_json("lint", "--root", self.root)
        self.assertEqual([f for f in env["data"]["findings"] if "search" in f["module"]], [])

    def test_no_role_at_all_is_a_module_doc_only(self):
        code, env, _ = self.create("--no-standard-roles", "--dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(env["data"]["files"], ["modules/catalog/submodules/search/MODULE.md"])

    def test_without_the_flag_every_standard_role_is_scaffolded(self):
        code, env, _ = self.create("--dry-run")
        self.assertEqual(code, 0)
        self.assertGreater(len(env["data"]["files"]), 2)

    def test_a_top_level_module_is_refused(self):
        code, out, err = run("create", "wishlist", "--non-interactive", "--no-standard-roles",
                             "--description", "A wishlist of books to buy later on.",
                             "--keywords", "wish, wishlist, later, save, list", "--root", self.root)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("--no-standard-roles needs --parent", err)
        self.assertFalse((Path(self.root) / "modules/wishlist").exists())


if __name__ == "__main__":
    unittest.main()
