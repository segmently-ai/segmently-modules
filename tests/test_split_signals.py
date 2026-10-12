"""P8.4 Task 5: skill split signals (D5) — MS068 / MS069, the `[budgets]` keys — and the
references a skill names (MS062, SI-P84-6) with the argument keys of its front matter."""
import hashlib
import os
import re
import tempfile
import unittest
from pathlib import Path

from tests.helpers import changelog_since_first_release, copy_fixture, run, run_json

S, P = 9000, 60000
SHELF = "stock-check"


def skill_text(size: int, name: str = SHELF, extra: str = "") -> str:
    """A SKILL.md of exactly `size` characters."""
    head = f"---\nname: {name}\ndescription: Checks the shelf stock.\n{extra}---\n"
    return head + "x" * (size - len(head))


class ShelfRepo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = copy_fixture(self._tmp.name)
        self.cfg = self.root / ".modsys"
        self.R = ("--root", str(self.root))

    def pack(self, skills: dict, pack_id: str = "shelf", body: str = "") -> Path:
        """skills: {id: {relative file: text}} — one repository pack declaring each."""
        d = self.cfg / "packs" / pack_id
        d.mkdir(parents=True, exist_ok=True)
        decl = "".join(f'[skills.{sid}]\npath = "skills/{sid}"\n' for sid in skills)
        (d / "pack.toml").write_text(f'id = "{pack_id}"\nversion = "0.1.0"\n{body}{decl}',
                                     encoding="utf-8")
        for sid, files in skills.items():
            for rel, text in files.items():
                f = d / "skills" / sid / rel
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(text, encoding="utf-8")
        return d

    def config(self, text: str, name: str = "config.toml") -> None:
        self.cfg.mkdir(exist_ok=True)
        (self.cfg / name).write_text(text, encoding="utf-8")

    def lint(self, *argv, prefix=("MS06", "MS07"), fail_on="never"):
        code, env, err = run_json("lint", "--fail-on", fail_on, *argv, *self.R)
        self.assertEqual(err, "")
        return code, [(f["code"], f["severity"], f["module"], f["message"], f["path"])
                      for f in env["data"]["findings"] if f["code"].startswith(prefix)]

    def codes(self, *codes, **kw):
        return [f for f in self.lint(**kw)[1] if f[0] in codes]


class Ms068Test(ShelfRepo):  # P84-AC-031
    def msg(self, label, n, s=S):
        return (f"{label}: {n} characters > skill split signal {s} — route its scenarios or "
                f"split the skill")

    def test_skill_md_at_and_over_the_boundary(self):
        self.pack({SHELF: {"SKILL.md": skill_text(S)}})
        self.assertEqual(self.codes("MS068"), [])
        self.pack({SHELF: {"SKILL.md": skill_text(S + 1)}})
        self.assertEqual(self.codes("MS068"), [
            ("MS068", "warning", "*", self.msg(SHELF, 9001),
             ".modsys/packs/shelf/skills/stock-check/SKILL.md")])

    def test_route_file_at_and_over_the_boundary(self):
        self.pack({SHELF: {"SKILL.md": skill_text(500), "references/restock.md": "y" * S}})
        self.assertEqual(self.codes("MS068"), [])
        self.pack({SHELF: {"SKILL.md": skill_text(500), "references/restock.md": "y" * (S + 1)}})
        self.assertEqual(self.codes("MS068"), [
            ("MS068", "warning", "*", self.msg("stock-check/restock", 9001),
             ".modsys/packs/shelf/skills/stock-check/references/restock.md")])

    def test_nested_and_non_markdown_files_are_not_measured(self):
        self.pack({SHELF: {"SKILL.md": skill_text(500), "references/deep/x.md": "y" * 20000,
                           "references/data.txt": "y" * 20000, "notes.md": "y" * 20000}})
        self.assertEqual(self.codes("MS068"), [])

    def test_a_file_that_is_not_utf8_is_not_measured(self):
        d = self.pack({SHELF: {"SKILL.md": skill_text(500)}})
        (d / "skills" / SHELF / "references").mkdir()
        (d / "skills" / SHELF / "references" / "bin.md").write_bytes(b"\xff" * 20000)
        self.assertEqual(self.codes("MS068"), [])

    def test_the_signal_is_configurable_in_every_layer(self):
        self.pack({SHELF: {"SKILL.md": skill_text(S + 1), "references/restock.md": "y"}})
        self.config("[budgets]\nskill_split_signal = 9001\n")
        self.assertEqual(self.codes("MS068"), [])
        self.config("[budgets]\nskill_split_signal = 1\n")
        self.assertEqual([f[3] for f in self.codes("MS068")],
                         [self.msg(SHELF, 9001, 1)])  # `y` is one character: not above 1
        self.config("", "config.toml")
        self.config("[budgets]\nskill_split_signal = 1\n", "config.user.toml")
        self.assertEqual(len(self.codes("MS068")), 1)
        (self.cfg / "config.user.toml").unlink()
        self.pack({SHELF: {"SKILL.md": skill_text(S + 1)}},
                  body="[budgets]\nskill_split_signal = 9001\n")
        self.assertEqual(self.codes("MS068"), [])

    def test_with_one_every_non_empty_skill_file_warns(self):
        self.pack({SHELF: {"SKILL.md": skill_text(300), "references/a.md": "aa",
                           "references/b.md": "b"}})
        self.config("[budgets]\nskill_split_signal = 1\n")
        self.assertEqual([f[3].split(":")[0] for f in self.codes("MS068")],
                         ["stock-check", "stock-check/a"])

    def test_exit_codes_follow_fail_on(self):
        self.pack({SHELF: {"SKILL.md": skill_text(S + 1)}})
        self.assertEqual(self.lint(fail_on="error")[0], 0)
        self.assertEqual(self.lint(fail_on="warning")[0], 1)

    def test_text_output_and_changed_mode(self):
        self.pack({SHELF: {"SKILL.md": skill_text(S + 1)}})
        code, out, err = run("lint", "--fail-on", "never", *self.R)
        self.assertIn("WARNING MS068 *: stock-check: 9001 characters > skill split signal 9000",
                      out)
        from tests.helpers import init_git
        init_git(self.root)
        code, env, err = run_json("lint", "--changed", "--fail-on", "never", *self.R)
        self.assertEqual([f for f in env["data"]["findings"]
                          if f["code"] in ("MS062", "MS068", "MS069")], [])


class Ms069Test(ShelfRepo):  # P84-AC-032
    def skills(self, total):
        sizes = [total // 7] * 7
        sizes[0] += total - sum(sizes)
        return {f"shelf-{i}": {"SKILL.md": skill_text(n, f"shelf-{i}")}
                for i, n in enumerate(sizes)}

    def test_boundary_counts_skill_md_only(self):
        self.pack(self.skills(P))
        self.assertEqual(self.codes("MS069"), [])
        skills = self.skills(P)
        skills["shelf-1"]["references/big.md"] = "r" * 20000
        self.pack(skills)
        self.assertEqual(self.codes("MS069"), [])
        self.pack(self.skills(P + 1))
        self.assertEqual(self.codes("MS069"), [
            ("MS069", "warning", "*", "pack 'shelf': 60001 characters of skills > pack split "
             "signal 60000 — route, split a skill out, or split the pack",
             ".modsys/packs/shelf/pack.toml")])

    def test_the_signal_is_configurable(self):
        self.pack(self.skills(P + 1))
        self.config("[budgets]\npack_split_signal = 60001\n")
        self.assertEqual(self.codes("MS069"), [])
        self.config("[budgets]\npack_split_signal = 100\n")
        self.assertIn("pack split signal 100", self.codes("MS069")[0][3])

    def test_core_at_this_base_does_not_cross(self):
        self.config('[packs]\nbuiltin = ["core", "qa", "ui"]\n')
        self.assertEqual(self.codes("MS068", "MS069"), [])


class EveryPackTest(ShelfRepo):  # P84-AC-033
    def test_repository_pack_with_a_builtin_id(self):
        self.pack({SHELF: {"SKILL.md": skill_text(S + 1)}}, pack_id="core")
        self.assertEqual([f[0] for f in self.codes("MS068")], ["MS068"])

    def test_builtin_enabled_in_each_config_file_and_not_enabled(self):
        self.config("[budgets]\nskill_split_signal = 1\npack_split_signal = 1\n")
        self.assertEqual(self.codes("MS068", "MS069"), [])  # no pack enabled
        self.config('[packs]\nbuiltin = ["qa"]\n[budgets]\nskill_split_signal = 1\n'
                    'pack_split_signal = 1\n')
        found = self.codes("MS068", "MS069")
        self.assertTrue(found)
        self.assertIn("MS069", [f[0] for f in found])
        self.assertTrue(all("packs/ui" not in f[4] and "packs/core" not in f[4] for f in found))
        self.config('[budgets]\nskill_split_signal = 1\npack_split_signal = 1\n')
        self.config('[packs]\nbuiltin = ["ui"]\n', "config.user.toml")
        users = self.codes("MS069")
        self.assertEqual([f[3].split("'")[1] for f in users], ["ui"])

    def test_an_ejected_copy_warns_under_its_label_and_is_never_counted(self):
        self.pack({SHELF: {"SKILL.md": skill_text(500)}})
        code, env, err = run_json("eject", SHELF, *self.R)
        self.assertEqual(code, 0, err)
        copy = self.cfg / "overrides/skills" / SHELF
        (copy / "SKILL.md").write_text(skill_text(S + 1), encoding="utf-8")
        found = self.codes("MS068", "MS069")
        self.assertEqual(found, [("MS068", "warning", "*", f"{SHELF}: 9001 characters > skill "
                                  f"split signal 9000 — route its scenarios or split the skill",
                                  ".modsys/overrides/skills/stock-check/SKILL.md")])
        self.config("[budgets]\npack_split_signal = 1\n")
        self.assertEqual([f for f in self.codes("MS069")], [
            ("MS069", "warning", "*", "pack 'shelf': 500 characters of skills > pack split "
             "signal 1 — route, split a skill out, or split the pack",
             ".modsys/packs/shelf/pack.toml")])


class BudgetKeysTest(ShelfRepo):  # P84-AC-034
    KEYS = ("skill_split_signal", "pack_split_signal")
    BAD = (("0", "0"), ("-1", "-1"), ('"9000"', "'9000'"), ("true", "True"),
           ("9000.5", "9000.5"))

    def layer(self, where: str, text: str) -> None:
        import shutil
        shutil.rmtree(self.cfg / "packs", ignore_errors=True)
        for name in ("config.toml", "config.user.toml"):
            (self.cfg / name).unlink(missing_ok=True)
        if where == "pack":
            self.pack({SHELF: {"SKILL.md": skill_text(300)}}, body=text)
        else:
            self.config(text, where)

    def test_valid_values_are_accepted(self):
        for where in ("config.toml", "config.user.toml", "pack"):
            for key in self.KEYS:
                for value in ("1", "9000"):
                    with self.subTest(where=where, key=key, value=value):
                        self.layer(where, f"[budgets]\n{key} = {value}\n")
                        for verb in (["lint"], ["list"], ["catalog"]):
                            code, out, err = run(*verb, *self.R)
                            self.assertIn(code, (0, 1), (verb, err))
                            self.assertEqual(err, "")

    def test_refused_values_name_the_key_in_every_layer_and_verb(self):
        for where in ("config.toml", "config.user.toml", "pack"):
            for key in self.KEYS:
                for value, shown in self.BAD:
                    with self.subTest(where=where, key=key, value=value):
                        self.layer(where, f"[budgets]\n{key} = {value}\n")
                        for verb in (["lint"], ["list"], ["catalog"]):
                            code, out, err = run(*verb, *self.R)
                            self.assertEqual((code, out), (2, ""), verb)
                            self.assertRegex(err, r"\A" + re.escape("modsys: error: ")
                                             + r"[^\n]*\.toml: " + re.escape(
                                                 f"[budgets] {key}: expected an integer >= 1, "
                                                 f"got {shown}") + r"\n\Z")
                            self.assertNotIn("Traceback", err)

    def test_the_defaults_file_holds_both_keys(self):
        from modsys.config import core_defaults
        b = core_defaults()["budgets"]
        self.assertEqual((b["skill_split_signal"], b["pack_split_signal"]), (9000, 60000))

    def test_the_starter_config_of_init_is_unchanged(self):
        from modsys.init_cmd import starter_config
        for layout in ("single", "per-module"):
            self.assertNotIn("skill_split_signal", starter_config(layout))
            self.assertNotIn("pack_split_signal", starter_config(layout))


class ReferencesTest(ShelfRepo):  # P84-AC-029
    def refs(self, *, skill_md="", files=None):
        text = skill_text(300) + skill_md
        self.d = self.pack({SHELF: {"SKILL.md": text, **(files or {})}})
        self.src = self.d / "skills" / SHELF

    def ms062(self):
        return self.codes("MS062")

    def test_named_and_present_raises_nothing_and_unnamed_extra_is_fine(self):
        self.refs(skill_md="\nRead `references/restock.md`, then references/restock.md.\n",
                  files={"references/restock.md": "# restock\n", "references/extra.md": "x\n"})
        self.assertEqual(self.ms062(), [])

    def test_missing_name(self):
        self.refs(skill_md="\nRead references/missing.md first.\n")
        self.assertEqual(self.ms062(), [
            ("MS062", "error", "*", "skill 'stock-check' of pack 'shelf': SKILL.md names "
             "references/missing.md, which does not exist",
             ".modsys/packs/shelf/skills/stock-check/SKILL.md")])

    def test_name_outside_the_skill_directory(self):
        self.refs(skill_md="\nSee (references/../../outside.md).\n")
        (self.d / "outside.md").write_text("o\n")
        self.assertEqual([f[3] for f in self.ms062()], [
            "skill 'stock-check' of pack 'shelf': SKILL.md names references/../../outside.md, "
            "which is outside the skill directory"])

    def test_missing_name_reached_only_from_a_route_file(self):
        self.refs(skill_md="\nRoute: references/restock.md\n",
                  files={"references/restock.md": "then references/missing.md\n"})
        self.assertEqual(self.ms062(), [
            ("MS062", "error", "*", "skill 'stock-check' of pack 'shelf': references/restock.md "
             "names references/missing.md, which does not exist",
             ".modsys/packs/shelf/skills/stock-check/references/restock.md")])

    def test_placeholders_and_globs_in_prose_name_no_file(self):
        self.refs(skill_md="\nOne file per scenario in references/<scenario>.md, i.e. "
                           "references/*.md, all under references/.\n")
        self.assertEqual(self.ms062(), [])

    def test_a_symlinked_route_keeps_the_old_text_and_is_invalid_for_sync(self):
        self.refs(skill_md="\nRoute: references/restock.md\n")
        (self.src / "references").mkdir()
        outside = self.root / "elsewhere.md"
        outside.write_text("e\n")
        os.symlink(outside, self.src / "references" / "restock.md")
        self.assertEqual([f[3] for f in self.ms062()], [
            "skill 'stock-check' of pack 'shelf' is not loadable by agents: symlink in "
            "source: references/restock.md"])
        code, env, err = run_json("packs", "sync", "--agent", "claude", *self.R)
        self.assertEqual([r["status"] for r in env["data"]["skills"]], ["invalid"])

    def test_sync_and_eject_do_not_look_at_names(self):
        self.refs(skill_md="\nRead references/missing.md.\n",
                  files={"references/extra.md": "x\n"})
        code, env, err = run_json("packs", "sync", "--agent", "claude", *self.R)
        self.assertEqual((code, [r["status"] for r in env["data"]["skills"]]), (0, ["created"]))
        self.assertTrue((self.root / ".claude/skills" / SHELF / "references/extra.md").is_file())
        code, env, err = run_json("eject", SHELF, *self.R)
        self.assertEqual(code, 0, err)

    def test_the_same_in_an_ejected_copy(self):
        self.refs()
        self.assertEqual(run("eject", SHELF, *self.R)[0], 0)
        copy = self.cfg / "overrides/skills" / SHELF
        (copy / "SKILL.md").write_text(skill_text(300) + "\nRead references/missing.md\n")
        found = [f for f in self.ms062() if "ejected" in f[3]]
        self.assertEqual(found, [
            ("MS062", "error", "*", "ejected skill 'stock-check' (.modsys/overrides/skills/"
             "stock-check): SKILL.md names references/missing.md, which does not exist",
             ".modsys/overrides/skills/stock-check/SKILL.md")])

    def test_changed_mode_raises_none(self):
        self.refs(skill_md="\nRead references/missing.md\n")
        from tests.helpers import init_git
        init_git(self.root)
        code, env, err = run_json("lint", "--changed", "--fail-on", "never", *self.R)
        self.assertEqual([f for f in env["data"]["findings"] if f["code"] == "MS062"], [])

    def test_the_shipped_skills_raise_none(self):
        self.config('[packs]\nbuiltin = ["core", "qa", "ui"]\n')
        self.assertEqual(self.ms062(), [])

    # final review I-3: ordinary Markdown around a name is not part of it
    PRESENT = {"references/restock.md": "# restock\n\n## steps\n"}

    def missing_names(self):
        return [f[3].split(" names ", 1)[1].split(", which", 1)[0] for f in self.ms062()]

    def test_an_anchor_or_a_query_ends_the_name(self):
        self.refs(skill_md="\nSee [steps](references/restock.md#steps), references/restock.md?plain=1"
                           " and [gone](references/missing.md#steps).\n", files=self.PRESENT)
        self.assertEqual(self.missing_names(), ["references/missing.md"])

    def test_a_table_cell_italics_and_dashes_end_the_name(self):
        for probe in ("| step |references/restock.md| file |", "| references/restock.md | x |",
                      "_references/restock.md_", "__references/restock.md__",
                      "references/restock.md\u2014it holds the steps",
                      "references/restock.md\u2013it holds the steps"):
            with self.subTest(probe=probe):
                self.refs(skill_md=f"\n{probe}\n", files=self.PRESENT)
                self.assertEqual(self.ms062(), [])

    def test_a_bold_name_is_checked(self):
        self.refs(skill_md="\nRead **references/restock.md**, then **references/missing-bold.md**."
                           "\n", files=self.PRESENT)
        self.assertEqual(self.missing_names(), ["references/missing-bold.md"])

    def test_ci_passes_a_pack_that_links_a_section(self):
        from tests.helpers import init_git
        self.refs(skill_md="\nSee [steps](references/restock.md#steps).\n", files=self.PRESENT)
        init_git(self.root)
        code, env, err = run_json("ci", "--base", "HEAD", "--fail-on", "error", *self.R)
        self.assertEqual((code, err), (0, ""))
        lint = next(st for st in env["data"]["steps"] if st["name"] == "lint")
        self.assertEqual([f for f in lint["findings"] if f["code"] == "MS062"], [])


class ArgumentKeysTest(ShelfRepo):  # P84-AC-028
    HINTS = ('argument-hint: "[scenario]"', "argument-hint: '[scenario]'",
             "argument-hint: [scenario]", "argument-hint: pick one")
    ARGS = ("arguments: scenario", 'arguments: "scenario"', "arguments: [scenario, depth]")

    def test_every_form_passes_lint_sync_and_eject(self):
        for hint in self.HINTS:
            for args in self.ARGS:
                with self.subTest(hint=hint, args=args):
                    self.pack({SHELF: {"SKILL.md": skill_text(
                        300, extra=f"{hint}\n{args}\n")}})
                    self.assertEqual(self.lint()[1], [])
                    argv = ("packs", "sync", "--agent", "claude", "--agent", "codex", *self.R)
                    code, env, err = run_json(*argv)
                    self.assertEqual([r["status"] for r in env["data"]["skills"]],
                                     ["created", "created"])
                    code, env, err = run_json(*argv)
                    self.assertEqual([r["status"] for r in env["data"]["skills"]],
                                     ["unchanged", "unchanged"])
                    self.assertEqual(run("eject", SHELF, *self.R)[0], 0)
                    import shutil
                    shutil.rmtree(self.root / ".claude", ignore_errors=True)
                    shutil.rmtree(self.root / ".agents", ignore_errors=True)
                    shutil.rmtree(self.cfg / "overrides", ignore_errors=True)

    def test_description_and_name_checks_are_unchanged(self):
        text = "---\nname: stock-check\ndescription: a: b\nargument-hint: [x]\n---\n"
        self.pack({SHELF: {"SKILL.md": text}})
        self.assertEqual([f[3] for f in self.codes("MS062")], [
            "skill 'stock-check' of pack 'shelf' is not loadable by agents: SKILL.md "
            "description: quote the value — a plain YAML value cannot contain ': ' (agents' "
            "YAML loaders reject it)"])
        self.pack({SHELF: {"SKILL.md": "---\ndescription: ok\narguments: x\n---\n"}})
        self.assertIn("SKILL.md front matter has no name", self.codes("MS062")[0][3])


class NoCrossingTest(ShelfRepo):  # P84-AC-036
    def test_clean_repository_lint_has_no_new_codes_and_ci_lists_a_planted_warning(self):
        self.config('[packs]\nbuiltin = ["core", "qa", "ui"]\n')
        self.assertEqual(self.codes("MS062", "MS068", "MS069"), [])
        from tests.helpers import init_git
        init_git(self.root)  # the clean tree: ci's lint step lists nothing of the new codes
        code, env, err = run_json("ci", "--base", "HEAD", *self.R)
        lint = next(st for st in env["data"]["steps"] if st["name"] == "lint")
        self.assertEqual([f["code"] for f in lint["findings"]
                          if f["code"] in ("MS062", "MS068", "MS069")], [])
        self.pack({SHELF: {"SKILL.md": skill_text(S + 1)}})  # one planted crossing
        for fail_on, expected in (("error", 0), ("warning", 1)):
            with self.subTest(fail_on=fail_on):
                code, env, err = run_json("ci", "--base", "HEAD", "--fail-on", fail_on, *self.R)
                self.assertEqual((code, err), (expected, ""))
                lint = next(st for st in env["data"]["steps"] if st["name"] == "lint")
                self.assertEqual([(f["code"], f["severity"]) for f in lint["findings"]],
                                 [("MS068", "warning")])
                self.assertEqual(lint["status"], "failed" if expected else "passed")


class DocsTest(unittest.TestCase):  # P84-AC-037
    ENGINE = Path(__file__).resolve().parent.parent

    def doc(self, rel):
        return (self.ENGINE / rel).read_text(encoding="utf-8")

    def test_configuration_reference(self):
        text = self.doc("docs/configuration.md")
        for needle in ("| `skill_split_signal` | `9000` |", "| `pack_split_signal` | `60000` |",
                       "An integer >= 1", "| MS068 | warning |", "| MS069 | warning |",
                       "`references/*.md`", "(plain `lint` only)"):
            self.assertIn(needle, text)
        for code in ("MS068", "MS069"):
            row = next(l for l in text.splitlines() if l.startswith(f"| {code} |"))
            self.assertTrue(row.endswith("(plain `lint` only) |"), row)
        self.assertIn("does not exist or lies outside the skill directory", text)

    def test_writing_a_pack(self):
        text = self.doc("docs/writing-a-pack.md")
        for needle in ("Size is a decomposition signal", "Never trim a useful rule",
                       "**Route** block", "Every\n`references/` file a skill names must exist "
                       "inside the skill directory", "| MS068 |", "| MS069 |"):
            self.assertIn(needle, text)

    def test_lint_docstring_and_changelog(self):
        import modsys.lint
        self.assertIn("MS068", modsys.lint.__doc__)
        self.assertIn("MS069", modsys.lint.__doc__)
        changelog = changelog_since_first_release(self.doc("CHANGELOG.md"))
        for needle in ("MS068", "MS069", "skill_split_signal", "pack_split_signal", "SPLIT_DECISIONS"):
            self.assertIn(needle, changelog)


if __name__ == "__main__":
    unittest.main()
