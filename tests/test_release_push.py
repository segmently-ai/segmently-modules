"""`tools/release.py` (P6 D7): the push is never put back; the publish repository's
foreign content is kept and the organisation of --publish-slug appears nowhere in the
engine. Split from `test_release.py` (P8.3 D5 R-3)."""
import json
import re
import shlex
import unittest

from tests.helpers import git
from tests.release_helpers import MACHINE_PATHS, NXT_DEV, REL, ReleaseRepo, TAGS


class PushTest(ReleaseRepo):  # final review I-4, M-9: the push is never put back
    def test_a_failed_push_leaves_the_release_and_names_the_commands(self):
        self.remotes()
        git(self.pub, "remote", "set-url", "origin", str(self.base / "missing.git"))
        proc = self.release("stable", "--push")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("release.py: step 10 push failed: publish repo: git push --atomic origin "
                      "refs/heads/stable", proc.stderr)
        self.assertIn("— nothing is put back: the release is committed and tagged locally; "
                      "pushed: nothing; left to push by hand:\n"
                      f"  git -C {shlex.quote(str(self.pub))} push --atomic origin "
                      f"refs/heads/stable refs/tags/v{REL} ", proc.stderr)
        self.assertIn(f"\n  git -C {self.engine} push --atomic origin refs/heads/main "
                      f"refs/tags/v{REL}\n", proc.stderr)
        self.assertNotIn("as they were", proc.stderr)
        self.assertEqual(git(self.engine, "log", "--format=%s", "-3").splitlines(),
                         [f"start modsys {NXT_DEV}", f"release modsys {REL}", "engine"])
        self.assertEqual(git(self.engine, "tag", "-l").split(), [f"v{REL}"])
        self.assertEqual(sorted(git(self.pub, "tag", "--points-at", "stable").split()),
                         [t.format(REL) for t in TAGS])
        self.assertEqual(list(self.tmpdir.iterdir()), [])

    def test_ctrl_c_during_the_engine_push_resets_nothing(self):
        remotes = self.remotes()
        self.git_wrapper(f'case "$*" in *"-C {self.engine} push "*) '  # the operator's Ctrl-C
                         'kill -INT $PPID; sleep 5; exit 1 ;; esac')  # while this push runs
        proc = self.release("stable", "--push")
        self.assertEqual(proc.returncode, 130, proc.stdout + proc.stderr)
        self.assertIn("release.py: interrupted during the push — nothing is put back", proc.stderr)
        self.assertIn("pushed: publish repo; left to push by hand:\n"
                      f"  git -C {self.engine} push --atomic origin refs/heads/main "
                      f"refs/tags/v{REL}\n", proc.stderr)
        self.assertNotIn(f"git -C {shlex.quote(str(self.pub))} push", proc.stderr)
        self.assertEqual(sorted(self.refs(remotes["publish"])),
                         ["refs/heads/stable"] + [f"refs/tags/{t.format(REL)}" for t in TAGS])
        self.assertEqual(self.refs(remotes["engine"]), ["refs/heads/main"])
        self.assertEqual(git(self.engine, "log", "--format=%s", "-3").splitlines(),
                         [f"start modsys {NXT_DEV}", f"release modsys {REL}", "engine"])
        self.assertEqual(git(self.engine, "tag", "-l").split(), [f"v{REL}"])
        self.assertEqual(self.log(self.pub, "stable"), [f"release modsys {REL} (stable)"])
        self.assertEqual(git(self.pub, "rev-parse", "stable"),
                         git(remotes["publish"], "rev-parse", "stable"))


class OwnershipTest(ReleaseRepo):  # P6-AC-016 (SI-17), P6-AC-021
    def test_foreign_content_is_kept(self):
        git(self.pub, "checkout", "-q", "-b", "dev")
        extra = {"name": "modsys-extra", "source": "./plugins/modsys-extra"}
        files = {
            "plugins/other-tool/plugin.json": '{"name": "other-tool"}\n',
            "plugins/modsys-extra/README.md": "not ours\n",
            "plugins/modsys/old.txt": "stale\n",
            ".claude-plugin/marketplace.json": json.dumps({"name": "x", "owner": {"name": "y"},
                                                           "plugins": [{"name": "other-tool",
                                                                        "source": "./plugins/"
                                                                                  "other-tool"},
                                                                       extra]}),
            ".agents/plugins/marketplace.json": json.dumps({"name": "x", "plugins": [
                {"name": "other-tool", "source": {"source": "local",
                                                  "path": "./plugins/other-tool"}},
                {"name": "modsys-extra", "source": {"source": "local",
                                                    "path": "./plugins/modsys-extra"}}]}),
            "README.md": "# Plugins\n\nIntro text.\n\n<!-- modsys:begin -->\nold\n"
                         "<!-- modsys:end -->\n\nOutro text.\n",
            "CHANGELOG.md": "# Changes\n\n## other-tool\n\n- 9.0.0\n"}
        for rel, text in files.items():
            (self.pub / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.pub / rel).write_text(text)
        git(self.pub, "add", "--", *files)
        git(self.pub, "commit", "-q", "-m", "foreign")
        proc = self.release("dev")
        self.assert_ok(proc)
        self.assertFalse((self.pub / "plugins/modsys/old.txt").exists())
        for rel in ("plugins/other-tool/plugin.json", "plugins/modsys-extra/README.md"):
            self.assertEqual((self.pub / rel).read_text(), files[rel])
        for rel in (".claude-plugin/marketplace.json", ".agents/plugins/marketplace.json"):
            doc = json.loads((self.pub / rel).read_text())
            self.assertEqual(doc["plugins"][:2], json.loads(files[rel])["plugins"])
            self.assertEqual([e["name"] for e in doc["plugins"]],
                             ["other-tool", "modsys-extra", "modsys", "modsys-qa", "modsys-ui"])
        readme = (self.pub / "README.md").read_text()
        self.assertTrue(readme.startswith("# Plugins\n\nIntro text.\n\n<!-- modsys:begin -->\n"))
        self.assertTrue(readme.endswith("<!-- modsys:end -->\n\nOutro text.\n"))
        self.assertNotIn("\nold\n", readme)
        log = (self.pub / "CHANGELOG.md").read_text()
        self.assertTrue(log.startswith(files["CHANGELOG.md"]))
        self.assertEqual(log.count("(dev): engine "), 1)
        written = git(self.pub, "show", "--name-only", "--format=", "HEAD").split()
        for rel in written:
            text = (self.pub / rel).read_bytes() if (self.pub / rel).is_file() else b""
            for bad in (*MACHINE_PATHS, str(self.base), str(self.tmpdir),
                        self.env["MODSYS_GUARD"]):
                self.assertNotIn(bad.encode(), text, rel)
            if rel != "README.md":
                self.assertNotIn(b"example-org", text, rel)  # D13: the README section only
        self.assertIn("example-org", readme)
        self.assertNotIn("example-org", git(self.pub, "log", "-1", "--format=%B"))

    def test_the_organisation_anywhere_in_the_engine(self):
        doc = self.engine / "modsys/defaults/templates/roles/po.md"
        original = doc.read_text()
        doc.write_text(original + "\nSee example-org/modsys.\n")
        proc = self.release("dev")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("appears in the engine: file modsys/defaults/templates/roles/po.md",
                      proc.stderr)
        git(self.engine, "commit", "-q", "-am", "planted")
        doc.write_text(original)
        git(self.engine, "commit", "-q", "-am", "removed")
        proc = self.release("dev")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("appears in the engine: history", proc.stderr)

    def test_the_organisation_scan_names_places_not_hashes(self):
        git(self.engine, "tag", "-a", "a-note", "-m", "as agreed with tag-org")
        proc = self.release("dev", slug="tag-org/modsys-plugins")  # an annotated tag's message
        self.assertEqual(proc.returncode, 2)
        self.assertIn("appears in the engine: history — no repository slug", proc.stderr)
        proc = self.release("dev", slug="a/modsys-plugins")  # in almost every file: one line
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stderr.count("\n"), 1)
        self.assertEqual(proc.stderr.count("file "), 10)
        self.assertRegex(proc.stderr, r"file \S+ … and \d+ more — no repository slug")
        self.assertLess(len(proc.stderr), 900)
        (self.pub / "scratch.txt").write_text("x\n")  # step 2 refuses: step 1 has passed
        commit = git(self.engine, "rev-parse", "HEAD").strip()
        blob = re.search(r"^index 0+\.\.([0-9a-f]{7,})", git(
            self.engine, "log", "-p", "--format=%B", "--", "pyproject.toml"), re.M).group(1)
        for hexlike in (commit[:12], blob):  # only a commit id / an `index` line holds it
            with self.subTest(organisation=hexlike):
                proc = self.release("dev", slug=f"{hexlike}/modsys-plugins")
                self.assertEqual(proc.returncode, 2)
                self.assertIn("the publish repo is dirty: scratch.txt", proc.stderr)


if __name__ == "__main__":
    unittest.main()
