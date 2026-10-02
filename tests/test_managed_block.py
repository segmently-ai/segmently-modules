"""`modsys agents-md` (D9): one managed block in agent instruction files — update rules, byte
safety, targets and the block's content."""
import os
import stat
import tempfile
import unittest
from unittest import mock

from modsys import __version__
from modsys.agents_md_cmd import BEGIN, END
from tests.helpers import copy_fixture, run, run_json


class BlockRepo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        self.R = ("--root", str(self.root))
        self.claude = self.root / "CLAUDE.md"

    def tearDown(self):
        self._tmp.cleanup()

    def agents_md(self, *argv, code=0, targets=("CLAUDE.md",)) -> dict:
        flags = [a for t in targets for a in ("--target", t)]
        got, env, err = run_json("agents-md", *flags, *argv, *self.R)
        self.assertEqual((got, err), (code, ""), env)
        self.assertEqual(env["schema"], "modsys.agents-md/1")
        return env["data"]

    def block(self) -> str:
        """The block as a created file holds it."""
        self.agents_md(targets=("fresh.md",))
        text = (self.root / "fresh.md").read_text(encoding="utf-8")
        (self.root / "fresh.md").unlink()
        return text[:-1]  # without the file's final newline

    def statuses(self, data) -> list[tuple]:
        return [(r["path"], r["status"]) for r in data["targets"]]


class UpdateRulesTest(BlockRepo):  # P4A-AC-019
    def test_created_added_updated_unchanged(self):
        block = self.block()
        self.assertTrue(block.startswith(BEGIN + "\n") and block.endswith("\n" + END))
        cases = [(None, "created", f"{block}\n"),
                 ("# Team\n\nOur rules.\n", "added", f"# Team\n\nOur rules.\n\n{block}\n"),
                 ("Our rules.", "added", f"Our rules.\n\n{block}\n"),
                 ("Our rules.\n\n", "added", f"Our rules.\n\n{block}\n"),
                 (f"Before.\n{BEGIN}\nstale\n{END}\nAfter.\n", "updated",
                  f"Before.\n{block}\nAfter.\n"),
                 (f"Before.\n<!-- modsys:begin v0 -->\n{block.split(chr(10), 1)[1]}\nAfter.",
                  "updated", f"Before.\n{block}\nAfter."),
                 (f"# Team\n\n{block}\n", "unchanged", f"# Team\n\n{block}\n")]
        for before, status, after in cases:
            with self.subTest(before=before):
                self.claude.unlink(missing_ok=True)
                if before is not None:
                    self.claude.write_text(before, encoding="utf-8", newline="")
                data = self.agents_md()
                self.assertEqual(self.statuses(data), [("CLAUDE.md", status)])
                self.assertEqual(self.claude.read_bytes().decode("utf-8"), after)

    def test_an_unchanged_file_is_not_rewritten(self):
        self.agents_md()
        mtime = self.claude.stat().st_mtime_ns
        self.assertEqual(self.statuses(self.agents_md()), [("CLAUDE.md", "unchanged")])
        self.assertEqual(self.claude.stat().st_mtime_ns, mtime)

    def test_malformed_markers_stop_the_run(self):
        cases = [(f"a\n{BEGIN}\nb\n", "CLAUDE.md:2: a begin marker without an end marker "
                                      "(<!-- modsys:end -->)"),
                 (f"{END}\n{BEGIN}\n", "CLAUDE.md:1: an end marker before any begin marker"),
                 (f"{BEGIN}\n{END}\n{BEGIN}\n{END}\n", "CLAUDE.md:3: a second begin marker "
                                                       "(the first is on line 1)"),
                 (f"{BEGIN}\n{END}\n{END}\n", "CLAUDE.md:3: a second end marker (the first is "
                                              "on line 2)")]
        for text, needle in cases:
            with self.subTest(needle=needle):
                self.claude.write_text(text, encoding="utf-8")
                code, out, err = run("agents-md", "--target", "AGENTS.md", "--target",
                                     "CLAUDE.md", "--json", *self.R)
                self.assertEqual((code, out), (2, ""))
                self.assertIn(f"modsys: error: {needle} — fix the markers by hand; nothing "
                              f"written", err)
                self.assertEqual(self.claude.read_text(encoding="utf-8"), text)
                self.assertFalse((self.root / "AGENTS.md").exists())  # no target written

    def test_a_marker_inside_prose_is_text(self):
        text = f"See {BEGIN} in prose.\n  {END}\n"
        self.claude.write_text(text, encoding="utf-8")
        self.assertEqual(self.statuses(self.agents_md()), [("CLAUDE.md", "added")])
        self.assertTrue(self.claude.read_text(encoding="utf-8").startswith(text + "\n" + BEGIN))


class ByteSafetyTest(BlockRepo):  # P4A-AC-020
    def test_crlf_and_non_ascii_text_around_the_block(self):
        before, after = "# Équipe\r\n\r\n日本 rules.\r\n", "\r\nMore — text.\r\n"
        self.claude.write_bytes((before + f"{BEGIN}\r\nold\r\n{END}\r\n" + after)
                                .encode("utf-8"))
        self.agents_md()
        data = self.claude.read_bytes().decode("utf-8")
        self.assertTrue(data.startswith(before + BEGIN + "\r\n"))
        self.assertTrue(data.endswith(END + "\r\n" + after))
        block = data[len(before):-len(after)]
        self.assertEqual(block.count("\n"), block.count("\r\n"))

    def test_the_mode_is_kept(self):
        self.claude.write_text("x\n")
        os.chmod(self.claude, 0o600)
        self.agents_md()
        self.assertEqual(stat.S_IMODE(self.claude.stat().st_mode), 0o600)

    def test_a_symlinked_target_is_written_once_through_the_link(self):
        self.claude.write_text("# Team\n")
        os.symlink("CLAUDE.md", self.root / "AGENTS.md")
        data = self.agents_md(targets=("CLAUDE.md", "AGENTS.md"))
        self.assertEqual(data["targets"], [{"path": "CLAUDE.md", "status": "added"},
                                           {"path": "AGENTS.md", "status": "added",
                                            "same_as": "CLAUDE.md"}])
        self.assertTrue((self.root / "AGENTS.md").is_symlink())
        self.assertEqual(self.claude.read_text().count(BEGIN), 1)
        out = run("agents-md", "--target", "CLAUDE.md", "--target", "AGENTS.md", *self.R)[1]
        self.assertEqual(out.splitlines(), ["unchanged  CLAUDE.md",
                                            "unchanged  AGENTS.md  (same file as CLAUDE.md)"])

    def test_dangling_links_missing_dirs_and_empty_files(self):  # Review Focus
        os.symlink("CLAUDE.md", self.root / "AGENTS.md")  # CLAUDE.md does not exist yet
        (self.root / "empty.md").write_text("")
        data = self.agents_md(targets=("AGENTS.md", "docs/agents/AGENTS.md", "empty.md"))
        self.assertEqual(self.statuses(data), [("AGENTS.md", "created"),
                                               ("docs/agents/AGENTS.md", "created"),
                                               ("empty.md", "added")])
        self.assertTrue((self.root / "AGENTS.md").is_symlink())
        block = self.claude.read_text()
        self.assertTrue(block.startswith(BEGIN) and block.endswith(END + "\n"))
        for rel in ("docs/agents/AGENTS.md", "empty.md"):
            self.assertEqual((self.root / rel).read_text(), block)
        (self.root / "notes").write_text("a file, not a directory\n")
        code, out, err = run("agents-md", "--target", "notes/AGENTS.md", "--json", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("modsys: error: cannot write notes/AGENTS.md: "), err)

    def test_check_and_dry_run(self):
        self.claude.write_text("# Team\n")
        before = self.claude.read_bytes()
        data = self.agents_md("--check", code=1)
        self.assertEqual((self.statuses(data), data["check"]), ([("CLAUDE.md", "added")], True))
        self.assertEqual(self.claude.read_bytes(), before)
        data = self.agents_md("--dry-run")
        self.assertEqual((self.statuses(data), data["dry_run"]), ([("CLAUDE.md", "added")], True))
        self.assertEqual(self.claude.read_bytes(), before)
        self.agents_md()
        self.agents_md("--check")
        code, out, err = run("agents-md", "--target", "CLAUDE.md", "--check", "--dry-run",
                             *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("--check and --dry-run cannot be combined", err)

    def test_refused_targets(self):
        (self.root / "docs").mkdir()
        (self.root / "latin1.md").write_bytes("caf\xe9\n".encode("latin-1"))
        outside = os.path.join(os.path.dirname(self.root), "x.md")
        for target, needle in [("../x.md", "outside the repository root"),
                               (outside, "outside the repository root"),
                               ("docs", "is a directory"), (".", "is a directory"),
                               ("latin1.md", "latin1.md is not valid UTF-8 text; nothing "
                                             "written")]:
            with self.subTest(target=target):
                code, out, err = run("agents-md", "--target", target, "--json", *self.R)
                self.assertEqual((code, out), (2, ""))
                self.assertIn(needle, err)
        self.assertFalse(os.path.exists(outside))
        self.assertEqual((self.root / "latin1.md").read_bytes(), "caf\xe9\n".encode("latin-1"))
        code, out, err = run("agents-md", "--json", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("--target", err)


class BlockContentTest(BlockRepo):  # P4A-AC-021
    def body(self) -> list[str]:
        return self.block().split("\n")[1:-1]

    def test_the_default_block(self):
        self.assertEqual(run("packs", "new", "team", "--role", "reviewer", "--skill",
                             "api-review", *self.R)[0], 0)
        md = self.root / ".modsys/packs/team/skills/api-review/SKILL.md"
        md.write_text(md.read_text().replace(
            md.read_text().split("\n")[2], "description: Reviews API changes against the "
                                           "reviewer docs."))
        body = self.body()
        text = "\n".join(body)
        self.assertLessEqual(len(body), 25)
        self.assertIn('modsys context --task "<the task>" --role <role>', text)
        self.assertIn("Roles in this repository: developer, qa, po, architect, designer, "
                      "reviewer.", text)
        self.assertIn("- `api-review` — Reviews API changes against the reviewer docs.", body)
        flat = " ".join(text.split())  # fix wave M7: the P4b flow after a change
        self.assertIn("`modsys sync-instructions --from-diff <base>..HEAD`", flat)
        self.assertIn("`git merge-base <target> HEAD`", flat)
        self.assertIn("`module-sync`", flat)
        self.assertNotIn("discover --from-diff", flat)
        self.assertNotIn("instead of editing module docs", flat)
        self.assertNotIn("${", text)
        self.assertNotIn(__version__, text)
        data = self.agents_md("--dry-run")
        self.assertEqual(self.statuses(data), [("CLAUDE.md", "created")])

    def test_no_skills_yet(self):
        self.assertIn("- none yet (add one: modsys packs new ID --skill NAME)", self.body())

    def test_a_team_template(self):
        over = self.root / ".modsys/overrides/templates/agents-md.md"
        over.parent.mkdir(parents=True)
        over.write_text("Custom ${roles} v${version}\n")
        self.assertEqual(self.body(), [f"Custom developer, qa, po, architect, designer "
                                       f"v{__version__}"])
        rows = {r["template"]: r["source"] for r in run_json("templates", "list",
                                                            *self.R)[1]["data"]}
        self.assertEqual(rows["agents-md.md"], "override")


class AgentsMdContractTest(BlockRepo):  # P4A-AC-023
    def test_garbage_config_and_interrupt(self):
        (self.root / ".modsys/config.toml").write_text("code_map = 5\n")
        code, out, err = run("agents-md", "--target", "CLAUDE.md", "--json", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("modsys: error: "), err)
        (self.root / ".modsys/config.toml").unlink()
        with mock.patch("modsys.agents_md_cmd.atomic_write", side_effect=KeyboardInterrupt):
            self.assertEqual(run("agents-md", "--target", "CLAUDE.md", *self.R),
                             (130, "", "modsys: interrupted\n"))
        self.assertFalse(self.claude.exists())

    def test_text_output(self):
        self.claude.write_text("# Team\n")
        out = run("agents-md", "--target", "CLAUDE.md", "--target", "AGENTS.md", *self.R)[1]
        self.assertEqual(out.splitlines(), ["added      CLAUDE.md", "created    AGENTS.md"])
        self.claude.write_text("# Team\n")
        out = run("agents-md", "--target", "CLAUDE.md", "--check", *self.R)[1]
        self.assertEqual(out.splitlines(), ["added      CLAUDE.md", "agents-md --check: stale — "
                                            "run modsys agents-md with the same --target flags"])


if __name__ == "__main__":
    unittest.main()


class SkillListTest(BlockRepo):  # P81-AC-038, P81-AC-039
    def enable(self, delivery=None):
        text = '[packs]\nbuiltin = ["core", "ui", "qa"]\n'
        if delivery:
            text += f'builtin_delivery = "{delivery}"\n'
        (self.root / ".modsys/config.toml").write_text(text, encoding="utf-8")

    def test_plugin_delivery_names_the_plugins(self):  # P81-AC-038
        self.enable("plugin")
        text = self.block()
        self.assertIn("(the modsys plugins provide these skills):", text)
        self.assertNotIn("packs sync", text)
        self.assertNotIn("copies them", text)

    def test_repo_delivery_keeps_the_old_wording(self):  # P81-AC-038
        for delivery in (None, "repo"):
            with self.subTest(delivery=delivery):
                self.enable(delivery)
                self.assertIn("Skills from packs (`modsys packs sync` copies them into the "
                              "agents' skill directories):\n", self.block())

    def test_one_short_line_per_skill(self):  # P81-AC-039
        from modsys.config import builtin_packs_root
        from modsys.skills import read_front_matter
        self.enable("plugin")
        lines = [ln for ln in self.block().split("\n") if ln.startswith("- `")]
        skills = sorted(p.parent.name for p in builtin_packs_root().glob("*/skills/*/SKILL.md"))
        self.assertGreaterEqual(len(skills), 9)
        self.assertEqual([ln.split("`")[1] for ln in lines], skills)
        for ln in lines:
            sid = ln.split("`")[1]
            path = next(builtin_packs_root().glob(f"*/skills/{sid}/SKILL.md"))
            full = " ".join(read_front_matter(path)["description"].split())
            first = full.split(". ")[0].rstrip(".")
            self.assertEqual(ln, f"- `{sid}` — {first}.")
            self.assertLessEqual(len(ln), len(f"- `{sid}` — {full}"))
        self.assertLess(len(self.block()), 3200)

    def test_check_is_stable(self):  # P81-AC-039
        self.enable("plugin")
        self.agents_md()
        self.assertEqual(self.block(), self.block())
        self.assertEqual(self.agents_md("--check")["targets"][0]["status"], "unchanged")
        self.claude.write_text(self.claude.read_text().replace("Roles in", "Our roles in"))
        code, _env, err = run_json("agents-md", "--target", "CLAUDE.md", "--check", *self.R)
        self.assertEqual((code, err), (1, ""))
