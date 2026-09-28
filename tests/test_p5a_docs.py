"""D6 and the D0b / D1 docs items: the README sections for `adopt` and `init map`, the
contract rows and the files the engine creates, the configuration reference (`[init]`, MS066,
the adopt rules, the keyword hints), the proposals `--run-id` and batch sentences, the "when
something goes wrong" example."""
import re
import unittest
from pathlib import Path

from modsys.create import GENERIC_KEYWORDS

ENGINE = Path(__file__).resolve().parents[1]


def flat(rel: str) -> str:
    return " ".join((ENGINE / rel).read_text(encoding="utf-8").split())


class P5aDocsTest(unittest.TestCase):  # P5A-AC-042
    def test_the_contract(self):
        text = flat("docs/cli-contract.md")
        for needle in ("| `adopt` |", "| `init map\\|confirm\\|status\\|resume` |",
                       "`--rebase [--dry-run]`: `{skill, pack, rebased_from: {pack, version}, "
                       "rebased_to: {pack, version}, files_changed, dry_run}`",
                       "{action, root, files: [{path, status}], preflight, proposal, "
                       "candidates: [name], unassigned, hints, phase, next, dry_run}",
                       "{action, confirmed, included: [name], excluded: [name], status, dry_run}",
                       "{action, phase, phases: {phase: status}, next}",
                       "{action, ran: [phase], phase, next, message}",
                       "phase 4 (fan-out) is not available in this engine version",
                       "`init resume` after gate 3", "`<config_dir>/init/`",
                       "`<config_dir>/adopt.proposed.toml`",
                       "only `modsys eject <skill> --rebase` rewrites it",
                       "`create NAME` | `{module, files, entry, warnings, dry_run}`",
                       "`committed` / `uncommitted`", "diff, reason}"):
            self.assertIn(needle, text)
        self.assertNotIn("the engine never rewrites it", text)
        block = re.search(r"```gitignore\n(.*?)```",
                          (ENGINE / "docs/cli-contract.md").read_text(encoding="utf-8"), re.S)
        self.assertEqual(block.group(1).splitlines(), ["modules/registry.json.lock",
                                                       ".modsys/proposals/", ".modsys/init/"])

    def test_the_configuration_reference(self):
        text = flat("docs/configuration.md")
        for needle in ("## `[init]`", "| `exclude` | `[]` |", "| `co_change_commits` | `500` |",
                       "| MS066 | info |", "## Adopting an existing registry",
                       "at least 80 % of the top-level modules", "`count * 5 >= total * 4`",
                       "at least 50 % of the top-level modules", "`count * 2 >= total`",
                       "at most 2 levels deep", "COMMENTED OUT", "`inferred.skipped`",
                       "a hint by suffix, not linguistics", "3 characters or fewer"):
            self.assertIn(needle, text)
        for word in GENERIC_KEYWORDS:
            self.assertIn(f"`{word}`", text)

    def test_the_readme(self):
        text = flat("README.md")
        adopt = text.split("## Adopt an existing registry", 1)[1].split(" ## ", 1)[0]
        for needle in ("modsys adopt --dry-run", "modsys adopt ", "never changes the registry",
                       "adopt.proposed.toml", "--registry"):
            self.assertIn(needle, adopt)
        start = text.split("## Start from existing code", 1)[1].split(" ## ", 1)[0]
        for needle in ("modsys init map", "modsys init confirm", "modsys init status",
                       "modsys init resume", "arrives with a later engine version"):
            self.assertIn(needle, start)
        reference = text.split("## Reference", 1)[1]
        for anchor in ("(#adopt-an-existing-registry)", "(#start-from-existing-code)"):
            self.assertIn(anchor, reference)
        self.assertIn("(#start-from-existing-code)",
                      text.split("## Brownfield", 1)[1].split(" ## ", 1)[0])

    def test_the_d0b_items(self):
        text = flat("README.md")
        self.assertIn('--apply-proposals # every pending run', text)
        self.assertIn('--apply-proposals --run-id r1 # only run r1', text)
        self.assertIn("the modules before it stay created", text)
        wrong = text.split("### When something goes wrong", 1)[1].split(" ## ", 1)[0]
        for needle in ("exit 2, nothing written", "MS052", "MS053", "exclusive = true",
                       "exits 0 again"):
            self.assertIn(needle, wrong)


class FixWaveDocsTest(unittest.TestCase):  # the P5a final review and E-B docs items
    NEEDLES = {
        "docs/cli-contract.md": (
            "code_map, code_map_suggestion, budgets, skipped}",
            "`code_map_suggestion`: `{pattern, covered, total}`",
            "`next_steps` names `modsys init` when `.gitignore` lacks the engine's lines",
            "except `adopt`'s new `config.toml`: its temp file is hard-linked into place",
            "role docs only with `--role R` (that role's) or `--all-roles` (every role's)",
            "only when gate 3 already passed with these bytes",
            "reads the later ones as pending"),
        "docs/configuration.md": (
            "reported as `inferred.code_map_suggestion` (`{pattern, covered, total}`",
            "a symlink at the ejected path (warning: it is in the way",
            "An exclusive rule wins only over non-exclusive rules: two exclusive rules that route "
            "one file to different modules are still an MS053 overlap",
            "any path whose name is not valid UTF-8", "The hint never suggests a generic word"),
        "modsys/defaults/packs/core/skills/module-lint/references/lint-codes.md": (
            "a symlink at the ejected path (warning: in the way)",),
        "README.md": (
            'modsys code-map add orders-extra --module orders --glob "app/jobs/nightly_totals.py" '
            '--glob "app/api/order_export.py"',
            "`exclusive` wins only over NON-exclusive rules",
            "modsys init # adds the .gitignore lines (lock file, proposals, init); keeps the "
            "config", "reported as `code_map_suggestion`",
            "add it to `[init] exclude` and run `modsys init map --restart`")}

    def test_the_needles(self):
        for rel, needles in self.NEEDLES.items():
            text = flat(rel)
            for needle in needles:
                with self.subTest(doc=rel, needle=needle[:40]):
                    self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
