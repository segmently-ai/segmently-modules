"""`modsys adopt` (D2): the config an existing registry needs, inferred with its evidence —
paths, roles, fields, the dir whitelist, updated_at_path, a code-map rule, budgets (commented
out); written to config.toml or adopt.proposed.toml, never touching the registry or its docs;
lint in report mode; the fixture regenerates equivalent declarations (row 5.1)."""
import hashlib
import json
import os
import re
import shutil
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from modsys.adopt_cmd import ADOPT_CLAUSE, STARTER_CLAUSE, adopt_header
from modsys.cli import build_parser
from modsys.config import load_config
from modsys.init_cmd import _HEADER
from tests.helpers import FIXTURE, run, run_json
from tests.test_cli_contract import DOC as CONTRACT, GOLDEN

KEY_LINE = re.compile(r"^(?:[A-Za-z0-9_-]+|\"[^\"]*\") = ")


def manifest(root: Path, skip: str = ".modsys") -> dict:
    """sha256 of every file outside `skip` (paths relative to the root)."""
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file() and not p.is_symlink()
            and p.relative_to(root).parts[0] not in (skip, ".git")}


def entry(name: str, **extra) -> dict:
    doc = f"modules/{name}/MODULE.md"
    return {"name": name, "description": f"The {name} module.", "status": "active",
            "keywords": [name], "context_files": {"universal": doc}, **extra}


class AdoptRepo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve() / "repo"
        self.root.mkdir()
        self.R = ("--root", str(self.root))

    def tearDown(self):
        for path in self.root.rglob("*"):
            if path.is_dir() and not path.is_symlink():
                os.chmod(path, 0o755)
        self._tmp.cleanup()

    def registry(self, modules: dict, rel: str = "modules/registry.json", docs=True,
                 **top) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"modules": modules, **top}, indent=2) + "\n")
        for name, e in modules.items() if docs else ():
            for label, sub in [(name, e)] + [(f"{name}/{c}", s) for c, s in
                                             (e.get("submodules") or {}).items()]:
                cf = sub.get("context_files") or {}
                for doc in [cf.get("universal")] + list((cf.get("roles") or {}).values()):
                    if isinstance(doc, str) and not (self.root / doc).exists():
                        (self.root / doc).parent.mkdir(parents=True, exist_ok=True)
                        (self.root / doc).write_text(f"# {label}\n")
        return path

    def write(self, rel: str, text: str = "x = 1\n") -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def adopt(self, *argv, code=0) -> dict:
        got, env, err = run_json("adopt", *argv, *self.R)
        self.assertEqual((got, err), (code, ""), env)
        if code == 0:
            self.assertEqual(env["schema"], "modsys.adopt/1")
            return env["data"]
        return env

    def refused(self, *argv) -> str:
        before = manifest(self.root, skip="")
        code, out, err = run("adopt", *argv, "--json", *self.R)
        self.assertEqual((code, out), (2, ""), err)
        self.assertTrue(err.startswith("modsys: error: "), err)
        self.assertEqual(manifest(self.root, skip=""), before)
        return err

    def toml(self, data: dict) -> dict:
        return tomllib.loads(data["config"])


class AdoptOutputsTest(AdoptRepo):  # P5A-AC-015
    def setUp(self):
        super().setUp()
        self.registry({"catalog": entry("catalog", file_paths=["src/catalog/a.py"])})
        self.write("src/catalog/a.py")
        self.write(".gitignore", "node_modules/\n")

    def check_text(self, text: str) -> None:
        self.assertTrue(text.startswith(adopt_header()))
        flat = " ".join(_HEADER.replace("##", " ").split())
        self.assertEqual(" ".join(adopt_header().replace("##", " ").split()),
                         flat.replace(STARTER_CLAUSE, ADOPT_CLAUSE))
        layer = tomllib.loads(text)
        self.assertNotIn("packs", layer)
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if KEY_LINE.match(line):
                self.assertTrue(lines[i + 1].startswith("# adopt: "), line)

    def untouched(self, *argv) -> dict:
        """`adopt` with every file outside the config dir byte-identical before and after."""
        before = manifest(self.root)
        data = self.adopt(*argv)
        self.assertEqual(manifest(self.root), before)
        self.assertFalse((self.root / "modules/registry.json.lock").exists())
        return data

    def test_the_decision_table(self):
        data = self.untouched("--dry-run")  # absent, dry run: nothing, not even .modsys/
        self.assertFalse((self.root / ".modsys").exists())
        self.assertEqual((data["config_path"], data["dry_run"]), (".modsys/config.toml", True))
        self.check_text(data["config"])
        data = self.untouched()  # absent: config.toml created
        config = self.root / ".modsys/config.toml"
        self.assertEqual(config.read_text(), data["config"])
        self.check_text(config.read_text())
        load_config(self.root / ".modsys", self.root)
        self.assertEqual((data["config_path"], data["dry_run"]), (".modsys/config.toml", False))
        self.assertEqual(set(data), {"root", "registry", "layout", "inferred", "config_path",
                                     "config", "lint", "next_steps", "dry_run"})
        self.assertEqual(set(data["inferred"]), {"paths", "roles", "fields", "dir_whitelist",
                                                 "updated_at_path", "code_map", "budgets",
                                                 "skipped"})
        steps = " ".join(data["next_steps"])
        self.assertIn("review .modsys/config.toml", steps)
        self.assertIn('[packs] builtin = ["core"]', steps)
        stamp = (config.read_bytes(), config.stat().st_mtime_ns)
        self.write("src/checkout/b.py")
        self.registry({"catalog": entry("catalog", file_paths=["src/catalog/a.py"]),
                       "checkout": entry("checkout", owner="team-b")})
        data = self.untouched("--dry-run")  # present, dry run: nothing
        self.assertFalse((self.root / ".modsys/adopt.proposed.toml").exists())
        self.assertEqual(data["config_path"], ".modsys/adopt.proposed.toml")
        data = self.untouched()  # present: the proposal, config.toml untouched
        proposal = self.root / ".modsys/adopt.proposed.toml"
        self.assertEqual(proposal.read_text(), data["config"])
        self.assertEqual(self.toml(data)["fields"], {"owner": {"type": "string",
                                                               "scope": ["module"]}})
        self.assertEqual((config.read_bytes(), config.stat().st_mtime_ns), stamp)
        self.assertIn("merge .modsys/adopt.proposed.toml into .modsys/config.toml by hand",
                      " ".join(data["next_steps"]))
        self.check_text(proposal.read_text())
        config.write_text(config.read_text() + '\n[fields.owner]\ntype = "string"\n')
        self.untouched()  # present, nothing left: header + nothing to add
        self.assertEqual(proposal.read_text(), adopt_header() + "# adopt: nothing to add\n")

    def test_a_config_dir_of_its_own(self):
        before = manifest(self.root, skip="cfg")
        data = self.adopt("--config-dir", str(self.root / "cfg"))
        self.assertEqual(data["config_path"], "cfg/config.toml")
        self.assertTrue((self.root / "cfg/config.toml").is_file())
        self.assertEqual(manifest(self.root, skip="cfg"), before)

    def test_text_output(self):
        code, out, err = run("adopt", "--dry-run", *self.R)
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(out.startswith(adopt_header()))
        self.assertIn("[fields.file_paths]", out)
        self.assertIn("would write .modsys/config.toml", out)
        code, out, _ = run("adopt", *self.R)
        self.assertNotIn("[fields.file_paths]", out)
        self.assertIn("wrote .modsys/config.toml", out)
        self.assertIn("next: review .modsys/config.toml", out)


class RoleInferenceTest(AdoptRepo):  # P5A-AC-016
    def standard(self, total: int, carrying: int) -> bool:
        shutil.rmtree(self.root / "modules", ignore_errors=True)
        modules = {}
        for i in range(total):
            name = f"m{i:02}"
            roles = {"reviewer": f"modules/{name}/roles/reviewer.md"} if i < carrying else {}
            modules[name] = entry(name, context_files={"universal": f"modules/{name}/MODULE.md",
                                                       "roles": roles})
        self.registry(modules)
        return self.toml(self.adopt("--dry-run"))["roles"]["reviewer"]["standard"]

    def test_the_80_percent_boundary(self):
        for total, carrying, expected in [(5, 4, True), (5, 3, False), (4, 3, False),
                                          (10, 8, True), (10, 7, False), (1, 1, True)]:
            with self.subTest(total=total, carrying=carrying):
                self.assertIs(self.standard(total, carrying), expected)

    def test_only_a_child_carries_it(self):
        refunds = {"description": "Refunds.", "keywords": ["refund"], "context_files": {
            "universal": "modules/a/submodules/r/MODULE.md",
            "roles": {"reviewer": "modules/a/submodules/r/roles/reviewer.md"}}}
        self.registry({"a": entry("a", submodules={"r": refunds}), "b": entry("b"),
                       "c": entry("c")})
        data = self.adopt("--dry-run")
        self.assertEqual(data["inferred"]["roles"], [{"name": "reviewer", "order": 50,
                                                      "standard": False, "modules": ["a/r"]}])
        self.assertIn("carried by 1 entry: a/r", data["config"])

    def test_order_and_declared_roles(self):
        def carry(*roles):
            return {"universal": "modules/x/MODULE.md",
                    "roles": {r: f"modules/x/roles/{r}.md" for r in roles}}
        self.registry({"a": entry("a", context_files=carry("auditor", "reviewer", "ux",
                                                           "developer", "team_role")),
                       "b": entry("b", context_files=carry("auditor", "reviewer")),
                       "c": entry("c", context_files=carry("auditor", "reviewer"))})
        self.write(".modsys/packs/team/pack.toml", 'id = "team"\n[roles.team_role]\norder = 45\n')
        data = self.adopt("--dry-run")
        rows = [(r["name"], r["order"]) for r in data["inferred"]["roles"]]
        self.assertEqual(rows, [("auditor", 55), ("reviewer", 65), ("ux", 75)])
        roles = self.toml(data)["roles"]
        for spec in roles.values():
            self.assertEqual(set(spec), {"order", "standard"})
        self.write(".modsys/config.toml", '[roles.auditor]\norder = 70\n')
        rows = [(r["name"], r["order"]) for r in self.adopt("--dry-run")["inferred"]["roles"]]
        self.assertEqual(rows, [("reviewer", 80), ("ux", 90)])


class FieldInferenceTest(AdoptRepo):  # P5A-AC-017
    def fields(self, modules: dict) -> tuple[dict, dict]:
        shutil.rmtree(self.root / "modules", ignore_errors=True)
        self.registry(modules)
        data = self.adopt("--dry-run")
        return self.toml(data).get("fields", {}), data["inferred"]

    def test_code_pointers_and_the_80_percent_boundary(self):
        self.write("src/catalog/service.py")
        self.write("src/b.py")
        decl, _ = self.fields({"catalog": entry("catalog", paths=["src/catalog/service.py"]),
                               "b": entry("b")})
        self.assertEqual(decl["paths"], {"type": "string[]", "kind": "code_pointer",
                                         "scope": ["module"]})
        for exist, total, kind in [(4, 5, "code_pointer"), (3, 4, None)]:
            with self.subTest(exist=exist, total=total):
                modules = {f"m{i}": entry(f"m{i}", home="src/b.py" if i < exist else "src/no.py")
                           for i in range(total)}
                decl, _ = self.fields(modules)
                self.assertEqual(decl["home"].get("kind"), kind)
                self.assertEqual(decl["home"]["type"], "string")

    def test_what_counts_as_an_existing_path(self):
        self.write("src/catalog/service.py")
        (self.root.parent / "outside.py").write_text("x\n")
        counted = ["src/catalog/", "src/catalog/service.py:42", "src/catalog/service.py#L3"]
        never = ["../outside.py", "/etc/hosts", "src/**", "~/x"]
        for values, kind in [(counted, "code_pointer"), (never, None)]:
            with self.subTest(values=values):
                decl, _ = self.fields({f"m{i}": entry(f"m{i}", where=v)
                                       for i, v in enumerate(values)})
                self.assertEqual(decl["where"].get("kind"), kind)
        probed = []
        real = os.path.lexists
        with mock.patch("modsys.adopt_cmd.os.path.lexists",
                        side_effect=lambda p: probed.append(str(p)) or real(p)):
            self.fields({f"m{i}": entry(f"m{i}", where=v) for i, v in enumerate(never)})
        self.assertFalse([p for p in probed if "outside" in p or "hosts" in p or "~" in p])

    def test_types(self):
        for value, expected in [(True, "bool"), (3, "int"), ({"a": 1}, "object"),
                                ([{"x": 1}], "object[]"), ([["a", "b"]], "string[][]"),
                                ([], "string[]")]:
            with self.subTest(value=value):
                decl, _ = self.fields({"a": entry("a", v=value)})
                self.assertEqual(decl["v"]["type"], expected)
        decl, _ = self.fields({"a": entry("a", v="x"), "b": entry("b", v="y"),
                               "c": entry("c", v="z"), "d": entry("d", v=["x"])})
        self.assertEqual(decl["v"]["type"], ["string", "string[]"])
        decl, _ = self.fields({"a": entry("a", v=["x"]), "b": entry("b", v=[])})
        self.assertEqual(decl["v"]["type"], "string[]")

    def test_values_the_grammar_cannot_express(self):
        for value, reason in [(1.5, "a float value"), (None, "a null value"),
                              (["a", 1], "a list mixing element types")]:
            with self.subTest(value=value):
                decl, inferred = self.fields({"a": entry("a", v="ok"), "b": entry("b", v=value)})
                self.assertNotIn("v", decl)
                self.assertEqual([s["key"] for s in inferred["skipped"]], ["v"])
                self.assertIn(reason, inferred["skipped"][0]["reason"])
                self.adopt()
                lint = run_json("lint", "--fail-on", "never", *self.R)[1]["data"]
                self.assertIn(("MS012", "b"), [(f["code"], f["module"])
                                               for f in lint["findings"]])
                shutil.rmtree(self.root / ".modsys")

    def test_scope_and_what_is_never_inferred(self):
        child = {"description": "Child.", "keywords": ["c"], "note": "x",
                 "context_files": {"universal": "modules/a/submodules/c/MODULE.md"}}
        self.write(".modsys/config.toml", '[fields.declared]\ntype = "string"\n')
        decl, inferred = self.fields({"a": entry("a", both="y", declared="z",
                                                 submodules={"c": {**child, "both": "w"}})})
        self.assertEqual((decl["note"]["scope"], decl["both"]["scope"]),
                         (["submodule"], ["module", "submodule"]))
        self.assertEqual(sorted(f["name"] for f in inferred["fields"]), ["both", "note"])
        for spec in decl.values():
            self.assertFalse({"deprecated", "description", "used_by", "ask_on_create"} & set(spec))
        (self.root / ".modsys/config.toml").unlink()
        shutil.rmtree(self.root / "modules")
        self.registry({"a": entry("a", both="y", declared="z",
                                  submodules={"c": {**child, "both": "w"}})})
        self.adopt()
        lint = run_json("lint", "--fail-on", "never", *self.R)[1]["data"]
        self.assertFalse([f for f in lint["findings"] if f["code"] in ("MS012", "MS013")])
        code, _, err = run("registry", "set", "a/c", "note", '"changed"', *self.R)
        self.assertEqual((code, err), (0, ""))

    def test_keys_that_need_quoting(self):
        names = ["review notes", "a.b", "é", 'review "notes"', "a\\b"]
        decl, _ = self.fields({"a": entry("a", **{n: "x" for n in names})})
        self.assertEqual(sorted(decl), sorted(names))


class DirsAndTimestampTest(AdoptRepo):  # P5A-AC-018
    def test_dir_whitelist(self):
        shutil.copytree(FIXTURE, self.root, dirs_exist_ok=True)
        shutil.rmtree(self.root / ".modsys")
        self.write("modules/_shared/notes.md")
        self.write("modules/.cache/x")
        data = self.adopt()
        self.assertEqual(data["inferred"]["dir_whitelist"], ["_shared"])
        self.assertEqual(self.toml(data)["registry"]["dir_whitelist"], ["_shared"])
        self.assertIn("# adopt: modules/_shared/ is not a registry module", data["config"])
        lint = run_json("lint", "--fail-on", "never", *self.R)[1]["data"]
        self.assertNotIn("MS014", [f["code"] for f in lint["findings"]])

    def test_updated_at_path(self):
        stamp = "2026-01-01T00:00:00Z"
        for top, expected in [({"metadata": {"last_updated": stamp}}, "metadata.last_updated"),
                              ({"metadata": {"created_at": stamp}}, None),
                              ({"updatedAt": "2026-01-01"}, "updatedAt"),
                              ({"meta": {"info": {"modified": stamp}}}, None),
                              ({"last_updated": "yesterday"}, None),
                              ({"updatedAt": "2026-01-01",
                                "metadata": {"last_updated": stamp}}, "updatedAt")]:
            with self.subTest(top=top):
                self.registry({"a": entry("a")}, **top)
                data = self.adopt("--dry-run")
                self.assertEqual(data["inferred"]["updated_at_path"], expected)
        self.assertIn("(also found: metadata.last_updated)", data["config"])
        self.registry({"a": entry("a", updated_at=stamp)})
        self.assertIsNone(self.adopt("--dry-run")["inferred"]["updated_at_path"])


class CodeMapInferenceTest(AdoptRepo):  # P5A-AC-019
    def rule(self, total: int, dirs: dict[str, int]) -> dict | None:
        shutil.rmtree(self.root / "modules", ignore_errors=True)
        for d in list(self.root.iterdir()):
            if d.name != "modules":
                shutil.rmtree(d) if d.is_dir() else d.unlink()
        names = [f"m{i}" for i in range(total)]
        self.registry({n: entry(n) for n in names})
        for prefix, count in dirs.items():
            for n in names[:count]:
                self.write(f"{prefix}/{n}/x.py")
        return self.adopt("--dry-run")["inferred"]["code_map"]

    def test_the_decision_table(self):
        self.assertEqual(self.rule(4, {"src": 2}), {"id": "src", "pattern": "src/{module}/**",
                                                    "covered": 2, "total": 4,
                                                    "alternatives": []})
        self.assertIsNone(self.rule(5, {"src": 2}))
        rule = self.rule(4, {"src": 2, "app/features": 3})
        self.assertEqual((rule["id"], rule["pattern"], rule["alternatives"]),
                         ("app-features", "app/features/{module}/**",
                          [{"pattern": "src/{module}/**", "covered": 2}]))
        self.assertEqual(self.rule(4, {"lib": 3, "src": 3})["pattern"], "lib/{module}/**")
        for prefix in ("node_modules", ".venv", "build", ".hidden", "a/b/c/d"):
            with self.subTest(prefix=prefix):
                self.assertIsNone(self.rule(2, {prefix: 2}))
        self.assertIsNone(self.rule(2, {}))  # modules/<m> exists for every module: not code

    def test_the_committed_fixture_and_an_existing_rule(self):
        shutil.copytree(FIXTURE, self.root, dirs_exist_ok=True)
        shutil.rmtree(self.root / ".modsys")
        self.assertIsNone(self.adopt("--dry-run")["inferred"]["code_map"])  # 1 of 3
        self.write("src/checkout/cart.py")
        self.write(".modsys/config.toml", '[[code_map]]\nid = "x"\nglobs = ["x/**"]\n'
                                          'module = "catalog"\n')
        self.assertIsNone(self.adopt("--dry-run")["inferred"]["code_map"])

    def test_code_pointer_values_count(self):
        self.registry({"a": entry("a", code=["pkg/a/main.py"]), "b": entry("b"),
                       "c": entry("c", code=["pkg/c"])})
        self.write("pkg/a/main.py")
        self.write("pkg/c/x.py")
        data = self.adopt()
        self.assertEqual(data["inferred"]["code_map"]["pattern"], "pkg/{module}/**")
        self.assertEqual(run_json("code-map", "list", *self.R)[1]["data"][0]["pattern"],
                         "pkg/{module}/**")
        show = run_json("show", "a", *self.R)[1]["data"]
        self.assertEqual(show["code_globs"], ["pkg/a/**"])


class BudgetsTest(AdoptRepo):  # P5A-AC-020
    def budgets(self, module_lines: int, role_lines: int) -> dict:
        shutil.rmtree(self.root / "modules", ignore_errors=True)
        self.registry({"a": entry("a", context_files={
            "universal": "modules/a/MODULE.md", "roles": {"developer": "modules/a/roles/d.md"}})})
        self.write("modules/a/MODULE.md", "x\n" * module_lines)
        self.write("modules/a/roles/d.md", "x\n" * role_lines)
        data = self.adopt("--dry-run")
        self.assertNotIn("budgets", self.toml(data))
        return data

    def test_the_boundaries(self):
        self.assertEqual(self.budgets(600, 600)["inferred"]["budgets"], [])
        data = self.budgets(601, 1)
        self.assertEqual(data["inferred"]["budgets"],
                         [{"key": "module_doc_split_signal", "observed_max": 601, "clears": 1}])
        self.assertIn("# module_doc_split_signal = 601\n# adopt: 1 MODULE.md over 600 lines",
                      data["config"])
        self.assertEqual(data["lint"]["counts"], {"MS030": 1})
        data = self.budgets(1001, 1)
        self.assertEqual([(b["key"], b["observed_max"]) for b in data["inferred"]["budgets"]],
                         [("module_doc_hard_stop", 1001), ("module_doc_split_signal", 1001)])
        self.assertEqual(data["lint"]["counts"], {"MS031": 1})
        data = self.budgets(1, 601)
        self.assertEqual(data["inferred"]["budgets"],
                         [{"key": "role_doc_max", "observed_max": 601, "clears": 1}])
        self.assertIn("# role_doc_max = 601", data["config"])


class PathsAndLayoutTest(AdoptRepo):  # P5A-AC-021
    def listed(self) -> list[str]:
        return [r["module"] for r in run_json("list", *self.R)[1]["data"]]

    def test_the_decision_table(self):
        self.registry({"a": entry("a")})
        data = self.adopt("--dry-run")
        self.assertEqual((data["inferred"]["paths"], data["layout"]), ({}, "single"))
        shutil.rmtree(self.root / "modules")
        a = {**entry("a"), "context_files": {"universal": "docs/modules/a/MODULE.md"}}
        self.registry({"a": a}, rel="docs/modules/registry.json")
        self.assertIn("no registry at modules/registry.json — pass the registry file with "
                      "--registry PATH", self.refused())
        self.assertIn("modsys init map", self.refused())
        data = self.adopt("--registry", "docs/modules/registry.json")
        self.assertEqual(self.toml(data)["paths"], {"registry": "docs/modules/registry.json",
                                                    "modules_dir": "docs/modules"})
        self.assertEqual(self.listed(), ["a"])
        show = run_json("show", "a", *self.R)[1]["data"]
        self.assertEqual(show["read"][0]["path"], "docs/modules/a/MODULE.md")
        self.assertTrue(show["read"][0]["exists"])

    def test_the_per_module_layout(self):
        self.registry({"a": entry("a"), "b": entry("b")})
        for name in ("a", "b"):
            self.write(f"modules/{name}/module.json", json.dumps(entry(name)) + "\n")
        data = self.adopt()
        self.assertEqual((data["layout"], self.toml(data)["paths"]),
                         ("per-module", {"registry_layout": "per-module"}))
        self.assertEqual(self.listed(), ["a", "b"])
        shutil.rmtree(self.root / ".modsys")
        (self.root / "modules/b/module.json").unlink()
        self.assertIn("these do not: b", self.refused())

    def test_bad_registries_and_paths(self):
        self.registry({"a": entry("a")})
        self.assertIn("outside the repository", self.refused("--registry", "../x/registry.json"))
        self.assertIn("outside the repository",
                      self.refused("--registry", str(self.root.parent / "registry.json")))
        self.assertIn("registry not found", self.refused("--registry", "nope.json"))
        self.write("modules/registry.json", "{not json")
        self.assertIn("invalid JSON", self.refused())
        self.write("modules/registry.json", '{"modules": []}')
        self.assertIn("no 'modules' object", self.refused())
        self.registry({"a": entry("a")})
        data = self.adopt("--dry-run", "--registry", str(self.root / "modules/registry.json"))
        self.assertEqual((data["registry"], data["inferred"]["paths"]),
                         ("modules/registry.json", {}))  # absolute inside the root: accepted


class LintReportTest(AdoptRepo):  # P5A-AC-022
    def modules(self, n: int, docs=False) -> None:
        shutil.rmtree(self.root / "modules", ignore_errors=True)
        self.registry({f"m{i:02}": entry(f"m{i:02}") for i in range(n)}, docs=docs)

    def test_the_counts_and_the_cap(self):
        self.modules(3, docs=True)
        data = self.adopt("--dry-run")
        self.assertEqual(data["lint"], {"counts": {}, "findings": []})
        for n in (50, 51):
            with self.subTest(n=n):
                self.modules(n)
                lint = self.adopt("--dry-run")["lint"]
                self.assertEqual(sum(lint["counts"].values()), n)
                self.assertEqual(len(lint["findings"]), 50)
                self.assertEqual(set(lint["findings"][0]),
                                 {"code", "severity", "module", "message", "path"})
                self.assertEqual([f["module"] for f in lint["findings"]],
                                 [f"m{i:02}" for i in range(50)])

    def test_report_mode_and_the_real_lint(self):
        self.registry({"a": entry("a", odd="value"), "b": entry("b")}, docs=False)
        self.write("modules/a/MODULE.md")
        dry = self.adopt("--dry-run")["lint"]
        self.assertEqual(dry["counts"], {"MS004": 1})
        self.adopt()
        real = run_json("lint", "--fail-on", "never", *self.R)[1]["data"]["findings"]
        self.assertEqual(dry["findings"], real)
        self.registry({"a": entry("a", odd="value", other=1), "b": entry("b")}, docs=False)
        data = self.adopt()
        self.assertEqual(self.toml(data)["fields"], {"other": {"type": "int",
                                                               "scope": ["module"]}})
        self.assertEqual(data["lint"]["counts"], {"MS004": 1})  # config + proposal merged


class FixtureEquivalenceTest(unittest.TestCase):  # P5A-AC-023 (row 5.1)
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name).resolve()
        self.ref, self.new = base / "reference", base / "adopted"
        for root in (self.ref, self.new):
            shutil.copytree(FIXTURE, root)
            for rel in ("src/checkout/cart.py", "src/payments/gateway.py"):
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text("VALUE = 1\n")
        (self.ref / ".modsys/config.toml").write_text('[[code_map]]\nid = "src"\n'
                                                      'pattern = "src/{module}/**"\n')
        shutil.rmtree(self.new / ".modsys")

    def tearDown(self):
        self._tmp.cleanup()

    def out(self, root: Path, *argv) -> str:
        code, out, err = run(*argv, "--json", "--root", str(root))
        self.assertEqual((code, err), (0, ""))
        return out

    def test_adopt_regenerates_equivalent_declarations(self):
        before = run_json("lint", "--fail-on", "never", "--root", str(self.new))[1]["data"]
        self.assertEqual(sorted(f["code"] for f in before["findings"]), ["MS012", "MS015"])
        code, env, err = run_json("adopt", "--root", str(self.new))
        self.assertEqual((code, err), (0, ""))
        inferred = env["data"]["inferred"]
        self.assertEqual(inferred["roles"], [{"name": "designer", "order": 50,
                                              "standard": False, "modules": ["catalog"]}])
        self.assertEqual(inferred["fields"], [{"name": "file_paths", "type": ["string[]"],
                                               "kind": "code_pointer", "scope": ["module"],
                                               "entries": 1}])
        self.assertEqual((inferred["code_map"]["pattern"], inferred["updated_at_path"]),
                         ("src/{module}/**", "metadata.last_updated"))
        self.assertNotIn("depends_on_modules", env["data"]["config"])
        self.assertEqual(self.out(self.ref, "list"), self.out(self.new, "list"))
        for target in ("catalog", "checkout", "payments", "payments/refunds"):
            with self.subTest(target=target):
                self.assertEqual(self.out(self.ref, "show", target, "--all-roles"),
                                 self.out(self.new, "show", target, "--all-roles"))
        self.assertEqual(run("lint", "--fail-on", "warning", "--root", str(self.new))[0], 0)
        self.assertFalse(run("lint", "--root", str(FIXTURE))[0])
        self.assertFalse((FIXTURE / ".modsys/config.toml").exists())


class EdgeInputsTest(AdoptRepo):  # P5A-AC-043
    def test_an_empty_registry(self):
        self.registry({})
        data = self.adopt()
        self.assertEqual(data["inferred"], {"paths": {}, "roles": [], "fields": [],
                                            "skipped": [], "dir_whitelist": [],
                                            "updated_at_path": None, "code_map": None,
                                            "budgets": []})
        self.assertIn("modsys init map", " ".join(data["next_steps"]))

    def test_odd_names_and_non_ascii_evidence(self):
        cf = {"universal": "modules/käse/MODULE.md",
              "roles": {"ux designer": "modules/käse/roles/ux.md"}}
        self.registry({"käse": entry("käse", context_files=cf,
                                     **{'review "notes"': "x", "a\\b": "y"})})
        data = self.adopt()
        layer = tomllib.loads((self.root / ".modsys/config.toml").read_text(encoding="utf-8"))
        self.assertEqual((list(layer["roles"]), sorted(layer["fields"])),
                         (["ux designer"], ["a\\b", 'review "notes"']))
        self.assertIn("carried by 1 entry: käse", data["config"])

    def test_a_fixed_point(self):
        shutil.copytree(FIXTURE, self.root, dirs_exist_ok=True)
        shutil.rmtree(self.root / ".modsys")
        self.write("modules/_shared/x.md")
        self.adopt()
        again = self.adopt("--dry-run")["inferred"]
        self.assertEqual({k: v for k, v in again.items() if v not in ([], {}, None)}, {})

    def test_a_missing_doc_and_a_config_dir_that_is_a_file(self):
        self.registry({"a": entry("a")}, docs=False)
        self.assertEqual(self.adopt("--dry-run")["lint"]["counts"], {"MS004": 1})
        self.write("cfg", "a file\n")
        self.assertIn("is not a directory (the config dir)",
                      self.refused("--config-dir", str(self.root / "cfg")))


class WritesAndRacesTest(AdoptRepo):  # P5A-AC-044
    def setUp(self):
        super().setUp()
        self.registry({"a": entry("a", odd="x")})

    def test_a_config_that_appears_meanwhile(self):
        from modsys import adopt_cmd
        real = adopt_cmd.plan_adopt

        def racing(*args):
            plan = real(*args)
            self.write(".modsys/config.toml", "# theirs\n")
            return plan

        with mock.patch("modsys.adopt_cmd.plan_adopt", side_effect=racing):
            code, out, err = run("adopt", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn(".modsys/config.toml appeared while adopt was running; run adopt again",
                      err)
        self.assertEqual((self.root / ".modsys/config.toml").read_text(), "# theirs\n")
        self.assertEqual([p.name for p in (self.root / ".modsys").iterdir()], ["config.toml"])

    @unittest.skipIf(os.geteuid() == 0, "root writes into read-only directories")
    def test_a_read_only_config_dir(self):
        (self.root / ".modsys").mkdir()
        os.chmod(self.root / ".modsys", 0o555)
        code, out, err = run("adopt", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("cannot write .modsys/config.toml", err)
        os.chmod(self.root / ".modsys", 0o755)
        self.assertEqual(list((self.root / ".modsys").iterdir()), [])

    def test_ctrl_c_while_writing(self):
        with mock.patch("modsys.adopt_cmd.os.link", side_effect=KeyboardInterrupt):
            self.assertEqual(run("adopt", *self.R), (130, "", "modsys: interrupted\n"))
        self.assertEqual(list((self.root / ".modsys").iterdir()), [])
        self.adopt()
        proposal = self.root / ".modsys/adopt.proposed.toml"
        proposal.write_text("# old\n")
        with mock.patch("modsys.store.os.replace", side_effect=KeyboardInterrupt):
            self.assertEqual(run("adopt", *self.R), (130, "", "modsys: interrupted\n"))
        self.assertEqual(proposal.read_text(), "# old\n")
        self.assertEqual(sorted(p.name for p in (self.root / ".modsys").iterdir()),
                         ["adopt.proposed.toml", "config.toml"])


class AdoptContractTest(AdoptRepo):  # P5A-AC-046, P5A-AC-042
    def test_garbage_config_interrupt_and_options_after_the_verb(self):
        self.registry({"a": entry("a")})
        self.write(".modsys/config.toml", "code_map = 5\n")
        code, out, err = run("adopt", "--json", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("config.toml", err)
        self.assertNotIn("Traceback", err)
        (self.root / ".modsys/config.toml").unlink()
        with mock.patch("modsys.adopt_cmd.lint_registry", side_effect=KeyboardInterrupt):
            self.assertEqual(run("adopt", "--dry-run", *self.R),
                             (130, "", "modsys: interrupted\n"))
        with mock.patch("modsys.adopt_cmd.lint_registry", side_effect=RuntimeError("boom")):
            with mock.patch.dict(os.environ):
                os.environ.pop("MODSYS_DEBUG", None)
                code, out, err = run("adopt", "--dry-run", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("modsys: internal error: RuntimeError: boom", err)
        code, out, err = run("adopt", "--dry-run", "--root", str(self.root), "--config-dir",
                             str(self.root / ".modsys"), "--json")
        self.assertEqual((code, err, json.loads(out)["schema"]), (0, "", "modsys.adopt/1"))

    def test_twenty_six_verbs_everywhere(self):
        parser = set(build_parser()._subparsers._group_actions[0].choices)
        contract = set(re.findall(r"^\| `([a-z-]+)", CONTRACT.read_text(encoding="utf-8"), re.M))
        self.assertEqual((len(parser), parser, {argv[0] for argv, _ in GOLDEN}),
                         (26, contract, contract))
        self.assertIn("adopt", parser)

    def test_help(self):
        out = " ".join(run("adopt", "--help")[1].split())
        for needle in ("--registry PATH", "--dry-run", "adopt.proposed.toml",
                       "never changed"):
            self.assertIn(needle, out)


if __name__ == "__main__":
    unittest.main()
