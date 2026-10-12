"""Lint over the module docs as files: MS005 a registered doc that is damaged (NUL bytes, not
UTF-8) · MS016 an unregistered doc in a module's `roles/` directory, with the role its name
reads as · MS017 (info) the unregistered docs directly in a module's directory, one finding per
module · MS041 a link whose target is missing (`[lint] link_severity`) · MS042 (info) an anchor
that names no heading · MS043 (info) backticked repository paths missing on disk, one finding per
module."""
import tempfile
import unittest
from pathlib import Path

from modsys.doc_checks import anchors
from tests.helpers import copy_fixture, git, init_git, mutate_registry, run, run_json

CHECKOUT = "modules/checkout/MODULE.md"


def write(root: Path, rel: str, text: str | bytes) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")


class Repo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def findings(self, *codes: str) -> list[tuple]:
        code, env, err = run_json("lint", "--root", str(self.root), "--fail-on", "never")
        self.assertEqual((code, err), (0, ""))
        return [(f["code"], f["severity"], f["module"], f["message"], f["path"])
                for f in env["data"]["findings"] if f["code"] in codes]


class DamagedDocTest(Repo):
    def test_nul_bytes_and_bad_utf8_in_a_registered_doc(self):
        write(self.root, "modules/checkout/roles/developer.md", b"# Dev\n\0\0ok\n")
        write(self.root, "modules/catalog/roles/qa.md", "# QA\n— fine\n".encode() + b"\xff\n")
        write(self.root, "modules/catalog/notes.md", b"\0")  # not registered: MS017 only
        self.assertEqual(self.findings("MS005"), [
            ("MS005", "error", "catalog", "doc is not valid UTF-8 (byte 0xff on line 3) — the "
             "file is damaged; restore it from git history or re-save it as UTF-8",
             "modules/catalog/roles/qa.md"),
            ("MS005", "error", "checkout", "doc holds 2 NUL byte(s) — the file is damaged; "
             "restore it from git history or re-save it as UTF-8",
             "modules/checkout/roles/developer.md")])
        code, _out, _err = run("lint", "--root", str(self.root))
        self.assertEqual(code, 1)

    def test_a_clean_fixture_has_no_doc_findings(self):
        self.assertEqual(self.findings("MS005", "MS016", "MS017", "MS041", "MS042", "MS043"), [])


class UnregisteredDocTest(Repo):
    def test_a_doc_in_roles_names_the_role_it_reads_as(self):
        write(self.root, "modules/checkout/roles/ARCHITECTURE.md", "# Architecture\n")
        write(self.root, "modules/checkout/roles/notes.md", "# Notes\n")
        write(self.root, "modules/checkout/roles/developer.legacy.md", "# frozen\n")
        write(self.root, "modules/catalog/roles/qa-old.md", "# old QA\n")
        write(self.root, "modules/payments/submodules/refunds/roles/po.md", "# PO\n")
        got = {(m, p): msg for _c, sev, m, msg, p in self.findings("MS016")
               if self.assertEqual(sev, "warning") is None}
        self.assertEqual(got, {
            ("catalog", "modules/catalog/roles/qa-old.md"):
                "modules/catalog/roles/qa-old.md is not registered — agents never load it; it "
                "reads like the qa doc, which is registered already — merge it into that doc or "
                "delete it",
            ("checkout", "modules/checkout/roles/ARCHITECTURE.md"):
                "modules/checkout/roles/ARCHITECTURE.md is not registered — agents never load "
                "it; it reads like the architect doc: rename it to "
                "modules/checkout/roles/architect.md, then modsys roles add architect checkout "
                "registers it",
            ("checkout", "modules/checkout/roles/notes.md"):
                "modules/checkout/roles/notes.md is not registered — agents never load it; "
                "register it (modsys registry append checkout context_files.supplementary "
                "'\"modules/checkout/roles/notes.md\"') or delete it",
            ("payments/refunds", "modules/payments/submodules/refunds/roles/po.md"):
                "modules/payments/submodules/refunds/roles/po.md is not registered — agents "
                "never load it; it is the po doc: modsys roles add po payments/refunds "
                "registers it"})

    def test_the_hint_clears_the_finding(self):
        write(self.root, "modules/checkout/roles/architect.md", "# Architect\n")
        self.assertEqual(len(self.findings("MS016")), 1)
        code, _out, err = run("roles", "add", "architect", "checkout", "--root", str(self.root))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.findings("MS016"), [])
        self.assertEqual((self.root / "modules/checkout/roles/architect.md").read_text(),
                         "# Architect\n")  # registered as it is, never rewritten

    def test_loose_docs_in_a_module_directory_one_finding_per_module(self):
        write(self.root, "modules/catalog/plan.md", "# Plan\n")
        write(self.root, "modules/catalog/notes.md", "# Notes\n")
        write(self.root, "modules/catalog/MODULE.legacy.md", "# frozen\n")
        write(self.root, "modules/catalog/plans/deep.md", "# nested: not checked\n")
        self.assertEqual(self.findings("MS017"), [
            ("MS017", "info", "catalog", "2 doc(s) in modules/catalog/ are not registered — "
             "agents never load them: notes.md, plan.md; list one (modsys registry append catalog "
             "context_files.supplementary '\"<path>\"') or move it out of the module directory",
             "modules/catalog")])
        mutate_registry(self.root, lambda d: d["modules"]["catalog"]["context_files"].update(
            supplementary=["modules/catalog/notes.md", "modules/catalog/plan.md"]))
        self.assertEqual(self.findings("MS017"), [])


LINKS = """# Checkout

See [the catalog](../catalog/MODULE.md) and [search](../nope/MODULE.md).
The [service](src/catalog/service.py) and the [root one](/src/catalog/service.py) and
[angle](<../catalog/MODULE.md>), [web](https://example.com/x.md), [mail](mailto:a@b.c).
Code: `[skip](missing.md)` and [placeholder](../{module}/MODULE.md).
Deep [link](../../src/catalog/gone.py) and [depth](../src/catalog/service.py "title").

```
[in a fence](missing-too.md)
```

[ref]: ./missing-ref.md
"""


class LinkTest(Repo):
    def test_missing_targets(self):
        write(self.root, CHECKOUT, LINKS)
        self.assertEqual([(m, msg, p) for _c, _s, m, msg, p in self.findings("MS041")], [
            ("checkout", "line 3: link to ../nope/MODULE.md — modules/nope/MODULE.md is missing on "
             "disk", CHECKOUT),
            ("checkout", "line 7: link to ../../src/catalog/gone.py — src/catalog/gone.py is "
             "missing on disk", CHECKOUT),
            ("checkout", "line 7: link to ../src/catalog/service.py — "
             "modules/src/catalog/service.py is missing on disk (from the repository root it is "
             "src/catalog/service.py: fix the ../ depth)", CHECKOUT),
            ("checkout", "line 13: link to ./missing-ref.md — modules/checkout/missing-ref.md is "
             "missing on disk", CHECKOUT)])
        self.assertEqual({s for _c, s, *_ in self.findings("MS041")}, {"warning"})

    def test_link_severity(self):
        write(self.root, CHECKOUT, LINKS)
        config = self.root / ".modsys/config.toml"
        config.write_text('[lint]\nlink_severity = "info"\n', encoding="utf-8")
        self.assertEqual({s for _c, s, *_ in self.findings("MS041")}, {"info"})
        config.write_text('[lint]\nlink_severity = "loud"\n', encoding="utf-8")
        code, out, err = run("lint", "--root", str(self.root))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("[lint] link_severity: expected info, warning or error, got 'loud'", err)


HEADINGS = """# Catalog

## Set-Cookie + @fastify/compress pitfall
## Notes
## Notes
## 🔥 Hot
## Custom heading {#custom-id}
<a id="anchor-x"></a>

Setext title
============

```
## Not a heading
```
"""


class AnchorTest(Repo):
    def test_slugs(self):
        self.assertEqual(anchors(HEADINGS), {
            "catalog", "set-cookie--fastifycompress-pitfall", "notes", "notes-1", "-hot",
            "custom-id", "custom-heading", "anchor-x", "setext-title"})

    def test_missing_anchors(self):
        write(self.root, "modules/catalog/MODULE.md", HEADINGS)
        write(self.root, CHECKOUT, "# Checkout\n\n"
              "[a](../catalog/MODULE.md#set-cookie--fastifycompress-pitfall) "
              "[b](../catalog/MODULE.md#Notes-1) [c](../catalog/MODULE.md#notes-2) "
              "[d](../catalog/MODULE.md#L10-L20) [e](#checkout) [f](#gone) "
              "[g](../catalog/MODULE.md#not-a-heading) [h](../../src/catalog/service.py#nope)\n")
        self.assertEqual([(s, msg) for _c, s, _m, msg, _p in self.findings("MS042")], [
            ("info", "line 3: link to ../catalog/MODULE.md#notes-2 — modules/catalog/MODULE.md "
             "has no heading for #notes-2"),
            ("info", "line 3: link to #gone — modules/checkout/MODULE.md has no heading for "
             "#gone"),
            ("info", "line 3: link to ../catalog/MODULE.md#not-a-heading — "
             "modules/catalog/MODULE.md has no heading for #not-a-heading")])


class StalePathTest(Repo):
    def test_missing_backticked_paths_one_finding_per_module(self):
        write(self.root, "src/catalog/src/util.py", "x = 1\n")
        write(self.root, "modules/catalog/roles/developer.md",
              "# Dev\n\n`src/catalog/service.py` `src/catalog/gone.py` `src/util.py` "
              "`dist/app.js` `nowhere/x.py` `src/catalog/gone.py` `@scope/pkg` `src/{module}/x`\n")
        write(self.root, "modules/catalog/roles/qa.md", "# QA\n\n`src/catalog/test_gone.py`\n")
        self.assertEqual([(m, msg, p) for _c, _s, m, msg, p in self.findings("MS043")], [
            ("catalog", "2 backticked path(s) missing on disk in 2 doc(s): src/catalog/gone.py "
             "(developer.md), src/catalog/test_gone.py (qa.md)", None)])
        write(self.root, "modules/catalog/roles/qa.md", "# QA\n")
        self.assertEqual([(m, p) for _c, _s, m, _msg, p in self.findings("MS043")],
                         [("catalog", "modules/catalog/roles/developer.md")])

    def test_the_components_table_is_ms040s(self):
        write(self.root, "modules/catalog/MODULE.md", "# Catalog\n\n## EXISTING Components\n\n"
              "| Name | Path |\n|---|---|\n| Gone | `src/catalog/gone.py` |\n")
        self.assertEqual([c for c, *_ in self.findings("MS040", "MS043")], ["MS040"])

    def test_a_directory_git_ignores_is_build_output(self):
        write(self.root, "out/keep.txt", "x\n")
        write(self.root, "modules/catalog/roles/developer.md", "# Dev\n\n`out/app.js`\n")
        init_git(self.root)
        self.assertEqual(len(self.findings("MS043")), 1)
        write(self.root, ".gitignore", "out/\n")
        git(self.root, "rm", "-r", "-q", "--cached", "out")
        self.assertEqual(self.findings("MS043"), [])


if __name__ == "__main__":
    unittest.main()
