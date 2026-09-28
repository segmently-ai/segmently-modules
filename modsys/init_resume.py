"""`init resume` — continue from the recorded phase (D5, SI-21): every scripted step that can run
runs; the first step that needs an agent or a person stops the run, named in `next` (exit 0).

  plain                 re-runs an interrupted phase before gate 3, stops at gate 3; after it:
                        the fan-out (when it has not run), running / failed modules back to
                        pending, then reconcile and verify when their inputs exist
  --executor CMD        also runs the pending modules (`init run`) and writes the routing tasks
                        (`init eval-tasks`) when they are missing
  --non-interactive     never waits for a person: gate 3 passes as the proposal stands (`init
                        confirm`), a missing executor is exit 2, a verify that does not pass is
                        exit 1; it stops before gate 7 unless `--open-pr`
  --open-pr             gate 7 as a pull request: `init finish --open-pr` (or, after a failed
                        push or `gh`, the steps that are left)"""
import json

from modsys.output import EXIT_FINDINGS, EXIT_OK, UsageError


class Chain:
    def __init__(self, flow, work, argv: list[str] | None, non_interactive: bool,
                 open_pr: bool, base: str | None, branch: str):
        self.flow, self.work, self.argv = flow, work, argv
        self.non_interactive, self.open_pr = non_interactive, open_pr
        self.base, self.branch = base, branch
        self.ran: list[str] = []
        self.messages: list[str] = []

    def need_executor(self, what: str) -> None:
        if self.non_interactive and self.argv is None:
            raise UsageError(f"{what}: init resume --non-interactive needs --executor "
                             f"\"<command>\"")

    def verified(self) -> bool:
        """verify ran, passed, and the staging tree is the one it verified."""
        from modsys.init_verify import tree_sha
        try:
            doc = json.loads((self.flow.work / "verify.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return doc.get("passed") is True and doc.get("staging_sha256") == \
            tree_sha(self.work.staging)

    def run(self) -> int:
        """The steps that are left; the exit code."""
        from modsys.init_finish import Finish
        from modsys.init_reconcile import Reconcile
        from modsys.init_run import Runner
        from modsys.init_verify import Verify
        flow, work = self.flow, self.work
        state = flow.load_state()
        if state is None:
            raise UsageError("no init state to resume — run modsys init map")
        if state["phases"]["finish"]["status"] == "done":
            if state.get("pr") == "pending" and self.open_pr:
                self.ran.append("pr")
                url, error = Finish(work).publish(state)
                if error:
                    self.messages.append(f"the pull request is still pending: {error}")
                    return EXIT_FINDINGS
                return EXIT_OK
            self.messages.append("init is finished")
            return EXIT_OK
        state, ran = flow.resume()
        self.ran += ran
        if state["phases"]["gate-map"]["status"] != "done":
            if not self.non_interactive:
                return EXIT_OK  # gate 3 is a person's
            flow.confirm(False)
            self.ran.append("gate-map")
        state = flow.load_state()
        if state["phases"]["fanout"]["status"] != "done":
            work.fanout()
            self.ran.append("fanout")
        reset = work.reset()
        if reset:
            self.messages.append(f"back to pending (their staging cleared): {', '.join(reset)}")
        state = flow.load_state()
        if any(e["status"] != "done" for e in state["modules"].values()):
            self.need_executor("modules are pending")
            if self.argv is None:
                return EXIT_OK  # an agent writes them: init next / done, or init run
            result = Runner(work, self.argv).run()
            self.ran.append("run")
            failed = [r["module"] for r in result["modules"] if r["status"] == "failed"]
            if failed or result["outside"]:
                self.messages += [f"{m} failed (see modsys init status)" for m in failed]
                self.messages += [f"wrote outside the staging dir: {p}"
                                  for p in result["outside"]]
                return EXIT_FINDINGS
        state = flow.load_state()
        if state["phases"]["reconcile"]["status"] != "done":
            Reconcile(work).run(False)
            self.ran.append("reconcile")
        check = Verify(work)
        if not check.tasks_path.is_file():
            self.need_executor("the routing tasks are missing")
            if self.argv is None:
                return EXIT_OK  # an agent (or a person) writes them
            result = check.eval_tasks(self.argv, False)
            self.ran.append("eval-tasks")
            if result["problems"]:
                self.messages += [f"eval-tasks: {p}" for p in result["problems"]]
                return EXIT_FINDINGS
        if not self.verified():
            result = check.run()
            self.ran.append("verify")
            if not result["passed"]:
                self.messages.append("verify did not pass — see verify.json")
                return EXIT_FINDINGS
        if not self.open_pr:
            return EXIT_OK  # gate 7 is a person's: init finish
        result = Finish(work).run(False, [], True, self.base, self.branch)
        self.ran.append("finish")
        if result["error"]:
            self.messages.append(f"the pull request is pending: {result['error']}")
            return EXIT_FINDINGS
        return EXIT_OK
