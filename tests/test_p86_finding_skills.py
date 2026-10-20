"""P8.6 (D1–D4; the plan's fast mode, C2): `module-discover`, `module-scout` and `module-research`
are full skills again, with the job and the output contract of the host originals they replace —
discover is the complete context pull before a plan (modules, docs for every role with what bears
on the task, existing code touch points), not a search for a bug's cause; scout is the quick load
during a discussion that proposes candidates when none is named; research is the doc-vs-code
audit. Their agents only run them (`test_p84_agent_build`, `test_p84_codex_agents`). Pinned here:
the contract's phrases, the removed P8.3 / P8.5 rules, the files each skill names, that the
commands run, and that the references travel. The shared candidate search, routed to
`references/choose.md` (X4: the core pack's size signal), is pinned word for word by
`test_p81_skill_text`; the unchanged descriptions by `test_builtin_skills`. Formalization eval
2026-10-15: the owner adopted the lite text — the procedure is the model's, the contract is pinned:
module-discover's step 2 is one score (0–10, kept at 5 or more), step 3 follows forward edges only,
and the four questions, the edge kinds, "the average goes in the report", the reference module's
role docs never read and its pointer extracted unread left the skill on purpose."""
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from segmently_modules.config import builtin_packs_root, core_defaults
from segmently_modules.skills import front_matter
from tests.helpers import SPLIT_FIXTURE, copy_fixture, init_git, run, run_json

ENGINE = Path(__file__).resolve().parents[1]
CORE = builtin_packs_root() / "core" / "skills"
FINDING = ("module-discover", "module-scout", "module-research")
SPLIT_SIGNAL = core_defaults()["budgets"]["skill_split_signal"]
REFERENCES = {"module-discover": ["choose.md", "from-diff.md", "report.md", "rules.md"],
              "module-scout": ["brief.md", "choose.md"], "module-research": ["choose.md"]}


def skill(name: str) -> str:
    return (CORE / name / "SKILL.md").read_text(encoding="utf-8")


def ref(name: str, file: str) -> str:
    return (CORE / name / "references" / file).read_text(encoding="utf-8")


def flat(text: str) -> str:
    return " ".join(text.split())


def every_file(name: str) -> str:
    return flat("\n".join([skill(name)] + [ref(name, f) for f in REFERENCES[name]]))


class ShapeTest(unittest.TestCase):  # D1: the steps live in the skill; the agent only runs it
    def test_front_matter(self):
        for name in FINDING:
            with self.subTest(skill=name):
                self.assertEqual(list(front_matter(skill(name))),
                                 ["name", "description", "argument-hint"])

    def test_the_steps_are_in_the_skill_and_nothing_hands_them_off(self):
        for name in FINDING:
            with self.subTest(skill=name):
                text = skill(name)
                self.assertFalse((CORE / name / "references/procedure.md").exists())
                for heading in ("## When to use", "## When not to use", "## Scope", "## Steps",
                                "## Exit codes", "## Gates"):
                    self.assertEqual(text.count(f"\n{heading}\n"), 1, heading)
                self.assertNotIn("procedure.md", every_file(name))
                self.assertNotIn("Delegate", text)
                self.assertNotIn("custom agent", text)
                self.assertIn(f"`{name}-agent`", text)  # Scope: the agent runs this skill

    def test_the_references_are_the_named_ones(self):
        for name in FINDING:
            with self.subTest(skill=name):
                on_disk = sorted(p.name for p in (CORE / name / "references").iterdir())
                self.assertEqual(on_disk, REFERENCES[name])
                named = sorted(set(re.findall(r"`references/([\w-]+\.md)`", skill(name))))
                self.assertEqual(named, REFERENCES[name])

    def test_sizes_are_signals_never_caps(self):  # X4: routed, never trimmed
        for name in FINDING:
            for path in [CORE / name / "SKILL.md", *(CORE / name / "references").iterdir()]:
                with self.subTest(file=path.relative_to(CORE).as_posix()):
                    self.assertLessEqual(len(path.read_text(encoding="utf-8")), SPLIT_SIGNAL)

    def test_no_placeholder(self):
        for name in FINDING:
            with self.subTest(skill=name):
                self.assertEqual(re.findall(r"\$[A-Za-z0-9{]\w*", every_file(name)), [])


class DiscoverContractTest(unittest.TestCase):  # D2: the host's MODE=discover contract
    PHRASES = [
        # the job: the complete context pull for planning, not a search for a bug's cause
        "the complete context a task needs before it is planned",
        "nothing important is missed in the discussion or the plan",
        "It does not look for a bug's cause",
        # user-named modules: verified, never dropped, never exclusive
        "Modules the user named are verified like the rest but never dropped",
        "never dropped, and the list is never limited to them",
        # one score (the lite text: the formalization eval), the rejected list
        "Score how much the task needs the module, 0–10, and keep it at 5 or more",
        'a dropped candidate goes on the rejected list with its score or "off-topic by its '
        'description"',
        # one hop of related
        "may show another module the task needs (follow forward edges only); verify it as in "
        "step 2",
        # the usage
        "`modify` (the task changes its code or contracts)",
        "`consume` (calls its API as it is)",
        "`reference` (follows its patterns or rules)",
        # docs for every role, the extracts that bear on the task, the "nothing" line
        "A `modify` or `consume` module: every doc `segmently-modules show <module> --discover > "
        "<temp file>` lists, each read to the end",  # owner 2026-10-19: text through a file, read whole
        "a `reference` module: its main doc only.",  # C5 read a reference module's role docs
        "Never `MODULE.legacy.md` or `roles/*.legacy.md`.",
        "Take from each doc what bears on the task — rules, constraints, contracts, pitfalls — as "
        "short extracts with the doc's path and role",
        '"read, nothing for this task"',
        "Never a retelling.",
        # code: existing touch points only, never the files the work will create
        "Record existing code only, as `<edit | read> — file:line — symbol — why`",  # DCP-AC-011
        "the files the work will create are the plan's decision and are never listed",
        "where new code goes is the plan's decision",
        "No code search for a `reference` module.",
        # owners, docs to update, files outside, missing; the kept pick (P8.5) stays
        "`docs_to_update` (role docs too, not only the main doc)",
        "`files_outside_modules`", "`missing_files`",
        "A module step 2 kept stays in the report even when this gives its files to another "
        "module or to none",
        "drop a kept module only with a stated reason, on the rejected list",
        # the report reaches the conversation; the result is saved (task context plan 2026-10-20, §8.4)
        "The extracts are in the report, so they reach the conversation through an agent too.",
        "**Save the result** under `[discover] save` (step 1's settings), as `references/report.md` says.",
    ]
    GONE = [  # P8.3 / P8.5 rules D2 removes: discover is no root-cause search
        "computed and set", "files the change edits", "read for evidence", "Go to the code",
        "Get the touch-set", "hand the user's task verbatim",
    ]
    REPORT = ["## Discovery: <task, one line>",
              # one score (owner ruling 2026-10-16); no `searched` form (owner ruling 2026-10-18)
              "### <module>[/<child>] — usage: modify | consume | reference (score <0–10>)",
              "Why:", "Docs:", "(<role>): read, nothing for this task",
              "Docs to update:",
              "Code:", "- `edit` — `<file>:<line>` — `<symbol>` — <what changes there, one clause>",
              "- `read` — `<file>:<line>` — `<symbol>` — <why it was read: called as is / "
              "alternative / pattern to follow>",  # DCP-AC-011: the tagged lines
              "Risks / unknowns:", "### Rejected", "### Files outside every module",
              "### Missing files"]

    def test_the_contract(self):
        body = every_file("module-discover")
        self.assertEqual([p for p in self.PHRASES if p not in body], [])

    def test_the_removed_rules_are_gone(self):
        body = every_file("module-discover")
        self.assertEqual([p for p in self.GONE if p in body], [])

    def test_the_steps_in_order(self):
        steps = skill("module-discover").split("\n## Steps\n", 1)[1].split("\n## ", 1)[0]
        heads = re.findall(r"^(\d)\. \*\*([^*]+)\*\*", steps, re.M)
        self.assertEqual(heads, [("1", "Candidates."), ("2", "Verify."), ("3", "One hop out."),
                                 ("4", "Usage."), ("5", "Docs for every role."),
                                 ("6", "Code touch points."), ("7", "Owners and docs to update."),
                                 ("8", "Report"), ("9", "Save the result")])

    def test_the_report_template(self):
        text = ref("module-discover", "report.md")
        self.assertEqual([p for p in self.REPORT if p not in text], [])
        self.assertIn("A file the work will create is never listed", flat(text))

    def test_the_saved_result(self):  # the §8.1 input of `task-context save` (plan 2026-10-20); 1.1 by export only
        text = ref("module-discover", "report.md")
        block = re.search(r"```json\n(.*?)\n```", text, re.S)
        doc = json.loads(block.group(1))
        self.assertEqual(list(doc), ["task", "search", "modules", "docs", "rules", "rejected", "summary"])
        self.assertEqual(list(doc["modules"][0]), ["module", "usage", "score", "why", "named_by_user", "files",
                                                   "tests", "risks", "consequences"])
        self.assertEqual(list(doc["modules"][0]["files"][0]), ["path", "line", "tag", "symbol", "why"])
        self.assertEqual(list(doc["rules"][0]), ["ref", "applies"])  # named by doc:line, never retyped
        self.assertEqual(list(doc["docs"][0]), ["path", "nothing", "extracts"])
        body = flat(text)
        for phrase in ("segmently-modules task-context save --from <temp file> --json",
                       "`--out <path>`", "the report's last line is `Saved: <path>`",
                       "A rule is named by its `doc:line` as `rules` prints it, never retyped",
                       "`task-context export <file> --format discovery-1.1`",
                       '`"always"` — save; `"ask"` — ask after the report; `"off"` — only when the user or a caller '
                       "asks"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, body)
        self.assertNotIn('"version"', block.group(1))

    def test_the_change_only_scenario(self):
        text = flat(ref("module-discover", "from-diff.md"))
        for phrase in ("segmently-modules discover --from-diff <base>..HEAD --json",
                       "`git merge-base <target> HEAD`", "never the target itself",
                       "the docs of every `modify` module for every role"):
            self.assertIn(phrase, text)


class ScoutContractTest(unittest.TestCase):  # D3: the host's MODE=scout contract
    PHRASES = [
        "**The references, path first.**",
        "a path outside the registry (a skill, a spec, any other doc) → not a module: read the "
        "file itself",
        "Never add modules to the ones the user named: a search is only for a request that names "
        "none.",
        "No module named? Choose the candidates.",
        'Propose them ("looks like X, Y — load them?")',
        "load nothing until the user answers",
        "only the children the topic touches", "never all of them",
        "read its successor instead and say so",
        "A role doc only when the discussion is clearly about that role",
        "one hop, forward edges only",
        "a `depends-on`, `implemented-in` or `shares-contract` target → read its main doc too, each "
        "one, even when it looks off the topic: the edge says the module is not understood without "
        "it",  # F2: two runs skipped hard edges as off-topic
        "A role doc the main doc points to otherwise goes in Suggested next reads, unread.",  # F2
        "its INDEX only; no role docs, no further hop",
        "a `complements` target and every reverse edge",
        '"worth loading if the task also touches X"',
        "No code.",
        "the auto-pulled modules, listed under the module that pulled them with the edge type",
        "**Suggested next reads:**",
        "No code search and no touch-set claims",
    ]

    def test_the_contract(self):
        body = every_file("module-scout")
        self.assertEqual([p for p in self.PHRASES if p not in body], [])

    def test_the_proposal_comes_after_the_search_and_before_any_load(self):
        text = flat(skill("module-scout"))
        self.assertLess(text.index("Follow `references/choose.md`."), text.index("Propose them"))
        self.assertLess(text.index("Propose them"), text.index("**Each module's docs.**"))


class ResearchContractTest(unittest.TestCase):  # D4: kept, a full skill, a stub's successor
    def test_the_contract(self):
        body = every_file("module-research")
        for phrase in ("Pin the question in one sentence.",
                       "segmently-modules show <module> --all-roles --json",
                       "research its successor instead and say so",
                       "`edges`: the modules it relies on; `reverse`: those pointing at it",
                       "segmently-modules code-map files <module> --json", "segmently-modules lint --json",
                       '"the docs say X (doc:line), the code does Y (file:line)"',
                       "the gaps table", "gaps are reported, not fixed"):
            self.assertIn(phrase, body)
        steps = skill("module-research").split("\n## Steps\n", 1)[1].split("\n## ", 1)[0]
        self.assertEqual(re.findall(r"^(\d)\. ", steps, re.M), [str(i) for i in range(1, 8)])


class CommandsRunTest(unittest.TestCase):  # the verbs the steps name, on the split fixture
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = copy_fixture(self._tmp.name, SPLIT_FIXTURE)
        init_git(self.root)
        self.R = ("--root", str(self.root))

    def data(self, *args):
        code, env, err = run_json(*args, *self.R)
        self.assertEqual((code, err), (0, ""), args)
        return env["data"]

    def test_discover_docs_code_and_owners(self):
        shown = self.data("show", "orders", "--all-roles")
        self.assertTrue(any("role:" in r["label"] for r in shown["read"]))
        self.assertIn("code", shown)
        self.assertIn("edges", self.data("related", "orders"))
        files = self.data("code-map", "files", "orders")["files"]
        self.assertIn("src/orders/service.py", [f["path"] for f in files if f["via"] != ["docs"]])
        terms = Path(self._tmp.name) / "terms.txt"
        terms.write_text("refund\n", encoding="utf-8")
        found = self.data("discover", "--files", "src/orders/service.py", "--task-file",
                          str(terms), "--match", "lexical")
        row = {m["module"]: m for m in found["modules"]}["orders"]
        self.assertIn("docs_to_update", row)
        self.assertEqual((found["files_outside_modules"], found["missing_files"]), ([], []))

    def test_scout_takes_a_doc_path_as_well_as_a_name(self):
        main = self.data("show", "orders")["read"][0]["path"]
        self.assertEqual(self.data("show", main)["module"], "orders")


class SandboxLineTest(unittest.TestCase):  # P84-AC-015, now in each skill's choose.md
    TASK = 'refund a "late" book: $HOME and `whoami` stay text'

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = copy_fixture(self._tmp.name, SPLIT_FIXTURE)
        init_git(self.root)

    def test_the_shell_hands_choose_the_text_byte_exact(self):
        for name in FINDING:
            with self.subTest(skill=name):
                text = ref(name, "choose.md")
                self.assertEqual(text.count("<<'EOF'"), 1)
                block = re.search(r"```bash\n(segmently-modules choose --task-file - <<'EOF'\n.*?\nEOF)\n",
                                  text, re.S).group(1)
                script = block.replace("<the task text, verbatim>", self.TASK).replace(
                    "segmently-modules choose --task-file -",
                    f"'{sys.executable}' -m segmently_modules choose --task-file - --root '{self.root}'", 1)
                env = {**os.environ, "PYTHONPATH": str(ENGINE)}
                proc = subprocess.run(["sh", "-c", script], capture_output=True, text=True,
                                      env=env, timeout=120)
                self.assertEqual((proc.returncode, proc.stderr), (0, ""))
                self.assertTrue(proc.stdout.startswith(f"Task:\n{self.TASK}\n"), proc.stdout[:200])

    def test_choose_reads_stdin_in_process(self):
        with mock.patch("sys.stdin", io.StringIO(self.TASK)):
            code, out, err = run("choose", "--task-file", "-", "--root", str(self.root))
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(out.startswith(f"Task:\n{self.TASK}\n"))


class ReferencesTravelTest(unittest.TestCase):  # P84-AC-030: copies, markers, eject
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = copy_fixture(self._tmp.name)
        (self.root / ".segmently-modules/config.toml").write_text('[packs]\nbuiltin = ["core"]\n',
                                                       encoding="utf-8")
        self.R = ("--root", str(self.root))

    def test_sync_copies_every_reference_with_its_hash(self):
        code, env, err = run_json("packs", "sync", "--agent", "claude", "--agent", "codex", *self.R)
        self.assertEqual((code, err), (0, ""))
        for name in FINDING:
            for agent_dir in (".claude/skills", ".agents/skills"):
                with self.subTest(skill=name, where=agent_dir):
                    dest = self.root / agent_dir / name
                    marker = json.loads((dest / ".segmently-modules-managed").read_text(encoding="utf-8"))
                    self.assertEqual(sorted(marker["files"]),
                                     sorted(["SKILL.md"] + [f"references/{f}"
                                                            for f in REFERENCES[name]]))
                    for rel in marker["files"]:
                        data = (dest / rel).read_bytes()
                        self.assertEqual(data, (CORE / name / rel).read_bytes())
                        self.assertEqual(marker["files"][rel], hashlib.sha256(data).hexdigest())
        self.assertEqual(run("packs", "sync", "--check", "--agent", "claude", "--agent", "codex",
                             *self.R)[0], 0)

    def test_an_edited_reference_in_a_copy_is_a_conflict(self):
        run_json("packs", "sync", "--agent", "claude", *self.R)
        copy = self.root / ".claude/skills/module-scout/references/choose.md"
        copy.write_text(copy.read_text(encoding="utf-8") + "\nlocal edit\n", encoding="utf-8")
        code, env, _ = run_json("packs", "sync", "--agent", "claude", *self.R)
        self.assertEqual(code, 1)
        self.assertEqual([r["status"] for r in env["data"]["skills"]
                          if r["skill"] == "module-scout"], ["conflict"])

    def test_eject_carries_the_references(self):
        code, _, err = run_json("eject", "module-discover", *self.R)
        self.assertEqual((code, err), (0, ""))
        for file in REFERENCES["module-discover"]:
            copy = self.root / ".segmently-modules/overrides/skills/module-discover/references" / file
            self.assertEqual(copy.read_bytes(),
                             (CORE / "module-discover/references" / file).read_bytes())


if __name__ == "__main__":
    unittest.main()
