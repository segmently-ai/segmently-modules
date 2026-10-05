"""P8.4 task 1, the delivery part (D3): `packs sync` and `setup` write the three agents of the
core pack's wrapped skills for Codex as `.codex/agents/<name>.toml` — managed files with a marker
line, `data.agent_files` rows, `--check`, removal and conflicts, only when `codex` is synced — the
stdlib TOML encoder that round-trips any procedure, and the docs (P84-AC-002, 006…010, 038)."""
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

import modsys
from modsys import skill_sync, skills
from modsys.config import builtin_packs_root
from tests.helpers import copy_fixture, init_git, run, run_json

V = modsys.__version__
ENGINE = Path(__file__).resolve().parents[1]
CORE = builtin_packs_root() / "core" / "skills"
CORE_N = len(list(CORE.glob("*/SKILL.md")))  # the core pack's skills, as shipped
NAMES = ["module-discover-agent", "module-research-agent", "module-scout-agent"]
SKILL_OF = {"module-discover-agent": "module-discover", "module-research-agent": "module-research",
            "module-scout-agent": "module-scout"}
WRAPPED = sorted(SKILL_OF.values())
FIVE = ("claude", "codex", "cursor", "gemini", "copilot")
KEYS = ["agent", "name", "path", "status", "pack", "skill", "version", "reason"]
DATA_KEYS = ["agents", "check", "dry_run", "skills", "agent_files", "summary", "failed", "notes"]
OLD_KEYS = ["agents", "check", "dry_run", "skills", "summary", "failed", "notes"]
COUNTS = "0 updated, 0 unchanged, 0 removed, 0 conflict"
NASTY = ('Quotes " and "" and """ and \'\'\' and \'\' inside; a backslash \\ and \\\\ and \\n '
         'and \\u0041; a line ending in a backslash \\\n\ttab, CRLF\r\nlone CR\r, NUL \x00, '
         'BEL \x07, ESC \x1b, DEL \x7f, \u2028, \U0001F4DA, \ufeff and a last quote "')


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def instructions(skill: str) -> str:  # P8.6 D1: the agent runs its skill; no skill text in it
    return (f"Run the `{skill}` skill on the task you are handed, verbatim, with what the caller "
            f"settled (files, constraints, the depth), and return its output unchanged: its "
            f"report, or the question it asks the user. Only when that skill is not available "
            f"to you, read `.agents/skills/{skill}/SKILL.md` and follow it.\n")


def marker(data: bytes) -> tuple[dict, bytes]:
    """The parsed first line of an agent file and the bytes after it."""
    line, _, rest = data.partition(b"\n")
    prefix = b"# modsys-managed: "
    assert line.startswith(prefix), line
    return json.loads(line[len(prefix):]), rest


def snap(root: Path) -> dict:
    """Every path below `root` (outside `.git/`) with its mode, bytes and mtime; a symlink by
    its link text — the tree hash a read-only run must keep."""
    out = {}
    for path in sorted(root.rglob("*")):
        rel, st = path.relative_to(root).as_posix(), path.lstat()
        if rel == ".git" or rel.startswith(".git/"):
            continue
        if stat.S_ISLNK(st.st_mode):
            out[rel] = ("link", os.readlink(path))
        elif stat.S_ISDIR(st.st_mode):
            out[rel + "/"] = (stat.S_IMODE(st.st_mode), st.st_mtime_ns)
        else:
            out[rel] = (stat.S_IMODE(st.st_mode), path.read_bytes(), st.st_mtime_ns)
    return out


class CodexRepo(unittest.TestCase):
    """The bookshop fixture with the built-in `core` pack enabled."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name).resolve()
        self.root = copy_fixture(self.tmp)
        self.R = ("--root", str(self.root))
        self.config('[packs]\nbuiltin = ["core"]\n')

    def tearDown(self):
        for path in (self.root / ".codex", self.root / ".codex/agents"):
            if path.is_dir() and not path.is_symlink():
                path.chmod(0o755)
        self._tmp.cleanup()

    def config(self, text: str) -> None:
        (self.root / ".modsys/config.toml").write_text(text, encoding="utf-8")

    def sync(self, *argv: str, agents=("codex",), code: int = 0) -> dict:
        flags = [a for agent in agents for a in ("--agent", agent)]
        got, env, err = run_json("packs", "sync", *flags, *argv, *self.R)
        self.assertEqual((got, err), (code, ""), env)
        self.assertEqual(set(env), {"schema", "data"})
        self.assertEqual(env["schema"], "modsys.packs/1")
        self.assertIs(env["data"]["failed"], code == 1)
        return env["data"]

    def text(self, *argv: str, agents=("codex",), code: int = 0) -> list[str]:
        flags = [a for agent in agents for a in ("--agent", agent)]
        got, out, err = run("packs", "sync", *flags, *argv, *self.R)
        self.assertEqual((got, err), (code, ""), out)
        return out.splitlines()

    def agent_file(self, name: str) -> Path:
        return self.root / ".codex/agents" / f"{name}.toml"

    def rows(self, data: dict) -> list[tuple]:
        return [(r["name"], r["status"]) for r in data["agent_files"]]

    def repo_core(self, version: str = "9.0.0", skills_: dict | None = None) -> Path:
        """A repository pack `core` (it replaces the built-in one) declaring `skills_` {skill:
        the text of an extra `references/procedure.md`, or None for none}; default: the three
        wrapped skills, no extra file. The agent files never read that file (P8.6 D1)."""
        pack = self.root / ".modsys/packs/core"
        shutil.rmtree(pack, ignore_errors=True)
        wanted = skills_ if skills_ is not None else {s: None for s in WRAPPED}
        text = f'id = "core"\nversion = "{version}"\n'
        for sid, proc in wanted.items():
            d = pack / "skills" / sid
            d.mkdir(parents=True)
            (d / "SKILL.md").write_bytes((CORE / sid / "SKILL.md").read_bytes())
            if proc is not None:
                (d / "references").mkdir()
                (d / "references/procedure.md").write_bytes(proc.encode("utf-8"))
            text += f'\n[skills.{sid}]\npath = "skills/{sid}"\n'
        (pack / "pack.toml").write_text(text, encoding="utf-8")
        return pack


class WrittenTest(CodexRepo):  # P84-AC-006
    def test_created_then_unchanged(self):
        self.assertFalse((self.root / ".codex").exists())
        data = self.sync()
        self.assertEqual(data["agent_files"], [
            {"agent": "codex", "name": n, "path": f".codex/agents/{n}.toml", "status": "created",
             "pack": "core", "skill": SKILL_OF[n], "version": V, "reason": None}
            for n in NAMES])
        for row in data["agent_files"]:
            self.assertEqual(list(row), KEYS)
        self.assertEqual(sorted(p.name for p in (self.root / ".codex/agents").iterdir()),
                         [f"{n}.toml" for n in NAMES])
        before = snap(self.root)
        again = self.sync()
        self.assertEqual(self.rows(again), [(n, "unchanged") for n in NAMES])
        self.assertEqual(snap(self.root), before)  # nothing written, mtimes kept

    def test_the_file_marker_and_toml(self):
        self.sync()
        for name in NAMES:
            with self.subTest(agent=name):
                data = self.agent_file(name).read_bytes()
                head, rest = marker(data)
                self.assertEqual(list(head), ["schema", "pack", "skill", "version", "sha256"])
                self.assertEqual(head, {"schema": "modsys.managed/1", "pack": "core",
                                        "skill": SKILL_OF[name], "version": V,
                                        "sha256": sha(rest)})
                self.assertEqual(data.split(b"\n", 1)[0].decode(),
                                 "# modsys-managed: " + json.dumps(head))
                doc = tomllib.loads(data.decode("utf-8"))
                self.assertEqual(sorted(doc), ["description", "developer_instructions", "name"])
                self.assertEqual(doc["name"], name)
                self.assertEqual(doc["description"], skills.SKILL_AGENTS[name]["description"])
                self.assertEqual(doc["developer_instructions"], instructions(SKILL_OF[name]))
                self.assertNotIn("## Steps", doc["developer_instructions"])  # no procedure text
                self.assertEqual(stat.S_IMODE(self.agent_file(name).stat().st_mode), 0o644)

    def test_the_exact_layout(self):  # an extra procedure file in the skill is never read
        self.repo_core(skills_={"module-scout": "Read the docs.\nReport.\n"})
        self.sync()
        rest = marker(self.agent_file("module-scout-agent").read_bytes())[1]
        description = skills.SKILL_AGENTS["module-scout-agent"]["description"]
        self.assertEqual(rest.decode("utf-8"), (
            f'name = "module-scout-agent"\ndescription = "{description}"\n'
            f'developer_instructions = """\n{instructions("module-scout")}"""\n'))

    def test_through_setup(self):
        repo = self.tmp / "fresh"
        (repo / "src").mkdir(parents=True)
        (repo / "README.md").write_text("# Bookshop\n", encoding="utf-8")
        init_git(repo)
        got, env, err = run_json("setup", "--agent", "codex", "--root", str(repo))
        self.assertEqual((got, err), (0, ""))
        step = env["data"]["steps"][1]
        self.assertEqual((step["step"], step["status"]), ("packs sync", "created"))
        self.assertEqual(list(step["detail"]), DATA_KEYS)
        self.assertEqual([(r["name"], r["status"]) for r in step["detail"]["agent_files"]],
                         [(n, "created") for n in NAMES])
        for name in NAMES:
            text = (repo / ".codex/agents" / f"{name}.toml").read_text(encoding="utf-8")
            self.assertEqual(tomllib.loads(text)["developer_instructions"],
                             instructions(SKILL_OF[name]))
        got, env, err = run_json("setup", "--agent", "codex", "--root", str(repo))
        self.assertEqual((got, err), (0, ""))
        self.assertEqual(env["data"]["steps"][1]["status"], "unchanged")

    def test_plugin_delivery_writes_the_same_three_files(self):
        self.config('[packs]\nbuiltin = ["core"]\nbuiltin_delivery = "plugin"\n')
        data = self.sync()
        self.assertEqual(data["skills"], [])
        self.assertEqual(self.rows(data), [(n, "created") for n in NAMES])
        self.assertFalse((self.root / ".agents").exists())
        for name in NAMES:
            doc = tomllib.loads(self.agent_file(name).read_text(encoding="utf-8"))
            self.assertEqual(doc["developer_instructions"], instructions(SKILL_OF[name]))
        lines = self.text()
        self.assertEqual(lines[:3], [f"unchanged  codex   .codex/agents/{n}.toml  (core {V})"
                                     for n in NAMES])
        self.assertFalse([line for line in lines if line.startswith("nothing to copy")])

    def test_an_ejected_and_edited_skill_keeps_its_agent_file(self):  # the agent runs the copy
        self.sync()
        before = self.agent_file("module-discover-agent").read_bytes()
        code, out, err = run("eject", "module-discover", *self.R)
        self.assertEqual((code, err), (0, ""))
        edited = self.root / ".modsys/overrides/skills/module-discover/SKILL.md"
        edited.write_bytes(edited.read_bytes() + b"\nTeam rule: name the ticket.\n")
        data = self.sync()
        self.assertEqual([r["status"] for r in data["skills"] if r["skill"] == "module-discover"],
                         ["updated"])
        self.assertEqual(self.rows(data), [(n, "unchanged") for n in NAMES])
        self.assertEqual(self.agent_file("module-discover-agent").read_bytes(), before)
        self.assertEqual(data["agent_files"][0]["pack"], "core")

    def test_a_skill_whose_source_is_invalid_keeps_its_agent_file(self):
        self.sync()
        before = self.agent_file("module-scout-agent").read_bytes()
        pack = self.repo_core()
        (pack / "skills/module-scout/SKILL.md").write_text("no front matter\n", encoding="utf-8")
        data = self.sync(code=1)
        self.assertEqual([r["status"] for r in data["skills"] if r["skill"] == "module-scout"],
                         ["invalid"])
        self.assertNotIn("module-scout-agent", [r["name"] for r in data["agent_files"]])
        self.assertEqual(self.agent_file("module-scout-agent").read_bytes(), before)

    def test_an_extra_file_that_is_not_utf8_is_never_read(self):
        pack = self.repo_core()
        (pack / "skills/module-scout/references").mkdir()
        (pack / "skills/module-scout/references/procedure.md").write_bytes(b"caf\xe9\n")
        self.assertEqual(self.rows(self.sync()), [(n, "created") for n in NAMES])


class EncoderTest(CodexRepo):  # the stdlib TOML encoder (brief: quotes, backslashes, ''' and """)
    CASES = ["", "\n", '"', '""', '"""', "'''", "\\", "\\\n", "a\r\nb", "\r", "\t\x00\x1f\x7f",
             "ends with a quote\"", "x\"\"\"\"y", NASTY, NASTY * 3]

    def test_every_string_round_trips(self):
        for text in self.CASES:
            for multiline in (False, True):
                with self.subTest(text=text, multiline=multiline):
                    doc = f"x = {skill_sync.toml_string(text, multiline=multiline)}\n"
                    self.assertEqual(tomllib.loads(doc), {"x": text})
                    if not multiline:
                        self.assertNotIn("\n", doc[:-1])

    def test_a_whole_agent_file_round_trips(self):
        for name, spec in skills.SKILL_AGENTS.items():
            with self.subTest(agent=name):
                data = skill_sync.codex_agent(name, "team", spec["skill"], "1.0.0")
                head, rest = marker(data)
                self.assertEqual(head["sha256"], sha(rest))
                self.assertEqual(tomllib.loads(data.decode("utf-8"))["developer_instructions"],
                                 instructions(spec["skill"]))


class LifecycleTest(CodexRepo):  # P84-AC-007
    def test_check_in_sync(self):
        self.sync()
        before = snap(self.root)
        data = self.sync("--check")
        self.assertEqual(self.rows(data), [(n, "unchanged") for n in NAMES])
        self.assertEqual(snap(self.root), before)
        self.assertEqual(self.text("--check")[-1],
                         f"packs sync --check: 0 created, 0 updated, {CORE_N} unchanged, 0 removed, "
                         f"0 conflict, 0 invalid; agent files: 0 created, 0 updated, 3 unchanged, "
                         f"0 removed, 0 conflict: in sync")

    def test_an_agent_file_of_the_procedure_form_is_updated(self):  # P8.5 -> P8.6 (D1)
        self.sync()
        path = self.agent_file("module-discover-agent")
        old_body = ('name = "module-discover-agent"\ndescription = "x"\n'
                    'developer_instructions = """\n## Steps\n\n1. Choose.\n"""\n').encode()
        head = {"schema": "modsys.managed/1", "pack": "core", "skill": "module-discover",
                "version": V, "sha256": sha(old_body)}
        path.write_bytes(("# modsys-managed: " + json.dumps(head) + "\n").encode() + old_body)
        old = path.read_bytes()
        before = snap(self.root)
        data = self.sync("--check", code=1)
        self.assertEqual(self.rows(data), [("module-discover-agent", "updated"),
                                           ("module-research-agent", "unchanged"),
                                           ("module-scout-agent", "unchanged")])
        self.assertEqual(snap(self.root), before)
        self.assertTrue(self.text("--check", code=1)[-1].endswith(
            "stale — run modsys packs sync --agent codex"))
        data = self.sync()
        self.assertEqual(self.rows(data)[0], ("module-discover-agent", "updated"))
        new = self.agent_file("module-discover-agent").read_bytes()
        self.assertNotEqual(marker(new)[0]["sha256"], marker(old)[0]["sha256"])
        self.assertEqual(tomllib.loads(new.decode())["developer_instructions"],
                         instructions("module-discover"))
        self.assertEqual(self.rows(self.sync("--check")), [(n, "unchanged") for n in NAMES])

    def test_a_version_change_alone_rewrites_the_marker(self):
        self.repo_core("9.0.0")
        self.sync()
        self.repo_core("9.1.0")
        data = self.sync()
        self.assertEqual(self.rows(data), [(n, "updated") for n in NAMES])
        self.assertEqual(marker(self.agent_file("module-scout-agent").read_bytes())[0]["version"],
                         "9.1.0")

    def test_a_local_edit_is_a_conflict(self):
        self.sync()
        path = self.agent_file("module-scout-agent")
        path.write_bytes(path.read_bytes() + b"# mine\n")
        before = snap(self.root)
        data = self.sync(code=1)
        row = data["agent_files"][2]
        self.assertEqual((row["name"], row["status"], row["reason"]),
                         ("module-scout-agent", "conflict", "module-scout-agent.toml (locally "
                                                           "edited)"))
        self.assertEqual(snap(self.root), before)
        lines = self.text(code=1)
        i = lines.index(f"conflict   codex   .codex/agents/module-scout-agent.toml  (core {V})")
        self.assertEqual(lines[i + 1], "  module-scout-agent.toml (locally edited) — revert it "
                                       "(git checkout -- .codex/agents/module-scout-agent.toml) "
                                       "and sync again, or keep the change: modsys eject "
                                       "module-scout, edit .modsys/overrides/skills/module-scout/"
                                       "SKILL.md, then packs sync")
        self.assertEqual(lines[-1], f"packs sync: 0 created, 0 updated, {CORE_N} unchanged, 0 removed, "
                                    f"0 conflict, 0 invalid; agent files: 0 created, 0 updated, "
                                    f"2 unchanged, 0 removed, 1 conflict")

    def test_a_foreign_file_is_a_conflict(self):
        path = self.agent_file("module-discover-agent")
        path.parent.mkdir(parents=True)
        path.write_text('name = "module-discover-agent"\n', encoding="utf-8")
        before = snap(self.root)
        data = self.sync("--check", code=1)
        self.assertEqual(snap(self.root), before)
        data = self.sync(code=1)
        row = data["agent_files"][0]
        self.assertEqual(row["status"], "conflict")
        self.assertTrue(row["reason"].startswith("not managed by modsys"), row)
        self.assertEqual(path.read_text(encoding="utf-8"), 'name = "module-discover-agent"\n')
        self.assertEqual(self.rows(data)[1:], [("module-research-agent", "created"),
                                               ("module-scout-agent", "created")])

    def test_a_damaged_marker_is_a_conflict(self):
        self.sync()
        path = self.agent_file("module-research-agent")
        damaged = path.read_bytes().replace(b'"sha256": "', b'"sha256": "x', 1)
        path.write_bytes(damaged)
        data = self.sync(code=1)
        row = data["agent_files"][1]
        self.assertEqual(row["status"], "conflict")
        self.assertIn("not a valid marker", row["reason"])
        self.assertEqual(path.read_bytes(), damaged)
        path.write_bytes(b"# modsys-managed: {not json\n" + damaged.split(b"\n", 1)[1])
        self.assertEqual(self.sync(code=1)["agent_files"][1]["status"], "conflict")

    def test_another_skills_marker_is_a_conflict(self):
        self.sync()
        scout = self.agent_file("module-scout-agent").read_bytes()
        self.agent_file("module-discover-agent").write_bytes(scout)
        row = self.sync(code=1)["agent_files"][0]
        self.assertEqual((row["status"], row["reason"]),
                         ("conflict", "managed for pack 'core', skill 'module-scout'"))

    def test_core_disabled_removes_them(self):
        self.sync()
        self.config("[packs]\nbuiltin = []\n")
        data = self.sync()
        self.assertEqual(self.rows(data), [(n, "removed") for n in NAMES])
        self.assertEqual(data["agent_files"][0]["pack"], "core")
        self.assertTrue((self.root / ".codex/agents").is_dir())
        self.assertEqual(list((self.root / ".codex/agents").iterdir()), [])
        self.assertEqual(self.sync()["agent_files"], [])

    def test_a_repository_core_pack_without_the_wrapped_skill(self):
        self.sync()
        self.repo_core(skills_={"module-scout": None, "module-discover": None})
        data = self.sync()  # a declared skill has its agent, procedure file or not (P8.6 D1)
        self.assertEqual(self.rows(data), [("module-discover-agent", "updated"),
                                           ("module-research-agent", "removed"),
                                           ("module-scout-agent", "updated")])
        self.assertEqual(sorted(p.name for p in (self.root / ".codex/agents").iterdir()),
                         ["module-discover-agent.toml", "module-scout-agent.toml"])

    def test_an_edited_file_is_not_removed(self):
        self.sync()
        path = self.agent_file("module-scout-agent")
        path.write_bytes(path.read_bytes() + b"# mine\n")
        self.config("[packs]\nbuiltin = []\n")
        data = self.sync(code=1)
        self.assertEqual(self.rows(data), [("module-discover-agent", "removed"),
                                           ("module-research-agent", "removed"),
                                           ("module-scout-agent", "conflict")])
        self.assertEqual(data["agent_files"][2]["reason"],
                         "module-scout-agent.toml (locally edited; not removed)")
        self.assertTrue(path.is_file())

    def test_a_foreign_file_is_never_removed(self):
        path = self.agent_file("module-scout-agent")
        path.parent.mkdir(parents=True)
        path.write_text("# my own agent\n", encoding="utf-8")
        self.config("[packs]\nbuiltin = []\n")
        self.assertEqual(self.sync()["agent_files"], [])
        self.assertEqual(self.sync("--remove")["agent_files"], [])
        self.assertTrue(path.is_file())

    def test_remove(self):
        self.sync()
        (self.root / ".codex/agents/mine.toml").write_text('name = "mine"\n', encoding="utf-8")
        data = self.sync("--remove")
        self.assertEqual(self.rows(data), [(n, "removed") for n in NAMES])
        self.assertEqual(sorted(p.name for p in (self.root / ".codex/agents").iterdir()),
                         ["mine.toml"])
        self.assertEqual(self.text("--remove")[-1], "packs sync --remove: 0 created, 0 updated, "
                                                    "0 unchanged, 0 removed, 0 conflict, "
                                                    "0 invalid")

    def unwanted_state(self, cause: str, kind: str) -> tuple[Path, Path]:
        """A fresh fixture synced for codex; then `.codex/agents` becomes `kind` and `cause`
        makes the agents unwanted (AC-007, amended). Its old files move to `<tmp>/outside`,
        which keeps the managed `module-scout-agent.toml`, a hand-written
        `module-discover-agent.toml` (no marker) and a `notes.txt`. `kind`: `marked` — a symlink
        to that directory; `unmarked` — the same without the managed file; `file` — a regular
        file; `plain` — a plain directory holding what `unmarked` points at (the reference)."""
        shutil.rmtree(self.root)
        copy_fixture(self.tmp)
        self.config('[packs]\nbuiltin = ["core"]\n')
        self.sync()
        agents, outside = self.root / ".codex/agents", self.tmp / "outside"
        shutil.rmtree(outside, ignore_errors=True)
        agents.rename(outside)
        for name in ("module-discover-agent", "module-research-agent"):
            (outside / f"{name}.toml").unlink()
        (outside / "module-discover-agent.toml").write_text('name = "mine"\n', encoding="utf-8")
        (outside / "notes.txt").write_text("keep\n", encoding="utf-8")
        if kind != "marked":
            (outside / "module-scout-agent.toml").unlink()
        if kind == "file":
            agents.write_text("not a directory\n", encoding="utf-8")
        elif kind == "plain":
            shutil.copytree(outside, agents)
        else:
            os.symlink(outside, agents)
        if cause == "core disabled":
            self.config("[packs]\nbuiltin = []\n")
        else:
            self.repo_core(skills_={"module-lint": None})
        return agents, outside

    def test_a_marked_file_behind_a_symlinked_agents_directory(self):  # AC-007, amended
        """No agent wanted (core disabled, or a repository `core` without the wrapped skills)
        and `.codex/agents` a symlink: a read-only look behind it. The agent file there that
        carries a modsys marker line is a `conflict` (exit 1: packs sync cannot remove it
        through the symlink); the hand-written one gives no row; nothing is written or removed
        through it — in sync, `--check`, `--dry-run`, `--remove` and `setup`."""
        reason = (".codex/agents is a symlink — packs sync cannot remove module-scout-agent.toml "
                  "through it")
        hint = ("delete that file where the symlink points, or make .codex/agents a plain "
                "directory, then sync again")
        want = [{"agent": "codex", "name": "module-scout-agent",
                 "path": ".codex/agents/module-scout-agent.toml", "status": "conflict",
                 "pack": "core", "skill": "module-scout", "version": V, "reason": reason}]
        suffix = "; agent files: 0 created, 0 updated, 0 unchanged, 0 removed, 1 conflict"
        for cause in ("core disabled", "repository core without the wrapped skills"):
            with self.subTest(cause=cause):
                agents, outside = self.unwanted_state(cause, "marked")
                there = snap(outside)
                self.assertEqual(self.sync("--check", code=1)["agent_files"], want)
                line = self.text("--check", code=1)[-1]
                self.assertIn(f"{suffix}: ", line)
                self.assertTrue(line.endswith("blocked — resolve the conflict / invalid rows "
                                              "above"), line)
                self.assertEqual(self.sync("--dry-run", code=1)["agent_files"], want)
                self.assertEqual(self.sync(code=1)["agent_files"], want)  # the skills go
                lines = self.text(code=1)
                self.assertEqual(lines[-3:-1], [
                    f"conflict   codex   .codex/agents/module-scout-agent.toml  (core {V})",
                    f"  {reason} — {hint}"])
                self.assertTrue(lines[-1].startswith("packs sync: 0 created, 0 updated, "))
                self.assertTrue(lines[-1].endswith(f", 0 removed, 0 conflict, 0 invalid{suffix}"),
                                lines[-1])
                got, env, err = run_json("setup", "--agent", "codex", *self.R)
                self.assertEqual((got, err), (1, ""))
                step = env["data"]["steps"][1]
                self.assertEqual((step["step"], step["status"], step["detail"]["agent_files"]),
                                 ("packs sync", "conflict", want))
                got, out, err = run("setup", "--agent", "codex", *self.R)
                lines = out.splitlines()
                self.assertEqual((got, err), (1, ""))
                i = lines.index("  conflict  codex   .codex/agents/module-scout-agent.toml")
                self.assertEqual(lines[i + 1], f"    {reason} — {hint}")
                self.assertEqual(lines[-1], "setup: packs sync left 1 agent file unwritten — "
                                            "resolve it as shown above, then run modsys setup "
                                            "again")
                self.assertEqual(self.sync("--remove", code=1)["agent_files"], want)
                self.assertTrue(self.text("--remove", code=1)[-1].endswith(suffix))
                self.assertEqual(snap(outside), there)  # nothing written or removed through it
                self.assertTrue(agents.is_symlink())

    def test_nothing_ours_behind_an_unusable_agents_directory(self):  # AC-007, amended
        """No agent wanted and `.codex/agents` a symlink to a directory without a managed agent
        file, or a regular file: no agent rows, exit 0 — every byte of `packs sync` (plain,
        `--check`, `--dry-run`, `--remove`) and `setup`, text and `--json`, equals the output
        with a plain directory; nothing behind it is written or removed."""
        def outputs(cause: str, kind: str) -> list:
            agents, outside = self.unwanted_state(cause, kind)
            there, got = snap(outside), []
            for argv in (("packs", "sync"), ("packs", "sync", "--check"),  # the skills go first
                         ("packs", "sync", "--dry-run"), ("setup",),
                         ("packs", "sync", "--remove")):
                for fmt in ((), ("--json",)):
                    got.append((argv, fmt, run(*argv, "--agent", "codex", *fmt, *self.R)))
            for argv, fmt, (code, out, err) in got:
                self.assertEqual((code, err), (0, ""), (argv, fmt, out))
                if fmt:
                    data = json.loads(out)["data"]
                    files = data["steps"][1]["detail"] if argv == ("setup",) else data
                    self.assertEqual(files["agent_files"], [], (argv, fmt))
                else:
                    self.assertNotIn("agent file", out, argv)
            self.assertEqual(snap(outside), there)
            self.assertEqual((agents.is_symlink(), agents.is_file()),
                             (kind == "unmarked", kind == "file"))
            return got

        for cause in ("core disabled", "repository core without the wrapped skills"):
            plain = outputs(cause, "plain")
            for kind in ("unmarked", "file"):
                with self.subTest(cause=cause, kind=kind):
                    self.assertEqual(outputs(cause, kind), plain)

    def test_remove_looks_behind_a_symlinked_agents_directory(self):  # AC-007, amended
        """`--remove` wants no agent: through a symlinked `.codex/agents` (or `.codex`) each
        agent file with a modsys marker line — a damaged one too — is a `conflict`, a file
        without one gives no row, and nothing behind the symlink is removed."""
        self.sync()
        outside = self.tmp / "outside"
        (self.root / ".codex/agents").rename(outside)
        os.symlink(outside, self.root / ".codex/agents")
        path = outside / "module-research-agent.toml"
        path.write_bytes(b"# modsys-managed: {broken\n" + path.read_bytes().partition(b"\n")[2])
        path = outside / "module-discover-agent.toml"
        path.write_bytes(path.read_bytes().partition(b"\n")[2])  # no marker line: not ours
        there = snap(outside)
        why = ".codex/agents is a symlink — packs sync cannot remove {} through it".format
        data = self.sync("--remove", code=1)
        self.assertEqual(data["agent_files"], [
            {"agent": "codex", "name": "module-research-agent",
             "path": ".codex/agents/module-research-agent.toml", "status": "conflict",
             "pack": None, "skill": "module-research", "version": None,
             "reason": why("module-research-agent.toml")},
            {"agent": "codex", "name": "module-scout-agent",
             "path": ".codex/agents/module-scout-agent.toml", "status": "conflict",
             "pack": "core", "skill": "module-scout", "version": V,
             "reason": why("module-scout-agent.toml")}])
        self.assertEqual({r["status"] for r in data["skills"]}, {"removed"})
        self.assertEqual(snap(outside), there)
        (self.root / ".codex/agents").unlink()  # now `.codex` itself is the symlink
        shutil.rmtree(self.root / ".codex")
        (outside / "module-research-agent.toml").unlink()
        top = self.tmp / "top"
        (top / "agents").mkdir(parents=True)
        outside.rename(top / "agents")
        os.symlink(top, self.root / ".codex")
        there = snap(top)
        rows = self.sync("--remove", code=1)["agent_files"]
        self.assertEqual([(r["name"], r["status"], r["reason"]) for r in rows], [
            ("module-scout-agent", "conflict", ".codex is a symlink — packs sync cannot remove "
                                               "module-scout-agent.toml through it")])
        self.assertEqual(snap(top), there)

    def test_the_edit_hint_under_plugin_delivery(self):  # review M-2: eject needs "repo"
        self.config('[packs]\nbuiltin = ["core"]\nbuiltin_delivery = "plugin"\n')
        self.sync()
        path = self.agent_file("module-scout-agent")
        path.write_bytes(path.read_bytes() + b"# mine\n")
        lines = self.text(code=1)
        i = lines.index(f"conflict   codex   .codex/agents/module-scout-agent.toml  (core {V})")
        self.assertEqual(lines[i + 1], "  module-scout-agent.toml (locally edited) — revert it "
                                       "(git checkout -- .codex/agents/module-scout-agent.toml) "
                                       "and sync again, or keep the change: set [packs] "
                                       "builtin_delivery = \"repo\", modsys eject module-scout, "
                                       "edit .modsys/overrides/skills/module-scout/SKILL.md, "
                                       "then packs sync")

    def test_a_symlinked_or_regular_agents_directory(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        (self.root / ".codex").mkdir()
        cases = (("symlink", lambda p: os.symlink(outside, p)),
                 ("file", lambda p: p.write_text("not a directory\n", encoding="utf-8")))
        for kind, make in cases:
            with self.subTest(kind=kind):
                agents = self.root / ".codex/agents"
                if agents.is_symlink() or agents.is_file():
                    agents.unlink()
                make(agents)
                before, there = snap(self.root / ".codex"), snap(outside)
                for argv in ((), ("--check",)):  # the agents are wanted: all three conflict
                    data = self.sync(*argv, code=1)
                    self.assertEqual(self.rows(data), [(n, "conflict") for n in NAMES])
                    self.assertTrue(data["agent_files"][0]["reason"].startswith(
                        ".codex/agents is "), data["agent_files"][0])
                # --remove wants none (AC-007, amended): nothing of ours behind it, no row
                self.assertEqual(self.sync("--remove")["agent_files"], [])
                self.assertEqual((snap(self.root / ".codex"), snap(outside)), (before, there))
        shutil.rmtree(self.root / ".codex")
        os.symlink(outside, self.root / ".codex")
        self.assertEqual(self.rows(self.sync(code=1)), [(n, "conflict") for n in NAMES])
        self.assertEqual(list(outside.iterdir()), [])

    def test_an_agent_held_by_its_skill_is_still_wanted(self):  # AC-007, amended
        """Only `module-scout` declared, and its source not loadable: its agent is held, not
        unwanted, so a symlinked `.codex/agents` stays a `conflict` for all three."""
        pack = self.repo_core(skills_={"module-scout": None})
        (pack / "skills/module-scout/SKILL.md").write_text("no front matter\n", encoding="utf-8")
        outside = self.tmp / "outside"
        outside.mkdir()
        (self.root / ".codex").mkdir()
        os.symlink(outside, self.root / ".codex/agents")
        data = self.sync(code=1)
        self.assertEqual(self.rows(data), [(n, "conflict") for n in NAMES])
        self.assertEqual({r["reason"] for r in data["agent_files"]},
                         {".codex/agents is a symlink — packs sync writes nothing through it"})
        self.assertEqual(list(outside.iterdir()), [])

    @unittest.skipIf(os.geteuid() == 0, "root writes into a read-only directory")
    def test_a_read_only_agents_directory(self):
        (self.root / ".codex/agents").mkdir(parents=True)
        (self.root / ".codex/agents").chmod(0o555)
        code, out, err = run("packs", "sync", "--agent", "codex", "--json", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("modsys: error: cannot write .codex/agents/"
                                       "module-discover-agent.toml: Permission denied — fix it "
                                       "and run packs sync again"), err)
        self.assertEqual(err.count("\n"), 1)
        self.assertEqual(list((self.root / ".codex/agents").iterdir()), [])

    def test_an_interrupt_between_two_agent_files(self):
        self.repo_core("9.0.0")
        self.sync()
        self.repo_core("9.1.0")  # every agent file stale: its marker's version
        old = {n: self.agent_file(n).read_bytes() for n in NAMES}
        from modsys import packs_cmd
        real, calls = packs_cmd.apply_agent_file, []

        def seam(plan):
            calls.append(plan.name)
            if len(calls) == 2:
                raise KeyboardInterrupt
            real(plan)

        with mock.patch.object(packs_cmd, "apply_agent_file", side_effect=seam):
            self.assertEqual(run("packs", "sync", "--agent", "codex", "--json", *self.R),
                             (130, "", "modsys: interrupted\n"))
        self.assertNotEqual(self.agent_file(NAMES[0]).read_bytes(), old[NAMES[0]])
        for name in NAMES[1:]:
            self.assertEqual(self.agent_file(name).read_bytes(), old[name])
        calls.clear()

        def inside(plan):  # Ctrl-C between the temp file and the rename
            calls.append(plan.name)
            if len(calls) == 1:
                with mock.patch.object(skill_sync.os, "replace", side_effect=KeyboardInterrupt):
                    return real(plan)
            return real(plan)

        with mock.patch.object(packs_cmd, "apply_agent_file", side_effect=inside):
            self.assertEqual(run("packs", "sync", "--agent", "codex", *self.R)[0], 130)
        self.assertEqual(self.agent_file(NAMES[1]).read_bytes(), old[NAMES[1]])
        self.assertEqual(sorted(p.name for p in (self.root / ".codex/agents").iterdir()),
                         [f"{n}.toml" for n in NAMES])  # no temp file left
        data = self.sync()
        self.assertEqual(self.rows(data), [(NAMES[0], "unchanged"), (NAMES[1], "updated"),
                                           (NAMES[2], "updated")])
        for name in NAMES:
            head, rest = marker(self.agent_file(name).read_bytes())
            self.assertEqual(head["sha256"], sha(rest))
            self.assertEqual(head["version"], "9.1.0")


class OnlyForCodexTest(CodexRepo):  # P84-AC-008
    def setUp(self):
        super().setUp()
        (self.root / ".codex").mkdir()
        (self.root / ".codex/config.toml").write_text('model = "x"\n', encoding="utf-8")
        (self.root / ".codex/notes.txt").write_text("keep\n", encoding="utf-8")
        old = 1_000_000_000_000_000_000
        for name in ("config.toml", "notes.txt"):
            os.utime(self.root / ".codex" / name, ns=(old, old))

    def codex_files(self) -> dict:
        return {p.name: (p.read_bytes(), p.stat().st_mtime_ns)
                for p in sorted((self.root / ".codex").iterdir()) if p.is_file()}

    def test_without_codex_nothing_under_codex(self):
        before = snap(self.root / ".codex")
        for agents in (("claude",), ("cursor",), ("gemini",), ("copilot",),
                       ("claude", "cursor", "gemini", "copilot")):
            with self.subTest(agents=agents), mock.patch(
                    "modsys.packs_cmd.plan_agent_files", side_effect=AssertionError("read")):
                for argv in ((), ("--check",), ("--dry-run",)):
                    data = self.sync(*argv, agents=agents)
                    self.assertEqual(list(data), OLD_KEYS)
                    self.assertNotIn("agent files", "\n".join(self.text(*argv, agents=agents)))
                data = self.sync("--remove", agents=agents)
                self.assertEqual(list(data), OLD_KEYS)
        self.assertEqual(snap(self.root / ".codex"), before)
        self.assertFalse((self.root / ".codex/agents").exists())

    def test_setup_without_codex(self):
        got, env, err = run_json("setup", "--agent", "claude", *self.R)
        self.assertEqual((got, err), (0, ""))
        self.assertEqual(list(env["data"]["steps"][1]["detail"]), OLD_KEYS)
        self.assertFalse((self.root / ".codex/agents").exists())

    def test_every_choice_with_codex(self):
        before = self.codex_files()
        for how in (("codex",), ("claude", "codex"), ("cursor", "codex"), FIVE, "config",
                    "inferred"):
            with self.subTest(how=how):
                for top in (".codex/agents", ".agents", ".claude"):
                    shutil.rmtree(self.root / top, ignore_errors=True)
                if how == "config":
                    self.config('[packs]\nbuiltin = ["core"]\nagents = ["codex"]\n')
                    data = self.sync(agents=())
                elif how == "inferred":  # a marker in .agents/skills means codex
                    self.config('[packs]\nbuiltin = ["core"]\n')
                    self.sync(agents=("cursor",))
                    data = self.sync(agents=())
                    self.assertEqual(data["agents"], ["codex"])
                else:
                    data = self.sync(agents=how)
                self.assertEqual(list(data), DATA_KEYS)
                self.assertEqual(self.rows(data), [(n, "created") for n in NAMES])
                self.assertEqual(self.codex_files(), before)

    def test_setup_with_codex_keeps_the_codex_config(self):
        before = self.codex_files()
        got, env, err = run_json("setup", *self.R)  # default agents: claude and codex
        self.assertEqual((got, err), (0, ""))
        self.assertEqual(env["data"]["agents"], ["claude", "codex"])
        self.assertEqual(len(env["data"]["steps"][1]["detail"]["agent_files"]), 3)
        self.assertEqual(self.codex_files(), before)


class OutputShapeTest(CodexRepo):  # P84-AC-009, P84-AC-038
    def test_the_json_shape(self):
        data = self.sync("--dry-run")
        self.assertEqual(list(data), DATA_KEYS)
        self.assertEqual(self.rows(data), [(n, "created") for n in NAMES])
        self.assertFalse((self.root / ".codex").exists())  # --dry-run writes nothing
        data = self.sync(agents=("claude", "codex"))
        self.assertEqual(sum(data["summary"].values()), len(data["skills"]))  # skills only
        self.assertEqual(data["summary"]["created"], 2 * CORE_N)

    def test_check_and_failed_count_both_lists(self):
        self.sync()
        self.agent_file("module-scout-agent").unlink()
        data = self.sync("--check", code=1)
        self.assertEqual({r["status"] for r in data["skills"]}, {"unchanged"})
        self.assertEqual(self.rows(data)[2], ("module-scout-agent", "created"))
        self.assertEqual(data["summary"]["created"], 0)
        self.sync()
        path = self.agent_file("module-scout-agent")
        path.write_bytes(path.read_bytes() + b"# mine\n")
        data = self.sync(code=1)
        self.assertEqual(data["summary"]["conflict"], 0)

    def test_the_text(self):
        lines = self.text("--dry-run")
        rows = [f"created    codex   .codex/agents/{n}.toml  (core {V})" for n in NAMES]
        self.assertEqual(lines[-4:], rows + [
            f"packs sync: {CORE_N} created, 0 updated, 0 unchanged, 0 removed, 0 conflict, 0 invalid; "
            f"agent files: 3 created, {COUNTS}  (dry run: nothing written)"])
        self.assertTrue(lines[CORE_N - 1].startswith("created    codex   .agents/skills/module-sync"))
        lines = self.text()
        self.assertEqual(lines[-4:], rows + [
            f"packs sync: {CORE_N} created, 0 updated, 0 unchanged, 0 removed, 0 conflict, 0 invalid; "
            f"agent files: 3 created, {COUNTS}"])
        lines = self.text(agents=("claude", "codex"))
        self.assertEqual(lines[2 * CORE_N:2 * CORE_N + 3], [r.replace("created  ", "unchanged") for r in rows])
        self.assertTrue(lines[2 * CORE_N + 3].startswith("note: GitHub Copilot reads both"))

    def test_setup_text_and_status(self):
        got, out, err = run("setup", "--agent", "codex", *self.R)
        self.assertEqual((got, err), (0, ""))
        self.assertIn(f"packs sync  created      {CORE_N} skill copies, 3 agent files", out.splitlines())
        got, out, err = run("setup", "--agent", "codex", *self.R)
        self.assertIn(f"packs sync  unchanged    {CORE_N} skill copies, 3 agent files", out.splitlines())
        self.agent_file("module-scout-agent").unlink()
        got, env, err = run_json("setup", "--agent", "codex", *self.R)
        self.assertEqual(env["data"]["steps"][1]["status"], "created")  # folded with the rows
        got, out, err = run("setup", "--agent", "codex", *self.R)
        self.assertIn(f"packs sync  unchanged    {CORE_N} skill copies, 3 agent files", out.splitlines())
        path = self.agent_file("module-scout-agent")
        path.write_bytes(path.read_bytes() + b"# mine\n")
        got, env, err = run_json("setup", "--agent", "codex", *self.R)
        self.assertEqual((got, env["data"]["steps"][1]["status"]), (1, "conflict"))
        got, out, err = run("setup", "--agent", "codex", *self.R)
        lines = out.splitlines()
        self.assertEqual(got, 1)
        self.assertIn(f"packs sync  conflict     {CORE_N} skill copies, 3 agent files (2 unchanged, "
                      "1 conflict)", lines)
        self.assertIn("  conflict  codex   .codex/agents/module-scout-agent.toml", lines)
        self.assertEqual(lines[-1], "setup: packs sync left 1 agent file unwritten — resolve it "
                                    "as shown above, then run modsys setup again")

    def test_read_only_runs_keep_the_tree(self):  # P84-AC-038
        self.sync()
        path = self.agent_file("module-research-agent")
        path.write_bytes(path.read_bytes() + b"# mine\n")
        before = snap(self.root)
        for argv in (("--check",), ("--dry-run",)):
            got, out, err = run("packs", "sync", "--agent", "codex", *argv, "--json", *self.R)
            self.assertIn(got, (0, 1))
            self.assertEqual(json.loads(out)["schema"], "modsys.packs/1")
        self.assertEqual(snap(self.root), before)

    @unittest.skipIf(os.geteuid() == 0, "root writes into a read-only directory")
    def test_a_real_process(self):  # one JSON document; a refusal: empty stdout, one line
        env = {**os.environ, "PYTHONPATH": str(ENGINE)}
        env.pop("MODSYS_DEBUG", None)
        argv = [sys.executable, "-m", "modsys", "packs", "sync", "--agent", "codex", "--json",
                *self.R]
        proc = subprocess.run(argv, capture_output=True, text=True, env=env, cwd=self.tmp)
        self.assertEqual((proc.returncode, proc.stderr), (0, ""))
        self.assertEqual(json.loads(proc.stdout)["data"]["agent_files"][0]["status"], "created")
        shutil.rmtree(self.root / ".codex")
        (self.root / ".codex/agents").mkdir(parents=True)
        (self.root / ".codex/agents").chmod(0o555)
        proc = subprocess.run(argv, capture_output=True, text=True, env=env, cwd=self.tmp)
        self.assertEqual((proc.returncode, proc.stdout), (2, ""))
        self.assertEqual(proc.stderr.count("\n"), 1)
        self.assertTrue(proc.stderr.startswith("modsys: error: cannot write .codex/agents/"),
                        proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_help_names_the_agent_files(self):  # SI-P84-16: one clause each, pinned
        for verb in ("packs", "setup"):
            got, out, err = run(verb, "--help")
            self.assertEqual(got, 0)
            self.assertIn(".codex/agents/", " ".join(out.split()), verb)


class ProbeOutcomeTest(CodexRepo):  # P84-AC-002 (outcome A ruled: the keys are kept)
    def test_codex_copies_are_byte_identical_to_the_sources(self):
        team = self.root / ".modsys/packs/team/skills/stock-check"
        team.mkdir(parents=True)
        (team.parent.parent / "pack.toml").write_text(
            'id = "team"\nversion = "1.0.0"\n\n[skills.stock-check]\npath = "skills/stock-check"\n',
            encoding="utf-8")
        text = ('---\nname: stock-check\ndescription: Checks the stock of a book.\n'
                'argument-hint: "[task]"\narguments: task\n---\n\nCheck $task in the catalog.\n')
        (team / "SKILL.md").write_text(text, encoding="utf-8")
        self.sync()
        self.assertEqual((self.root / ".agents/skills/stock-check/SKILL.md").read_text("utf-8"),
                         text)
        for skill in sorted(p.name for p in CORE.iterdir()):
            for src in sorted((CORE / skill).rglob("*")):
                if src.is_file():
                    copy = self.root / ".agents/skills" / skill / src.relative_to(CORE / skill)
                    self.assertEqual(copy.read_bytes(), src.read_bytes(), copy)
        source = (ENGINE / "modsys/skill_sync.py").read_text(encoding="utf-8")
        self.assertNotIn("argument-hint", source)  # no strip code for the two keys
        self.assertNotIn("arguments:", source)


class DocsTest(unittest.TestCase):  # P84-AC-010
    def flat(self, rel: str) -> str:
        return " ".join((ENGINE / rel).read_text(encoding="utf-8").split())

    def test_skills_doc(self):
        text = self.flat("docs/skills.md")
        for needle in ("the `modsys` plugin ships four agents",
                       "`module-discover-agent`, `module-scout-agent` and `module-research-agent`",
                       "tools Read, Grep, Glob, Bash, Agent, Skill", "`model: sonnet`",
                       "`skills: [modsys:module-<x>]`",  # P8.6 D1: the agent only runs its skill
                       "read `.agents/skills/module-<x>/SKILL.md` and follow it",
                       "`.codex/agents/module-discover-agent.toml`",
                       "whenever the agents they sync for include `codex`",
                       "`# modsys-managed:`", "`packs sync --check`",
                       "`packs sync --remove --agent codex`", "A locally edited file",
                       "Nothing is written or removed through a symlinked or non-directory "
                       "`.codex/agents`: while the repository wants the agents, all three are "
                       "conflicts; when it wants none",
                       "only an agent file with the marker behind a symlinked `.codex/agents` is "
                       "one — it cannot be removed through the link — and otherwise that "
                       "directory is left alone, with no agent rows",
                       'Claude Code with `builtin_delivery = "repo"` has no agent',
                       "the skills run in the conversation"):
            self.assertIn(needle, text)
        self.assertNotIn("Codex ignores `agents/`", text)

    def test_configuration_doc(self):  # beside `[packs] agents`: in its table row
        lines = (ENGINE / "docs/configuration.md").read_text(encoding="utf-8").splitlines()
        row = next(line for line in lines if line.startswith("| `agents` |"))
        self.assertIn("`.codex/agents/`", row)
        self.assertIn("`codex`", row)

    def test_changelog(self):
        log = (ENGINE / "CHANGELOG.md").read_text(encoding="utf-8")
        unreleased = " ".join(log.split("## [Unreleased]", 1)[1].split("\n## [", 1)[0].split())
        for needle in ("`module-discover-agent`, `module-scout-agent` and `module-research-agent`",
                       "`.codex/agents/<name>.toml`", "`modsys/defaults/agents/`",
                       "nothing is written or removed through a symlinked or non-directory "
                       "`.codex/agents` (all three files are conflicts while the agents are "
                       "wanted; when none is, only a file with the marker behind a symlink is "
                       "one)"):
            self.assertIn(needle, unreleased)


if __name__ == "__main__":
    unittest.main()
