"""P5b D12: the docs describe phases 4–7 — docs/init.md (new), the README "Start from existing
code" section with its three drivers, the contract rows, the `[init]` keys and the two skills."""
import re
import unittest
from pathlib import Path

from tests.test_docs import USER_DOCS

ENGINE = Path(__file__).resolve().parents[1]


def flat(rel: str) -> str:
    return " ".join((ENGINE / rel).read_text(encoding="utf-8").split())


class InitDocsTest(unittest.TestCase):  # P5B-AC-037
    def test_init_md(self):
        self.assertIn(ENGINE / "docs" / "init.md", USER_DOCS)
        text = flat("docs/init.md")
        for needle in ("| 4 | fan-out |", "| 5 | reconcile |", "| 6 | verify |", "gate 3",
                       "gate 7", "`pending` → `running` (claimed) → `done` or `failed`",
                       "`files_total`", "`init/module_prompt.md`", "`init/routing_prompt.md`",
                       "segmently-modules templates override init/module_prompt.md",
                       "`SEGMENTLY_MODULES_INIT_MODULE`, `SEGMENTLY_MODULES_INIT_STAGING` and `SEGMENTLY_MODULES_INIT_WORK`",
                       "1. **lint**", "2. **invented components**", "3. **keywords**", "4. **routing**",
                       "segmently-modules eval routing --prompt", "segmently-modules init finish --open-pr",
                       "segmently-modules init resume --non-interactive --executor", "`[init] max_parallel`",
                       "`[init] routing_min_hit_rate`", "never the tasks", "never a commit",
                       # the P5b follow-up: a documentation-only agent stops at gate 3 (G11)
                       "An agent that drives init stops after `init map`: it shows the "
                       "candidates and asks the person before `init confirm`"):
            self.assertIn(needle, text)

    def test_the_readme(self):
        start = flat("README.md").split("## Start from existing code", 1)[1].split(" ## ", 1)[0]
        for needle in ("**The `module-init` skill**", "**One agent, one module at a time**",
                       "**CI**", 'segmently-modules init run --executor "<command>"',
                       'segmently-modules init resume --non-interactive --executor "my-writer" --open-pr',
                       "segmently-modules init reconcile", "segmently-modules init verify", "segmently-modules init finish",
                       "(docs/init.md)"):
            self.assertIn(needle, start)
        self.assertNotIn("arrives with a later engine version", start)

    def test_the_contract_and_the_configuration(self):
        contract = flat("docs/cli-contract.md")
        for needle in ("| `init fanout\\|next\\|done` |", "| `init run --executor CMD` |",
                       "| `init reconcile` |", "| `init eval-tasks --executor CMD` |",
                       "| `init verify` |", "| `init finish` |", "| `eval routing` |",
                       "`SEGMENTLY_MODULES_INIT_TASKS`", "`work/<module>.json`", "`staging/registry.json`",
                       "`reconcile.json`", "`routing-tasks.json`", "`verify.json`",
                       "`state.json.lock`", "`pr-body.md`"):
            self.assertIn(needle, contract)
        config = flat("docs/configuration.md")
        self.assertIn("| `max_parallel` | `4` |", config)
        self.assertIn("| `routing_min_hit_rate` | `0.8` |", config)
        skills = flat("docs/skills.md")
        for sid in ("module-init", "module-adopt"):
            self.assertIn(f"| `{sid}` |", skills)

    def test_reconcile_removes_a_shared_keyword(self):  # P5C-AC-015 (D1), P6-AC-038 (D14)
        text = flat("docs/init.md")
        self.assertIn("another module loses it from its keywords only when none of its own files "
                      "holds it — a module whose code holds the word keeps it — and never as a "
                      "negative keyword", text)
        self.assertNotIn("negative_keywords", text)
        row = contract_row("| `init reconcile` |")
        self.assertIn("`collisions` `[{keyword, owner, others, files: {module: n}, removed}]`",
                      row)
        self.assertIn("another holder loses it from `keywords` only when none of its own files "
                      "holds it", row)
        self.assertIn("`kept by <module>, … (their files hold it)`", row)
        for doc in (text, row):  # no rule without its condition (P6-AC-038)
            self.assertNotIn("the others lose it", doc)
        self.assertIn("<the fields create asks for>, related_modules?}", row)
        self.assertIsNone(re.search(r"\bmoved\b", row))
        self.assertNotIn("negative_keywords", row)

    def test_the_placeholder_rule(self):  # P5C-AC-015 (D4)
        text = flat("docs/init.md")
        for needle in ("none empty or still holding a placeholder of the templates",
                       "Any other `${…}` is text", "`${title}` in a JavaScript string"):
            self.assertIn(needle, text)
        row = contract_row("| `init fanout\\|next\\|done` |")
        self.assertIn("one of the templates' own placeholders", row)
        self.assertNotIn("holding `${`", row)

    def test_the_check_at_init_done(self):  # P5C-AC-015 (D2)
        text = flat("docs/init.md")
        for needle in ("`init done` also runs the invented-component check",
                       "a writer may cite a sibling's doc before it is written",
                       "`MODULE.md:12: path does not exist: src/lines.ts (write paths from the "
                       "repository root, as in the file list)`",
                       "`init verify` still runs the full check"):
            self.assertIn(needle, text)
        row = contract_row("| `init fanout\\|next\\|done` |")
        self.assertIn("then the invented-component check of `init verify`", row)
        self.assertIn("`<doc>:<line>: path does not exist: <path> (write paths from the "
                      "repository root, as in the file list)`", row)

    def test_the_retry_and_the_note(self):  # P5C-AC-015 (D3, SI-5)
        text = flat("docs/init.md")
        for needle in ("retried once in the same run", "`segmently-modules: <module>: refused — retrying "
                       "once`", "`previous_problems`", "`## The previous attempt was refused`",
                       "it may quote a `${…}` from a problem line", "no retry"):
            self.assertIn(needle, text)
        rows = {start: contract_row(start) for start in (
            "| `init fanout\\|next\\|done` |", "| `init run --executor CMD` |",
            "| `init map\\|confirm\\|status\\|resume` |")}
        self.assertIn("`previous_problems: [problem]`", rows["| `init fanout\\|next\\|done` |"])
        run_row = rows["| `init run --executor CMD` |"]
        for needle in ("retried once in this run", "`segmently-modules: <module>: refused — retrying once`",
                       "`problems`"):
            self.assertIn(needle, run_row)
        self.assertIn("existing?, problems?}", rows["| `init map\\|confirm\\|status\\|resume` |"])


def contract_row(start: str) -> str:
    """The row of docs/cli-contract.md that starts with `start`."""
    lines = (ENGINE / "docs/cli-contract.md").read_text(encoding="utf-8").splitlines()
    return next(line for line in lines if line.startswith(start))


if __name__ == "__main__":
    unittest.main()
