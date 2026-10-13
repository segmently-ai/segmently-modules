"""`init` end to end without a person (D5, SI-21, SI-25): the explicit chain, `init resume
--non-interactive --executor … [--open-pr]` from every recorded phase, plain `init resume`, the
pull request retried after a failed push or `gh`; staging only until gate 7; modules a P5a user
created by hand."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.fixtures.build_monorepo import build
from tests.helpers import git, run, run_json
from tests.init_fake_executor import write_docs
from tests.init_helpers import (IDENTITY, SIX, WORK, bare_remote, executor, gh_shim, ok,
                                protected_sha, shop, state, statuses)

DESC = "The {} module of the bookshop: its code and what it does."


class ChainRepo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name).resolve()
        self.log = self.base / "gh.jsonl"
        gh_shim(self.base / "bin", self.log)
        self.env = {**IDENTITY, "PATH": f"{self.base / 'bin'}{os.pathsep}{os.environ['PATH']}"}

    def tearDown(self):
        self._tmp.cleanup()

    def resume(self, root: Path, *flags: str, code: int = 0, fake: tuple = ()) -> dict:
        argv = ["init", "resume", *flags]
        if fake is not None:
            argv += ["--executor", executor(*fake)]
        with mock.patch.dict(os.environ, self.env):
            got, env, err = run_json(*argv, "--root", str(root))
        self.assertEqual(got, code, err)
        return {**(env["data"] if env else {}), "err": err}

    def prs(self) -> list[dict]:
        return [json.loads(l) for l in self.log.read_text().splitlines()] \
            if self.log.exists() else []


class ChainTest(ChainRepo):  # P5B-AC-026
    def test_the_explicit_chain(self):
        root = shop(self.base)
        bare_remote(root, self.base / "remote.git")
        for argv in (("fanout",), ("run", "--executor", executor()), ("reconcile",),
                     ("eval-tasks", "--executor", executor()), ("verify",)):
            ok(root, "init", *argv)
        with mock.patch.dict(os.environ, self.env):
            data = ok(root, "init", "finish", "--open-pr")
        self.assertEqual((data["pr"], state(root)["phase"], len(self.prs())),
                         ("https://example.invalid/bookshop/pull/1", "finished", 1))
        for action in ("map", "confirm"):  # they never prompt: no --non-interactive (SI-25)
            code, out, err = run("init", action, "--non-interactive", "--root", str(root))
            self.assertEqual((code, out), (2, ""))
            self.assertIn(f"init {action} never prompts: drop --non-interactive", err)

    def test_from_gate_3(self):
        root = build(self.base / "shop")
        ok(root, "init", "map")
        data = self.resume(root, "--non-interactive")
        self.assertEqual(data["ran"], ["gate-map", "fanout", "run", "reconcile", "eval-tasks",
                                       "verify"])
        self.assertIn("segmently-modules init finish", data["next"])  # gate 7 stays with a person or a PR
        self.assertEqual(sorted(statuses(root)), sorted(SIX + ["tools"]))

    def test_from_a_half_done_fan_out(self):
        root = shop(self.base)
        ok(root, "init", "fanout")
        s = state(root)
        for m in ("cart", "catalog"):
            write_docs(root, json.loads((root / WORK / "work" / f"{m}.json").read_text()))
            s["modules"][m].update(status="done", attempts=1)
        s["modules"]["payments"].update(status="running", attempts=1)
        (root / WORK / "state.json").write_text(json.dumps(s))
        data = self.resume(root, "--non-interactive")
        self.assertEqual(data["ran"], ["run", "reconcile", "eval-tasks", "verify"])
        self.assertEqual(data["message"], "back to pending (their staging cleared): payments")
        self.assertEqual(set(statuses(root).values()), {"done"})
        self.assertEqual(state(root)["modules"]["cart"]["attempts"], 1)  # never re-run
        with mock.patch.dict(os.environ, self.env):
            bare_remote(root, self.base / "remote.git")
        data = self.resume(root, "--non-interactive", "--open-pr")
        self.assertEqual((data["ran"], state(root)["phase"], len(self.prs())),
                         (["finish"], "finished", 1))
        data = self.resume(root, "--non-interactive")
        self.assertEqual((data["ran"], data["message"]), ([], "init is finished"))

    def test_a_failed_verify_and_a_missing_executor(self):
        root = shop(self.base)
        data = self.resume(root, "--non-interactive", code=1, fake=("--tasks-mode", "half"))
        self.assertIn("verify", data["err"])
        self.assertEqual(state(root)["phases"]["finish"]["status"], "pending")
        other = shop(self.base, name="other")
        ok(other, "init", "fanout")
        data = self.resume(other, "--non-interactive", code=2, fake=None)
        self.assertIn('modules are pending: init resume --non-interactive needs --executor', data["err"])

    def test_a_missing_executor_is_refused_before_anything_runs(self):  # M-2, from gate 3
        root = build(self.base / "shop")
        ok(root, "init", "map")
        before = {p: p.read_bytes() for p in (root / WORK).rglob("*") if p.is_file()}
        data = self.resume(root, "--non-interactive", code=2, fake=None)
        self.assertIn('modules are pending: init resume --non-interactive needs --executor '
                      '"<command>" (nothing ran)', data["err"])
        self.assertEqual({p: p.read_bytes() for p in (root / WORK).rglob("*") if p.is_file()},
                         before)  # gate 3 is still open: the proposal can still be edited
        self.assertEqual(ok(root, "init", "confirm")["status"], "confirmed")
        other = shop(self.base, name="other")  # every module written: the tasks are missing
        ok(other, "init", "fanout")
        ok(other, "init", "run", "--executor", executor())
        data = self.resume(other, "--non-interactive", code=2, fake=None)
        self.assertIn("the routing tasks are missing: init resume --non-interactive needs "
                      "--executor", data["err"])
        self.assertEqual(state(other)["phases"]["reconcile"]["status"], "pending")

    def test_plain_resume(self):
        root = shop(self.base)
        data = self.resume(root, fake=None)  # the fan-out, then a writer is needed
        self.assertEqual(data["ran"], ["fanout"])
        self.assertIn("segmently-modules init run --executor", data["next"])
        ok(root, "init", "run", "--executor", executor("--fail", "cart"), code=1)
        data = self.resume(root, fake=None)
        self.assertEqual((data["ran"], data["message"]),
                         ([], "back to pending (their staging cleared): cart"))
        ok(root, "init", "run", "--executor", executor())
        data = self.resume(root, fake=None)  # reconcile runs; the routing tasks need an agent
        self.assertEqual(data["ran"], ["reconcile"])
        self.assertIn("segmently-modules init eval-tasks", data["next"])
        ok(root, "init", "eval-tasks", "--executor", executor())
        data = self.resume(root, fake=None)
        self.assertEqual(data["ran"], ["verify"])
        self.assertIn("segmently-modules init finish", data["next"])


class PullRequestRetryTest(ChainRepo):  # P5B-AC-025 (the retries), SI-20
    def verified(self) -> Path:
        root = shop(self.base)
        self.resume(root, "--non-interactive")
        return root

    def test_a_failed_push_then_resume(self):
        root = self.verified()
        remote = bare_remote(root, self.base / "remote.git")
        shutil.rmtree(remote)  # the remote is gone: the push fails
        with mock.patch.dict(os.environ, self.env):
            code, env, err = run_json("init", "finish", "--open-pr", "--root", str(root))
        self.assertEqual((code, env["data"]["pr"]), (1, "pending"))
        self.assertIn("git push failed", err)
        git(self.base, "init", "-q", "--bare", "remote.git")
        data = self.resume(root, "--open-pr", fake=None)
        self.assertEqual((data["ran"], state(root)["pr"]),
                         (["pr"], "https://example.invalid/bookshop/pull/1"))
        self.assertEqual(len(self.prs()), 1)
        self.assertEqual(git(self.base / "remote.git", "rev-parse", "segmently-modules/init"),
                         git(root, "rev-parse", "HEAD"))
        self.assertEqual(git(root, "rev-list", "--count", "main..HEAD").strip(), "1")

    def test_a_failed_commit_then_resume(self):  # a pre-commit hook refuses it once (C-1)
        root = self.verified()
        bare_remote(root, self.base / "remote.git")
        marker = self.base / "the hook ran"
        hook = root / ".git/hooks/pre-commit"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text(f"#!/bin/sh\nif [ ! -f '{marker}' ]; then touch '{marker}'; "
                        f"echo 'lint-staged: failed' >&2; exit 1; fi\n")
        hook.chmod(0o755)
        with mock.patch.dict(os.environ, self.env):
            code, env, err = run_json("init", "finish", "--open-pr", "--root", str(root))
        self.assertEqual((code, env["data"]["pr"]), (1, "pending"))
        self.assertIn("git commit failed on branch segmently-modules/init: lint-staged: failed", err)
        self.assertIn("the retry picks up from the branch", err)
        record = state(root)["open_pr"]
        self.assertEqual((record["branch_created"], record["committed"], record["pushed"]),
                         (True, False, False))
        git(root, "checkout", "-q", "main")  # the person looked around: resume goes back
        data = self.resume(root, "--open-pr", fake=None)
        self.assertEqual((data["ran"], state(root)["pr"]),
                         (["pr"], "https://example.invalid/bookshop/pull/1"))
        self.assertEqual(len(self.prs()), 1)  # one gh, one push, one commit
        self.assertEqual(git(self.base / "remote.git", "rev-parse", "segmently-modules/init"),
                         git(root, "rev-parse", "segmently-modules/init"))
        self.assertEqual(git(root, "rev-list", "--count", "main..segmently-modules/init").strip(), "1")
        self.assertEqual(git(root, "branch", "--show-current").strip(), "segmently-modules/init")
        self.assertEqual(git(root, "log", "-1", "--format=%s", "segmently-modules/init").strip(),
                         "docs: module docs for 6 module(s) (segmently-modules init)")
        self.assertEqual(git(root, "status", "--porcelain"), "")
        data = self.resume(root, "--open-pr", fake=None)
        self.assertEqual((data["ran"], data["message"]), ([], "init is finished"))

    def test_a_failed_gh_then_resume(self):
        root = self.verified()
        bare_remote(root, self.base / "remote.git")
        gh_shim(self.base / "bin", self.log, code=1)
        with mock.patch.dict(os.environ, self.env):
            code, env, _ = run_json("init", "finish", "--open-pr", "--root", str(root))
        self.assertEqual((code, state(root)["open_pr"]["pushed"]), (1, True))
        gh_shim(self.base / "bin", self.log)
        data = self.resume(root, "--open-pr", fake=None)
        self.assertEqual(data["ran"], ["pr"])
        self.assertEqual(len(self.prs()), 2)  # gh again; nothing pushed twice
        self.assertEqual(git(root, "rev-list", "--count", "main..HEAD").strip(), "1")
        self.assertIn("pr         https://example.invalid/bookshop/pull/1",
                      run("init", "status", "--root", str(root))[1].splitlines())

    def killed(self, root: Path, when) -> None:
        """`init finish --open-pr`, killed right after the step `when(state)` recognises and
        before the state records it."""
        from segmently_modules.init_flow import InitFlow
        real = InitFlow.save_state

        def save(flow, s):
            if when(s):
                raise KeyboardInterrupt
            return real(flow, s)

        with mock.patch.dict(os.environ, self.env), \
                mock.patch("segmently_modules.init_flow.InitFlow.save_state", autospec=True,
                           side_effect=save):
            code, _, err = run_json("init", "finish", "--open-pr", "--root", str(root))
        self.assertEqual((code, err), (130, "segmently-modules: interrupted\n"))

    def test_a_commit_made_but_not_recorded(self):  # N-2: never "nothing to commit" forever
        root = self.verified()
        remote = bare_remote(root, self.base / "remote.git")
        self.killed(root, lambda s: (s.get("open_pr") or {}).get("committed") is True)
        self.assertEqual(state(root)["open_pr"]["committed"], False)
        self.assertEqual(git(root, "rev-list", "--count", "main..segmently-modules/init").strip(), "1")
        data = self.resume(root, "--open-pr", fake=None)
        self.assertEqual((data["ran"], state(root)["pr"]),
                         (["pr"], "https://example.invalid/bookshop/pull/1"))
        self.assertEqual(len(self.prs()), 1)
        self.assertEqual(git(root, "rev-list", "--count", "main..segmently-modules/init").strip(), "1")
        self.assertEqual(git(remote, "rev-parse", "segmently-modules/init"), git(root, "rev-parse", "HEAD"))
        record = state(root)["open_pr"]
        self.assertEqual((record["committed"], record["pushed"]), (True, True))

    def test_a_pr_created_but_not_recorded(self):  # N-2: gh's "already exists" is that PR
        root = self.verified()
        bare_remote(root, self.base / "remote.git")
        gh_shim(self.base / "bin", self.log, remember=True)
        self.killed(root, lambda s: str(s.get("pr")).startswith("https://"))
        self.assertEqual(state(root)["pr"], "pending")
        data = self.resume(root, "--open-pr", fake=None)
        self.assertEqual((data["ran"], state(root)["pr"]),
                         (["pr"], "https://example.invalid/bookshop/pull/1"))
        self.assertEqual([c["created"] for c in self.prs()], [True, False])  # one PR, not two
        self.assertEqual(git(root, "rev-list", "--count", "main..HEAD").strip(), "1")
        data = self.resume(root, "--open-pr", fake=None)
        self.assertEqual((data["ran"], data["message"]), ([], "init is finished"))


class StagingOnlyChainTest(ChainRepo):  # P5B-AC-011 (every phase before gate 7)
    def test_only_finish_changes_the_protected_files(self):
        root = shop(self.base)
        (root / "CLAUDE.md").write_text("# notes\n")
        before = protected_sha(root)
        steps = [("fanout",), ("next",), ("run", "--executor", executor()), ("resume",),
                 ("reconcile",), ("eval-tasks", "--executor", executor("--tasks-mode", "half")),
                 ("verify",), ("eval-tasks", "--executor", executor(), "--force"), ("verify",)]
        codes = [0, 0, 0, 0, 0, 0, 1, 0, 0]
        for argv, code in zip(steps, codes):
            with self.subTest(step=argv[0]):
                got = run("init", *argv, "--root", str(root))[0]
                self.assertEqual(got, code)
                self.assertEqual(protected_sha(root), before)
        ok(root, "init", "finish")
        self.assertNotEqual(protected_sha(root), before)


class ExistingModulesChainTest(ChainRepo):  # P5B-AC-051 (a P5a user who created them by hand)
    def test_all_six_created_by_hand(self):
        root = shop(self.base)
        for m in SIX:
            ok(root, "create", m, "--non-interactive", "--description", DESC.format(m),
               "--keywords", f"{m}, {m}-code, {m}-docs, {m}-change, {m}-fix")
        registry = (root / "modules/registry.json").read_bytes()
        docs = {p: p.read_bytes() for p in (root / "modules").rglob("*.md")}
        data = self.resume(root, fake=None)
        self.assertEqual(data["ran"], ["fanout", "reconcile"])
        self.assertTrue(all(e.get("existing") for e in state(root)["modules"].values()))
        ok(root, "init", "verify")
        data = ok(root, "init", "finish")
        self.assertEqual((data["moved"], data["code_map"]), ([], []))
        self.assertEqual((root / "modules/registry.json").read_bytes(), registry)
        self.assertEqual({p: p.read_bytes() for p in (root / "modules").rglob("*.md")}, docs)
        self.assertEqual(run("lint", "--fail-on", "warning", "--root", str(root))[0], 0)


if __name__ == "__main__":
    unittest.main()
