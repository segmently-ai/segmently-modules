"""The docs after the discover cost/precision work say what module-discover does under
`[search] chooser` (the residuals of its reviews): docs/skills.md names `catalog --settings` and
the chooser setting where it says the search by meaning is the default; docs/configuration.md
says when `low_score` can fire and the `always` row's exception; the README's `[search]`
paragraph names `chooser`; docs/cli-contract.md's row headers list the new flags; the
module-assistant how-to answers how to stop discover from always running the chooser; the
changelog says so."""
from __future__ import annotations

import unittest
from pathlib import Path

from segmently_modules.config import builtin_packs_root

ENGINE = Path(__file__).resolve().parents[1]
CHOOSER = '(module-discover: unless `[search] chooser` says otherwise, below)'


def flat(text: str) -> str:
    return " ".join(text.split())


def read(name: str) -> str:
    return (ENGINE / name).read_text(encoding="utf-8")


def unreleased() -> str:
    return read("CHANGELOG.md").split("## [Unreleased]", 1)[1].split("\n## [0.3.0]", 1)[0]


class SkillsDocTest(unittest.TestCase):  # task-1 review M1, extended by the final review
    def part(self) -> str:
        doc = flat(read("docs/skills.md"))
        return doc.split("## Choosing modules by meaning", 1)[1].split(" ## ", 1)[0]

    def test_module_discover_reads_catalog_settings(self):
        self.assertIn("The skill runs `segmently-modules catalog --json` (module-discover: "
                      "`segmently-modules catalog --settings --json`, the settings alone), reads "
                      "`match.mode` and `search`", self.part())

    def test_the_default_sentences_name_the_chooser_setting(self):
        part = self.part()
        self.assertIn(f"**Hybrid is the default** {CHOOSER}:", part)
        self.assertIn(f"never skips the search by meaning {CHOOSER},", part)
        self.assertIn('`[match] mode = "semantic"` makes meaning-only the skills\' default '
                      '(module-discover: only under `[search] chooser = "always"`).', part)


class ConfigurationDocTest(unittest.TestCase):
    def rows(self) -> dict[str, str]:
        return {line.split(" | ", 1)[0]: line for line in read("docs/configuration.md").split("\n")
                if line.startswith("| `[search] ")}

    def test_the_default_sure_min_score_never_yields_low_score(self):  # task-1 review M2
        self.assertIn("With the default weights every keyword row scores at least 3, so the "
                      "default 2 never yields `low_score`; raise it above one hit's score (4 or "
                      "more) to make a single hit unsure.", self.rows()["| `[search] sure_min_score`"])
        self.assertIn("at the default weights a keyword hit scores 3, so the default "
                      "`sure_min_score` 2 never yields `low_score` — set 4 or more to make a single "
                      "hit unsure", flat(unreleased()))

    def test_the_chooser_row_keeps_the_always_exception(self):  # final review M-6
        row = self.rows()["| `[search] chooser`"]
        self.assertIn("`[match] mode` stays the command line's default only, except that under "
                      "`always` a `semantic` one keeps module-discover meaning-only", row)


class ReadmeTest(unittest.TestCase):  # final review M-6
    def test_the_search_paragraph_names_the_chooser(self):
        readme = flat(read("README.md"))
        self.assertIn('say "only lexical" to switch it off; module-discover follows `[search] '
                      'chooser` — `when_unsure` asks for meaning only when the keyword result is '
                      'unsure, `never` not at all)', readme)


class CliContractTest(unittest.TestCase):  # final review M-6: the row headers list the flags
    def test_the_headers(self):
        heads = [line.split(" | ", 1)[0] for line in read("docs/cli-contract.md").split("\n")
                 if line.startswith("| `catalog") or line.startswith("| `code-map")]
        self.assertEqual(sorted(heads), ["| `catalog [--settings]`",
                                         "| `code-map list\\|add\\|files [--source-only] [--paths]`"])


class AssistantHowToTest(unittest.TestCase):  # final review M-6
    HOWTO = builtin_packs_root() / "core/skills/module-assistant/references/how-to/search.md"

    def test_how_to_stop_discover_from_always_running_the_chooser(self):
        text = self.HOWTO.read_text(encoding="utf-8")
        self.assertIn("\n## When module-discover runs the chooser\n", text)
        body = flat(text.split("## When module-discover runs the chooser", 1)[1].split("\n## ")[0])
        for phrase in ("`segmently-modules catalog --settings --json`", "`[search] chooser`",
                       '`chooser = "when_unsure"`', '`"never"`', "`[search] sure_min_score`",
                       '`[search] cards = "brief"`', "`segmently-modules choose --cards brief`",
                       '("by meaning", "only lexical") still win'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, body)
        index = read("segmently_modules/defaults/packs/core/skills/module-assistant/references/"
                     "how-to.md")
        self.assertIn("| finding modules for a task: match modes, choose, when module-discover "
                      "runs the chooser, keywords, routing eval |", index)


class ChangelogTest(unittest.TestCase):
    def test_the_pack_sections_line(self):  # task-3 review M-4, extended by the final review
        fixed = unreleased().split("### Fixed", 1)
        self.assertEqual(len(fixed), 2)
        self.assertIn("Plain `lint` no longer warns MS060 about a pack's `[search]` or `[tests]` "
                      "table", flat(fixed[1]))


if __name__ == "__main__":
    unittest.main()
