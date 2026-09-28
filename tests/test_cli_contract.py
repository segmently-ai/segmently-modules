"""Golden contract: every verb's --json envelope and data keys match docs/cli-contract.md."""
import re
import tempfile
import unittest
from pathlib import Path

from modsys.cli import build_parser
from tests.helpers import copy_fixture, init_git, run_json

DOC = Path(__file__).resolve().parents[1] / "docs" / "cli-contract.md"
DESC = "Customer reviews of books: ratings, comments and moderation."
KW = [a for k in ("review", "rating", "stars", "comment", "moderation") for a in ("--keyword", k)]

# (argv, expected top-level keys of data, or None when data is a list)
GOLDEN = [
    (("adopt", "--dry-run"), {"root", "registry", "layout", "inferred", "config_path", "config",
                              "lint", "next_steps", "dry_run"}),
    (("init", "--dry-run"), {"root", "layout", "files", "dry_run"}),
    (("schema",), {"$schema", "title", "type", "required", "properties"}),
    (("match", "book"), None),
    (("show", "catalog"), {"module", "status", "description", "keywords", "read", "code",
                           "code_globs"}),
    (("related", "catalog"), {"module", "edges", "reverse"}),
    (("list",), None),
    (("lint", "--fail-on", "never"), {"findings", "summary", "failed"}),
    (("registry", "set", "catalog", "status", '"draft"', "--dry-run"),
     {"op", "target", "field", "dry_run", "changed", "diff"}),
    (("index", "split", "--dry-run"), {"files", "dry_run", "next"}),
    (("propose", "--module", "catalog", "--op", "set", "--field", "status", "--value", '"draft"',
      "--reason", "r", "--run-id", "g1"), {"file", "run_id", "agent", "item"}),
    (("proposals", "list"), None),
    (("hooks", "list"), None),
    (("sync", "--files", "src/catalog/service.py", "--dry-run"),
     {"run_id", "diff_range", "changed_files", "modules", "unmapped", "missing_files", "hooks",
      "proposals", "dry_run"}),
    (("sync-instructions", "--files", "src/catalog/service.py"),
     {"modules", "files_outside_modules"}),
    (("create", "reviews", "--description", DESC, *KW, "--dry-run"),
     {"module", "files", "entry", "warnings", "dry_run"}),
    (("migrate", "--dry-run"), {"applied", "dry_run", "diff"}),
    (("context", "--task", "isbn"), {"task", "role", "all_roles", "modules", "read",
                                     "near_misses"}),
    (("discover", "--task", "isbn"), {"task", "modules", "files", "files_outside_modules",
                                      "missing_files", "summary"}),
    (("coverage",), {"total", "mapped", "share", "modules", "unmapped"}),
    (("code-map", "list"), None),
    (("code-map", "files", "catalog"), {"target", "files", "total"}),
    (("ci", "--fail-on", "never"), {"base", "fail_on", "steps", "failed", "notes"}),
    (("templates", "list"), None),
    (("templates", "override", "roles/qa.md", "--dry-run"), {"template", "file", "from",
                                                             "dry_run"}),
    (("packs", "list"), None),
    (("packs", "new", "team", "--role", "reviewer", "--skill", "api-review", "--dry-run"),
     {"pack", "dir", "files", "dry_run"}),
    (("packs", "sync", "--agent", "claude", "--dry-run"),
     {"agents", "check", "dry_run", "skills", "summary", "failed"}),
    (("packs", "new", "team2", "--skill", "notes"), {"pack", "dir", "files", "dry_run"}),
    (("eject", "notes", "--dry-run"), {"skill", "pack", "version", "dir", "files", "dry_run"}),
    (("eject", "notes"), {"skill", "pack", "version", "dir", "files", "dry_run"}),
    (("eject", "notes", "--diff"), {"skill", "pack", "ejected_from", "upstream_version",
                                    "behind", "files", "diff", "reason"}),
    (("agents-md", "--target", "CLAUDE.md", "--dry-run"), {"targets", "check", "dry_run"}),
]


class CliContractTest(unittest.TestCase):
    def test_every_verb_envelope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            init_git(root)  # coverage lists files through git
            for argv, keys in GOLDEN:
                with self.subTest(verb=argv[0]):
                    code, env, err = run_json(*argv, "--root", str(root))
                    self.assertEqual((code, err), (0, ""))
                    self.assertEqual(set(env), {"schema", "data"})
                    self.assertEqual(env["schema"], f"modsys.{argv[0]}/1")
                    if keys is None:
                        self.assertIsInstance(env["data"], list)
                    else:
                        self.assertEqual(set(env["data"]), keys)

    def test_every_verb_is_documented_and_covered(self):
        verbs = set(build_parser()._subparsers._group_actions[0].choices)
        documented = set(re.findall(r"^\| `([a-z-]+)", DOC.read_text(encoding="utf-8"), re.M))
        self.assertEqual(verbs, documented)
        self.assertEqual(verbs, {argv[0] for argv, _ in GOLDEN})

    def test_the_verb_table_rows_are_contiguous(self):  # I-2
        """A blank line between two `| \\`<verb>\\` |` rows would split the table in rendered
        Markdown (GFM ends a table at the first non-row line)."""
        lines = DOC.read_text(encoding="utf-8").splitlines()
        rows = [i for i, l in enumerate(lines) if re.match(r"^\| `[a-z-]+", l)]
        self.assertTrue(rows)
        for i in range(rows[0], rows[-1] + 1):
            self.assertTrue(lines[i].startswith("|"), f"line {i + 1} breaks the table: {lines[i]!r}")


if __name__ == "__main__":
    unittest.main()
