"""`init` phase 1, preflight (D4): the file set and its counts (1 MB, the NUL sniff, odd
files), and the repository metadata — git, languages, manifests, agent docs, ADRs, top dirs."""
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from modsys import preflight
from modsys.config import load_config
from tests.helpers import git, run_json

ENGINE = Path(__file__).resolve().parents[1]


class PreflightRepo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve() / "repo"
        self.root.mkdir()

    def tearDown(self):
        for path in self.root.rglob("*"):
            if not path.is_symlink():
                os.chmod(path, 0o755 if path.is_dir() else 0o644)
        self._tmp.cleanup()

    def write(self, rel: str, data) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        (path.write_bytes if isinstance(data, bytes) else path.write_text)(data)
        return path

    def doc(self) -> dict:
        code, env, err = run_json("init", "map", "--dry-run", "--root", str(self.root))
        self.assertEqual((code, err), (0, ""))
        files = preflight.list_files(self.root, load_config(self.root / ".modsys", self.root))
        counts = preflight.scan(self.root, files)
        return preflight.build(self.root, files, preflight.manifests(self.root, files,
                                                                     counts["texts"]), counts)


class FileSetTest(PreflightRepo):  # P5A-AC-030
    def test_the_counting_table(self):
        self.write(".modsys/config.toml", '[init]\nexclude = ["docs/**"]\n')
        self.write(".gitignore", "build/\n")
        self.write("src/a.py", "a = 1\nb = 2\nc = 3\n")  # tracked, 3 lines (18 bytes)
        self.write("src/gone.py", "x = 1\n")
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "add", "--", ".gitignore", ".modsys", "src")
        git(self.root, "commit", "-q", "-m", "base")
        (self.root / "src/gone.py").unlink()  # in the index, deleted from disk
        self.write("src/b.py", "b = 2\n")  # untracked, 1 line (6 bytes)
        self.write("build/out.js", "ignored();\n")
        self.write("docs/x.md", "# excluded\n")
        self.write("big/exact.txt", b"a" * (preflight.BIG - 1) + b"\n")  # 1 line, counted
        self.write("big/over.txt", b"a" * preflight.BIG + b"\n")  # files / bytes only
        self.write("bin/nul8191.dat", b"x" * 8191 + b"\0" + b"\n")  # binary
        self.write("bin/nul8192.txt", b"x" * 8192 + b"\0" + b"\n")  # text: 1 line
        self.write("misc/empty.txt", b"")
        self.write("misc/two.txt", "one\ntwo")  # 2 lines, no final newline
        (self.root / "misc/link.py").symlink_to(self.root / "src/a.py")
        unreadable = self.write("misc/secret.txt", "hidden\n")
        if os.geteuid() != 0:
            os.chmod(unreadable, 0)
        files = preflight.list_files(self.root, load_config(self.root / ".modsys", self.root))
        self.assertEqual(files, [".gitignore", ".modsys/config.toml", "big/exact.txt",
                                 "big/over.txt", "bin/nul8191.dat", "bin/nul8192.txt",
                                 "misc/empty.txt", "misc/link.py", "misc/secret.txt",
                                 "misc/two.txt", "src/a.py", "src/b.py"])
        read = []
        real = preflight._read
        with mock.patch("modsys.preflight._read",
                        side_effect=lambda p: read.append(p) or real(p)):
            counts = preflight.scan(self.root, files)
        self.assertNotIn(self.root / "misc/link.py", read)  # a symlink's target is never read
        self.assertNotIn(self.root / "big/over.txt", read)
        lines = {".gitignore": 1, ".modsys/config.toml": 2, "big/exact.txt": 1,
                 "bin/nul8192.txt": 1, "misc/empty.txt": 0, "misc/two.txt": 2, "src/a.py": 3,
                 "src/b.py": 1}
        if os.geteuid() == 0:  # root reads the mode-000 file: a text file like the others
            lines["misc/secret.txt"] = 1
        text = {rel: ((self.root / rel).stat().st_size, n) for rel, n in lines.items()}
        binary = {"big/over.txt": preflight.BIG + 1, "bin/nul8191.dat": 8193}
        self.assertEqual((text["big/exact.txt"][0], text["misc/two.txt"][0]),
                         (preflight.BIG, 7))
        self.assertEqual(counts["files"], 12)
        self.assertEqual(counts["bytes"], sum(b for b, _ in text.values())
                         + sum(binary.values()))
        self.assertEqual(counts["lines"], sum(n for _, n in text.values()))
        self.assertEqual(counts["text_bytes"], sum(b for b, _ in text.values()))
        self.assertEqual(counts["languages"], {"Python": [2, 4]})

    def test_the_token_estimate_and_outside_git(self):
        self.write("a.txt", "abcdef\n")  # 7 bytes -> 1
        self.write(".hidden/x.py", "x = 1\n")
        self.write("node_modules/dep/index.js", "module.exports = 1;\n")
        doc = self.doc()
        self.assertEqual((doc["files"], doc["token_estimate"], doc["git"]), (1, 1, None))
        self.write("b.txt", "a\n")  # 7 + 2 = 9 bytes -> 2
        self.assertEqual(self.doc()["token_estimate"], 2)

    def test_the_document_is_written_the_house_way(self):
        self.write("src/x/a.py", "x = 1\n")
        git(self.root, "init", "-q", "-b", "main")
        code, _, err = run_json("init", "map", "--root", str(self.root))
        self.assertEqual((code, err), (0, ""))
        text = (self.root / ".modsys/init/preflight.json").read_text(encoding="utf-8")
        doc = json.loads(text)
        self.assertEqual(text, json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
        self.assertEqual(list(doc), ["schema", "root", "git", "files", "lines", "bytes",
                                     "token_estimate", "languages", "manifests", "agent_docs",
                                     "adrs", "top_dirs"])


class MetadataTest(PreflightRepo):  # P5A-AC-031
    def test_git(self):
        self.assertIsNone(self.doc()["git"])
        git(self.root, "init", "-q", "-b", "main")
        self.assertEqual(self.doc()["git"], {"head": None, "commits": 0})
        self.write("a.py", "a = 1\n")
        git(self.root, "add", "--", "a.py")
        git(self.root, "commit", "-q", "-m", "one")
        head = git(self.root, "rev-parse", "HEAD").strip()
        self.assertEqual(self.doc()["git"], {"head": head, "commits": 1})

    def test_languages_manifests_agent_docs_adrs_and_top_dirs(self):
        files = {
            "web/package.json": '{"name": "@shop/web", "workspaces": {"packages": ["a/*"]}}',
            "root/package.json": '{"name": "shop", "workspaces": ["packages/*"]}',
            "api/pyproject.toml": '[project]\nname = "Shop_Api"\n',
            "legacy/setup.cfg": "[metadata]\nname = old-shop\n",
            "svc/go.mod": "module example.com/shop/svc\n\ngo 1.22\n",
            "rs/Cargo.toml": '[package]\nname = "shop-rs"\n',
            "php/composer.json": '{"name": "shop/php"}',
            "dotnet/Shop.Api.csproj": "<Project />",
            "bad/package.json": "{not json",
            "web/app.ts": "export const a = 1;\nexport const b = 2;\n",
            "api/main.py": "print(1)\n", "CLAUDE.md": "# notes\n", "AGENTS.md": "# notes\n",
            "docs/adr/0001-record.md": "# ADR\n", "README": "readme\n",
        }
        for rel, text in files.items():
            self.write(rel, text + ("\n" if not text.endswith("\n") else ""))
        doc = self.doc()
        self.assertEqual(doc["languages"], [{"language": "Python", "files": 1, "lines": 1},
                                            {"language": "TypeScript", "files": 1, "lines": 2}])
        self.assertEqual(doc["manifests"], [
            {"path": "api/pyproject.toml", "kind": "pyproject.toml", "name": "Shop_Api",
             "workspaces": []},
            {"path": "bad/package.json", "kind": "package.json", "name": None, "workspaces": []},
            {"path": "dotnet/Shop.Api.csproj", "kind": "csproj", "name": "Shop.Api",
             "workspaces": []},
            {"path": "legacy/setup.cfg", "kind": "setup.cfg", "name": "old-shop",
             "workspaces": []},
            {"path": "php/composer.json", "kind": "composer.json", "name": "shop/php",
             "workspaces": []},
            {"path": "root/package.json", "kind": "package.json", "name": "shop",
             "workspaces": ["packages/*"]},
            {"path": "rs/Cargo.toml", "kind": "Cargo.toml", "name": "shop-rs", "workspaces": []},
            {"path": "svc/go.mod", "kind": "go.mod", "name": "example.com/shop/svc",
             "workspaces": []},
            {"path": "web/package.json", "kind": "package.json", "name": "@shop/web",
             "workspaces": ["a/*"]}])
        self.assertEqual((doc["agent_docs"], doc["adrs"]), (["AGENTS.md", "CLAUDE.md"],
                                                            ["docs/adr/"]))
        self.assertEqual(doc["top_dirs"], ["api", "bad", "docs", "dotnet", "legacy", "php",
                                           "root", "rs", "svc", "web"])

    def test_the_docs_table_is_the_code_table(self):
        text = (ENGINE / "docs/configuration.md").read_text(encoding="utf-8")
        rows = dict(re.findall(r"^\| `(\.[a-z0-9]+)` \| ([^|]+?) \|$", text, re.M))
        self.assertEqual(rows, preflight.LANGUAGES)
        for name in preflight.AGENT_DOCS + tuple(f"{d}/" for d in preflight.ADR_DIRS):
            self.assertIn(f"`{name}`", text)


if __name__ == "__main__":
    unittest.main()
