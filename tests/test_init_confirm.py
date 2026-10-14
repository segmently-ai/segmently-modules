"""`segmently-modules init confirm` (D3, gate 3): an edited proposal is validated — names by the `create`
rule and unique, every included candidate with globs that match files, no file claimed twice —
every problem named at once; an unedited proposal always passes."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.helpers import git, run, run_json

UNITS = {  # directory -> (manifest file, its text, a code file)
    "packages/catalog": ("package.json", '{"name": "@bookshop/catalog"}', "src/index.ts"),
    "packages/cart": ("package.json", '{"name": "@bookshop/cart"}', "src/index.ts"),
    "packages/ui-kit": ("package.json", '{"name": "@bookshop/ui-kit"}', "src/button.tsx"),
    "apps/storefront": ("package.json", '{"name": "storefront"}', "src/main.ts"),
    "services/payments": ("pyproject.toml", '[project]\nname = "payments"\n',
                          "payments/__init__.py"),
    "services/recommendations": ("pyproject.toml", '[project]\nname = "recommendations"\n',
                                 "recommendations/__init__.py"),
}


def monorepo(root: Path) -> None:
    """A small bookshop monorepo: a root package.json with workspaces and six units."""
    files = {"package.json": '{"private": true, "workspaces": ["packages/*", "apps/*"]}',
             "tools/seed.py": "SEED = 1"}
    for unit, (manifest, text, code) in UNITS.items():
        files[f"{unit}/{manifest}"] = text
        files[f"{unit}/{code}"] = "export const x = 1;" if code.endswith(("ts", "tsx")) \
            else "X = 1"
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text + "\n")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "--", ".")
    git(root, "commit", "-q", "-m", "bookshop")


class ConfirmTest(unittest.TestCase):  # P5A-AC-028
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve() / "shop"
        monorepo(self.root)
        self.R = ("--root", str(self.root))
        code, _, err = run_json("init", "map", *self.R)
        self.assertEqual((code, err), (0, ""))
        self.path = self.root / ".segmently-modules/init/proposal.json"
        self.original = self.path.read_text()

    def tearDown(self):
        self._tmp.cleanup()

    def edited(self, fn) -> None:
        doc = json.loads(self.original)
        fn({c["name"]: c for c in doc["candidates"]}, doc["candidates"])
        self.path.write_text(json.dumps(doc, indent=2) + "\n")

    def confirm(self, fn=None, code=0, *argv) -> dict | str:
        self.edited(fn or (lambda by, cs: None))
        state = (self.root / ".segmently-modules/init/state.json").read_bytes()
        confirmed = self.root / ".segmently-modules/init/confirmed.json"
        before = confirmed.read_bytes() if confirmed.exists() else None
        got, out, err = run("init", "confirm", *argv, "--json", *self.R)
        self.assertEqual(got, code, err)
        if code == 0:
            return json.loads(out)["data"]
        self.assertEqual(out, "")
        self.assertEqual((self.root / ".segmently-modules/init/state.json").read_bytes(), state)
        self.assertEqual(confirmed.read_bytes() if confirmed.exists() else None, before)
        return err

    def test_accepted_edits(self):
        data = self.confirm()
        self.assertEqual((sorted(data["included"]), data["excluded"]),
                         (sorted(["catalog", "cart", "ui-kit", "storefront", "payments",
                                  "recommendations", "tools"]), []))  # P5B-AC-043: + tools
        data = self.confirm(lambda by, cs: by["storefront"].update(include=False))
        self.assertEqual((len(data["included"]), data["excluded"]), (6, ["storefront"]))
        for name in ("design-kit", "d" * 48):
            with self.subTest(name=name):
                data = self.confirm(lambda by, cs: by["ui-kit"].update(name=name))
                self.assertIn(name, data["included"])

    def test_merge_and_split(self):
        def merge(by, cs):
            by["cart"]["include"] = False
            by["catalog"]["paths"].append("packages/cart/**")
        self.assertEqual(self.confirm(merge)["excluded"], ["cart"])

        def split(by, cs):
            by["payments"]["paths"] = ["services/payments/payments/**"]
            cs.append({"name": "payments-config", "include": True,
                       "paths": ["services/payments/pyproject.toml"], "owner": "team-pay"})
        data = self.confirm(split)
        self.assertIn("payments-config", data["included"])
        confirmed = json.loads((self.root / ".segmently-modules/init/confirmed.json").read_text())
        self.assertEqual(confirmed["candidates"][-1]["owner"], "team-pay")

    def test_refusals(self):
        rule = "the name breaks the create rule (lowercase words joined by '-', max 48)"
        for name in ("Design_Kit", "d" * 49, "ui/kit"):
            with self.subTest(name=name):
                err = self.confirm(lambda by, cs: by["ui-kit"].update(name=name), 2)
                self.assertIn(f"candidate '{name}': {rule}", err)
        err = self.confirm(lambda by, cs: by["cart"].update(name="catalog"), 2)
        self.assertIn("duplicate name 'catalog': 2 included candidates", err)
        self.confirm(lambda by, cs: by["cart"].update(name="catalog", include=False))
        for paths in ([], None):
            with self.subTest(paths=paths):
                def drop(by, cs):
                    if paths is None:
                        del by["cart"]["paths"]
                    else:
                        by["cart"]["paths"] = paths
                self.assertIn("candidate 'cart' has no paths", self.confirm(drop, 2))
        err = self.confirm(lambda by, cs: by["cart"].update(paths=["nowhere/**"]), 2)
        self.assertIn("candidate 'cart': glob 'nowhere/**' matches no file", err)
        err = self.confirm(lambda by, cs: by["cart"].update(paths=["packages/**"]), 2)
        self.assertIn("candidates 'cart' and 'catalog' both claim 2 file(s), e.g. "
                      "packages/catalog/package.json", err)
        err = self.confirm(lambda by, cs: [c.update(include=False) for c in cs], 2)
        self.assertIn("no candidate is included", err)
        err = self.confirm(lambda by, cs: by["cart"].update(include="yes"), 2)
        self.assertIn("candidate 'cart': include must be true or false", err)
        err = self.confirm(lambda by, cs: (by["cart"].update(include="yes"),
                                           by["ui-kit"].update(name="UI"),
                                           by["catalog"].update(paths=[])), 2)
        for needle in ("'cart': include must be", "'UI': the name breaks",
                       "'catalog' has no paths"):
            self.assertIn(needle, err)

    def test_dry_run_and_the_init_exclude(self):
        data = self.confirm(None, 0, "--dry-run")
        self.assertEqual((data["status"], data["dry_run"]), ("confirmed", True))
        self.assertFalse((self.root / ".segmently-modules/init/confirmed.json").exists())
        config = self.root / ".segmently-modules/config.toml"
        config.write_text(config.read_text() + '\n[init]\nexclude = ["apps/**"]\n')
        err = self.confirm(None, 2)
        self.assertIn("candidate 'storefront': glob 'apps/storefront/**' matches no file", err)


if __name__ == "__main__":
    unittest.main()
