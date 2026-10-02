"""`modsys next [--base REF]` (P6.1 W4, D2, D4, SI-P61-4…8): one ranked, read-only list of what
the repository needs now, each item with the modsys command that fixes it — and what an engine
upgrade brought, derived from the repository alone (no state file)."""
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import modsys
from modsys.cli import build_parser
from tests.helpers import (copy_fixture, engine_version, git, init_git, mutate_registry,
                           next_dev, run, run_json)
from tests.plugin_helpers import copy_engine, default_signals

VERSION = modsys.__version__
TEAM_PACK = ('id = "team"\nversion = "9.0.0"\ndescription = "Team skills"\n\n'
             '[skills.team-review]\npath = "skills/team-review"\n\n'
             '[skills.team-notes]\npath = "skills/team-notes"\n')
SEEDED_CONFIG = ('[packs]\nagents = ["claude"]\n\n[coverage]\nexclude = ["*.md"]\n\n'
                 '[[code_map]]\nid = "catalog-src"\nmodule = "catalog"\n'
                 'globs = ["src/catalog/**"]\n')
CORE_CONFIG = '[packs]\nbuiltin = ["core"]\nagents = ["claude"]\n'
BOOKSHOP = ["catalog", "checkout", "payments", "payments/refunds"]  # legacy-search is a stub
DESC = "Customer reviews of books: ratings, comments and moderation."
KW = [a for k in ("review", "rating", "stars", "comment", "moderation") for a in ("--keyword", k)]
SECURITY = ('\n[roles.security]\norder = 50\nstandard = true\n'
            'description = "Threats, secrets and permissions the module touches"\n')
CORE_SKILLS = ["module-adopt", "module-create", "module-discover", "module-init", "module-lint",
               "module-research", "module-scout", "module-split", "module-sync"]
NOT_SET_UP = "modsys is not set up here: no config, no registry"


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def skill_md(name: str) -> str:
    return (f"---\nname: {name}\ndescription: The {name} skill of the team.\n---\n\n"
            f"# {name}\n\nBody.\n")


def must(*argv) -> str:
    """Run a verb that must succeed (exit 0); its stdout."""
    code, out, err = run(*argv)
    assert code == 0, (argv, code, out, err)
    return out


def nxt(root: Path, *argv) -> dict:
    """`modsys next --json`: exit 0, nothing on stderr, one `modsys.next/1` document; its data."""
    code, out, err = run("next", *argv, "--json", "--root", str(root))
    assert (code, err) == (0, ""), (code, out, err)
    env, end = json.JSONDecoder().raw_decode(out)
    assert out[end:].strip() == "" and set(env) == {"schema", "data"}, out
    assert env["schema"] == "modsys.next/1", env
    assert list(env["data"]) == ["version", "items", "skipped"], env
    assert env["data"]["version"] == VERSION
    ranks = [i["rank"] for i in env["data"]["items"]]
    assert ranks == list(range(1, len(ranks) + 1)), ranks
    for item in env["data"]["items"]:
        assert list(item) == ["rank", "kind", "summary", "command"], item
    return env["data"]


def rows(data: dict) -> list[tuple]:
    return [(i["kind"], i["summary"], i["command"]) for i in data["items"]]


def text_of(data: dict, version: str = VERSION) -> str:
    """The text `next` prints for `data`: the version line, then per item `<rank>. <summary>` and
    the command indented under it — or `nothing to do`."""
    lines = [f"modsys {version}"]
    for i in data["items"]:
        head = f"{i['rank']}. "
        lines += [head + i["summary"], " " * len(head) + i["command"]]
    return "\n".join(lines + ([] if data["items"] else ["nothing to do"])) + "\n"


def snap(root: Path) -> dict:
    """Every file, directory and symlink below `root` — tracked, untracked and ignored alike —
    by content and mode (a symlink by its link text); of git's own `.git/` directory the index
    only, by content and mtime (a `git diff` that refreshes it rewrites it)."""
    out = {}
    for path in sorted(root.rglob("*")):
        rel, st = path.relative_to(root).as_posix(), path.lstat()
        if rel == ".git/index":
            out[rel] = ("index", st.st_mtime_ns, path.read_bytes())
        if rel == ".git" or rel.startswith(".git/"):
            continue
        if stat.S_ISLNK(st.st_mode):
            out[rel] = ("symlink", os.readlink(path))
        elif stat.S_ISDIR(st.st_mode):
            out[rel + "/"] = (stat.S_IMODE(st.st_mode), b"")
        else:
            out[rel] = (stat.S_IMODE(st.st_mode), path.read_bytes())
    return out


def drop_locks(root: Path) -> None:
    """Remove every `*.lock` below `root`, `.git/` included: the writers that built the fixture
    leave their (empty) lock files, which would hide one a read-only verb created."""
    for path in root.rglob("*.lock"):
        path.unlink()


def seeded(tmp: Path) -> Path:
    """A bookshop copy with exactly one finding of each `next` kind: committed as `main` (in
    sync: copies, block, qa and po docs), then on branch `work` a deprecated field (MS011), the
    team pack moved to 9.1.0 (a stale copy of team-review; the ejected team-notes behind,
    MS063), a hand edit inside the CLAUDE.md block, a queued proposal, an undeclared field
    (MS012), an unmapped file under the [[code_map]] config and catalog's code changed."""
    root = copy_fixture(tmp)
    R = ("--root", str(root))
    write(root / ".modsys/packs/team/pack.toml", TEAM_PACK)
    for name in ("team-review", "team-notes"):
        write(root / f".modsys/packs/team/skills/{name}/SKILL.md", skill_md(name))
    write(root / ".modsys/config.toml", SEEDED_CONFIG)
    for argv in (("packs", "sync"), ("eject", "team-notes"), ("packs", "sync"),
                 ("agents-md", "--target", "CLAUDE.md"), ("roles", "add", "qa", "--all"),
                 ("roles", "add", "po", "--all")):
        must(*argv, *R)
    init_git(root)
    git(root, "checkout", "-q", "-b", "work")
    mutate_registry(root, lambda d: d["modules"]["catalog"].update(
        depends_on_modules=["checkout"]))
    mutate_registry(root, lambda d: d["modules"]["checkout"].update(owner_team="shop"))
    write(root / ".modsys/packs/team/pack.toml", TEAM_PACK.replace('"9.0.0"', '"9.1.0"'))
    claude = root / "CLAUDE.md"
    claude.write_text(claude.read_text(encoding="utf-8").replace(
        "Read them before a task", "Read them before any task"), encoding="utf-8")
    must("propose", "--module", "catalog", "--op", "set", "--field", "status", "--value",
         '"draft"', "--reason", "r", "--run-id", "r1", *R)
    write(root / "src/misc/tool.py", "x = 1\n")
    with (root / "src/catalog/service.py").open("a", encoding="utf-8") as fh:
        fh.write("# changed\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "work")
    return root


SEEDED_ITEMS = [
    ("lint-error", "MS011 catalog: deprecated field 'depends_on_modules': use related_modules",
     "modsys lint"),
    ("skills", "skill copies not in sync (claude): stale team-review", "modsys packs sync"),
    ("agents-md", "CLAUDE.md: the modsys block is stale", "modsys agents-md --target CLAUDE.md"),
    ("role", "architect: no doc in 3 module(s)", "modsys roles add architect --all"),
    ("ejected", "ejected skill 'team-notes' is behind pack 'team' (ejected from 9.0.0, pack is "
                "now 9.1.0)", "modsys eject --diff team-notes"),
    ("proposals", "1 pending proposal file(s), 1 item(s)", "modsys proposals list"),
    ("lint-warning", "1 lint warning(s): MS012", "modsys lint"),
    ("unmapped", "1 file(s) map to no module: src/misc/tool.py", "modsys coverage"),
    ("drift", "drift since main: code changed without a doc update: catalog",
     "modsys sync-instructions --from-diff main..HEAD"),
]


class SeededTest(unittest.TestCase):  # P61-AC-011, P61-AC-013, P61-AC-015, SI-P61-6
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls._tmp.name).resolve()
        cls.root = seeded(cls.tmp / "seeded")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_one_ranked_list_each_item_with_its_command(self):  # P61-AC-011
        data = nxt(self.root, "--base", "main")
        self.assertEqual(rows(data), SEEDED_ITEMS)
        self.assertEqual(data["skipped"], [])
        code, out, err = run("next", "--base", "main", "--root", str(self.root))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, text_of(data))  # the same items, in the same order
        parser = build_parser()
        for _, _, command in SEEDED_ITEMS:  # each command is a modsys command line
            argv = shlex.split(command)
            self.assertEqual(argv[0], "modsys")
            parser.parse_args(argv[1:])

    def test_each_command_works_on_its_finding(self):  # P61-AC-011 (runnable)
        work = self.tmp / "commands"
        shutil.copytree(self.root, work, symlinks=True)
        for _, _, command in SEEDED_ITEMS:
            with self.subTest(command=command):
                code, _, err = run(*shlex.split(command)[1:], "--root", str(work))
                self.assertIn(code, (0, 1), err)  # lint exits 1 on its error finding
                self.assertNotIn("error:", err)
        kinds = [i["kind"] for i in nxt(work, "--base", "main")["items"]]
        for fixed in ("skills", "agents-md", "role"):  # the commands that write fixed these
            self.assertNotIn(fixed, kinds)

    def test_a_finding_appears_once(self):  # SI-P61-6: MS063 is the ejected kind only
        code, env, _ = run_json("lint", "--root", str(self.root))
        warnings = sorted(f["code"] for f in env["data"]["findings"]
                          if f["severity"] == "warning")
        self.assertEqual(warnings, ["MS012", "MS063"])
        data = nxt(self.root)
        self.assertEqual([i["summary"] for i in data["items"] if i["kind"] == "lint-warning"],
                         ["1 lint warning(s): MS012"])
        self.assertEqual([i for i in data["items"] if "MS063" in i["summary"]], [])

    def test_drift_only_with_base(self):  # P61-AC-015
        data = nxt(self.root)
        self.assertNotIn("drift", [i["kind"] for i in data["items"]])
        self.assertIn("drift: no --base", data["skipped"])
        self.assertEqual(rows(data), SEEDED_ITEMS[:-1])
        data = nxt(self.root, "--base", "main")
        self.assertEqual([i for i in rows(data) if i[0] == "drift"], [SEEDED_ITEMS[-1]])
        self.assertNotIn("drift: no --base", data["skipped"])
        sha = git(self.root, "rev-parse", "main").strip()
        drift = [i for i in nxt(self.root, "--base", sha)["items"] if i["kind"] == "drift"]
        self.assertEqual((drift[0]["summary"], drift[0]["command"]),
                         (f"drift since {sha}: code changed without a doc update: catalog",
                          f"modsys sync-instructions --from-diff {sha}..HEAD"))

    def test_next_and_roles_list_never_write(self):  # P61-AC-013
        stamps = [self.root / p for p in ("modules/registry.json", ".modsys/config.toml",
                                          ".modsys/packs/team/pack.toml",
                                          ".modsys/packs/bookshop/pack.toml")]
        drop_locks(self.root)
        before = snap(self.root)
        mtimes = [p.stat().st_mtime_ns for p in stamps]
        for argv in (("next",), ("next", "--base", "main"), ("roles", "list")):
            for extra in ((), ("--json",)):
                with self.subTest(argv=argv + extra):
                    code, out, err = run(*argv, *extra, "--root", str(self.root))
                    self.assertEqual((code, err), (0, ""))
                    self.assertTrue(out)
        self.assertEqual(snap(self.root), before)
        self.assertEqual([p.stat().st_mtime_ns for p in stamps], mtimes)
        self.assertEqual(sorted(self.root.rglob("*.lock")), [])


class GitIndexTest(unittest.TestCase):  # P61-AC-013 (the git index; review fix round 1)
    def test_drift_never_refreshes_the_real_index(self):
        """`git diff` against the working tree rewrites the index (through `index.lock`) when a
        tracked file is stat-dirty; `next --base` diffs against a copy of it, and still sees
        what `lint --changed` and `ci` see — the stat-only file is no drift."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp).resolve()
            root = copy_fixture(tmp / "a")
            write(root / ".modsys/config.toml",
                  '[[code_map]]\nid = "src"\npattern = "src/{module}/**"\n')
            write(root / "src/checkout/cart.py", "CART = []\n")
            init_git(root)
            git(root, "checkout", "-q", "-b", "work")
            write(root / "src/checkout/cart.py", "CART = [1]\n")  # checkout's code changed
            git(root, "add", "src/checkout/cart.py")
            git(root, "commit", "-q", "-m", "work")
            index, service = root / ".git/index", root / "src/catalog/service.py"
            service.write_bytes(service.read_bytes())  # the same bytes: stat-dirty only
            later = index.stat().st_mtime + 100
            os.utime(service, (later, later))
            drop_locks(root)
            before = snap(root)
            data = nxt(root, "--base", "main")
            self.assertEqual(run("next", "--base", "main", "--root", str(root)),
                             (0, text_of(data), ""))
            self.assertEqual(snap(root), before)  # the index: the same bytes and mtime
            self.assertEqual(sorted(root.rglob("*.lock")), [])
            self.assertEqual([i for i in rows(data) if i[0] == "drift"], [
                ("drift", "drift since main: code changed without a doc update: checkout",
                 "modsys sync-instructions --from-diff main..HEAD")])
            for argv in (("lint", "--changed", "--base", "main"),
                         ("ci", "--base", "main", "--fail-on", "never")):
                twin = tmp / argv[0]  # the same tree; these verbs may refresh their index
                shutil.copytree(root, twin, symlinks=True)
                with self.subTest(verb=argv[0]):
                    code, env, err = run_json(*argv, "--root", str(twin))
                    self.assertEqual(err, "")
                    if argv[0] == "lint":
                        findings = env["data"]["findings"]
                        self.assertEqual(env["data"]["changed"]["files"],
                                         ["src/checkout/cart.py"])
                    else:
                        findings = [f for step in env["data"]["steps"]
                                    if step["name"] == "drift" for f in step["findings"]]
                    self.assertEqual(sorted({f["module"] for f in findings
                                             if f["code"] == "MS050"}), ["checkout"])


    def test_the_index_copy_lies_outside_the_root_and_goes_on_every_exit(self):
        from modsys import next_cmd
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp).resolve()
            root = copy_fixture(tmp / "a")
            init_git(root)
            scratch = tmp / "scratch"
            scratch.mkdir()
            seen, real = [], next_cmd.drift_report

            def spy(ws, base, findings, env=None):  # where the git calls read the index
                copy = Path(env["GIT_INDEX_FILE"])
                seen.append((copy.is_file(), root in copy.parents,
                             copy.read_bytes() == (root / ".git/index").read_bytes()))
                return real(ws, base, findings, env=env)

            with mock.patch("tempfile.tempdir", str(scratch)):
                with mock.patch("modsys.next_cmd.drift_report", side_effect=spy):
                    self.assertEqual(nxt(root, "--base", "HEAD")["items"][-1]["kind"], "role")
                self.assertEqual(seen, [(True, False, True)])  # a copy, outside the root
                self.assertEqual(list(scratch.iterdir()), [])
                for error, code in ((RuntimeError("boom"), 2), (KeyboardInterrupt(), 130)):
                    with self.subTest(error=type(error).__name__), mock.patch.dict(os.environ), \
                            mock.patch("modsys.next_cmd.drift_report", side_effect=error):
                        os.environ.pop("MODSYS_DEBUG", None)
                        self.assertEqual(run("next", "--base", "HEAD", "--root", str(root))[0],
                                         code)
                        self.assertEqual(list(scratch.iterdir()), [])


class UncommittedDriftTest(unittest.TestCase):  # final review I-1 (P61-AC-015's command)
    """`sync-instructions --from-diff REF..HEAD` sees commits only: drift that includes an
    uncommitted or untracked file names the drifted modules instead (`--module`, one per
    module, in registry order) — a command that reports them."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = root = copy_fixture(Path(self._tmp.name).resolve())
        write(root / ".modsys/config.toml", '[[code_map]]\nid = "src"\npattern = '
                                            '"src/{module}/**"\n')
        for module in ("checkout", "payments"):
            write(root / f"src/{module}/api.py", "API = []\n")
        mutate_registry(root, lambda d: d.update(modules={  # registry order is not sorted order
            name: d["modules"][name] for name in ("payments", "checkout", "catalog")}))
        init_git(root)
        git(root, "checkout", "-q", "-b", "work")

    def tearDown(self):
        self._tmp.cleanup()

    def drift(self) -> list[tuple]:
        return [i for i in rows(nxt(self.root, "--base", "main")) if i[0] == "drift"]

    def reported(self, command: str) -> list[str]:
        """Run a `sync-instructions` command `next` printed; the modules it reports."""
        code, env, err = run_json(*shlex.split(command)[1:], "--root", str(self.root))
        self.assertEqual((code, err), (0, ""))
        return [m["module"] for m in env["data"]["modules"]]

    def test_an_uncommitted_edit(self):  # the review's probe: an edited, uncommitted file
        append(self.root / "src/catalog/service.py", "# changed\n")
        self.assertEqual(self.drift(), [
            ("drift", "drift since main: code changed without a doc update: catalog",
             "modsys sync-instructions --module catalog")])
        self.assertEqual(self.reported("modsys sync-instructions --module catalog"),
                         ["catalog"])
        self.assertEqual(self.reported("modsys sync-instructions --from-diff main..HEAD"), [])

    def test_committed_untracked_and_edited_modules_in_registry_order(self):
        append(self.root / "src/catalog/service.py", "# committed\n")
        git(self.root, "commit", "-q", "-am", "catalog")
        write(self.root / "src/checkout/cart.py", "CART = []\n")  # untracked
        append(self.root / "src/payments/api.py", "# edited\n")  # tracked, not committed
        command = "modsys sync-instructions --module payments --module checkout --module catalog"
        self.assertEqual(self.drift(), [
            ("drift", "drift since main: code changed without a doc update: catalog, checkout, "
                      "payments", command)])
        self.assertEqual(self.reported(command), ["payments", "checkout", "catalog"])

    def test_a_snapshot_outside_the_modules_dir_names_no_module(self):
        write(self.root / "docs/setup.legacy.md", "# Old setup\n")
        git(self.root, "add", "docs/setup.legacy.md")
        git(self.root, "commit", "-q", "-m", "snapshot")
        git(self.root, "checkout", "-q", "-b", "later")
        append(self.root / "docs/setup.legacy.md", "Edited.\n")  # not committed
        drift = [i for i in rows(nxt(self.root, "--base", "work")) if i[0] == "drift"]
        self.assertEqual(drift, [("drift", "drift since work: a frozen snapshot changed: *",
                                  "modsys lint --changed --base work")])
        code, env, err = run_json("lint", "--changed", "--base", "work", "--root",
                                  str(self.root))
        self.assertEqual([(f["code"], f["path"]) for f in env["data"]["findings"]],
                         [("MS051", "docs/setup.legacy.md")])

    def test_committed_drift_keeps_the_range(self):  # P61-AC-015 as it was
        append(self.root / "src/catalog/service.py", "# committed\n")
        git(self.root, "commit", "-q", "-am", "catalog")
        write(self.root / "notes.txt", "maps to no module\n")  # untracked, but no drift
        command = "modsys sync-instructions --from-diff main..HEAD"
        self.assertEqual(self.drift(), [
            ("drift", "drift since main: code changed without a doc update: catalog", command)])
        self.assertEqual(self.reported(command), ["catalog"])


class NothingToDoTest(unittest.TestCase):  # P61-AC-012
    def test_a_clean_bookshop_after_setup_by_hand(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(Path(tmp).resolve())
            R = ("--root", str(root))
            write(root / ".modsys/config.toml", CORE_CONFIG)
            for argv in (("packs", "sync"), ("agents-md", "--target", "CLAUDE.md"),
                         *(("roles", "add", role, "--all") for role in ("qa", "po", "architect"))):
                must(*argv, *R)
            init_git(root)
            self.assertEqual(run("next", *R), (0, f"modsys {VERSION}\nnothing to do\n", ""))
            data = nxt(root)
            self.assertEqual(data["items"], [])
            self.assertEqual(data["skipped"],
                             ["unmapped: no [[code_map]] rule", "drift: no --base"])
            data = nxt(root, "--base", "HEAD")
            self.assertEqual((data["items"], data["skipped"]),
                             ([], ["unmapped: no [[code_map]] rule"]))


def engine_cli(engine: Path, root: Path, *argv) -> tuple[int, str, str]:
    """Run the CLI of the engine copy `engine` (its own `modsys` package) on `root`."""
    proc = subprocess.run([sys.executable, "-P", "-m", "modsys", *argv, "--root", str(root)],
                          capture_output=True, text=True, cwd=engine.parent,
                          preexec_fn=default_signals,
                          env={**os.environ, "PYTHONPATH": str(engine)})
    return proc.returncode, proc.stdout, proc.stderr


def engine_json(engine: Path, root: Path, *argv) -> dict:
    code, out, err = engine_cli(engine, root, *argv, "--json")
    assert (code, err) == (0, ""), (argv, code, out, err)
    return json.loads(out)["data"]


def append(path: Path, text: str) -> None:
    path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")


class UpgradeTest(unittest.TestCase):  # P61-AC-010, P61-AC-014 (D2: no state file)
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name).resolve()

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_role_added_by_a_new_engine_reaches_existing_modules(self):  # P61-AC-010
        root = copy_fixture(self.tmp / "repo")
        R = ("--root", str(root))
        write(root / ".modsys/config.toml", '[lint]\nfail_on = "error"\n')
        must("create", "reviews", "--description", DESC, *KW, "--non-interactive", *R)
        for role in ("qa", "po", "architect"):  # the base engine's standard roles everywhere
            must("roles", "add", role, "--all", *R)
        self.assertEqual(nxt(root)["items"], [])
        targets = sorted(t for t in BOOKSHOP + ["reviews"] if "/" not in t)  # a child inherits
        engine = copy_engine(self.tmp / "engine")
        append(engine / "modsys/defaults/config.toml", SECURITY)
        drop_locks(root)
        before = snap(root)
        row = {r["name"]: r for r in engine_json(engine, root, "roles", "list")["roles"]}
        self.assertEqual((row["security"]["docs"], row["security"]["missing"]), ([], targets))
        data = engine_json(engine, root, "next")  # (2)
        self.assertEqual(rows(data), [("role", f"security: no doc in {len(targets)} module(s)",
                                       "modsys roles add security --all")])
        self.assertEqual(engine_cli(engine, root, "next"),
                         (0, text_of(data), ""))
        self.assertEqual(snap(root), before)  # (1) and (2) read only
        self.assertEqual(sorted(root.rglob("*.lock")), [])
        results = engine_json(engine, root, "roles", "add", "security", "--all")["results"]
        self.assertEqual(sorted(r["module"] for r in results if r["status"] == "created"), targets)
        row = {r["name"]: r for r in engine_json(engine, root, "roles", "list")["roles"]}
        self.assertEqual((row["security"]["docs"], row["security"]["missing"]), (targets, []))
        self.assertEqual(engine_json(engine, root, "next")["items"], [])  # (4)
        self.assertEqual(engine_json(engine, root, "lint")["summary"]["error"], 0)
        after = snap(root)
        changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
        docs = {r["path"] for r in results if r["status"] == "created"}
        self.assertEqual(changed - {"modules/registry.json.lock"},
                         docs | {"modules/registry.json"})

    def upgraded_repo(self) -> Path:
        """A bookshop copy in sync with the base engine: the core pack synced for claude with
        module-scout ejected, the CLAUDE.md block, every standard role's docs."""
        root = copy_fixture(self.tmp / "repo")
        R = ("--root", str(root))
        write(root / ".modsys/config.toml", CORE_CONFIG)
        for argv in (("packs", "sync"), ("eject", "module-scout"), ("packs", "sync"),
                     ("agents-md", "--target", "CLAUDE.md"),
                     *(("roles", "add", role, "--all") for role in ("qa", "po", "architect"))):
            must(*argv, *R)
        self.assertEqual(run("next", *R), (0, f"modsys {VERSION}\nnothing to do\n", ""))
        drop_locks(root)
        return root

    def test_what_an_upgrade_brought_without_a_state_file(self):  # P61-AC-014
        root = self.upgraded_repo()
        engine = copy_engine(self.tmp / "engine")
        core = engine / "modsys/defaults/packs/core/skills"
        append(engine / "modsys/defaults/config.toml", SECURITY)  # (a)
        append(core / "module-lint/SKILL.md", "\nOne more step.\n")  # (b)
        template = engine / "modsys/defaults/templates/agents-md.md"  # (c)
        template.write_text(template.read_text(encoding="utf-8").replace(
            "Read them before a task", "Read them before every task"), encoding="utf-8")
        append(core / "module-scout/SKILL.md", "\nOne more step.\n")  # (d): the pack moved on
        before = snap(root)
        data = engine_json(engine, root, "next")
        self.assertEqual(rows(data), [
            ("skills", "skill copies not in sync (claude): stale module-lint",
             "modsys packs sync"),
            ("agents-md", "CLAUDE.md: the modsys block is stale",
             "modsys agents-md --target CLAUDE.md"),
            ("role", "security: no doc in 3 module(s)", "modsys roles add security --all"),
            ("ejected", "ejected skill 'module-scout' is behind pack 'core' (the pack's files "
                        "changed since the eject)", "modsys eject --diff module-scout")])
        self.assertEqual(engine_cli(engine, root, "next"), (0, text_of(data), ""))
        self.assertEqual(snap(root), before)  # nothing written, no "last seen version" file
        self.assertEqual(sorted(root.rglob("*.lock")), [])

    def test_a_new_engine_version_alone_brings_the_copies(self):  # P61-AC-014 (d), D2
        root = self.upgraded_repo()
        engine = copy_engine(self.tmp / "engine")
        newer = next_dev(engine_version())
        init = engine / "modsys/__init__.py"
        init.write_text(init.read_text(encoding="utf-8").replace(
            f'"{engine_version()}"', f'"{newer}"'), encoding="utf-8")
        before = snap(root)
        code, out, err = engine_cli(engine, root, "next", "--json")
        env = json.loads(out)
        self.assertEqual((code, err, env["data"]["version"]), (0, "", newer))
        stale = [s for s in CORE_SKILLS if s != "module-scout"]  # the copies' markers name it
        self.assertEqual(rows(env["data"]), [
            ("skills", f"skill copies not in sync (claude): stale {', '.join(stale)}",
             "modsys packs sync")])  # a built-in pack's version moves no ejected copy (MS063)
        self.assertEqual(engine_cli(engine, root, "next")[1].splitlines()[0], f"modsys {newer}")
        self.assertEqual(snap(root), before)
        self.assertEqual(sorted(root.rglob("*.lock")), [])


class EdgesTest(unittest.TestCase):  # P61-AC-029, SI-P61-4, SI-P61-5, SI-P61-7, SI-P61-8
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name).resolve()

    def tearDown(self):
        self._tmp.cleanup()

    def test_no_modsys_here_is_one_setup_item(self):  # (a), SI-P61-8
        empty = self.tmp / "empty"
        empty.mkdir()
        data = nxt(empty)
        self.assertEqual((rows(data), data["skipped"]),
                         ([("setup", NOT_SET_UP, "modsys setup")], []))
        self.assertEqual(run("next", "--root", str(empty)), (0, text_of(data), ""))
        self.assertEqual(list(empty.iterdir()), [])
        git_repo = self.tmp / "code"
        write(git_repo / "src/app.py", "x = 1\n")
        init_git(git_repo)
        cwd = os.getcwd()
        try:
            for where in (empty, git_repo / "src"):  # no --root: no marker, or a git root
                os.chdir(where)
                with self.subTest(where=where.name):
                    code, env, err = run_json("next")
                    self.assertEqual((code, err), (0, ""))
                    self.assertEqual(rows(env["data"]), [("setup", NOT_SET_UP, "modsys setup")])
        finally:
            os.chdir(cwd)

    def test_outside_git_drift_and_unmapped_are_skipped(self):  # (b)
        root = copy_fixture(self.tmp)
        write(root / ".modsys/config.toml", '[[code_map]]\nid = "c"\nmodule = "catalog"\n'
                                            'globs = ["src/catalog/**"]\n')
        reason = f"{root} is not inside a work tree"
        for argv, drift in (((), "drift: no --base"), (("--base", "HEAD"), f"drift: {reason}")):
            with self.subTest(argv=argv):
                data = nxt(root, *argv)
                self.assertEqual(data["skipped"][-2:], [f"unmapped: {reason}", drift])
                self.assertEqual([i["summary"] for i in data["items"]],  # the others still run
                                 ["qa: no doc in 2 module(s)", "po: no doc in 3 module(s)",
                                  "architect: no doc in 3 module(s)"])

    def test_no_code_map_no_unmapped_item(self):  # (c)
        root = copy_fixture(self.tmp)
        write(root / "src/misc/tool.py", "x = 1\n")
        init_git(root)
        data = nxt(root)
        self.assertNotIn("unmapped", [i["kind"] for i in data["items"]])
        self.assertIn("unmapped: no [[code_map]] rule", data["skipped"])
        self.assertEqual(json.loads(run("coverage", "--json", "--root", str(root))[1])
                         ["data"]["unmapped"], ["src/misc/tool.py"])

    def test_a_missing_role_doc_points_at_roles_add_recreate(self):  # (d), SI-P61-7
        root = copy_fixture(self.tmp)
        (root / "modules/checkout/roles/developer.md").unlink()
        (root / "modules/payments/submodules/refunds/roles/developer.md").unlink()
        mutate_registry(root, lambda d: d["modules"]["catalog"]["context_files"]["roles"].update(
            qa=["modules/catalog/roles/qa.md", "modules/catalog/roles/qa-extra.md"]))
        (root / "modules/payments/MODULE.md").unlink()  # not a role doc: lint's own command
        errors = [i for i in nxt(root)["items"] if i["kind"] == "lint-error"]
        self.assertEqual([(i["summary"], i["command"]) for i in errors], [
            ("MS004 catalog: context_files.roles.qa[] path missing on disk "
             "(modules/catalog/roles/qa-extra.md)", "modsys roles add qa catalog --recreate"),
            ("MS004 checkout: context_files.roles.developer path missing on disk "
             "(modules/checkout/roles/developer.md)",
             "modsys roles add developer checkout --recreate"),
            ("MS004 payments: context_files.universal path missing on disk "
             "(modules/payments/MODULE.md)", "modsys lint"),
            ("MS004 payments/refunds: submodules.refunds.context_files.roles.developer path "
             "missing on disk (modules/payments/submodules/refunds/roles/developer.md)",
             "modsys roles add developer payments/refunds --recreate")])
        code, _, err = run("roles", "add", "developer", "checkout", "--recreate",
                           "--root", str(root))
        self.assertEqual((code, err), (0, ""))
        self.assertNotIn("MS004 checkout", " ".join(i["summary"] for i in nxt(root)["items"]))

    def test_skills_agents_resolved_as_a_bare_packs_sync(self):  # SI-P61-5
        root = copy_fixture(self.tmp)
        R = ("--root", str(root))
        data = nxt(root)  # no [packs] agents, no copy yet
        self.assertIn("skills: no agent to check: [packs] agents is not set and no agent's "
                      "skill directory holds a copy packs sync made", data["skipped"])
        write(root / ".modsys/packs/team/pack.toml", TEAM_PACK)
        for name in ("team-review", "team-notes"):
            write(root / f".modsys/packs/team/skills/{name}/SKILL.md", skill_md(name))
        must("packs", "sync", "--agent", "claude", "--agent", "codex", *R)
        self.assertEqual([i for i in nxt(root)["items"] if i["kind"] == "skills"], [])
        append(root / ".modsys/packs/team/skills/team-review/SKILL.md", "More.\n")
        write(root / ".modsys/packs/team/skills/team-extra/SKILL.md", skill_md("team-extra"))
        append(root / ".modsys/packs/team/pack.toml",
               '\n[skills.team-extra]\npath = "skills/team-extra"\n')
        (root / ".claude/skills/team-notes/SKILL.md").write_text("edited\n", encoding="utf-8")
        skills = [i for i in nxt(root)["items"] if i["kind"] == "skills"]
        self.assertEqual(rows({"items": skills}), [
            ("skills", "skill copies not in sync (claude, codex): stale team-review; missing "
                       "team-extra; in conflict team-notes", "modsys packs sync")])
        self.assertEqual(run("packs", "sync", "--check", *R)[0], 1)  # the same verdict

    def test_plugin_delivery_follows_packs_sync_check(self):  # SI-P61-5 (P6-AC-001/002)
        root = copy_fixture(self.tmp)
        write(root / ".modsys/config.toml", CORE_CONFIG)
        must("packs", "sync", "--root", str(root))
        self.assertEqual([i for i in nxt(root)["items"] if i["kind"] == "skills"], [])
        write(root / ".modsys/config.toml", CORE_CONFIG + 'builtin_delivery = "plugin"\n')
        skills = [i for i in nxt(root)["items"] if i["kind"] == "skills"]
        self.assertEqual(rows({"items": skills}), [
            ("skills", f"skill copies not in sync (claude): to remove {', '.join(CORE_SKILLS)}",
             "modsys packs sync")])
        must("packs", "sync", "--root", str(root))
        self.assertEqual([i for i in nxt(root)["items"] if i["kind"] == "skills"], [])

    def test_instruction_files_that_hold_a_block(self):  # SI-P61-4
        root = copy_fixture(self.tmp)
        R = ("--root", str(root))
        write(root / "AGENTS.md", "# Agents\n\nNo modsys block here.\n")
        for rel in ("GEMINI.md", ".github/copilot-instructions.md", "CLAUDE.md"):
            must("agents-md", "--target", rel, *R)
        self.assertEqual([i for i in nxt(root)["items"] if i["kind"] == "agents-md"], [])
        write(root / ".modsys/config.toml", "[roles.po]\nenabled = false\n")  # every block
        blocks = [i for i in nxt(root)["items"] if i["kind"] == "agents-md"]
        self.assertEqual([(i["summary"], i["command"]) for i in blocks], [
            ("CLAUDE.md: the modsys block is stale", "modsys agents-md --target CLAUDE.md"),
            ("GEMINI.md: the modsys block is stale", "modsys agents-md --target GEMINI.md"),
            (".github/copilot-instructions.md: the modsys block is stale",
             "modsys agents-md --target .github/copilot-instructions.md")])
        (root / "GEMINI.md").unlink()
        (root / "GEMINI.md").symlink_to("CLAUDE.md")  # the same file: one item
        text = (root / "CLAUDE.md").read_text(encoding="utf-8")
        write(root / ".github/copilot-instructions.md", text + "<!-- modsys:end -->\n")
        data = nxt(root)
        self.assertEqual([i["summary"] for i in data["items"] if i["kind"] == "agents-md"],
                         ["CLAUDE.md: the modsys block is stale"])
        self.assertTrue(any(s.startswith("agents-md: .github/copilot-instructions.md:")
                            and "a second end marker" in s for s in data["skipped"]),
                        data["skipped"])


class ContractTest(unittest.TestCase):  # P61-AC-026, P61-AC-037 (the `next` part)
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(Path(self._tmp.name).resolve())
        init_git(self.root)
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def test_the_verb_and_its_help(self):
        self.assertIn("next", build_parser()._subparsers._group_actions[0].choices)
        code, out, _ = run("next", "--help")
        self.assertEqual(code, 0)
        text = " ".join(out.split())
        for needle in ("--root", "--config-dir", "--json", "--base REF"):
            self.assertIn(needle, text)

    def test_one_json_document_per_run(self):
        for argv in (("next",), ("next", "--base", "HEAD")):
            with self.subTest(argv=argv):
                code, out, err = run(*argv, "--json", *self.R)
                self.assertEqual((code, err), (0, ""))
                env, end = json.JSONDecoder().raw_decode(out)
                self.assertEqual((out[end:].strip(), env["schema"]), ("", "modsys.next/1"))

    def test_refusals(self):
        for argv, needle in ((("--base", "nope"), "--base 'nope' is not a commit"),
                             (("--base=-x",), "may not start with '-'")):
            for extra in ((), ("--json",)):
                with self.subTest(argv=argv + extra):
                    code, out, err = run("next", *argv, *extra, *self.R)
                    self.assertEqual((code, out), (2, ""), err)
                    self.assertTrue(err.startswith("modsys: error: "), err)
                    self.assertIn(needle, err)
                    self.assertNotIn("Traceback", err)
        write(self.root / ".modsys/config.toml", "code_map = 5\n")  # a broken config
        code, out, err = run("next", "--json", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("modsys: error: "), err)

    def test_a_root_that_is_not_a_directory(self):  # final review M-1: as setup and init
        for root in (self.root / "nowhere", self.root / "modules/registry.json"):
            for extra in ((), ("--json",)):
                with self.subTest(root=root.name, extra=extra):
                    self.assertEqual(run("next", *extra, "--root", str(root)),
                                     (2, "", f"modsys: error: --root {root} is not a "
                                             f"directory\n"))
        self.assertFalse((self.root / "nowhere").exists())

    def test_an_internal_failure_and_ctrl_c(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("MODSYS_DEBUG", None)
            with mock.patch("modsys.next_cmd.lint_registry", side_effect=RuntimeError("boom")):
                code, out, err = run("next", "--json", *self.R)
            self.assertEqual((code, out), (2, ""))
            self.assertTrue(err.startswith("modsys: internal error: RuntimeError: boom"), err)
            self.assertNotIn("Traceback", err)
            with mock.patch("modsys.next_cmd.lint_registry", side_effect=KeyboardInterrupt):
                self.assertEqual(run("next", *self.R), (130, "", "modsys: interrupted\n"))
            os.environ["MODSYS_DEBUG"] = "1"
            with mock.patch("modsys.next_cmd.lint_registry", side_effect=RuntimeError("boom")), \
                    self.assertRaises(RuntimeError):
                run("next", *self.R)


if __name__ == "__main__":
    unittest.main()
