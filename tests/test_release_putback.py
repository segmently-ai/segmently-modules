"""`tools/release.py` (P6 D7) all or nothing, part 2: an empty publish repository and a
detached HEAD, publish files the release cannot use, a symlinked directory on the channel
branch, what appears beside the run, a put-back that cannot finish. Split from
`test_release.py` (P8.3 D5 R-3: `AllOrNothingTest` in two modules, method names kept)."""
import os
import subprocess
import unittest

from tests.helpers import git
from tests.release_helpers import AllOrNothingBase


class AllOrNothingTest(AllOrNothingBase):  # P6-AC-031 (SI-16)
    def test_an_empty_repository_and_a_detached_head(self):
        (self.pub / ".git/info/exclude").write_text("keep.me\n")
        (self.pub / "keep.me").write_text("ignored, the owner's\n")
        self.failed("dev", "step 8 smoke install failed", env={"FAKE_CLAUDE_FAIL": "install"})
        self.assertEqual(sorted(p.name for p in self.pub.iterdir()), [".git", "keep.me"])
        self.assert_ok(self.release("dev"))
        git(self.pub, "checkout", "-q", "--detach")
        self.failed("stable", "interrupted", env={"MODSYS_RELEASE_INTERRUPT": "7"}, code=130)
        self.assertEqual((self.pub / "keep.me").read_text(), "ignored, the owner's\n")

    def test_a_publish_file_the_release_cannot_use(self):
        git(self.pub, "checkout", "-q", "-b", "dev")
        (self.pub / ".claude-plugin").mkdir()
        (self.pub / ".claude-plugin/marketplace.json").write_text("{not json")
        outside = self.base / "outside.md"
        outside.write_text("not the release's\n")
        os.symlink(outside, self.pub / "CHANGELOG.md")
        lost = ("# Plugins\n\n<!-- modsys:begin -->\nold text\n\n## Other tool\n\n"
                "KEEP THIS PARAGRAPH.\n")  # the end marker was lost in a hand edit
        (self.pub / "README.md").write_text(lost)
        git(self.pub, "add", "--", ".claude-plugin", "CHANGELOG.md", "README.md")
        git(self.pub, "commit", "-q", "-m", "damaged")
        err = self.failed("dev", "step 6 publish repo failed")
        self.assertIn(".claude-plugin/marketplace.json in the publish repo is not valid JSON",
                      err)
        (self.pub / ".claude-plugin/marketplace.json").write_text('{"name": "x", "plugins": {}}')
        git(self.pub, "commit", "-q", "-am", "valid JSON, no list")
        err = self.failed("dev", "step 6 publish repo failed")
        self.assertIn(".claude-plugin/marketplace.json: plugins is not a list", err)
        (self.pub / ".claude-plugin/marketplace.json").write_text('{"name": "x", "plugins": []}')
        git(self.pub, "commit", "-q", "-am", "valid again")
        err = self.failed("dev", "step 6 publish repo failed")
        self.assertIn("README.md: the markers of the modsys section are damaged (1 "
                      "`<!-- modsys:begin -->`, 0 `<!-- modsys:end -->`)", err)
        self.assertEqual((self.pub / "README.md").read_text(), lost)
        (self.pub / "README.md").write_text("# Plugins\n")
        git(self.pub, "commit", "-q", "-am", "markers gone")
        err = self.failed("dev", "step 6 publish repo failed")
        self.assertIn("CHANGELOG.md in the publish repo is not a regular file", err)
        self.assertEqual(outside.read_text(), "not the release's\n")

    def test_a_symlinked_directory_on_the_channel_branch(self):  # re-review N-1
        outside = self.base / "outside"
        (outside / "modsys").mkdir(parents=True)
        (outside / "modsys/THEIRS.txt").write_text("not the release's\n")
        self.commit(self.pub, "README.md", "# Plugins\n", "root")
        git(self.pub, "switch", "-q", "-c", "dev")
        os.symlink(outside, self.pub / "plugins")  # on `dev` only: step 2 sees `main`
        git(self.pub, "add", "--", "plugins")
        git(self.pub, "commit", "-q", "-m", "plugins is a link")
        git(self.pub, "switch", "-q", "main")
        err = self.failed("dev", "step 6 publish repo failed")  # a local dev, not checked out
        self.assertIn("plugins is a symlink or a file on the dev branch of the publish repo", err)
        bare = self.base / "clone-origin.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
        git(self.pub, "remote", "add", "origin", str(bare))
        git(self.pub, "push", "-q", "origin", "main", "dev")
        clone = self.base / "clone"  # dev only as origin/dev
        subprocess.run(["git", "clone", "-q", str(bare), str(clone)], check=True,
                       capture_output=True)
        before = self.state(clone)
        proc = self.release("dev", pub=clone)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("step 6 publish repo failed: plugins is a symlink or a file on the dev "
                      "branch", proc.stderr)
        self.assertTrue(proc.stderr.rstrip().endswith("both repositories are as they were"))
        self.assertEqual(self.state(clone), before)
        self.assertEqual(sorted(p.relative_to(outside).as_posix() for p in outside.rglob("*")),
                         ["modsys", "modsys/THEIRS.txt"])  # nothing written outside
        self.assertEqual((outside / "modsys/THEIRS.txt").read_text(), "not the release's\n")

    def test_what_appears_beside_the_run_is_never_put_back(self):  # final review I-2
        kept = [True, ["refs/heads/hotfix", "refs/tags/my-mark"]]
        self.commit(self.pub, "README.md", "# Plugins\n", "root")
        before = self.state(self.pub)  # 1. in the engine, while step 3 runs: a refusal at the
        proc = self.release("stable", env={"PLANT_IN": str(self.engine)})  # first write there
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("release.py: error: the engine changed since step 2 checked it: "
                      "refs/heads/hotfix appeared, refs/tags/my-mark appeared, NOTES.txt — "
                      "nothing was written to it", proc.stderr)
        self.assertEqual(self.planted(self.engine), kept)
        self.assertEqual(self.log(self.engine, "main"), ["engine"])
        self.assertEqual(self.state(self.pub), before)
        (self.engine / "NOTES.txt").unlink()
        git(self.engine, "branch", "-q", "-D", "hotfix")
        git(self.engine, "tag", "-d", "my-mark")
        before = self.state(self.engine)  # 2. in the publish repository: the engine's release
        proc = self.release("stable", env={"PLANT_IN": str(self.pub)})  # commit is put back
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("the publish repo changed since step 2 checked it: refs/heads/hotfix "
                      "appeared, refs/tags/my-mark appeared, NOTES.txt — nothing was written "
                      "to it", proc.stderr)
        self.assertEqual(self.planted(self.pub), kept)
        self.assertEqual(self.state(self.engine), before)
        (self.pub / "NOTES.txt").unlink()
        git(self.pub, "branch", "-q", "-D", "hotfix")
        git(self.pub, "tag", "-d", "my-mark")
        plant = " ".join(f'echo mine > "{repo}/NOTES.txt"; "$real" -C "{repo}" branch hotfix; '
                         f'"$real" -C "{repo}" tag my-mark;' for repo in (self.engine, self.pub))
        self.git_wrapper('case "$*" in *"commit -q -m release modsys"*"(stable)"*) '
                         f'"$real" "$@"; rc=$?; {plant} exit $rc ;; esac')
        proc = self.release("stable", env={"FAKE_CLAUDE_FAIL": "install"})  # 3. after the
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)  # writes: step 8 fails
        self.assertIn("step 8 smoke install failed", proc.stderr)
        self.assertTrue(proc.stderr.rstrip().endswith("both repositories are as they were"))
        for repo in (self.engine, self.pub):  # theirs survives, the run's own is gone
            self.assertEqual(self.planted(repo), kept)
            self.assertEqual(git(repo, "status", "--porcelain"), "?? NOTES.txt\n")
            self.assertEqual(git(repo, "symbolic-ref", "HEAD").strip(), "refs/heads/main")
            self.assertEqual(self.refs(repo), ["refs/heads/hotfix", "refs/heads/main",
                                               "refs/tags/my-mark"])
        self.assertEqual(self.log(self.engine, "main"), ["engine"])
        self.assertEqual(self.log(self.pub, "main"), ["root"])
        self.assertEqual(sorted(p.name for p in self.pub.iterdir()),
                         [".git", "NOTES.txt", "README.md"])

    def test_the_put_back_finishes_and_says_what_is_true(self):  # task-8 review C2
        self.git_wrapper('case "$*" in *update-ref*) kill -INT $PPID ;; esac')  # Ctrl-C again,
        self.failed("stable", "interrupted", env={"MODSYS_RELEASE_INTERRUPT": "7"},  # inside
                    code=130)  # the put-back: ignored, both repositories are put back
        self.git_wrapper()
        self.commit(self.pub, "README.md", "# Plugins\n", "root")
        hook = self.pub / ".git/hooks/post-commit"  # another git process holds the index
        hook.write_text('#!/bin/sh\n: > "$(git rev-parse --git-dir)/index.lock"\n')
        hook.chmod(0o755)
        engine = self.state(self.engine)
        proc = self.release("stable", env={"FAKE_CLAUDE_FAIL": "install"})
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("release.py: step 8 smoke install failed", proc.stderr)
        self.assertIn("release.py: the put-back is incomplete — finish it by hand:\n"
                      "  publish repo: git reset -q --hard failed: ", proc.stderr)
        self.assertIn("\n  publish repo: still changed: ", proc.stderr)
        self.assertNotIn("as they were", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertEqual(self.state(self.engine), engine)  # the other one is put back
        self.assertEqual(self.refs(self.pub), ["refs/heads/main"])


if __name__ == "__main__":
    unittest.main()
