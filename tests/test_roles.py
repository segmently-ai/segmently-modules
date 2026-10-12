"""`modsys roles list` / `roles add` (P6.1 W3, D1, D3, SI-P61-1…3): every configured role with
its owner and the targets that have (or lack) its doc; a role doc added to EXISTING modules —
rendered exactly as `create` renders it, registered in either layout, all or nothing."""
import contextlib
import errno
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from modsys import roles_cmd
from modsys.output import UsageError
from modsys.store import file_lock
from modsys.workspace import Workspace
from tests.helpers import copy_fixture, make_repo, mutate_registry, run, run_json
from tests.plugin_helpers import copy_engine, default_signals
from tests.test_layout import convert

REVIEWER = "What a reviewer checks in a change to the module"
PACK = ('id = "reviews"\ndescription = "A reviewer role"\n\n[roles.reviewer]\norder = 60\n'
        f'standard = false\ndescription = "{REVIEWER}"\n')
TEAM_REVIEWER = f'[roles.reviewer]\norder = 60\nstandard = false\ndescription = "{REVIEWER}"\n'
DESC = "Customer reviews of books: ratings, comments and moderation."
KW = [a for k in ("review", "rating", "stars", "comment", "moderation") for a in ("--keyword", k)]
BOOKSHOP = ["catalog", "checkout", "payments", "payments/refunds"]  # legacy-search is a stub
ROW_KEYS = {"name", "order", "standard", "enabled", "applies_when", "description", "owner",
            "docs", "missing", "inherited", "skipped"}
LOCK = "modules/registry.json.lock"


def add_pack(root: Path, text: str = PACK, pack: str = "reviews") -> Path:
    path = root / ".modsys/packs" / pack / "pack.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path.parent


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def snap(root: Path, drop_lock: bool = False) -> dict:
    """Every file, directory and symlink below `root` (a symlink by its link text, never
    followed); `drop_lock`: without the registry's lock file (a writer that took the lock
    leaves it, empty, by design)."""
    out = {}
    for path in sorted(root.rglob("*")):
        rel, st = path.relative_to(root).as_posix(), path.lstat()
        if stat.S_ISLNK(st.st_mode):
            out[rel] = ("symlink", os.readlink(path))
        elif stat.S_ISDIR(st.st_mode):
            out[rel + "/"] = (stat.S_IMODE(st.st_mode), b"")
        else:
            out[rel] = (stat.S_IMODE(st.st_mode), path.read_bytes())
    if drop_lock:
        lock = out.pop(LOCK, None)
        assert lock is None or lock[1] == b"", lock
    return out


def holder(root: Path, target: str, entry_file: str | None = None) -> dict:
    """The registry entry of `module` or `module/child` (from `entry_file` in a per-module
    repository, else the single registry)."""
    parent, _, child = target.partition("/")
    if entry_file:
        entry = json.loads((root / entry_file).read_text(encoding="utf-8"))
    else:
        entry = json.loads((root / "modules/registry.json").read_text(
            encoding="utf-8"))["modules"][parent]
    return entry["submodules"][child] if child else entry


@contextlib.contextmanager
def umask(mask: int):
    old = os.umask(mask)
    try:
        yield
    finally:
        os.umask(old)


class Repo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name).resolve()
        self.root = copy_fixture(self.tmp / "main")
        add_pack(self.root)
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def ok(self, *argv, root: Path | None = None):
        code, env, err = run_json(*argv, "--root", str(root or self.root))
        self.assertEqual((code, err), (0, ""), err)
        self.assertEqual(set(env), {"schema", "data"})
        self.assertEqual(env["schema"], "modsys.roles/1")
        return env["data"]

    def refused(self, *argv, root: Path | None = None) -> str:
        """Exit 2, nothing on stdout (text and --json), no traceback; the stderr text."""
        for extra in ((), ("--json",)):
            code, out, err = run(*argv, *extra, "--root", str(root or self.root))
            self.assertEqual((code, out), (2, ""), err)
            self.assertTrue(err.startswith("modsys: error: "), err)
            self.assertNotIn("Traceback", err)
        return err


class RolesListTest(Repo):  # P61-AC-005
    def setUp(self):
        super().setUp()
        write(self.root / ".modsys/config.toml", "[roles.po]\nenabled = false\n")

    def test_every_role_with_its_source_and_its_doc_counts(self):
        before = snap(self.root)
        data = self.ok("roles", "list")
        self.assertEqual(set(data), {"roles"})
        rows = data["roles"]
        self.assertTrue(all(set(r) == ROW_KEYS for r in rows), rows)
        self.assertEqual([(r["name"], r["order"], r["standard"], r["enabled"], r["owner"])
                          for r in rows],
                         [("developer", 10, True, True, "engine"),
                          ("qa", 20, True, True, "engine"),
                          ("po", 30, True, False, "engine"),
                          ("architect", 40, True, True, "engine"),
                          ("designer", 50, False, True, "bookshop"),
                          ("reviewer", 60, False, True, "reviews")])
        by = {r["name"]: r for r in rows}
        self.assertEqual((by["developer"]["docs"], by["developer"]["missing"]), (BOOKSHOP, []))
        top = [t for t in BOOKSHOP if "/" not in t]  # payments/refunds inherits its parent's
        self.assertEqual((by["qa"]["docs"], by["qa"]["missing"], by["qa"]["inherited"]),
                         (["catalog"], top[1:], ["payments/refunds"]))
        self.assertEqual((by["designer"]["docs"], by["designer"]["missing"]),
                         (["catalog"], top[1:]))
        for name in ("po", "architect", "reviewer"):
            self.assertEqual((by[name]["docs"], by[name]["missing"]), ([], top))
            self.assertEqual(by[name]["inherited"], ["payments/refunds"])
        self.assertEqual((by["reviewer"]["description"], by["reviewer"]["applies_when"]),
                         (REVIEWER, None))
        self.assertEqual(by["developer"]["description"],
                         "What to know when changing the module's code")
        code, out, err = run("roles", "list", *self.R)
        self.assertEqual((code, err), (0, ""))
        lines = out.splitlines()
        self.assertEqual([line.split()[0] for line in lines], [r["name"] for r in rows])
        for line, r in zip(lines, rows):
            self.assertIn(f"docs {len(r['docs'])}", line)
            self.assertIn(f"missing {len(r['missing'])}", line)
            self.assertIn(r["owner"], line)
        self.assertIn("disabled", lines[2])
        self.assertNotIn("disabled", lines[0])
        self.assertEqual(snap(self.root), before)  # read-only: no lock file either

    def test_a_registered_doc_missing_on_disk_is_in_neither_list(self):  # ruling
        (self.root / "modules/catalog/roles/qa.md").unlink()
        qa = {r["name"]: r for r in self.ok("roles", "list")["roles"]}["qa"]
        self.assertEqual((qa["docs"], qa["missing"]), ([], ["checkout", "payments"]))
        self.assertEqual(qa["inherited"], ["payments/refunds"])  # covered by payments' doc

    def test_owner_is_the_layer_that_declares_the_role(self):
        write(self.root / ".modsys/config.toml",
              '[roles.po]\nenabled = false\n\n[roles.security]\norder = 70\n'
              'description = "Threats"\n\n[roles.reviewer]\ndescription = "Team wording"\n')
        write(self.root / ".modsys/config.user.toml", '[roles.oncall]\norder = 80\n')
        rows = {r["name"]: r for r in self.ok("roles", "list")["roles"]}
        self.assertEqual({n: rows[n]["owner"] for n in ("security", "oncall", "reviewer")},
                         {"security": "team", "oncall": "user", "reviewer": "reviews"})
        self.assertEqual(rows["reviewer"]["description"], "Team wording")
        self.assertEqual(rows["oncall"]["standard"], False)

    def test_the_scan_for_next_skips_disabled_roles_and_writes_nothing(self):  # Task 4's input
        before = snap(self.root)
        rows = roles_cmd.role_rows(Workspace.load(self.root), enabled_only=True)
        self.assertEqual([r["name"] for r in rows],
                         ["developer", "qa", "architect", "designer", "reviewer"])
        self.assertEqual(rows, [r for r in self.ok("roles", "list")["roles"] if r["enabled"]])
        self.assertEqual(snap(self.root), before)

    def test_list_takes_no_role_target_or_add_flag(self):
        self.assertIn("roles list takes no ROLE or TARGET", self.refused("roles", "list", "qa"))
        for flag in ("--all", "--recreate", "--dry-run"):
            with self.subTest(flag=flag):
                self.assertIn(f"{flag} applies to roles add", self.refused("roles", "list", flag))


class StatusTest(unittest.TestCase):  # P61-AC-006
    TARGETS = ("catalog", "checkout", "orders", "payments", "payments/refunds")
    PATHS = {"catalog": "modules/catalog/roles/reviewer.md",
             "checkout": "modules/checkout/roles/reviewer.md",
             "orders": "modules/orders/roles/reviewer.md",
             "payments": "modules/payments/roles/reviewer.md",
             "payments/refunds": "modules/payments/submodules/refunds/roles/reviewer.md"}

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name).resolve()

    def tearDown(self):
        self._tmp.cleanup()

    def repo(self, name: str) -> Path:
        """catalog: rule 1 (nothing) · checkout: rule 2 (a doc, unregistered) · orders: rule 3
        (registered + doc) · payments and payments/refunds: registered, the doc missing (rule
        4 without --recreate, rule 5 with it)."""
        root = make_repo(self.tmp / name, {"catalog": ["book"], "checkout": ["cart"],
                                           "orders": ["order"], "payments": ["charge"],
                                           "payments/refunds": ["refund"]}, TEAM_REVIEWER)
        write(root / self.PATHS["checkout"], "# Checkout review notes — kept as they are\n")
        write(root / self.PATHS["orders"], "# Orders review notes\n")

        def register(data):
            for target in ("orders", "payments", "payments/refunds"):
                parent, _, child = target.partition("/")
                entry = data["modules"][parent]
                entry = entry["submodules"][child] if child else entry
                entry["context_files"]["roles"] = {"reviewer": self.PATHS[target]}
        mutate_registry(root, register)
        return root

    def add(self, root: Path, *flags: str):
        code, env, err = run_json("roles", "add", "reviewer", *self.TARGETS, *flags,
                                  "--root", str(root))
        self.assertEqual((code, err, env["schema"]), (0, "", "modsys.roles/1"))
        self.assertEqual(set(env["data"]), {"role", "dry_run", "results"})
        self.assertEqual(env["data"]["role"], "reviewer")
        return env["data"]

    def test_the_five_rules(self):
        for recreate in (False, True):
            with self.subTest(recreate=recreate):
                root = self.repo(f"r{int(recreate)}")
                before = snap(root)
                reg_before = json.loads((root / "modules/registry.json").read_text())
                data = self.add(root, *(("--recreate",) if recreate else ()))
                last = "recreated" if recreate else "missing"
                self.assertEqual([(r["module"], r["status"], r["path"]) for r in data["results"]],
                                 [("catalog", "created", self.PATHS["catalog"]),
                                  ("checkout", "registered", self.PATHS["checkout"]),
                                  ("orders", "exists", self.PATHS["orders"]),
                                  ("payments", last, self.PATHS["payments"]),
                                  ("payments/refunds", last, self.PATHS["payments/refunds"])])
                for r in data["results"]:
                    keys = {"module", "status", "path"} | ({"command"} if r["status"] == "missing"
                                                           else set())
                    self.assertEqual(set(r), keys)
                if not recreate:
                    self.assertEqual(data["results"][3]["command"],
                                     "modsys roles add reviewer payments --recreate")
                    self.assertEqual(data["results"][4]["command"],
                                     "modsys roles add reviewer payments/refunds --recreate")
                after = snap(root, drop_lock=True)
                changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
                new_docs = {self.PATHS["catalog"], "modules/catalog/roles/"}
                if recreate:
                    new_docs |= {self.PATHS["payments"], "modules/payments/roles/",
                                 self.PATHS["payments/refunds"],
                                 "modules/payments/submodules/refunds/roles/"}
                self.assertEqual(changed, new_docs | {"modules/registry.json"})
                text = (root / self.PATHS["catalog"]).read_text(encoding="utf-8")
                self.assertTrue(text.startswith(f"# Catalog — reviewer\n\n> {REVIEWER}\n"), text)
                if recreate:
                    self.assertTrue((root / self.PATHS["payments/refunds"]).read_text(
                        encoding="utf-8").startswith("# Refunds — reviewer\n"))
                reg = json.loads((root / "modules/registry.json").read_text())
                for target in ("catalog", "checkout"):  # rules 1, 2: the entry gains the path
                    self.assertEqual(holder(root, target)["context_files"]["roles"],
                                     {"reviewer": self.PATHS[target]})
                    reg["modules"][target]["context_files"].pop("roles")
                self.assertEqual(reg, reg_before)  # rules 3–5: the registry unchanged
                again = snap(root)
                data = self.add(root, *(("--recreate",) if recreate else ()))
                rest = "exists" if recreate else "missing"
                self.assertEqual([r["status"] for r in data["results"]],
                                 ["exists", "exists", "exists", rest, rest])
                self.assertEqual(snap(root), again)  # the second run writes nothing

    def test_a_dry_run_reports_the_same_rows_and_writes_nothing(self):
        root = self.repo("dry")
        before = snap(root)
        dry = self.add(root, "--dry-run")
        self.assertTrue(dry["dry_run"])
        self.assertEqual(snap(root), before)  # no lock file either
        real = self.add(root)
        self.assertFalse(real["dry_run"])
        self.assertEqual(dry["results"], real["results"])

    def test_the_text_lines_and_the_summary(self):
        root = self.repo("text")
        code, out, err = run("roles", "add", "reviewer", *self.TARGETS, "--root", str(root))
        self.assertEqual((code, err), (0, ""))
        lines = out.splitlines()
        self.assertEqual([line.split()[:2] for line in lines[:5]],
                         [["created", "catalog"], ["registered", "checkout"],
                          ["exists", "orders"], ["missing", "payments"],
                          ["missing", "payments/refunds"]])
        self.assertIn(self.PATHS["catalog"], lines[0])
        self.assertIn("modsys roles add reviewer payments --recreate", lines[3])
        self.assertEqual(lines[5], "reviewer: 1 created, 1 registered, 1 exists, 2 missing")
        self.assertEqual(len(lines), 6)
        code, out, _ = run("roles", "add", "reviewer", "catalog", "--root", str(root))
        self.assertEqual((code, out.splitlines()[-1]), (0, "reviewer: 1 exists — nothing to do"))
        root = self.repo("text-dry")
        out = run("roles", "add", "reviewer", "catalog", "checkout", "--dry-run",
                  "--root", str(root))[1].splitlines()
        self.assertEqual([line.split()[:3] for line in out[:2]],
                         [["would", "create", "catalog"], ["would", "register", "checkout"]])
        self.assertEqual(out[2], "reviewer: 1 created, 1 registered (dry run: nothing written)")

    def test_nothing_to_do_is_exit_0(self):
        root = self.tmp / "empty"
        write(root / "modules/registry.json", '{"modules": {}}\n')
        write(root / ".modsys/config.toml", TEAM_REVIEWER)
        data = self.ok_all(root)
        self.assertEqual(data["results"], [])
        code, out, _ = run("roles", "add", "reviewer", "--all", "--root", str(root))
        self.assertEqual((code, out), (0, "reviewer: no module to add it to\n"))
        root = self.repo("all-there")
        code, _, _ = run("roles", "add", "reviewer", "orders", "payments", "--root", str(root))
        self.assertEqual(code, 0)  # exists, missing: nothing to write — no lock taken
        self.assertFalse((root / LOCK).exists())

    def ok_all(self, root: Path) -> dict:
        code, env, err = run_json("roles", "add", "reviewer", "--all", "--root", str(root))
        self.assertEqual((code, err), (0, ""))
        return env["data"]


class RenderLikeCreateTest(unittest.TestCase):  # P61-AC-007
    TEMPLATE = ("# ${title} — ${role} (${article} ${role})\n\n> ${role_description}\n\n"
                "${name} of ${parent}: ${description}\nstatus: ${status}\n"
                "keywords: ${keywords}\n<!-- LAYER -->")  # no final newline: create adds one
    LAYERS = ("override", "role-template:reviews", "pack:reviews", "engine-fallback")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name).resolve()
        self.n = 0

    def tearDown(self):
        self._tmp.cleanup()

    def copy(self, top: str) -> Path:
        """A bookshop copy where `top` is the highest template layer for roles/reviewer.md and
        every lower layer is present too (each marked with its own name)."""
        self.n += 1
        root = copy_fixture(self.tmp / str(self.n))
        layers = self.LAYERS[self.LAYERS.index(top):]
        pack = PACK + ('template = "tpl/reviewer.md"\n' if "role-template:reviews" in layers
                       else "")
        pack_dir = add_pack(root, pack)
        files = {"override": root / ".modsys/overrides/templates/roles/reviewer.md",
                 "role-template:reviews": pack_dir / "tpl/reviewer.md",
                 "pack:reviews": pack_dir / "templates/roles/reviewer.md"}
        for layer in layers[:-1]:
            write(files[layer], self.TEMPLATE.replace("LAYER", layer))
        return root

    def create(self, root: Path, name: str, *extra: str) -> None:
        argv = ["create", name, "--non-interactive", "--root", str(root), *extra]
        if "--parent" in extra:
            argv += ["--description", "Chargeback disputes raised by card issuers.",
                     "--keyword", "dispute", "--keyword", "chargeback"]
        else:
            argv += ["--description", DESC, *KW, "--status", "active"]
        code, _, err = run(*argv)
        self.assertEqual(code, 0, err)

    def add(self, root: Path, role: str, target: str) -> None:
        code, env, err = run_json("roles", "add", role, target, "--root", str(root))
        self.assertEqual((code, err), (0, ""), err)
        self.assertEqual([r["status"] for r in env["data"]["results"]], ["created"])

    def same(self, a: Path, b: Path) -> str:
        self.assertEqual(b.read_bytes(), a.read_bytes())
        self.assertEqual(stat.S_IMODE(b.stat().st_mode), stat.S_IMODE(a.stat().st_mode))
        self.assertEqual(stat.S_IMODE(b.stat().st_mode), 0o644)
        text = b.read_text(encoding="utf-8")
        self.assertNotIn("${", text)
        return text

    def source(self, root: Path, template: str) -> str:
        code, env, _ = run_json("templates", "list", "--root", str(root))
        return {r["template"]: r["source"] for r in env["data"]}[template]

    def test_every_template_layer_byte_for_byte(self):
        doc = "modules/reviews/roles/reviewer.md"
        with umask(0o077):  # create gives 0644 whatever the umask; so must roles add
            for top in self.LAYERS:
                with self.subTest(layer=top):
                    a, b = self.copy(top), self.copy(top)
                    self.create(a, "reviews", "--role", "reviewer")
                    self.create(b, "reviews")
                    self.assertFalse((b / doc).exists())
                    self.add(b, "reviewer", "reviews")
                    text = self.same(a / doc, b / doc)
                    self.assertEqual(self.source(b, "roles/reviewer.md"), top)
                    if top == "engine-fallback":
                        self.assertTrue(text.startswith(f"# Reviews — reviewer\n\n> {REVIEWER}"))
                    else:
                        self.assertIn(f"<!-- {top} -->\n", text)
                        self.assertIn("reviews of : Customer reviews of books", text)
                        self.assertIn("status: active\nkeywords: review, rating, stars, comment, "
                                      "moderation\n", text)

    def test_a_child_byte_for_byte(self):
        doc = "modules/payments/submodules/disputes/roles/reviewer.md"
        a, b = self.copy("override"), self.copy("override")
        self.create(a, "disputes", "--parent", "payments", "--role", "reviewer")
        self.create(b, "disputes", "--parent", "payments")
        self.add(b, "reviewer", "payments/disputes")
        text = self.same(a / doc, b / doc)
        self.assertIn("disputes of payments: Chargeback disputes", text)
        self.assertIn("status: planned\n", text)  # a child: [create] default_status

    def test_an_engine_template_byte_for_byte(self):
        doc = "modules/reviews/roles/qa.md"
        a, b = self.copy("engine-fallback"), self.copy("engine-fallback")
        self.create(a, "reviews")
        self.create(b, "reviews")
        (b / doc).unlink()
        mutate_registry(b, lambda d: d["modules"]["reviews"]["context_files"]["roles"].pop("qa"))
        self.add(b, "qa", "reviews")
        self.same(a / doc, b / doc)
        self.assertEqual(self.source(b, "roles/qa.md"), "engine")


class TargetsTest(unittest.TestCase):  # P61-AC-008 (SI-P61-3)
    MODULES = {"shelf": ["shelf"], "orders": ["order"], "orders/returns": ["return"],
               "orders/invoices": ["invoice"]}
    PATHS = ["modules/shelf/roles/reviewer.md", "modules/orders/roles/reviewer.md",
             "modules/orders/submodules/returns/roles/reviewer.md",
             "modules/orders/submodules/invoices/roles/reviewer.md"]

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name).resolve()

    def tearDown(self):
        self._tmp.cleanup()

    def repo(self, name: str) -> Path:
        root = make_repo(self.tmp / name, self.MODULES, TEAM_REVIEWER)
        write(root / "modules/old-search/MODULE.md",
              "# Old search\n\n**Status:** retired — replaced by shelf.\n")
        return root

    def test_all_covers_modules_index_parents_and_children_never_a_stub(self):
        root = self.repo("all")
        code, env, err = run_json("roles", "add", "reviewer", "--all", "--root", str(root))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual([(r["module"], r["status"], r["path"]) for r in env["data"]["results"]],
                         list(zip(self.MODULES, ["created", "created", "inherited", "inherited"],
                                  self.PATHS)))  # a child without a doc of its own is covered
        self.assertEqual([(root / p).is_file() for p in self.PATHS], [True, True, False, False])
        self.assertEqual(sorted(p.name for p in (root / "modules/old-search").iterdir()),
                         ["MODULE.md"])
        rows = {r["name"]: r for r in run_json("roles", "list", "--root", str(root))[1]["data"][
            "roles"]}
        self.assertEqual((rows["reviewer"]["docs"], rows["reviewer"]["missing"]),
                         (["orders", "shelf"], []))
        self.assertEqual(rows["reviewer"]["inherited"], ["orders/invoices", "orders/returns"])
        self.assertEqual(rows["qa"]["missing"], ["orders", "shelf"])  # parents only

    def test_an_explicit_child(self):
        root = self.repo("one")
        before = json.loads((root / "modules/registry.json").read_text())
        code, env, err = run_json("roles", "add", "reviewer", "orders/returns",
                                  "--root", str(root))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(env["data"]["results"],
                         [{"module": "orders/returns", "status": "created", "path": self.PATHS[2]}])
        self.assertEqual([p for p in self.PATHS if (root / p).exists()], [self.PATHS[2]])
        after = json.loads((root / "modules/registry.json").read_text())
        after["modules"]["orders"]["submodules"]["returns"]["context_files"].pop("roles")
        self.assertEqual(after, before)

    def test_a_path_into_the_modules_dir_and_a_repeated_target(self):
        root = self.repo("path")
        code, env, _ = run_json("roles", "add", "reviewer", "modules/orders/submodules/invoices",
                                "orders/invoices", "--root", str(root))
        self.assertEqual((code, [r["module"] for r in env["data"]["results"]]),
                         (0, ["orders/invoices"]))


class LayoutsTest(unittest.TestCase):  # P61-AC-009
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name).resolve()

    def tearDown(self):
        self._tmp.cleanup()

    def test_both_layouts_for_a_module_and_a_child(self):
        paths = {"checkout": "modules/checkout/roles/reviewer.md",
                 "payments/refunds": "modules/payments/submodules/refunds/roles/reviewer.md"}
        for i, (layout, target) in enumerate([("single", "checkout"),
                                              ("single", "payments/refunds"),
                                              ("per-module", "checkout"),
                                              ("per-module", "payments/refunds")]):
            with self.subTest(layout=layout, target=target):
                root = copy_fixture(self.tmp / str(i))
                add_pack(root)
                R = ("--root", str(root))
                entry_file = f"modules/{target.partition('/')[0]}/module.json"
                if layout == "per-module":
                    convert(root)
                    others = {p: p.read_bytes() for p in (root / "modules").glob("*/module.json")
                              if p != root / entry_file}
                code, env, err = run_json("roles", "add", "reviewer", target, *R)
                self.assertEqual((code, err), (0, ""))
                self.assertEqual(env["data"]["results"],
                                 [{"module": target, "status": "created",
                                   "path": paths[target]}])
                self.assertTrue((root / paths[target]).is_file())
                if layout == "per-module":
                    self.assertEqual(holder(root, target, entry_file)["context_files"]["roles"]
                                     ["reviewer"], paths[target])
                    self.assertEqual(run("index", "build", "--check", *R)[0], 0)
                    self.assertEqual({p: p.read_bytes() for p in others}, others)
                self.assertEqual(holder(root, target)["context_files"]["roles"]["reviewer"],
                                 paths[target])  # the single registry, or the rebuilt index
                code, env, _ = run_json("show", target, "--role", "reviewer", *R)
                self.assertIn(paths[target], [r["path"] for r in env["data"]["read"]
                                              if r["label"].endswith("role:reviewer")
                                              and not r["label"].startswith("parent")])
                code, env, _ = run_json("lint", *R)
                self.assertEqual(env["data"]["summary"]["error"], 0, env["data"]["findings"])


class UpgradeTest(unittest.TestCase):  # P61-AC-010 (steps 1, 3, 4; Task 4 adds `next`)
    SECURITY = ('\n[roles.security]\norder = 50\nstandard = true\n'
                'description = "Threats, secrets and permissions the module touches"\n')

    def test_a_role_added_by_a_new_engine_reaches_existing_modules(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp).resolve()
            root = copy_fixture(tmp / "repo")
            write(root / ".modsys/config.toml", '[lint]\nfail_on = "error"\n')
            code, _, err = run("create", "reviews", "--description", DESC, *KW,
                               "--non-interactive", "--root", str(root))  # the base engine
            self.assertEqual(code, 0, err)
            targets = sorted(t for t in BOOKSHOP + ["reviews"] if "/" not in t)  # a child inherits
            self.assertNotIn("security", [r["name"] for r in run_json(
                "roles", "list", "--root", str(root))[1]["data"]["roles"]])
            engine = copy_engine(tmp / "engine")
            defaults = engine / "modsys/defaults/config.toml"
            defaults.write_text(defaults.read_text(encoding="utf-8") + self.SECURITY,
                                encoding="utf-8")

            def new_engine(*argv):
                proc = subprocess.run(
                    [sys.executable, "-P", "-m", "modsys", *argv, "--json", "--root", str(root)],
                    capture_output=True, text=True, cwd=tmp, preexec_fn=default_signals,
                    env={**os.environ, "PYTHONPATH": str(engine)})
                return proc.returncode, json.loads(proc.stdout), proc.stderr

            before = snap(root, drop_lock=True)  # the base engine's create took the lock
            reg_before = json.loads((root / "modules/registry.json").read_text())
            code, env, err = new_engine("roles", "list")  # (1)
            self.assertEqual((code, err), (0, ""))
            row = {r["name"]: r for r in env["data"]["roles"]}["security"]
            self.assertEqual((row["standard"], row["owner"], row["docs"], row["missing"]),
                             (True, "engine", [], targets))
            code, env, err = new_engine("roles", "add", "security", "--all")  # (3)
            self.assertEqual((code, err), (0, ""))
            self.assertEqual([(r["module"], r["status"]) for r in env["data"]["results"]],
                             [("catalog", "created"), ("checkout", "created"), ("payments", "created"),
                              ("payments/refunds", "inherited"), ("reviews", "created")])
            docs = {r["path"] for r in env["data"]["results"] if r["status"] == "created"}
            code, env, _ = new_engine("roles", "list")  # (4)
            row = {r["name"]: r for r in env["data"]["roles"]}["security"]
            self.assertEqual((len(row["docs"]), row["docs"], row["missing"]),
                             (len(targets), targets, []))
            code, env, _ = new_engine("lint")
            self.assertEqual((code, env["data"]["summary"]["error"]), (0, 0))
            after = snap(root, drop_lock=True)
            changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
            # every module already has a roles/ directory: the N docs and the registry change
            self.assertEqual(changed, docs | {"modules/registry.json"})
            self.assertEqual(len(docs), len(targets))
            reg = json.loads((root / "modules/registry.json").read_text())
            for target in targets:
                parent, _, child = target.partition("/")
                entry = reg["modules"][parent]
                entry = entry["submodules"][child] if child else entry
                self.assertTrue(entry["context_files"]["roles"].pop("security").endswith(
                    "/roles/security.md"))
            self.assertEqual(reg, reg_before)


class EdgesTest(unittest.TestCase):  # P61-AC-028
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name).resolve()
        self.root = make_repo(self.tmp, {"shelf": ["shelf"], "orders": ["order"]},
                              TEAM_REVIEWER)
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def refused(self, *argv) -> str:
        before = snap(self.root)
        for extra in ((), ("--json",)):
            code, out, err = run(*argv, *extra, *self.R)
            self.assertEqual((code, out), (2, ""), err)
            self.assertTrue(err.startswith("modsys: error: "), err)
            self.assertNotIn("Traceback", err)
        self.assertEqual(snap(self.root), before)
        return err

    def test_a_roles_path_that_is_a_regular_file(self):
        write(self.root / "modules/shelf/roles", "not a directory\n")
        err = self.refused("roles", "add", "reviewer", "shelf")
        self.assertIn("modules/shelf/roles is not a directory", err)
        self.refused("roles", "add", "reviewer", "--all")  # validated before any write

    def test_a_symlink_at_the_doc_path_is_never_written_through(self):
        outside = self.tmp / "outside.md"
        outside.write_text("someone else's file\n", encoding="utf-8")
        link = self.root / "modules/shelf/roles/reviewer.md"
        link.parent.mkdir(parents=True)
        link.symlink_to(outside)
        err = self.refused("roles", "add", "reviewer", "shelf")  # unregistered: would register
        self.assertIn("modules/shelf/roles/reviewer.md is in the way: a symlink", err)
        mutate_registry(self.root, lambda d: d["modules"]["shelf"]["context_files"].update(
            roles={"reviewer": "modules/shelf/roles/reviewer.md"}))
        outside.unlink()  # registered and dangling: --recreate would write
        err = self.refused("roles", "add", "reviewer", "shelf", "--recreate")
        self.assertIn("modules/shelf/roles/reviewer.md is in the way: a symlink", err)
        self.assertFalse(outside.exists())
        link.unlink()
        (self.root / "modules/orders/roles").symlink_to(self.tmp)
        err = self.refused("roles", "add", "reviewer", "orders")
        self.assertIn("modules/orders/roles is in the way: a symlink", err)

    def test_a_role_name_with_an_uppercase_letter(self):
        err = self.refused("roles", "add", "Reviewer", "shelf")
        self.assertIn("role 'Reviewer': use lowercase letters, digits and '_', words joined by "
                      "'-'", err)

    def test_non_ascii_text_stays_utf8(self):
        text = "Bücher und Regale — für Leserinnen: Übersicht, Größe, ½ Preis"
        mutate_registry(self.root, lambda d: d["modules"]["shelf"].update(description=text))
        write(self.root / ".modsys/overrides/templates/roles/reviewer.md",
              "# ${title} — ${role}\n\n${description}\n")
        reg = (self.root / "modules/registry.json").read_bytes()
        code, _, err = run("roles", "add", "reviewer", "shelf", *self.R)
        self.assertEqual((code, err), (0, ""))
        doc = (self.root / "modules/shelf/roles/reviewer.md").read_bytes()
        self.assertEqual(doc, f"# Shelf — reviewer\n\n{text}\n".encode("utf-8"))
        self.assertIn(text.encode("utf-8"), reg)
        self.assertIn(text.encode("utf-8"), (self.root / "modules/registry.json").read_bytes())

    def test_an_entry_without_context_files_gains_only_the_roles_object(self):
        mutate_registry(self.root, lambda d: d["modules"]["shelf"].pop("context_files"))
        before = holder(self.root, "shelf")
        code, _, err = run("roles", "add", "reviewer", "shelf", *self.R)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(holder(self.root, "shelf"), {
            **before, "context_files": {"roles": {"reviewer": "modules/shelf/roles/reviewer.md"}}})

    def test_garbage_context_files_are_refused(self):  # a dry run refuses what the run would
        for value, needle in ((["x"], "context_files of 'shelf' is not an object"),
                              (None, "context_files of 'shelf' is not an object"),
                              ({"roles": 5}, "context_files.roles of 'shelf' is not an object"),
                              ({"roles": None},
                               "context_files.roles of 'shelf' is not an object"),
                              ({"roles": {"reviewer": 5}},
                               "context_files.roles.reviewer of 'shelf' is not a path")):
            with self.subTest(value=value):
                mutate_registry(self.root, lambda d: d["modules"]["shelf"].update(
                    context_files=value))
                for dry in ((), ("--dry-run",)):
                    self.assertIn(needle, self.refused("roles", "add", "reviewer", "shelf", *dry))

    def test_a_registered_path_outside_the_repository_is_refused(self):
        mutate_registry(self.root, lambda d: d["modules"]["shelf"]["context_files"].update(
            roles={"reviewer": "../elsewhere/reviewer.md"}))
        err = self.refused("roles", "add", "reviewer", "shelf", "--recreate")
        self.assertIn("../elsewhere/reviewer.md: a role doc path must lie inside the "
                      "repository", err)

    def test_a_trailing_slash_names_the_module(self):  # final review M-4
        code, env, err = run_json("roles", "add", "reviewer", "shelf/", "shelf", *self.R)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(env["data"]["results"], [
            {"module": "shelf", "status": "created", "path": "modules/shelf/roles/reviewer.md"}])
        (self.root / "modules/shelf/roles/reviewer.md").unlink()
        code, env, err = run_json("roles", "add", "reviewer", "shelf/", *self.R)
        self.assertEqual(env["data"]["results"], [
            {"module": "shelf", "status": "missing", "path": "modules/shelf/roles/reviewer.md",
             "command": "modsys roles add reviewer shelf --recreate"}])
        code, out, err = run("roles", "add", "reviewer", "shelf//", *self.R)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.splitlines()[0],
                         "missing        shelf                            modules/shelf/roles/"
                         "reviewer.md  — modsys roles add reviewer shelf --recreate")

    def test_two_targets_writing_one_doc_path_are_refused(self):  # final review M-4
        shared = "modules/shared/reviewer.md"  # registered for both, missing on disk
        for name in ("shelf", "orders"):
            mutate_registry(self.root, lambda d: d["modules"][name]["context_files"].update(
                roles={"reviewer": shared}))
        for argv in (("--all",), ("orders", "shelf")):
            for dry in ((), ("--dry-run",)):
                with self.subTest(argv=argv + dry):
                    err = self.refused("roles", "add", "reviewer", *argv, "--recreate", *dry)
                    first, second = ("shelf", "orders") if argv == ("--all",) else argv
                    self.assertEqual(err, f"modsys: error: '{first}' and '{second}' would both "
                                          f"write {shared} — a role doc path belongs to one "
                                          f"target; nothing written\n")
        mutate_registry(self.root, lambda d: (  # shelf's doc at orders' own (unregistered) path
            d["modules"]["shelf"]["context_files"].update(
                roles={"reviewer": "modules/orders/roles/reviewer.md"}),
            d["modules"]["orders"]["context_files"].pop("roles")))
        err = self.refused("roles", "add", "reviewer", "--all", "--recreate")
        self.assertIn("'shelf' and 'orders' would both write modules/orders/roles/reviewer.md",
                      err)
        code, env, err = run_json("roles", "add", "reviewer", "--all", "--dry-run", *self.R)
        self.assertEqual((code, err), (0, ""))  # without --recreate only orders writes it
        self.assertEqual([r["status"] for r in env["data"]["results"]], ["missing", "created"])


class RefusalsTest(Repo):  # P61-AC-033
    def refused_clean(self, *argv) -> str:
        before = snap(self.root)
        err = self.refused(*argv)
        self.assertEqual(snap(self.root), before)
        return err

    def test_every_refusal_writes_nothing(self):
        rows = [(("roles", "add", "x", "catalog"), "modsys: error: unknown role 'x'"),
                (("roles", "add", "reviewer", "nope"), "unknown module 'nope'"),
                (("roles", "add", "reviewer", "payments/nope"), "unknown module 'payments/nope'"),
                (("roles", "add", "reviewer"),
                 "usage: modsys roles add ROLE (--all | TARGET…) [--recreate] [--dry-run]"),
                (("roles", "add"), "usage: modsys roles add ROLE (--all | TARGET…)"),
                (("roles", "add", "reviewer", "--all", "catalog"), "--all takes no target"),
                (("roles", "add", "reviewer", "catalog", "--all"), "--all takes no target"),
                (("roles", "add", "reviewer", "legacy-search"),
                 "'legacy-search' is a pointer stub (modules/legacy-search/MODULE.md)")]
        for argv, needle in rows:
            with self.subTest(argv=argv):
                self.assertIn(needle, self.refused_clean(*argv))

    def test_a_disabled_role_names_the_layer_that_disabled_it_last(self):
        cases = [({".modsys/config.toml": "[roles.reviewer]\nenabled = false\n"},
                  ".modsys/config.toml"),
                 ({".modsys/config.toml": "[roles.reviewer]\nenabled = false\n",
                   ".modsys/config.user.toml": "[roles.reviewer]\nenabled = false\n"},
                  ".modsys/config.user.toml"),
                 ({".modsys/packs/reviews/pack.toml": PACK + "enabled = false\n"},
                  "pack 'reviews' (.modsys/packs/reviews/pack.toml)")]
        for files, layer in cases:
            with self.subTest(layer=layer):
                for rel in (".modsys/config.toml", ".modsys/config.user.toml"):
                    (self.root / rel).unlink(missing_ok=True)
                add_pack(self.root)
                for rel, text in files.items():
                    write(self.root / rel, text)
                err = self.refused_clean("roles", "add", "reviewer", "catalog")
                self.assertIn(f"role 'reviewer' is disabled: [roles.reviewer] enabled = false "
                              f"in {layer}", err)
        add_pack(self.root, PACK.replace("[roles.reviewer]", "[roles.po]\nenabled = false\n\n"
                                                             "[roles.reviewer]"))
        for rel in (".modsys/config.toml", ".modsys/config.user.toml"):
            (self.root / rel).unlink(missing_ok=True)
        self.assertIn("role 'po' is disabled: [roles.po] enabled = false in pack 'reviews'",
                      self.refused_clean("roles", "add", "po", "catalog"))

    def test_the_lock_held_past_the_timeout(self):
        with file_lock(self.root / "modules/registry.json"), \
                mock.patch("modsys.roles_cmd.LOCK_TIMEOUT_S", 0.2):
            err = self.refused_clean("roles", "add", "reviewer", "--all")
        self.assertIn("locked by another writer", err)
        self.assertIn("modules/registry.json.lock", err)


class AllOrNothingTest(unittest.TestCase):  # P61-AC-034
    DOCS = ["modules/shelf/roles/reviewer.md", "modules/orders/roles/reviewer.md",
            "modules/checkout/roles/reviewer.md"]

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_repo(Path(self._tmp.name).resolve(),
                              {"shelf": ["shelf"], "orders": ["order"], "checkout": ["cart"]},
                              TEAM_REVIEWER)
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def per_module(self) -> None:
        convert(self.root)
        write(self.root / ".modsys/config.toml",
              '[paths]\nregistry_layout = "per-module"\n\n' + TEAM_REVIEWER)

    def failing(self, target: str, effect, code: int = 2) -> str:
        """Run `roles add reviewer --all` with `target` patched to `effect` (its side effect):
        exit `code`, nothing on stdout, no traceback, none of the docs left; the stderr."""
        with mock.patch(target, side_effect=effect):
            got, out, err = run("roles", "add", "reviewer", "--all", *self.R)
        self.assertEqual((got, out), (code, ""), err)
        self.assertNotIn("Traceback", err)
        self.assertEqual([p for p in self.DOCS if os.path.lexists(self.root / p)], [])
        return err

    def edit_after(self, n: int, edit):
        """`write_new_doc` that runs `edit` once it has written the n-th doc."""
        real, calls = roles_cmd.write_new_doc, []

        def write_then(path, text, rel):
            real(path, text, rel)
            calls.append(rel)
            if len(calls) == n:
                edit()
        return write_then

    def test_the_registry_changed_on_disk_after_it_was_read(self):
        before = snap(self.root)
        err = self.failing("modsys.roles_cmd.write_new_doc", self.edit_after(
            3, lambda: mutate_registry(self.root, lambda d: d.update(note="edited meanwhile"))))
        self.assertIn("modules/registry.json changed since it was read", err)
        edited = (self.root / "modules/registry.json").read_bytes()
        self.assertIn(b"edited meanwhile", edited)
        self.assertEqual(snap(self.root, drop_lock=True),
                         {**before, "modules/registry.json": (
                             before["modules/registry.json"][0], edited)})

    def test_a_registry_write_that_fails(self):
        before = snap(self.root)
        err = self.failing("modsys.store.atomic_write", OSError(
            errno.ENOSPC, "No space left on device"))
        self.assertIn("cannot write modules/registry.json: No space left on device", err)
        self.assertEqual(snap(self.root, drop_lock=True), before)
        temp = str(self.root / "modules/.registry.json.x1y2.tmp")  # a real failure names it
        err = self.failing("modsys.store.os.replace", OSError(errno.EXDEV, "Cross-device link",
                                                              temp))
        self.assertIn("cannot write modules/registry.json: Cross-device link", err)
        self.assertEqual(snap(self.root, drop_lock=True), before)

    def test_per_module_entry_changed_on_disk(self):
        self.per_module()
        before = snap(self.root)
        entry = self.root / "modules/orders/module.json"
        err = self.failing("modsys.roles_cmd.write_new_doc", self.edit_after(
            3, lambda: entry.write_text(entry.read_text() + " \n")))
        self.assertIn("modules/orders/module.json changed since it was read", err)
        self.assertEqual(snap(self.root, drop_lock=True),
                         {**before, "modules/orders/module.json": (
                             before["modules/orders/module.json"][0], entry.read_bytes())})

    def test_per_module_a_write_that_fails_halfway_puts_every_entry_back(self):
        self.per_module()
        before = snap(self.root)
        from modsys import layout
        real, calls = layout.atomic_write, []

        def second_fails(path, text):
            calls.append(path)
            if len(calls) == 2:
                raise OSError(errno.EIO, "Input/output error")
            real(path, text)
        err = self.failing("modsys.layout.atomic_write", second_fails)
        self.assertIn("cannot write modules/checkout/module.json, modules/orders/module.json, "
                      "modules/shelf/module.json: Input/output error; nothing written", err)
        self.assertEqual(snap(self.root, drop_lock=True), before)
        err = self.failing("modsys.roles_cmd.build_index", OSError(
            errno.EIO, "Input/output error"))  # the index, after every entry file
        self.assertIn("cannot write modules/registry.json: Input/output error", err)
        self.assertEqual(snap(self.root, drop_lock=True), before)

    def test_ctrl_c_during_the_lock_wait_and_after_the_docs(self):
        with file_lock(self.root / "modules/registry.json"):
            before = snap(self.root)
            err = self.failing("modsys.store.time.sleep", KeyboardInterrupt, 130)
            self.assertIn("modsys: interrupted", err)
            self.assertEqual(snap(self.root), before)
        before = snap(self.root)
        self.failing("modsys.roles_cmd._register", KeyboardInterrupt, 130)  # docs written
        self.assertEqual(snap(self.root), before)
        self.failing("modsys.store.RegistryStore.commit", KeyboardInterrupt, 130)
        self.assertEqual(snap(self.root), before)


    def test_ctrl_c_after_the_commit_point_keeps_every_write(self):
        with mock.patch("modsys.store._unlock", side_effect=KeyboardInterrupt):
            code, out, err = run("roles", "add", "reviewer", "--all", *self.R)
        self.assertEqual((code, out), (130, ""), err)
        self.assertTrue(all((self.root / p).is_file() for p in self.DOCS))
        self.assertEqual([holder(self.root, m)["context_files"]["roles"]["reviewer"]
                          for m in ("shelf", "orders", "checkout")], self.DOCS)

    def test_the_docs_go_while_the_lock_is_held(self):  # final review M-4
        """A failed run removes its docs and the directories it made inside the registry lock:
        a `roles add` waiting for the lock never plans against a doc that then goes (it would
        report `registered` and leave a registration without its file, MS004)."""
        registry, seen = self.root / "modules/registry.json", []
        real_unlink, real_rmdir = Path.unlink, Path.rmdir

        def held() -> bool:
            try:
                with file_lock(registry, timeout_s=0):
                    return False
            except UsageError:
                return True

        def spy(real):
            def call(path, *args, **kwargs):
                if self.root in path.parents and "roles" in path.parts:
                    seen.append((path.relative_to(self.root).as_posix(), held()))
                return real(path, *args, **kwargs)
            return call

        with mock.patch.object(Path, "unlink", spy(real_unlink)), \
                mock.patch.object(Path, "rmdir", spy(real_rmdir)):
            self.failing("modsys.roles_cmd._register", KeyboardInterrupt, 130)
        dirs = [p.rsplit("/", 1)[0] for p in reversed(self.DOCS)]  # deepest, last made first
        self.assertEqual(seen, [(p, True) for p in self.DOCS + dirs])
        self.assertEqual([d for d in dirs if (self.root / d).exists()], [])


class SurfaceTest(Repo):  # P61-AC-026, P61-AC-037 (the `roles` part)
    def test_the_verb_and_its_help(self):
        from modsys.cli import build_parser
        self.assertIn("roles", build_parser()._subparsers._group_actions[0].choices)
        code, out, _ = run("roles", "--help")
        self.assertEqual(code, 0)
        text = " ".join(out.split())
        for needle in ("{list,add,skip}", "--note", "--root", "--config-dir", "--json",
                       "--all", "--recreate", "--dry-run", "ROLE", "TARGET"):
            self.assertIn(needle, text)

    def test_options_may_come_before_or_after_the_targets(self):  # on 3.11 as on 3.12+
        code, env, err = run_json("roles", "add", "--dry-run", "reviewer", "--root",
                                  str(self.root), "catalog", "payments/refunds")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual([r["module"] for r in env["data"]["results"]],
                         ["catalog", "payments/refunds"])
        self.assertTrue(env["data"]["dry_run"])

    def test_one_json_document_per_run(self):
        for argv in (("roles", "list"), ("roles", "add", "reviewer", "--all", "--dry-run"),
                     ("roles", "add", "reviewer", "catalog")):
            with self.subTest(argv=argv):
                code, out, err = run(*argv, "--json", *self.R)
                self.assertEqual((code, err), (0, ""))
                env, end = json.JSONDecoder().raw_decode(out)
                self.assertEqual((out[end:].strip(), env["schema"]), ("", "modsys.roles/1"))

    def test_an_internal_failure(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("MODSYS_DEBUG", None)
            for argv, seam in ((("roles", "list"), "role_rows"),
                               (("roles", "add", "reviewer", "--all"), "plan_add")):
                with self.subTest(argv=argv), \
                        mock.patch(f"modsys.roles_cmd.{seam}", side_effect=RuntimeError("boom")):
                    code, out, err = run(*argv, "--json", *self.R)
                    self.assertEqual((code, out), (2, ""))
                    self.assertTrue(err.startswith("modsys: internal error: RuntimeError: boom"),
                                    err)
                    self.assertNotIn("Traceback", err)
            os.environ["MODSYS_DEBUG"] = "1"
            with mock.patch("modsys.roles_cmd.role_rows", side_effect=RuntimeError("boom")), \
                    self.assertRaises(RuntimeError):
                run("roles", "list", *self.R)


if __name__ == "__main__":
    unittest.main()
