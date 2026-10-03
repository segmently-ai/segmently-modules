"""`tools/release.py` (P6 D7) all or nothing, part 1: each failing step puts back what
the run wrote; SIGTERM and a closed terminal are an interrupt. Split from
`test_release.py` (P8.3 D5 R-3: `AllOrNothingTest` in two modules, method names kept)."""
import unittest

from tests.helpers import git
from tests.release_helpers import AllOrNothingBase, DATE, REL


class AllOrNothingTest(AllOrNothingBase):  # P6-AC-031 (SI-16)
    FROM_DEV_RELEASE = ("test_each_failing_step",)  # from the class's snapshot (R-3)

    def test_each_failing_step(self):
        self.assert_ok(self.release("dev"))  # the publish repo has a dev branch to put back
        git(self.pub, "switch", "-q", "-c", "main")  # and is on another one,
        self.commit(self.pub, "notes.md", "the owner's\n", "main work")
        for name in ("dev", "stable"):  # with a tag named like each channel branch
            git(self.pub, "tag", name)
        hook = self.engine / ".git/hooks/commit-msg"  # FAIL_COMMIT: that commit is refused
        hook.write_text('#!/bin/sh\n[ -n "$FAIL_COMMIT" ] && grep -q "^$FAIL_COMMIT" "$1" && '
                        'exit 1\nexit 0\n')
        hook.chmod(0o755)
        self.change_a_skill()
        self.failed("dev", "step 8 smoke install failed", env={"FAKE_CLAUDE_FAIL": "install"})
        self.failed("stable", "step 4 build failed", env={"FAIL_COMMIT": "release modsys"})
        self.failed("stable", "step 5 validate failed", env={"FAKE_CLAUDE_FAIL": "validate"})
        self.failed("stable", "step 8 smoke install failed", env={"FAKE_CLAUDE_FAIL": "install"})
        err = self.failed("stable", "step 8 smoke install failed",
                          env={"FAKE_CLAUDE_FAIL": "details"})  # whole names, not substrings
        self.assertIn("claude plugin details modsys does not name module-", err)
        self.failed("stable", "step 9 next version failed", env={"FAIL_COMMIT": "start modsys"})
        for seam in ("6", "7"):  # in the middle of step 6; after the commit, before the tags
            self.failed("stable", "interrupted", env={"MODSYS_RELEASE_INTERRUPT": seam},
                        code=130)  # P61-AC-036: the notes it dated in step 4 are put back
            self.assertIn(f"CHANGELOG.md [Unreleased] dated [{REL}] - {DATE}\n",
                          self.last.stdout)
        (self.engine / "tests/test_broken.py").write_text(
            "import unittest\n\n\nclass BrokenTest(unittest.TestCase):\n"
            "    def test_broken(self):\n        self.fail('planted')\n")
        git(self.engine, "add", "tests/test_broken.py")
        git(self.engine, "commit", "-q", "-m", "a failing test")
        self.failed("stable", "step 3 tests failed")

    def test_sigterm_and_a_closed_terminal_are_an_interrupt(self):
        self.failed("dev", "release.py: interrupted", env={"FAKE_GUARD_MODE": "hangup"},
                    code=130)
        self.git_wrapper('case "$*" in *"commit -q -m release modsys"*"(dev)"*) '
                         'kill -TERM $PPID; sleep 5; exit 1 ;; esac')
        self.failed("dev", "release.py: interrupted", code=130)


if __name__ == "__main__":
    unittest.main()
