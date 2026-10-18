"""Golden contract: every verb's --json envelope and data keys match docs/cli-contract.md."""
import re
import tempfile
import unittest
from pathlib import Path

from segmently_modules.cli import build_parser
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
    (("show", "catalog"), {"module", "status", "description", "keywords", "read", "rules", "code",
                           "code_globs", "fields", "rules_index", "rules_mode"}),
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
                                      "missing_files", "summary", "lexical_confidence"}),
    (("coverage",), {"total", "mapped", "share", "modules", "unmapped"}),
    (("code-map", "list"), None),
    (("code-map", "files", "catalog"), {"target", "files", "total"}),
    (("ci", "--fail-on", "never"), {"base", "base_commit", "fail_on", "steps", "failed",
                                    "notes"}),
    (("templates", "list"), None),
    (("templates", "override", "roles/qa.md", "--dry-run"), {"template", "file", "from",
                                                             "dry_run"}),
    (("packs", "list"), None),
    (("packs", "new", "team", "--role", "reviewer", "--skill", "api-review", "--dry-run"),
     {"pack", "dir", "files", "dry_run"}),
    (("packs", "sync", "--agent", "claude", "--dry-run"),
     {"agents", "check", "dry_run", "skills", "summary", "failed", "notes"}),  # P6 D2: notes
    (("packs", "sync", "--agent", "codex", "--dry-run"),  # P8.4 D3: codex adds agent_files
     {"agents", "check", "dry_run", "skills", "agent_files", "summary", "failed", "notes"}),
    (("packs", "new", "team2", "--skill", "notes"), {"pack", "dir", "files", "dry_run"}),
    (("eject", "notes", "--dry-run"), {"skill", "pack", "version", "dir", "files", "dry_run"}),
    (("eject", "notes"), {"skill", "pack", "version", "dir", "files", "dry_run"}),
    (("eject", "notes", "--diff"), {"skill", "pack", "ejected_from", "upstream_version",
                                    "behind", "files", "diff", "reason"}),
    (("eject", "notes", "--rebase", "--dry-run"), {"skill", "pack", "rebased_from",
                                                   "rebased_to", "files_changed", "dry_run"}),
    (("agents-md", "--target", "CLAUDE.md", "--dry-run"), {"targets", "check", "dry_run"}),
    (("eval", "routing", "--prompt"), {"mode", "per_module", "modules", "prompt"}),  # P5b D3
    (("roles", "list"), {"roles"}),  # P6.1 W3
    (("roles", "add", "designer", "checkout", "--dry-run"), {"role", "dry_run", "results"}),
    (("next", "--base", "HEAD"), {"version", "items", "skipped", "base"}),  # P6.1 W4
    (("catalog",), {"match", "search", "modules"}),  # P8.1 tasks 3a/3b
    (("choose", "--task", "refund a book"),
     {"task", "rules", "cards", "answer_schema", "catalog_digest", "max_picks", "search"}),
    (("setup", "--dry-run"), {"dry_run", "agents", "targets", "steps"}),  # P6.1 W5
    (("rules", "catalog", "--files", "src/catalog/service.py"),
     {"heading", "modules", "files_outside_modules", "missing_files"}),
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
                    self.assertEqual(env["schema"], f"segmently-modules.{argv[0]}/1")
                    if keys is None:
                        self.assertIsInstance(env["data"], list)
                    else:
                        self.assertEqual(set(env["data"]), keys)

    def test_the_agent_file_rows_are_as_documented(self):  # final review I-4
        row = next(line for line in DOC.read_text(encoding="utf-8").splitlines()
                   if line.startswith("| `packs new"))
        sync = row.split(" · sync ", 1)[1]
        shape = re.search(r"`\{agents, check, dry_run, skills: \[[^\]]*\], agent_files\?: "
                          r"\[\{([a-z_, ]+)\}\], summary: \{[a-z_, ]+\}, failed\}`", sync)
        self.assertIsNotNone(shape, sync[:400])
        documented = shape.group(1).split(", ")
        rows_text = sync.split("`agent_files` is there only when", 1)[1].split("`notes` =", 1)[0]
        statuses = re.findall(r"(?:^|· )`([a-z]+)`", rows_text.split("`status`: ", 1)[1])
        self.assertEqual(statuses, ["created", "unchanged", "updated", "removed", "conflict"])
        for needle in ("`agent_files` is there only when the agents include `codex`",
                       "Exit 1 when a row of `skills` or `agent_files` is `conflict` or "
                       "`invalid`", "unless every row of both lists is `unchanged`",
                       "`; agent files: <n> created, <n> updated, <n> unchanged, <n> removed, "
                       "<n> conflict`"):
            self.assertIn(needle, sync)
        setup = next(line for line in DOC.read_text(encoding="utf-8").splitlines()
                     if line.startswith("| `setup"))
        self.assertIn("its skill copies and agent files fold into one status", setup)
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            (root / ".segmently-modules/config.toml").write_text('[packs]\nbuiltin = ["core"]\n',
                                                      encoding="utf-8")
            code, env, err = run_json("packs", "sync", "--agent", "codex", "--dry-run",
                                      "--root", str(root))
            self.assertEqual((code, err), (0, ""))
            self.assertEqual(list(env["data"]), ["agents", "check", "dry_run", "skills",
                                                 "agent_files", "summary", "failed", "notes"])
            rows = env["data"]["agent_files"]
            self.assertEqual(len(rows), 3)
            for r in rows:
                self.assertEqual(list(r), documented)
                self.assertEqual((r["agent"], r["status"]), ("codex", "created"))
            self.assertEqual(run_json("packs", "sync", "--agent", "codex", "--root",
                                      str(root))[0], 0)
            edited = root / rows[0]["path"]
            edited.write_text(edited.read_text(encoding="utf-8") + "# ours\n", encoding="utf-8")
            for argv in ((), ("--check",)):  # every skill row unchanged, one agent file not
                with self.subTest(argv=argv):
                    code, env, _ = run_json("packs", "sync", *argv, "--agent", "codex",
                                            "--root", str(root))
                    self.assertEqual((code, env["data"]["failed"]), (1, True))
                    self.assertEqual({r["status"] for r in env["data"]["skills"]}, {"unchanged"})
                    self.assertEqual([r["status"] for r in env["data"]["agent_files"]],
                                     ["conflict", "unchanged", "unchanged"])

    def test_the_init_actions(self):  # P5A-AC-029, P5A-AC-042: on a repository without modules
        keys = {"map": {"action", "root", "files", "preflight", "proposal", "candidates",
                        "unassigned", "hints", "phase", "next", "dry_run"},
                "status": {"action", "phase", "phases", "next", "modules", "counts",
                           "pr"},  # P5B-AC-027
                "resume": {"action", "ran", "phase", "next", "message"},
                "confirm": {"action", "confirmed", "included", "excluded", "status",
                            "dry_run"}}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "code"
            (root / "src/shelf").mkdir(parents=True)
            (root / "src/shelf/books.py").write_text("BOOKS = []\n")
            for action in ("map", "status", "resume", "confirm"):
                with self.subTest(action=action):
                    code, env, err = run_json("init", action, "--root", str(root))
                    self.assertEqual((code, err), (0, ""))
                    self.assertEqual((set(env), env["schema"]), ({"schema", "data"},
                                                                 "segmently-modules.init/1"))
                    self.assertEqual(set(env["data"]), keys[action])

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
