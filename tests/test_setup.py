"""`modsys setup [--agent A]… [--target FILE]… [--dry-run]` (P6.1 W5, D5, SI-P61-13): the
one-command start — bare `init`, `packs sync` for the chosen agents and `agents-md` for the
chosen instruction files, run in-process, idempotently, each step reporting its status."""
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import modsys
from modsys.agents_md_cmd import render_block
from modsys.cli import build_parser
from modsys.init_cmd import starter_config
from modsys.output import UsageError
from modsys.workspace import Workspace
from tests.helpers import copy_fixture, init_git, run

VERSION = modsys.__version__
STEPS = ["init", "packs sync", "agents-md"]
CORE_SKILLS = ["module-adopt", "module-create", "module-discover", "module-init", "module-lint",
               "module-research", "module-scout", "module-split", "module-sync"]
EMPTY_REGISTRY = '{\n  "modules": {}\n}\n'
IGNORE_LINES = ["modules/registry.json.lock", ".modsys/proposals/", ".modsys/init/"]
COPILOT = ("  note: GitHub Copilot reads both .claude/skills and .agents/skills, so it sees each "
           "skill twice — where Copilot works, sync only one of the two directories (Copilot "
           "reads either)")
BEGIN, END = "<!-- modsys:begin v1 -->", "<!-- modsys:end -->"
TEAM_NOTES = "# Team notes\n\nRun the tests before a commit.\n"
TEAM_PACK = ('id = "team"\nversion = "1.0.0"\ndescription = "Team skills"\n\n'
             '[skills.team-review]\npath = "skills/team-review"\n')
TEAM_SKILL = ("---\nname: team-review\ndescription: Review a change the way the team does.\n"
              "---\n\n# team-review\n\nBody.\n")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def snap(root: Path) -> dict:
    """Every file, directory and symlink below `root` by content and mode (a symlink by its
    link text), outside git's own `.git/` directory — the tree's content hash."""
    out = {}
    for path in sorted(root.rglob("*")):
        rel, st = path.relative_to(root).as_posix(), path.lstat()
        if rel == ".git" or rel.startswith(".git/"):
            continue
        if stat.S_ISLNK(st.st_mode):
            out[rel] = ("symlink", os.readlink(path))
        elif stat.S_ISDIR(st.st_mode):
            out[rel + "/"] = (stat.S_IMODE(st.st_mode), b"")
        else:
            out[rel] = (stat.S_IMODE(st.st_mode), path.read_bytes())
    return out


def empty_repo(tmp: Path, name: str = "repo") -> Path:
    """An empty git repository: one commit (a README), no `.modsys/`, no `modules/`."""
    root = tmp / name
    write(root / "README.md", "# Bookshop\n")
    init_git(root)
    return root


def must(*argv) -> str:
    code, out, err = run(*argv)
    assert (code, err) == (0, ""), (argv, code, out, err)
    return out


def setup_json(root: Path, *argv, code: int = 0) -> dict:
    """`modsys setup … --json`: the exit code, nothing on stderr, one `modsys.setup/1`
    document with the step rows in order; its data."""
    got, out, err = run("setup", *argv, "--json", "--root", str(root))
    assert (got, err) == (code, ""), (got, out, err)
    env, end = json.JSONDecoder().raw_decode(out)
    assert out[end:].strip() == "" and set(env) == {"schema", "data"}, out
    assert env["schema"] == "modsys.setup/1", env
    assert list(env["data"]) == ["dry_run", "agents", "targets", "steps"], env
    assert [s["step"] for s in env["data"]["steps"]] == STEPS, env
    for step in env["data"]["steps"]:
        assert list(step) == ["step", "status", "detail"], step
    return env["data"]


def statuses(data: dict) -> list[str]:
    return [s["status"] for s in data["steps"]]


def detail(data: dict, step: str):
    return next(s["detail"] for s in data["steps"] if s["step"] == step)


def block(root: Path) -> str:
    return "\n".join(render_block(Workspace.load(root))) + "\n"


def no_dry_run(d: dict) -> dict:
    return {k: v for k, v in d.items() if k != "dry_run"}


class EmptyRepositoryTest(unittest.TestCase):  # P61-AC-016, P61-AC-017, P61-AC-019
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name).resolve()
        self.root = empty_repo(self.tmp)
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def test_three_steps_write_what_the_three_verbs_write(self):  # P61-AC-016
        data = setup_json(self.root, "--agent", "claude", "--agent", "codex")
        self.assertEqual((data["dry_run"], data["agents"], data["targets"]),
                         (False, ["claude", "codex"], ["CLAUDE.md", "AGENTS.md"]))
        self.assertEqual(statuses(data), ["created", "created", "created"])
        root = self.root
        self.assertEqual((root / ".modsys/config.toml").read_text(encoding="utf-8"),
                         starter_config("single"))
        self.assertEqual((root / "modules/registry.json").read_text(encoding="utf-8"),
                         EMPTY_REGISTRY)
        self.assertEqual((root / ".gitignore").read_text(encoding="utf-8").splitlines(),
                         IGNORE_LINES)
        for agent_dir in (".claude/skills", ".agents/skills"):  # the core pack (P6-AC-001)
            self.assertEqual(sorted(p.name for p in (root / agent_dir).iterdir()), CORE_SKILLS)
            for skill in CORE_SKILLS:
                self.assertTrue((root / agent_dir / skill / ".modsys-managed").is_file())
        for target in ("CLAUDE.md", "AGENTS.md"):
            self.assertEqual((root / target).read_text(encoding="utf-8"), block(root))
        # every byte is what the three verbs write when run by hand, and so is every row
        twin = empty_repo(self.tmp, "twin")
        T = ("--root", str(twin))
        init = json.loads(must("init", "--json", *T))["data"]
        synced = json.loads(must("packs", "sync", "--agent", "claude", "--agent", "codex",
                                 "--json", *T))["data"]
        written = json.loads(must("agents-md", "--target", "CLAUDE.md", "--target", "AGENTS.md",
                                  "--json", *T))["data"]
        self.assertEqual(snap(root), snap(twin))
        self.assertEqual(detail(data, "init"), {**init, "root": str(root)})
        self.assertEqual((detail(data, "packs sync"), detail(data, "agents-md")),
                         (synced, written))
        self.assertEqual(run("lint", *self.R)[0], 0)
        self.assertEqual(run("next", *self.R), (0, f"modsys {VERSION}\nnothing to do\n", ""))

    def test_the_text_of_a_first_and_a_second_run(self):  # P61-AC-016, P61-AC-017
        flags = ("--agent", "claude", "--agent", "codex")
        self.assertEqual(run("setup", *flags, *self.R), (0, "\n".join([
            "init        created      .modsys/config.toml, modules/registry.json, .gitignore",
            "packs sync  created      18 skill copies",
            COPILOT,
            "agents-md   created      CLAUDE.md, AGENTS.md",
            "agents      claude, codex",
            "targets     CLAUDE.md, AGENTS.md"]) + "\n", ""))
        before = snap(self.root)
        self.assertEqual(run("setup", *flags, *self.R), (0, "\n".join([
            "init        exists       .modsys/config.toml, modules/registry.json, .gitignore",
            "packs sync  unchanged    18 skill copies",
            COPILOT,
            "agents-md   unchanged    CLAUDE.md, AGENTS.md",
            "agents      claude, codex",
            "targets     CLAUDE.md, AGENTS.md"]) + "\n", ""))
        self.assertEqual(snap(self.root), before)

    def test_a_second_run_writes_nothing(self):  # P61-AC-017
        setup_json(self.root, "--agent", "claude", "--agent", "codex")
        before = snap(self.root)
        mtimes = {p: p.lstat().st_mtime_ns for p in self.root.rglob("*") if ".git" not in p.parts}
        for argv in (("--agent", "claude", "--agent", "codex"), ()):  # bare: inferred again
            with self.subTest(argv=argv):
                data = setup_json(self.root, *argv)
                self.assertEqual(statuses(data), ["exists", "unchanged", "unchanged"])
                self.assertEqual((data["agents"], data["targets"]),
                                 (["claude", "codex"], ["CLAUDE.md", "AGENTS.md"]))
                self.assertEqual({f["status"] for f in detail(data, "init")["files"]},
                                 {"exists"})  # bare init ran and found everything
                self.assertEqual({r["status"] for r in detail(data, "packs sync")["skills"]},
                                 {"unchanged"})
                self.assertEqual(snap(self.root), before)
        self.assertEqual({p: p.lstat().st_mtime_ns for p in mtimes}, mtimes)

    def test_dry_run_writes_nothing(self):  # P61-AC-019
        before = snap(self.root)
        scratch = self.tmp / "scratch"
        scratch.mkdir()
        with mock.patch("tempfile.tempdir", str(scratch)):
            data = setup_json(self.root, "--dry-run")
        self.assertEqual(list(scratch.iterdir()), [])  # the planning dir is gone again
        self.assertEqual((data["dry_run"], data["agents"], data["targets"]),
                         (True, ["claude", "codex"], ["CLAUDE.md", "AGENTS.md"]))
        self.assertEqual(statuses(data), ["created", "created", "created"])
        self.assertEqual(snap(self.root), before)
        self.assertEqual(run("setup", "--dry-run", *self.R), (0, "\n".join([
            "init        would create .modsys/config.toml, modules/registry.json, .gitignore",
            "packs sync  would create 18 skill copies",
            COPILOT,
            "agents-md   would create CLAUDE.md, AGENTS.md",
            "agents      claude, codex",
            "targets     CLAUDE.md, AGENTS.md",
            "dry run: nothing written"]) + "\n", ""))
        self.assertEqual(snap(self.root), before)
        real = setup_json(self.root)  # what the dry run said is what the run does
        self.assertEqual(statuses(real), statuses(data))
        for step in STEPS:
            self.assertEqual(no_dry_run(detail(real, step)), no_dry_run(detail(data, step)))


class PlanningTest(unittest.TestCase):  # P61-AC-019: a dry run reads the config init would write
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(Path(self._tmp.name).resolve())  # .modsys/packs, no config
        write(self.root / ".modsys/packs/team/pack.toml", TEAM_PACK)
        write(self.root / ".modsys/packs/team/skills/team-review/SKILL.md", TEAM_SKILL)

    def tearDown(self):
        self._tmp.cleanup()

    def test_the_planned_rows_are_the_rows_of_the_run(self):
        before = snap(self.root)
        dry = setup_json(self.root, "--dry-run")
        with mock.patch.object(Path, "symlink_to", side_effect=OSError("no symlinks here")):
            copied = setup_json(self.root, "--dry-run")  # the planning dir copies instead
        self.assertEqual(copied, dry)
        self.assertEqual(snap(self.root), before)
        skills = sorted({r["skill"] for r in detail(dry, "packs sync")["skills"]})
        self.assertEqual(skills, sorted(CORE_SKILLS + ["team-review"]))
        self.assertEqual([f["status"] for f in detail(dry, "init")["files"]],
                         ["created", "exists", "created"])
        real = setup_json(self.root)
        self.assertEqual(statuses(real), statuses(dry))
        for step in STEPS:
            self.assertEqual(no_dry_run(detail(real, step)), no_dry_run(detail(dry, step)))
        self.assertIn("`team-review` — Review a change the way the team does.",
                      (self.root / "CLAUDE.md").read_text(encoding="utf-8"))


    def test_a_dry_run_shows_the_real_config_paths(self):
        write(self.root / ".modsys/overrides/skills/notes/SKILL.md",  # no .modsys-ejected
              "---\nname: notes\ndescription: Notes.\n---\n\n# notes\n")
        reason = ("the ejected copy .modsys/overrides/skills/notes has no valid .modsys-ejected "
                  "record")
        dry = setup_json(self.root, "--agent", "claude", "--dry-run", code=1)
        real = setup_json(self.root, "--agent", "claude", code=1)
        for data in (dry, real):
            self.assertEqual(statuses(data)[1], "invalid")
            rows = {r["skill"]: r for r in detail(data, "packs sync")["skills"]}
            self.assertEqual((rows["notes"]["status"], rows["notes"]["reason"]),
                             ("invalid", reason))


class OrderTest(unittest.TestCase):  # P61-AC-018 (D5, SI-P61-13)
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name).resolve()

    def tearDown(self):
        self._tmp.cleanup()

    def repo(self, name: str, config: str | None = None, synced: tuple = (),
             drop_config: bool = False) -> Path:
        """An empty repository; `config` as its config.toml; `synced`: the agents whose skill
        directory gets the copies of an earlier `packs sync`; `drop_config` removes the
        config afterwards (the markers stay)."""
        root = empty_repo(self.tmp, name)
        if config is not None:
            write(root / ".modsys/config.toml", config)
        if synced:
            must("packs", "sync", *(f for a in synced for f in ("--agent", a)), "--root",
                 str(root))
        if drop_config:
            (root / ".modsys/config.toml").unlink()
        return root

    def test_the_decision_table(self):
        core = '[packs]\nbuiltin = ["core"]\n'
        claude = core + 'agents = ["claude"]\n'
        table = [  # rule, flags, repository, agents used, default targets
            (1, ("--agent", "cursor"), self.repo("r1", claude, ("claude",)),
             ["cursor"], ["AGENTS.md"]),
            (2, (), self.repo("r2", claude, ("codex",)), ["claude"], ["CLAUDE.md"]),
            (3, (), self.repo("r3", core, ("codex",), drop_config=True), ["codex"],
             ["AGENTS.md"]),
            (4, (), self.repo("r4"), ["claude", "codex"], ["CLAUDE.md", "AGENTS.md"]),
            (5, ("--agent", "claude", "--target", "GEMINI.md"), self.repo("r5"), ["claude"],
             ["GEMINI.md"]),
        ]
        for rule, flags, root, agents, targets in table:
            with self.subTest(rule=rule):
                before = snap(root)
                data = setup_json(root, *flags, "--dry-run")
                self.assertEqual((data["agents"], data["targets"]), (agents, targets))
                self.assertEqual(detail(data, "packs sync")["agents"], agents)
                self.assertEqual([t["path"] for t in detail(data, "agents-md")["targets"]],
                                 targets)
                self.assertEqual(snap(root), before)
                out = run("setup", *flags, "--dry-run", "--root", str(root))[1].splitlines()
                self.assertIn(f"agents      {', '.join(agents)}", out)
                self.assertIn(f"targets     {', '.join(targets)}", out)
        rule3 = setup_json(table[2][2], "--dry-run")  # planned against the starter config
        self.assertEqual(statuses(rule3), ["created", "unchanged", "created"])

    def test_a_skill_directory_without_a_marker_infers_nothing(self):
        root = self.repo("hand")
        write(root / ".agents/skills/notes/SKILL.md", TEAM_SKILL)
        data = setup_json(root, "--dry-run")
        self.assertEqual((data["agents"], data["targets"]),
                         (["claude", "codex"], ["CLAUDE.md", "AGENTS.md"]))

    def test_gemini_is_named_in_the_help(self):  # SI-P61-13
        code, out, _ = run("setup", "--help")
        self.assertEqual(code, 0)
        self.assertIn("--target GEMINI.md", " ".join(out.split()))


class TeamFilesTest(unittest.TestCase):  # P61-AC-030
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = empty_repo(Path(self._tmp.name).resolve())
        write(self.root / "CLAUDE.md", TEAM_NOTES)
        write(self.root / ".claude/skills/module-sync/SKILL.md", "# our own sync notes\n")
        self.hand = snap(self.root / ".claude/skills/module-sync")

    def tearDown(self):
        self._tmp.cleanup()

    def test_the_block_is_added_and_the_hand_written_skill_kept(self):
        data = setup_json(self.root, "--agent", "claude", code=1)
        self.assertEqual(statuses(data), ["created", "conflict", "updated"])
        rows = {r["skill"]: r for r in detail(data, "packs sync")["skills"]}
        self.assertEqual((rows["module-sync"]["status"], rows["module-sync"]["reason"]),
                         ("conflict", "not managed by modsys (no .modsys-managed)"))
        self.assertEqual({r["status"] for s, r in rows.items() if s != "module-sync"},
                         {"created"})
        self.assertEqual(detail(data, "agents-md")["targets"],
                         [{"path": "CLAUDE.md", "status": "added"}])
        self.assertEqual((self.root / "CLAUDE.md").read_text(encoding="utf-8"),
                         TEAM_NOTES + "\n" + block(self.root))
        self.assertEqual(snap(self.root / ".claude/skills/module-sync"), self.hand)

    def test_the_text_names_the_step(self):
        code, out, err = run("setup", "--agent", "claude", "--root", str(self.root))
        self.assertEqual((code, err), (1, ""))
        self.assertEqual(out, "\n".join([
            "init        created      .modsys/config.toml, modules/registry.json, .gitignore",
            "packs sync  conflict     9 skill copies (8 created, 1 conflict)",
            "  conflict  claude  .claude/skills/module-sync",
            "    not managed by modsys (no .modsys-managed) — a skill written by hand: move or "
            "rename it, then sync again",
            "agents-md   updated      CLAUDE.md (added)",
            "agents      claude",
            "targets     CLAUDE.md",
            "setup: packs sync left 1 skill copy unwritten — resolve it as shown above, then "
            "run modsys setup again"]) + "\n")
        code, out, err = run("setup", "--agent", "claude", "--root", str(self.root))
        self.assertEqual((code, err), (1, ""))
        self.assertEqual(out.splitlines()[:2], [
            "init        exists       .modsys/config.toml, modules/registry.json, .gitignore",
            "packs sync  conflict     9 skill copies (8 unchanged, 1 conflict)"])
        self.assertIn("agents-md   unchanged    CLAUDE.md", out.splitlines())
        self.assertEqual(snap(self.root / ".claude/skills/module-sync"), self.hand)


class ExistingConfigTest(unittest.TestCase):  # fix round 1, finding 1: bare init always runs
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = empty_repo(Path(self._tmp.name).resolve())
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_config_without_a_registry_gets_one(self):
        config = '[packs]\nbuiltin = ["core"]\nagents = ["claude"]\n'
        write(self.root / ".modsys/config.toml", config)
        dry = setup_json(self.root, "--dry-run")
        self.assertEqual(statuses(dry), ["created", "created", "created"])
        self.assertEqual(detail(dry, "init")["files"], [
            {"path": ".modsys/config.toml", "status": "exists"},
            {"path": "modules/registry.json", "status": "created"},
            {"path": ".gitignore", "status": "created"}])
        self.assertFalse((self.root / "modules").exists())
        code, out, err = run("setup", *self.R)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.splitlines()[0], "init        created      .modsys/config.toml "
                                              "(exists), modules/registry.json, .gitignore")
        self.assertEqual((self.root / ".modsys/config.toml").read_text(encoding="utf-8"),
                         config)
        self.assertEqual((self.root / "modules/registry.json").read_text(encoding="utf-8"),
                         EMPTY_REGISTRY)
        self.assertEqual((self.root / ".gitignore").read_text(encoding="utf-8").splitlines(),
                         IGNORE_LINES)
        self.assertEqual(run("lint", *self.R)[0], 0)
        self.assertEqual(run("next", *self.R), (0, f"modsys {VERSION}\nnothing to do\n", ""))
        before = snap(self.root)
        self.assertEqual(statuses(setup_json(self.root)), ["exists", "unchanged", "unchanged"])
        self.assertEqual(snap(self.root), before)

    def test_only_gitignore_lines_appended_is_updated(self):
        write(self.root / ".modsys/config.toml", '[packs]\nbuiltin = ["core"]\n')
        write(self.root / "modules/registry.json", EMPTY_REGISTRY)
        write(self.root / ".gitignore", "node_modules/\n")
        data = setup_json(self.root, "--agent", "claude")
        self.assertEqual(statuses(data)[0], "updated")
        self.assertEqual([f["status"] for f in detail(data, "init")["files"]],
                         ["exists", "exists", "updated"])
        self.assertEqual((self.root / ".gitignore").read_text(encoding="utf-8").splitlines(),
                         ["node_modules/"] + IGNORE_LINES)
        code, out, _ = run("setup", "--agent", "claude", *self.R)
        self.assertEqual(out.splitlines()[0], "init        exists       .modsys/config.toml, "
                                              "modules/registry.json, .gitignore")

    def test_a_broken_config_stops_setup_at_init(self):
        for text in ("[packs\n", "code_map = 5\n"):  # not TOML; TOML the config refuses
            with self.subTest(text=text):
                write(self.root / ".modsys/config.toml", text)
                before = snap(self.root)
                for extra in ((), ("--json",), ("--dry-run",)):
                    code, out, err = run("setup", *extra, *self.R)
                    self.assertEqual((code, out), (2, ""))
                    self.assertTrue(err.startswith("modsys: error: setup stopped at init: "), err)
                    self.assertEqual(len(err.splitlines()), 1, err)
                    self.assertNotIn("before it", err)
                    self.assertEqual(snap(self.root), before)


class NothingToCopyTest(unittest.TestCase):  # D5: `skipped` — packs sync has no skill to copy
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = empty_repo(Path(self._tmp.name).resolve())
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def test_the_plugins_provide_the_built_in_skills(self):
        write(self.root / ".modsys/config.toml",
              '[packs]\nbuiltin = ["core"]\nbuiltin_delivery = "plugin"\n')
        code, out, err = run("setup", "--agent", "claude", *self.R)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.splitlines()[:3], [
            "init        created      .modsys/config.toml (exists), modules/registry.json, "
            ".gitignore",
            "packs sync  skipped      nothing to copy",
            '  note: builtin_delivery = "plugin": the built-in skills come from the plugins '
            "modsys (core) — packs sync copies none of them"])
        self.assertFalse((self.root / ".claude").exists())
        before = snap(self.root)
        self.assertEqual(statuses(setup_json(self.root, "--agent", "claude")),
                         ["exists", "skipped", "unchanged"])
        self.assertEqual(snap(self.root), before)

    def test_no_pack_skills(self):
        write(self.root / ".modsys/config.toml", "[packs]\nbuiltin = []\n")
        code, out, err = run("setup", "--agent", "codex", *self.R)
        self.assertEqual((code, err), (0, ""))
        self.assertIn("packs sync  skipped      no pack skills (add one: modsys packs new ID "
                      "--skill NAME)", out.splitlines())


class StopTest(unittest.TestCase):  # P61-AC-035, D5 (a refusal stops setup and names the step)
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = empty_repo(Path(self._tmp.name).resolve())
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_malformed_block_stops_setup_at_agents_md(self):
        broken = f"# Team notes\n\n{BEGIN}\nold text\n"
        write(self.root / "CLAUDE.md", broken)
        error = (f"modsys: error: setup stopped at agents-md: CLAUDE.md:3: a begin marker "
                 f"without an end marker ({END}) — fix the markers by hand; nothing written "
                 f"(before it: init created, packs sync created)\n")
        self.assertEqual(run("setup", "--agent", "claude", *self.R), (2, "", error))
        self.assertTrue((self.root / ".modsys/config.toml").is_file())  # the first two ran
        self.assertTrue((self.root / "modules/registry.json").is_file())
        self.assertEqual(sorted(p.name for p in (self.root / ".claude/skills").iterdir()),
                         CORE_SKILLS)
        self.assertEqual((self.root / "CLAUDE.md").read_text(encoding="utf-8"), broken)
        before = snap(self.root)
        error = error.replace("init created, packs sync created", "init exists, packs sync "
                                                                  "unchanged")
        self.assertEqual(run("setup", "--agent", "claude", "--json", *self.R), (2, "", error))
        self.assertEqual(snap(self.root), before)
        dry = error.replace("nothing written (before it:", "nothing written (dry run: nothing "
                                                           "written; before it:")
        self.assertEqual(run("setup", "--agent", "claude", "--dry-run", *self.R), (2, "", dry))
        self.assertEqual(snap(self.root), before)
        write(self.root / "CLAUDE.md", broken + END + "\n")  # fixed by hand
        data = setup_json(self.root, "--agent", "claude")
        self.assertEqual(statuses(data), ["exists", "unchanged", "updated"])
        self.assertEqual((self.root / "CLAUDE.md").read_text(encoding="utf-8"),
                         "# Team notes\n\n" + block(self.root))

    def test_a_refused_init_runs_no_later_step(self):
        write(self.root / ".modsys", "not a directory\n")
        before = snap(self.root)
        code, out, err = run("setup", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("modsys: error: setup stopped at init: cannot write "
                                       ".modsys/config.toml: "), err)
        self.assertEqual(len(err.splitlines()), 1)
        self.assertEqual(snap(self.root), before)

    def test_a_refused_packs_sync_runs_no_agents_md(self):
        with mock.patch("modsys.setup_cmd.packs_sync",
                        side_effect=UsageError("cannot read .claude/skills/x: denied")):
            code, out, err = run("setup", "--json", *self.R)
        self.assertEqual((code, out, err), (2, "", "modsys: error: setup stopped at packs sync: "
                                                   "cannot read .claude/skills/x: denied "
                                                   "(before it: init created)\n"))
        self.assertTrue((self.root / ".modsys/config.toml").is_file())
        self.assertFalse((self.root / "CLAUDE.md").exists())


class ContractTest(unittest.TestCase):  # P61-AC-026, P61-AC-037 (the `setup` part)
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name).resolve()
        self.root = empty_repo(self.tmp)
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def test_the_verb_and_its_help(self):
        self.assertIn("setup", build_parser()._subparsers._group_actions[0].choices)
        code, out, _ = run("setup", "--help")
        self.assertEqual(code, 0)
        text = " ".join(out.split())
        for needle in ("--root", "--config-dir", "--json", "--agent", "--target FILE",
                       "--dry-run", "--target GEMINI.md"):
            self.assertIn(needle, text)

    def test_refusals_write_nothing(self):
        write(self.root / "docs/guide.md", "# Guide\n")
        before = snap(self.root)
        outside = self.tmp / "outside.md"
        cases = ((("--agent", "nobody"), "modsys: error: unknown agent 'nobody' (agents: "
                                         "claude, codex, cursor, gemini, copilot)\n"),
                 (("--target", str(outside)), f"modsys: error: --target {outside}: outside the "
                                              f"repository root {self.root}\n"),
                 (("--target", "docs"), "modsys: error: --target docs is a directory, not an "
                                        "instruction file\n"))
        for argv, error in cases:
            for extra in ((), ("--json",), ("--dry-run",)):
                with self.subTest(argv=argv + extra):
                    self.assertEqual(run("setup", *argv, *extra, *self.R), (2, "", error))
                    self.assertEqual(snap(self.root), before)
        code, out, err = run("setup", "--root", str(self.root / "README.md"))
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("modsys: error: --root "), err)

    def test_a_config_dir_elsewhere(self):
        C = ("--config-dir", str(self.root / "tools/modsys"))
        data = setup_json(self.root, "--agent", "claude", *C)
        self.assertEqual(statuses(data), ["created", "created", "created"])
        self.assertEqual((self.root / "tools/modsys/config.toml").read_text(encoding="utf-8"),
                         starter_config("single"))
        self.assertIn("tools/modsys/init/",
                      (self.root / ".gitignore").read_text(encoding="utf-8").splitlines())
        self.assertFalse((self.root / ".modsys").exists())
        before = snap(self.root)
        self.assertEqual(statuses(setup_json(self.root, "--agent", "claude", *C)),
                         ["exists", "unchanged", "unchanged"])
        self.assertEqual(snap(self.root), before)

    def test_the_root_defaults_to_the_git_top_level(self):
        sub = self.root / "src"
        sub.mkdir()
        cwd = os.getcwd()
        try:
            os.chdir(sub)
            code, out, err = run("setup", "--agent", "codex", "--json")
        finally:
            os.chdir(cwd)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out)["data"]["targets"], ["AGENTS.md"])
        self.assertTrue((self.root / ".modsys/config.toml").is_file())
        self.assertTrue((self.root / "AGENTS.md").is_file())
        self.assertEqual(list(sub.iterdir()), [])

    def test_a_nested_root_is_found_again(self):  # fix round 1, finding 2
        write(self.root / "CLAUDE.md", TEAM_NOTES)  # the top level's own, not modsys's
        shop = self.root / "shop"
        write(shop / "src/catalog.py", "BOOKS = []\n")
        setup_json(shop, "--agent", "claude")  # --root shop
        self.assertTrue((shop / ".modsys/config.toml").is_file())
        before = snap(self.root)
        cwd = os.getcwd()
        try:
            for where in (shop, shop / "src"):
                os.chdir(where)
                for argv in (("--agent", "claude"), ()):
                    with self.subTest(where=where.name, argv=argv):
                        code, out, err = run("setup", *argv, "--json")
                        self.assertEqual((code, err), (0, ""))
                        data = json.loads(out)["data"]
                        self.assertEqual(statuses(data), ["exists", "unchanged", "unchanged"])
                        self.assertEqual(detail(data, "init")["root"], str(shop))
                        self.assertEqual(snap(self.root), before)
                self.assertEqual(run("next"), (0, f"modsys {VERSION}\nnothing to do\n", ""))
        finally:
            os.chdir(cwd)
        self.assertEqual((self.root / "CLAUDE.md").read_text(encoding="utf-8"), TEAM_NOTES)
        self.assertFalse((self.root / ".modsys").exists())

    def test_an_internal_failure_and_ctrl_c(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("MODSYS_DEBUG", None)
            with mock.patch("modsys.setup_cmd.agents_md", side_effect=RuntimeError("boom")):
                code, out, err = run("setup", "--json", *self.R)
            self.assertEqual((code, out), (2, ""))
            self.assertEqual(err, "modsys: internal error: RuntimeError: boom (set "
                                  "MODSYS_DEBUG=1 for a traceback)\n")
            with mock.patch("modsys.setup_cmd.packs_sync", side_effect=KeyboardInterrupt):
                self.assertEqual(run("setup", *self.R), (130, "", "modsys: interrupted\n"))
            os.environ["MODSYS_DEBUG"] = "1"
            with mock.patch("modsys.setup_cmd.agents_md", side_effect=RuntimeError("boom")), \
                    self.assertRaises(RuntimeError):
                run("setup", *self.R)


if __name__ == "__main__":
    unittest.main()
