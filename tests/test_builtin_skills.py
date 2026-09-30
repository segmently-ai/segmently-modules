"""Structure of the built-in packs' skills (D6), a test per rule over every skill of every
built-in pack: names, loadability, description and file lengths, every `modsys …` command
parsed by the real CLI parser (the guard can fail: SI-7), no machine paths, `--json` for what a
skill parses, the sections, each core skill's scope and verbs (D3), the writer rules, generic
text. `CORE` and `PACK_SKILLS` list what each skill must say; a skill is added with its row."""
import contextlib
import hashlib
import io
import re
import shlex
import tempfile
import tomllib
import unittest
from pathlib import Path

from modsys.cli import build_parser
from modsys.config import BUILTIN_PACKS, builtin_packs_root
from modsys.skills import read_front_matter, source_problem
from tests.helpers import copy_fixture, git, init_git, run, run_json

ENGINE = Path(__file__).resolve().parents[1]

# skill -> (scope, the verbs its `## Steps` run, phrases its text must contain)
CORE: dict[str, tuple[str, list[tuple[str, ...]], list[str]]] = {
    "module-scout": ("read-only", [("show",), ("related",), ("context",)],
                     ["No gates — read-only", "near_misses", "never all of them"]),
    "module-discover": ("read-only", [("discover", "--task-file"), ("discover", "--from-diff"),
                                      ("discover", "--files"), ("code-map", "files")],
                        ["No gates — read-only", "files_outside_modules", "missing_files",
                         "docs_to_update", "file:line"]),
    "module-research": ("read-only", [("show", "--all-roles"), ("related",),
                                      ("code-map", "files"), ("lint",)],
                        ["No gates — read-only", "file:line", "the docs say X",
                         "gaps are reported, not fixed"]),
    "module-sync": ("writer", [("sync-instructions",), ("registry",), ("propose",), ("sync",),
                               ("ci",)],
                    ["Autonomous by default", "two children of a split module equally well",
                     "a new top-level module or a child", "contradicts a claim in the docs",
                     "the only home for the new text is a `*.legacy.md` file",
                     "never remove one from it",
                     "git ls-files --others --exclude-standard",  # fix wave M4
                     "Skip this step when step 5 ran"]),  # fix wave M5
    "module-create": ("writer", [("create", "--dry-run"), ("create",), ("code-map", "add"),
                                 ("lint",)],
                      ["Wait for an explicit yes", "at least five", "Never invent components"]),
    "module-split": ("writer", [("show",), ("create", "--parent"), ("code-map", "add"),
                                ("lint",)],
                     ["**STOP**", "copy it byte for byte to a sibling named `<name>.legacy.md`",
                      "The parent's keywords stay unchanged", "verbatim", "two to six",
                      "receives no section stays as `create` wrote it"]),  # fix wave M11
    "module-lint": ("fix-up", [("ci",), ("lint",), ("registry", "set")],
                    ["Leave the judgement calls to the user", "references/lint-codes.md"]),
    "module-init": ("writer", [("init", "status"), ("init", "map"), ("init", "confirm"),
                               ("init", "fanout"), ("init", "next"), ("init", "done"),
                               ("init", "reconcile"), ("eval", "routing", "--prompt"),
                               ("init", "verify"), ("init", "finish")],  # P5B-AC-028 (D6)
                    ["Run `modsys init status --json` first and continue from the recorded phase",
                     "**STOP — gate 3.**", "merges, splits, renames and exclusions",
                     "never dispatch an item you did not claim", "at most `max_parallel`",
                     "Without subagents, loop yourself", "Ask the user about each keyword tie",
                     "report the duplicate names", "never shows the keywords",
                     "never the tasks", "at most 2 rounds", "**STOP — gate 7.**",
                     "Never commit yourself",
                     # the P5b follow-up: an existing module's registry change and its
                     # reconcile --force first, then the new modules' keywords (N-4); gate 7
                     # asked as a question, not a next command named (G11)
                     "First, a missed module that was already in the registry",
                     "Then improve the keywords of the missed NEW modules",
                     "End that message with one direct yes/no question",
                     "naming the next command is not asking",
                     # the P5c follow-up: a tied keyword is kept unless the user names an owner
                     "a tied keyword stays on every module that holds it"]),
    "module-adopt": ("writer", [("adopt", "--dry-run"), ("adopt",), ("lint",)],  # P5B-AC-029
                     ["Explain each inference with its evidence", "`applies_when`",
                      "`deprecated`", "a commented-out doc budget", "Group the findings by code",
                      "Fix nothing here", "hand the fixes to `module-lint`",
                      "`<config_dir>/adopt.proposed.toml`", "only after the user says yes",
                      "never edits the registry or a module doc", "never commits",
                      # G11: write first, then ask — an agent that cannot reach the user
                      # still leaves the config the request asked for
                      "adopt never edits an existing one", "Write it without waiting",
                      "never report a lint result you did not run",
                      "Add each answer to the config only on the user's yes"]),
}
PACK_SKILLS: dict[str, tuple[str, str, list[tuple[str, ...]], list[str]]] = {
    "designer-review": ("ui", "writer", [("discover",), ("show", "--role", "designer")],
                        ["Must-fix", "Should-fix", "Nit", "`Result: PASS`", "`Result: FAIL",
                         "Design checker", "a UI task is not done while a Must-fix is open",
                         "git ls-files --others --exclude-standard"]),  # fix wave M4
    "qa-acceptance": ("qa", "writer", [("discover", "--task-file"), ("show", "--role", "qa"),
                                       ("show", "--role", "qa_acceptance")],
                      ["`PRE-NNN`", "`AC-NNN`", "**Given**", "**When**", "**Then**",
                       "equivalence partitioning", "boundary value analysis",
                       "decision table", "state transition", "instead of restating it"]),
    "qa-acceptance-baseline": ("qa", "writer", [("show", "--all-roles"),
                                                ("show", "--role", "qa_acceptance"), ("lint",)],
                               ["the next id after the highest existing `AC-NNN`",
                                "never renumber", "P0", "P1", "P2", "Gate 1", "Gate 2",
                                "Gate 3"]),
}
WRITER_VERBS = [("create",), ("registry", "set"), ("registry", "append"), ("propose",),
                ("code-map", "add")]
DESCRIPTION_MAX, FILE_LINES_MAX = 600, 250
SECTIONS = ("## When to use", "## When not to use", "## Scope", "## Steps", "## Gates")
FRAMEWORKS = ("React", "Vue", "Angular", "Svelte", "Storybook", "Figma", "Tailwind", "Material",
              "Playwright", "Cypress", "Puppeteer", "Jest", "Vitest", "pytest", "Selenium",
              "Firebase", "AWS", "GCP", "Azure")
_FENCE = re.compile(r"^([ \t]*)(`{3,})[^\n]*\n(.*?)^\1\2\s*$", re.M | re.S)
_INLINE = re.compile(r"`([^`\n]+)`")
_PLACEHOLDER = re.compile(r"<[^<>\n]*>")
_ABSOLUTE = re.compile(r"(?:^|[\s`'\"(=])(/[\w.-]+/[\w./-]*|[A-Za-z]:\\\S+)", re.M)
_SPLIT = re.compile(r"`(modsys [^`]*\n[^`]*)`")  # an inline command broken over two lines
MERGE_BASE = "`git merge-base <target> HEAD`"  # what `<base>` is: where the work branched off
TARGET_AS_BASE = re.compile(r"\bbase\b[^.(]*\([^)]*\bthe target branch\b")  # the branch itself


def skill_dirs() -> dict[str, tuple[str, Path]]:
    """Every skill every built-in pack declares: {id: (pack, directory)}."""
    out = {}
    for pack in BUILTIN_PACKS:
        data = tomllib.loads((builtin_packs_root() / pack / "pack.toml").read_text("utf-8"))
        for sid, spec in (data.get("skills") or {}).items():
            out[sid] = (pack, builtin_packs_root() / pack / spec["path"])
    return out


def skill_files(directory: Path) -> dict[str, str]:
    """{name: text} of a skill's SKILL.md and references/*.md."""
    files = {"SKILL.md": (directory / "SKILL.md").read_text("utf-8")}
    for ref in sorted((directory / "references").glob("*.md")):
        files[f"references/{ref.name}"] = ref.read_text("utf-8")
    return files


def section(text: str, heading: str) -> str:
    """The body of a `## ` section ('' when missing)."""
    part = text.split(f"\n{heading}\n", 1)
    return part[1].split("\n## ", 1)[0] if len(part) == 2 else ""


def commands(text: str) -> list[str]:
    """Every `modsys …` command of a text: fenced-block lines (continuations joined) and inline
    code spans."""
    out = []
    for block in _FENCE.finditer(text):
        for line in block.group(3).replace("\\\n", " ").splitlines():
            if line.strip().startswith("modsys "):
                out.append(line.strip())
    out += [s.strip() for s in _INLINE.findall(_FENCE.sub("", text))
            if s.strip().startswith("modsys ")]
    return out


def argv(command: str) -> list[str]:
    """A command's arguments: a comment or heredoc cut, every `<…>` and `…` one value."""
    command = _PLACEHOLDER.sub("X", command.split(" #")[0].split("<<")[0]).replace("…", "X")
    return shlex.split(command)[1:]


def parse_problem(command: str) -> str | None:
    """Why the real parser refuses a command (None: it parses)."""
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            build_parser().parse_args(argv(command))
    except SystemExit as e:
        if e.code:
            return err.getvalue().strip().splitlines()[-1]
    return None


def command_guard(files: dict[str, str]) -> list[str]:
    """`<file>: <command> — <reason>` for every command the parser refuses."""
    out = [f"{name}: {c} — {problem}" for name, text in files.items() for c in commands(text)
           if (problem := parse_problem(c))]
    return out + [f"{name}: {' '.join(s.split())} — split over two lines (the guard cannot "
                  f"read it)" for name, text in files.items()
                  for s in _SPLIT.findall(_FENCE.sub("", text))]


def uses(cmds: list[str], verb: tuple[str, ...]) -> bool:
    """A command runs `verb` (`("show", "--all-roles")`: `show` with that flag)."""
    return any(a[:1] == [verb[0]] and all(p in a[1:] for p in verb[1:])
               for a in (argv(c) for c in cmds))


def description_problem(description: str) -> str | None:
    if not 1 <= len(description) <= DESCRIPTION_MAX:
        return f"description has {len(description)} characters (1–{DESCRIPTION_MAX})"
    return None


def length_problem(text: str) -> str | None:
    lines = len(text.splitlines())
    return f"{lines} lines (max {FILE_LINES_MAX})" if lines > FILE_LINES_MAX else None


def path_problem(text: str) -> str | None:
    found = _ABSOLUTE.search(text)
    if found:
        return f"an absolute path: {found.group(1)}"
    for needle in ("~/", "modules/registry.json"):
        if needle in text:
            return f"a machine or layout path: {needle}"
    return None


class SkillRules(unittest.TestCase):
    def all_skills(self) -> dict[str, tuple[str, Path]]:
        return skill_dirs()


class NamesAndLoadingTest(SkillRules):  # P4B-AC-014
    def test_directories_are_the_declared_skills(self):
        declared = self.all_skills()
        for pack in BUILTIN_PACKS:
            with self.subTest(pack=pack):
                on_disk = sorted(p.name for p in (builtin_packs_root() / pack / "skills").glob("*")
                                 if p.is_dir())
                mine = sorted(s for s, (p, _) in declared.items() if p == pack)
                self.assertEqual(on_disk, mine)
                expected = CORE if pack == "core" else {s: r for s, r in PACK_SKILLS.items()
                                                       if r[0] == pack}
                self.assertEqual(mine, sorted(expected))
        for sid, (_, directory) in declared.items():
            self.assertEqual(directory.name, sid)

    def test_every_skill_is_loadable(self):
        for sid, (pack, directory) in self.all_skills().items():
            with self.subTest(skill=sid):
                self.assertIsNone(source_problem(directory, sid, builtin_packs_root() / pack))

    def test_description_length(self):
        self.assertIsNone(description_problem("d" * DESCRIPTION_MAX))
        self.assertEqual(description_problem("d" * (DESCRIPTION_MAX + 1)),
                         "description has 601 characters (1–600)")
        self.assertIsNotNone(description_problem(""))
        for sid, (_, directory) in self.all_skills().items():
            with self.subTest(skill=sid):
                meta = read_front_matter(directory / "SKILL.md")
                self.assertIsNone(description_problem(meta["description"]))

    def test_file_lengths(self):
        self.assertIsNone(length_problem("x\n" * FILE_LINES_MAX))
        self.assertEqual(length_problem("x\n" * (FILE_LINES_MAX + 1)), "251 lines (max 250)")
        for sid, (_, directory) in self.all_skills().items():
            for name, text in skill_files(directory).items():
                with self.subTest(skill=sid, file=name):
                    self.assertIsNone(length_problem(text))


class InstallLineTest(SkillRules):  # P6-AC-019 (D6, SI-4)
    LINE = ("If `modsys` is not found, tell the user how to install it — the `modsys` plugin "
            "for Claude Code, `uv tool install git+ssh://git@github.com/<owner>/<repo>.git`, or "
            "`pipx install git+ssh://git@github.com/<owner>/<repo>.git` — and stop until it "
            "runs.")
    DESCRIPTIONS = {  # sha256[:16] of each description at f1f5e46: a body edit never moves one
        "module-adopt": "3409f228fda67c5d", "module-create": "3d1a2d2954de0900",
        "module-discover": "fa2b6d6ba50b01fd", "module-init": "b64769f4c169e5b0",
        "module-lint": "bc2538a0a39d1da0", "module-research": "2c773e1a29f3fd6d",
        "module-scout": "83221c73a41cb280", "module-split": "25b942d14038d7dd",
        "module-sync": "18cbb93e3e8533c2", "qa-acceptance-baseline": "2a0efce95123748f",
        "qa-acceptance": "283ee6d99570ba9f", "designer-review": "83a63b52f3a24d79"}

    def test_every_body_holds_the_one_line(self):
        skills = self.all_skills()
        self.assertEqual(len(skills), 12)
        for sid, (_, directory) in skills.items():
            with self.subTest(skill=sid):
                text = (directory / "SKILL.md").read_text("utf-8")
                front, body = text.split("\n---\n", 1)
                self.assertEqual(body.splitlines().count(self.LINE), 1)
                self.assertNotIn("not found", front)  # the body, never the description
                self.assertLess(body.index(self.LINE), body.index("\n## Steps\n"))
                self.assertIn(f"\n\n{self.LINE}\n\n", body)  # its own paragraph
        urls = re.findall(r"github\.com(\S*)", self.LINE)  # placeholders only (D13)
        self.assertEqual(urls, ["/<owner>/<repo>.git`,", "/<owner>/<repo>.git`"])

    def test_no_description_changed(self):
        found = {sid: hashlib.sha256(read_front_matter(directory / "SKILL.md")["description"]
                                     .encode()).hexdigest()[:16]
                 for sid, (_, directory) in self.all_skills().items()}
        self.assertEqual(found, self.DESCRIPTIONS)


class CommandGuardTest(SkillRules):  # P4B-AC-018
    def test_every_command_parses(self):
        for sid, (_, directory) in self.all_skills().items():
            with self.subTest(skill=sid):
                self.assertEqual(command_guard(skill_files(directory)), [])

    def test_placeholders_stand_for_one_value(self):
        self.assertEqual(argv('modsys discover --task-file <file> --json  # the task'),
                         ["discover", "--task-file", "X", "--json"])
        self.assertEqual(argv('modsys context --task "<the task in one sentence>" --json'),
                         ["context", "--task", "X", "--json"])
        self.assertEqual(argv("modsys sync --from-diff <base>..HEAD --dry-run"),
                         ["sync", "--from-diff", "X..HEAD", "--dry-run"])
        self.assertEqual(argv("modsys create … --dry-run"), ["create", "X", "--dry-run"])

    def test_the_guard_can_fail(self):
        planted = {"SKILL.md": "Run `modsys shwo x` first.\n\n```bash\nmodsys packs install ui\n"
                               "modsys show x --rolee r\n```\n",
                   "references/more.md": "Then `modsys match x --from-diff a..b`, and\n"
                                         "`modsys show x\n--json`.\n"}
        failures = command_guard(planted)
        self.assertEqual([f.split(" — ")[0] for f in failures],
                         ["SKILL.md: modsys packs install ui", "SKILL.md: modsys show x --rolee r",
                          "SKILL.md: modsys shwo x",
                          "references/more.md: modsys match x --from-diff a..b",
                          "references/more.md: modsys show x --json"])
        self.assertTrue(all(" — " in f and f.split(" — ")[1] for f in failures), failures)


class TextRulesTest(SkillRules):  # P4B-AC-014, P4B-AC-017
    def test_no_machine_paths(self):
        for text in ("see /usr/local/share/x", "run ~/bin/tool", "open modules/registry.json",
                     "in C:\\work\\repo"):
            self.assertIsNotNone(path_problem(text), text)
        self.assertIsNone(path_problem("the docs `show` lists; A..B; parent/child; Must-fix / "
                                       "Should-fix; https://example.org/a/b"))
        for sid, (_, directory) in self.all_skills().items():
            for name, text in skill_files(directory).items():
                with self.subTest(skill=sid, file=name):
                    self.assertIsNone(path_problem(text))

    def test_what_a_skill_parses_is_json(self):
        for sid, (_, directory) in self.all_skills().items():
            for name, text in skill_files(directory).items():
                for command in commands(text):
                    with self.subTest(skill=sid, command=command):
                        self.assertTrue({"--json", "--dry-run"} & set(argv(command)))

    def test_sections(self):
        names = set(self.all_skills())
        for sid, (_, directory) in self.all_skills().items():
            text = (directory / "SKILL.md").read_text("utf-8")
            with self.subTest(skill=sid):
                self.assertEqual([h for h in SECTIONS if f"\n{h}\n" not in text], [])
                siblings = set(re.findall(r"`([a-z0-9-]+)`", section(text, "## When not to use")))
                self.assertTrue(siblings & (names - {sid}), "names no sibling skill")
                gates = section(text, "## Gates")
                self.assertTrue(gates.strip())

    def test_no_commits_and_the_writer_rules(self):
        for sid, (_, directory) in self.all_skills().items():
            text = "\n".join(skill_files(directory).values())
            code = "\n".join(b.group(3) for b in _FENCE.finditer(text)) + "\n".join(
                _INLINE.findall(_FENCE.sub("", text)))
            flat = " ".join(text.split())
            with self.subTest(skill=sid):
                self.assertIsNone(re.search(r"\bgit (commit|push)\b", code))
                if section(text, "## Scope").strip().startswith("Writes"):
                    self.assertIn("`*.legacy.md`", flat)
                    self.assertRegex(flat, r"never (edit|change)")
                    self.assertIn("review and commit", flat)

    def test_the_base_is_the_merge_base(self):  # fix wave I-1
        self.assertIsNotNone(TARGET_AS_BASE.search("Ask for the base (e.g. the target branch)."))
        self.assertIsNotNone(TARGET_AS_BASE.search("With a base (the target branch) run it."))
        self.assertIsNone(TARGET_AS_BASE.search("the base: the merge base of the target branch "
                                                "and HEAD (`git merge-base <target> HEAD`)"))
        for sid, (_, directory) in self.all_skills().items():
            text = "\n".join(skill_files(directory).values())
            flat = " ".join(text.split())
            with self.subTest(skill=sid):
                if "<base>" in text:
                    self.assertTrue(MERGE_BASE in flat, f"uses <base> but never says it is "
                                                        f"{MERGE_BASE}")
                self.assertIsNone(TARGET_AS_BASE.search(flat))

    def test_generic_text(self):
        word = re.compile(r"\b(" + "|".join(FRAMEWORKS) + r")\b", re.I)
        self.assertIsNotNone(word.search("built with react and TAILWIND"))
        files = [p for p in builtin_packs_root().rglob("*") if p.is_file()]
        for path in files:
            with self.subTest(file=path.relative_to(builtin_packs_root()).as_posix()):
                self.assertIsNone(word.search(path.read_text("utf-8")))


class ContractTest(SkillRules):  # P4B-AC-015, P4B-AC-016
    def test_scope_and_verbs(self):
        rows = {**{s: ("core", *r) for s, r in CORE.items()}, **PACK_SKILLS}
        for sid, (pack, scope, verbs, says) in rows.items():
            directory = builtin_packs_root() / pack / "skills" / sid
            text = "\n".join(skill_files(directory).values())
            steps = section((directory / "SKILL.md").read_text("utf-8"), "## Steps")
            with self.subTest(skill=sid):
                self.assertTrue(section(text, "## Scope").strip().startswith(
                    "Read-only" if scope == "read-only" else "Writes"))
                self.assertEqual([v for v in verbs if not uses(commands(steps), v)], [])
                if scope == "read-only":
                    self.assertEqual([v for v in WRITER_VERBS if uses(commands(text), v)], [])
                    self.assertFalse(any(argv(c)[:1] == ["sync"] and "--dry-run" not in argv(c)
                                         for c in commands(text)))
                flat = " ".join(text.split())
                self.assertEqual([p for p in says if p not in flat], [])


class LintCodesReferenceTest(unittest.TestCase):  # module-lint explains every code
    def test_the_safe_fixes_agree_with_the_reference(self):  # fix wave M6
        skill = builtin_packs_root() / "core/skills/module-lint"
        steps = section((skill / "SKILL.md").read_text("utf-8"), "## Steps")
        fields = {argv(c)[3] for c in commands(steps) if argv(c)[:2] == ["registry", "set"]}
        self.assertEqual(fields, {"name", "context_files"})
        rows = dict(re.findall(r"^\| (MS\d{3}) \| [^|]+ \| ([^|]+) \|$",
                               (skill / "references/lint-codes.md").read_text("utf-8"), re.M))
        self.assertTrue(rows["MS003"].startswith("Ask"), rows["MS003"])
        self.assertTrue(rows["MS002"].startswith("Safe"), rows["MS002"])

    def test_every_lint_code_is_explained(self):
        source = "".join((ENGINE / "modsys" / f).read_text(encoding="utf-8")
                         for f in ("lint.py", "rules.py"))
        ref = (builtin_packs_root() / "core/skills/module-lint/references/lint-codes.md")
        documented = re.findall(r"^\| (MS\d{3}) \|", ref.read_text("utf-8"), re.M)
        self.assertEqual(sorted(documented), sorted(set(re.findall(r"MS\d{3}", source))))


class InitAndAdoptSkillsTest(unittest.TestCase):  # P5B-AC-028, P5B-AC-029 (D6, D7)
    def test_the_siblings_they_name(self):
        for sid, sibling in (("module-init", "module-adopt"), ("module-init", "module-create"),
                             ("module-adopt", "module-init")):
            text = (builtin_packs_root() / "core/skills" / sid / "SKILL.md").read_text("utf-8")
            self.assertIn(f"`{sibling}`", section(text, "## When not to use"))

    def test_module_adopt_runs_no_registry_writer(self):
        files = skill_files(builtin_packs_root() / "core/skills/module-adopt")
        cmds = [c for text in files.values() for c in commands(text)]
        self.assertTrue(cmds)
        self.assertEqual([v for v in WRITER_VERBS if uses(cmds, v)], [])

    def test_module_adopt_writes_before_it_asks(self):  # G11: the order of the steps
        steps = section((builtin_packs_root() / "core/skills/module-adopt/SKILL.md")
                        .read_text("utf-8"), "## Steps")
        order = [steps.index(s) for s in ("modsys adopt --dry-run --json", "**Write it.**",
                                          "modsys adopt --json", "modsys lint --json",
                                          "**Then ask what adopt never guesses**", "**Report**")]
        self.assertEqual(order, sorted(order))

    def test_module_init_parses_the_phases_it_runs(self):
        files = skill_files(builtin_packs_root() / "core/skills/module-init")
        self.assertEqual(sorted(files), ["SKILL.md", "references/phases.md"])
        cmds = [argv(c) for text in files.values() for c in commands(text)]
        self.assertTrue(all("--json" in a or "--dry-run" in a for a in cmds))
        self.assertIn(["init", "done", "X", "--json"], cmds)
        self.assertIn(["eval", "routing", "--prompt", "--json"], cmds)

    def test_module_init_step_6_removes_a_shared_keyword(self):  # P5C-AC-014, P6-AC-038 (D14)
        root = builtin_packs_root() / "core/skills/module-init"
        text = " ".join((root / "SKILL.md").read_text("utf-8").split())
        self.assertIn("removes it only from the modules whose code never mentions it (no negative "
                      "keyword)", text)
        self.assertNotIn("removes it from the others", text)
        for rel in ("SKILL.md", "references/phases.md"):
            self.assertNotIn("negative_keywords", (root / rel).read_text("utf-8"))

    def test_module_init_writers_brief_asks_for_domain_words(self):  # P6-AC-040 (D15)
        root = builtin_packs_root() / "core/skills/module-init"
        phases = " ".join((root / "references/phases.md").read_text("utf-8").split())
        for needle in ("including the things and actions its `## Purpose` paragraph names even "
                       "where the code names them differently",
                       "routing matches whole words without stemming, so single words with the "
                       "plural and verb forms of the key nouns",  # kept from f1f5e46
                       "each key verb in every form tasks use: base, `-s`, `-ed`, `-ing`"):
            self.assertIn(needle, phases)

    def test_module_init_step_5_names_the_invented_check(self):  # P5C-AC-014 (D2, D5)
        root = builtin_packs_root() / "core/skills/module-init"
        text = " ".join((root / "SKILL.md").read_text("utf-8").split())
        self.assertIn("a path that does not exist, a symbol not in its row's file", text)
        self.assertIn("while it has the context", text)
        phases = " ".join((root / "references/phases.md").read_text("utf-8").split())
        self.assertIn("a path that does not exist or a symbol not in its row's file", phases)

    def test_module_init_step_5_passes_previous_problems(self):  # P5C-AC-014 (D3, D5)
        root = builtin_packs_root() / "core/skills/module-init"
        text = " ".join((root / "SKILL.md").read_text("utf-8").split())
        self.assertIn("A claim whose `item` has `previous_problems`", text)
        phases = " ".join((root / "references/phases.md").read_text("utf-8").split())
        self.assertIn("`previous_problems`", phases)
        for body in (text, phases):  # final review I-1: a subagent given the path gets them too
            self.assertIn("the work item file does not hold them", body)
            self.assertIn("fix them first", body)


class ScaffoldBaseTest(unittest.TestCase):  # P5A-AC-004 (D0a)
    def test_the_scaffold_says_what_the_base_is(self):
        scaffold = (ENGINE / "modsys/defaults/scaffold/SKILL.md").read_text("utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            code, _, err = run("packs", "new", "team", "--skill", "api-review", "--root",
                               str(root))
            self.assertEqual((code, err), (0, ""))
            skill = root / ".modsys/packs/team/skills/api-review"
            rendered = (skill / "SKILL.md").read_text("utf-8")
            self.assertIsNone(source_problem(skill, "api-review"))
        for text in (scaffold, rendered):
            flat = " ".join(text.split())
            self.assertIn("modsys discover --from-diff <base>..HEAD", flat)
            self.assertIn(MERGE_BASE, flat)
            self.assertIsNone(TARGET_AS_BASE.search(flat))


class SplitInOneChangeTest(unittest.TestCase):  # P4B-AC-015, SI-9
    def test_adding_legacy_copies_is_not_ms051(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            init_git(root)
            R = ("--root", str(root))
            doc = root / "modules/catalog/MODULE.md"
            (root / "modules/catalog/MODULE.legacy.md").write_bytes(doc.read_bytes())
            self.assertEqual(run("create", "search", "--parent", "catalog", "--non-interactive",
                                 "--description", "Finding books by title, author or isbn.",
                                 "--keywords", "search", *R)[0], 0)
            doc.write_text("# Catalog\n\n| Child | Scope |\n|---|---|\n| search | finding |\n")
            code, env, err = run_json("lint", "--changed", "--base", "HEAD", *R)
            self.assertEqual((code, err), (0, ""))
            self.assertEqual([f for f in env["data"]["findings"] if f["code"] == "MS051"], [])
            git(root, "add", "--", ".")
            git(root, "commit", "-q", "-m", "split")
            (root / "modules/catalog/MODULE.legacy.md").write_text("# edited\n")
            data = run_json("lint", "--changed", "--base", "HEAD", "--fail-on", "never",
                            *R)[1]["data"]
            self.assertEqual([f["path"] for f in data["findings"] if f["code"] == "MS051"],
                             ["modules/catalog/MODULE.legacy.md"])


if __name__ == "__main__":
    unittest.main()
