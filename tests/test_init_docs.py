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
                       "modsys templates override init/module_prompt.md",
                       "`MODSYS_INIT_MODULE`, `MODSYS_INIT_STAGING` and `MODSYS_INIT_WORK`",
                       "1. **lint**", "2. **invented components**", "3. **routing**",
                       "modsys eval routing --prompt", "modsys init finish --open-pr",
                       "modsys init resume --non-interactive --executor", "`[init] max_parallel`",
                       "`[init] routing_min_hit_rate`", "never the tasks", "never a commit",
                       # the P5b follow-up: a documentation-only agent stops at gate 3 (G11)
                       "An agent that drives init stops after `init map`: it shows the "
                       "candidates and asks the person before `init confirm`"):
            self.assertIn(needle, text)

    def test_the_readme(self):
        start = flat("README.md").split("## Start from existing code", 1)[1].split(" ## ", 1)[0]
        for needle in ("**The `module-init` skill**", "**One agent, one module at a time**",
                       "**CI**", 'modsys init run --executor "<command>"',
                       'modsys init resume --non-interactive --executor "my-writer" --open-pr',
                       "modsys init reconcile", "modsys init verify", "modsys init finish",
                       "(docs/init.md)"):
            self.assertIn(needle, start)
        self.assertNotIn("arrives with a later engine version", start)

    def test_the_contract_and_the_configuration(self):
        contract = flat("docs/cli-contract.md")
        for needle in ("| `init fanout\\|next\\|done` |", "| `init run --executor CMD` |",
                       "| `init reconcile` |", "| `init eval-tasks --executor CMD` |",
                       "| `init verify` |", "| `init finish` |", "| `eval routing` |",
                       "`MODSYS_INIT_TASKS`", "`work/<module>.json`", "`staging/registry.json`",
                       "`reconcile.json`", "`routing-tasks.json`", "`verify.json`",
                       "`state.json.lock`", "`pr-body.md`"):
            self.assertIn(needle, contract)
        config = flat("docs/configuration.md")
        self.assertIn("| `max_parallel` | `4` |", config)
        self.assertIn("| `routing_min_hit_rate` | `0.8` |", config)
        skills = flat("docs/skills.md")
        for sid in ("module-init", "module-adopt"):
            self.assertIn(f"| `{sid}` |", skills)

    def test_reconcile_removes_a_shared_keyword(self):  # P5C-AC-015 (D1)
        text = flat("docs/init.md")
        self.assertIn("the others lose it from their keywords — never a negative keyword", text)
        self.assertNotIn("negative_keywords", text)
        row = contract_row("| `init reconcile` |")
        self.assertIn("`collisions` `[{keyword, owner, others, files: {module: n}, removed}]`",
                      row)
        self.assertIn("<the fields create asks for>, related_modules?}", row)
        self.assertIsNone(re.search(r"\bmoved\b", row))
        self.assertNotIn("negative_keywords", row)


def contract_row(start: str) -> str:
    """The row of docs/cli-contract.md that starts with `start`."""
    lines = (ENGINE / "docs/cli-contract.md").read_text(encoding="utf-8").splitlines()
    return next(line for line in lines if line.startswith(start))


if __name__ == "__main__":
    unittest.main()
