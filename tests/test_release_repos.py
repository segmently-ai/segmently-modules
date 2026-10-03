"""`tools/release.py` (P6 D7): a fresh clone of the publish repository (a channel only on
origin) and the same build twice ("nothing to release"), a stable version released
twice. Split from `test_release.py` (P8.3 D5 R-3)."""
import re
import subprocess
import unittest

from tests.helpers import git
from tests.release_helpers import NXT, REL, ReleaseRepo, TAGS


class CloneTest(ReleaseRepo):  # final review I-3: a fresh clone of the publish repository
    def test_a_channel_that_exists_only_on_origin(self):
        self.commit(self.pub, "README.md", "# Plugins\n", "root")
        bare = self.remotes()["publish"]
        self.assert_ok(self.release("dev"))
        git(self.pub, "push", "-q", "origin", "main", "dev")
        clone = self.base / "clone"
        subprocess.run(["git", "clone", "-q", str(bare), str(clone)], check=True)
        self.assertEqual([r for r in self.refs(clone) if r.startswith("refs/heads/")],
                         ["refs/heads/main"])  # `dev` only as origin/dev
        before = self.state(clone)
        proc = self.release("dev", pub=clone)  # the engine's plugins are unchanged
        self.assert_ok(proc)
        self.assertIn("nothing to release", proc.stdout)
        self.assertEqual(self.state(clone), before)
        self.assertEqual(git(clone, "config", "--get-regexp", "^branch\\.").count("dev"), 0)
        self.assert_ok(self.release("stable"))  # the release, from the first clone
        git(self.pub, "push", "-q", "origin", "stable", "--tags")
        git(clone, "fetch", "-q", "--tags", "origin")
        self.notes("- The next release.")  # the first one dated the notes (D6)
        proc = self.release("stable", pub=clone)  # the next release, on top of what is published
        self.assert_ok(proc)
        self.assertEqual(self.log(clone, "stable"), [f"release modsys {NXT} (stable)",
                                                     f"release modsys {REL} (stable)", "root"])
        self.assertEqual(git(clone, "rev-parse", "stable~1"),
                         git(clone, "rev-parse", "origin/stable"))
        self.assertEqual(git(clone, "config", "branch.stable.merge").strip(),
                         "refs/heads/stable")  # it tracks origin's
        git(clone, "push", "-q", "--atomic", "origin", "refs/heads/stable",
            *(f"refs/tags/{t.format(NXT)}" for t in TAGS))  # a fast-forward: accepted
        git(self.pub, "fetch", "-q", "origin")  # the first clone is now behind origin/stable
        self.notes("- One more release.")  # step 1 passes: step 2 is what refuses
        before = self.both()
        proc = self.release("stable")
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("the publish repo's branch stable is behind origin/stable or has "
                      "diverged from it — run `git pull` there first", proc.stderr)
        self.assertEqual(self.both(), before)


class NoopTest(ReleaseRepo):  # P6-AC-029
    FROM_DEV_RELEASE = ("test_twice_then_a_change",)  # from the class's snapshot (R-3)

    def test_twice_then_a_change(self):
        self.assert_ok(self.release("dev"))
        before = self.state(self.pub)
        proc = self.release("dev")
        self.assert_ok(proc)
        self.assertIn("nothing to release", proc.stdout)
        self.assertEqual(self.state(self.pub), before)
        first = self.log(self.pub, "dev")
        self.change_a_skill()
        proc = self.release("dev")
        self.assert_ok(proc)
        after = self.log(self.pub, "dev")
        self.assertEqual(after[1:], first)
        self.assertNotEqual(after[0], first[0])
        self.assertRegex(after[0], rf"^release modsys {re.escape(REL)}-dev\.h[0-9a-f]{{8}} \(dev\)$")

    def test_stable_again_is_refused(self):
        self.assert_ok(self.release("stable"))
        subprocess.run(["git", "-C", str(self.engine), "reset", "-q", "--hard", "HEAD~1"],
                       check=True)  # back at the release commit: its tag exists
        self.notes("- Again.")  # notes: step 1 passes, the tag is what refuses
        proc = self.release("stable")
        self.assertEqual(proc.returncode, 2)
        self.assertIn(f"v{REL} already exists", proc.stderr)


if __name__ == "__main__":
    unittest.main()
