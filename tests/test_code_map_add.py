"""`modsys code-map add`: appends one rule to the team config — never a rewrite, never a
damaged file."""
import hashlib
import os
import stat
import tempfile
import tomllib
import unittest
from pathlib import Path

from tests.helpers import git, make_repo, run, run_json

DESC = "Task items: create, complete, reorder; the home of a single task."


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AddTest(unittest.TestCase):  # P32-AC-010
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve() / "repo"
        self.root.mkdir()
        git(self.root, "init", "-q", "-b", "main")
        self.R = ("--root", str(self.root))
        run("init", *self.R)
        for name in ("tasks", "lists"):
            self.assertEqual(run("create", name, "--non-interactive", "--description", DESC,
                                 "--keyword", f"{name}-a", "--keyword", f"{name}-b",
                                 "--keyword", f"{name}-c", "--keyword", f"{name}-d",
                                 "--keyword", f"{name}-e", *self.R)[0], 0)
        self.team = self.root / ".modsys" / "config.toml"

    def tearDown(self):
        self._tmp.cleanup()

    def add(self, *argv):
        code, env, err = run_json("code-map", "add", *argv, *self.R)
        self.assertEqual((code, err, env["schema"]), (0, "", "modsys.code-map/1"))
        return env["data"]

    def test_appends_one_rule_and_it_takes_effect(self):
        before = self.team.read_bytes()
        data = self.add("tasks-src", "--glob", "src/tasks/**", "--module", "tasks")
        block = '[[code_map]]\nid = "tasks-src"\nmodule = "tasks"\nglobs = ["src/tasks/**"]\n'
        self.assertEqual(data, {"id": "tasks-src", "file": ".modsys/config.toml", "block": block,
                                "dry_run": False})
        self.assertEqual(self.team.read_bytes(), before + b"\n" + block.encode())
        (self.root / "src/tasks").mkdir(parents=True)
        (self.root / "src/tasks/a.py").write_text("x = 1\n")
        _, env, _ = run_json("coverage", *self.R)
        self.assertEqual(env["data"]["modules"], {"tasks": 1})
        _, env, _ = run_json("code-map", "list", *self.R)
        self.assertIn({"id": "tasks-src", "module": "tasks", "pattern": None,
                       "globs": ["src/tasks/**"], "exclusive": False}, env["data"])

    def test_pattern_exclusive_and_several_globs(self):
        self.assertEqual(self.add("feat", "--pattern", "app/{module}/**", "--exclusive")["block"],
                         '[[code_map]]\nid = "feat"\npattern = "app/{module}/**"\n'
                         'exclusive = true\n')
        self.assertEqual(self.add("two", "--glob", "a/**", "--glob", "b/**", "--module",
                                  "lists")["block"],
                         '[[code_map]]\nid = "two"\nmodule = "lists"\nglobs = ["a/**", "b/**"]\n')
        rules = {r["id"]: r for r in tomllib.loads(self.team.read_text())["code_map"]}
        self.assertEqual(set(rules), {"feat", "two"})

    def test_dry_run_writes_nothing(self):
        before = sha(self.team)
        data = self.add("x", "--glob", "src/x/**", "--module", "tasks", "--dry-run")
        self.assertEqual((data["dry_run"], data["block"].splitlines()[1]), (True, 'id = "x"'))
        self.assertEqual(sha(self.team), before)
        out = run("code-map", "add", "x", "--glob", "src/x/**", "--module", "tasks", "--dry-run",
                  *self.R)[1]
        self.assertTrue(out.startswith("would append to .modsys/config.toml:\n[[code_map]]\n"))

    def test_the_same_id_again_is_refused(self):
        self.add("tasks-src", "--glob", "src/tasks/**", "--module", "tasks")
        before = sha(self.team)
        code, out, err = run("code-map", "add", "tasks-src", "--glob", "src/tasks/**",
                             "--module", "tasks", *self.R)
        self.assertEqual((code, out, sha(self.team)), (2, "", before))
        self.assertIn("already defined", err)


class RefusalTest(unittest.TestCase):  # P32-AC-011
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_repo(self._tmp.name, {"tasks": ["task"], "lists": ["list"]},
                              '## team config\n[[code_map]]\nid = "team-rule"\nmodule = "tasks"\n'
                              'globs = ["t/**"]\n')
        self.team = self.root / ".modsys" / "config.toml"
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def refused(self, *argv) -> str:
        before = self.team.read_bytes() if self.team.exists() else None
        code, out, err = run("code-map", "add", *argv, "--json", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("modsys: error:"), err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(self.team.read_bytes() if self.team.exists() else None, before)
        return err

    def test_argument_refusals(self):
        for argv, needle in [
                (("x", "--module", "nosuch", "--glob", "a/**"),
                 "'nosuch' is not a registry module or child"),
                (("d", "--pattern", "docs/**"),
                 'code_map.d: pattern "docs/**" has no {module} segment — for a fixed module use '
                 'globs = ["docs/**"] and module = "NAME"'),
                (("x", "--pattern", "a/{module}/**", "--glob", "b/**", "--module", "tasks"),
                 "give --pattern or --glob"),
                (("x",), "give --pattern or --glob"),
                (("x", "--glob", "a/**"), "--glob needs --module"),
                (("", "--glob", "a/**", "--module", "tasks"), "id must be a non-empty string"),
                ((), "code-map add needs an ID")]:
            with self.subTest(argv=argv):
                self.assertIn(needle, self.refused(*argv))

    def test_id_defined_in_any_layer(self):
        pack = self.root / ".modsys" / "packs" / "acme" / "pack.toml"
        pack.parent.mkdir(parents=True)
        pack.write_text('id = "acme"\n[[code_map]]\nid = "pack-rule"\npattern = "p/{module}/**"\n')
        (self.root / ".modsys" / "config.user.toml").write_text(
            '[[code_map]]\nid = "user-rule"\nmodule = "lists"\nglobs = ["u/**"]\n')
        for rule_id, where in (("team-rule", "config.toml"), ("pack-rule", "pack acme"),
                               ("user-rule", "config.user.toml")):
            with self.subTest(rule_id=rule_id):
                err = self.refused(rule_id, "--glob", "z/**", "--module", "tasks")
                self.assertIn("already defined", err)
                self.assertIn(where, err)

    def test_no_team_config(self):
        self.team.unlink()
        self.assertIn("run `modsys init` first", self.refused("x", "--glob", "a/**", "--module",
                                                              "tasks"))

    def test_a_static_code_map_array_makes_the_append_invalid(self):
        self.team.write_text("code_map = []\n")
        err = self.refused("x", "--glob", "a/**", "--module", "tasks")
        self.assertIn("would make", err)
        self.assertIn("invalid", err)

    def test_add_only_flags_elsewhere(self):
        code, out, err = run("code-map", "list", "--glob", "a/**", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("apply to code-map add", err)


class WriteSafetyTest(unittest.TestCase):  # P32-AC-012
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_repo(self._tmp.name, {"tasks": ["task"]}, "# starter\n")
        self.team = self.root / ".modsys" / "config.toml"
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def add(self, *globs) -> dict:
        argv = [a for g in globs for a in ("--glob", g)]
        code, env, err = run_json("code-map", "add", "r", *argv, "--module", "tasks", *self.R)
        self.assertEqual((code, err), (0, ""))
        return tomllib.loads(self.team.read_text(encoding="utf-8"))

    def test_the_init_starter_is_kept_byte_for_byte(self):
        self.team.unlink()
        self.assertEqual(run("init", *self.R)[0], 0)  # writes the commented starter
        before = self.team.read_bytes()
        self.add("src/**")
        self.assertTrue(self.team.read_bytes().startswith(before + b"\n[[code_map]]\n"))

    def test_crlf_endings_and_a_missing_final_newline(self):
        self.team.write_bytes(b"# team\r\n[paths]\r\nmodules_dir = \"modules\"\r\n")
        before = self.team.read_bytes()
        self.add("src/**")
        after = self.team.read_bytes()
        self.assertEqual(after, before + b'\r\n[[code_map]]\r\nid = "r"\r\nmodule = "tasks"\r\n'
                                          b'globs = ["src/**"]\r\n')
        self.team.write_bytes(b"# no newline")
        self.add("src/**")
        self.assertTrue(self.team.read_bytes().startswith(b"# no newline\n\n[[code_map]]\n"))

    def test_symlink_and_mode_are_kept(self):
        shared = self.root / "shared" / "modsys.toml"
        shared.parent.mkdir()
        shared.write_text("# shared team config\n")
        self.team.unlink()
        self.team.symlink_to(shared)
        os.chmod(shared, 0o600)
        self.add("src/**")
        self.assertTrue(self.team.is_symlink())
        self.assertIn('id = "r"', shared.read_text())
        self.assertEqual(stat.S_IMODE(shared.stat().st_mode), 0o600)

    def test_quotes_backslashes_non_ascii_and_newlines_read_back_exactly(self):
        for glob in ('src/"q"\\x/é/**', "src/a\nid = \"injected\"\n[x]/**", "tab\there/**"):
            with self.subTest(glob=glob):
                self.team.write_text("# team\n")
                config = self.add(glob)
                self.assertEqual(config, {"code_map": [{"id": "r", "module": "tasks",
                                                        "globs": [glob]}]})


if __name__ == "__main__":
    unittest.main()
