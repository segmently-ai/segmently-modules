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
    (("create", "reviews", "--description", DESC, *KW, "--dry-run"),
     {"module", "files", "entry", "dry_run"}),
    (("migrate", "--dry-run"), {"applied", "dry_run", "diff"}),
    (("context", "--task", "isbn"), {"task", "role", "all_roles", "modules", "read",
                                     "near_misses"}),
    (("discover", "--task", "isbn"), {"task", "modules", "files", "files_outside_modules",
                                      "missing_files", "summary"}),
    (("coverage",), {"total", "mapped", "share", "modules", "unmapped"}),
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
        documented = set(re.findall(r"^\| `([a-z]+)", DOC.read_text(encoding="utf-8"), re.M))
        self.assertEqual(verbs, documented)
        self.assertEqual(verbs, {argv[0] for argv, _ in GOLDEN})


if __name__ == "__main__":
    unittest.main()
