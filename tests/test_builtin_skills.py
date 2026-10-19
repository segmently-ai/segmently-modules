"""Structure of the built-in packs' skills (D6), a test per rule over every skill of every
built-in pack: names, loadability, description and file lengths, every `segmently-modules …` command
parsed by the real CLI parser (the guard can fail: SI-7), no machine paths, `--json` for what a
skill parses, the sections, each core skill's scope and verbs (D3), the writer rules, generic
text. `CORE` and `PACK_SKILLS` list what each skill must say; a skill is added with its row."""
from __future__ import annotations

import contextlib
import hashlib
import io
import re
import shlex
import tempfile
import unittest
from pathlib import Path

from segmently_modules._toml import tomllib
from segmently_modules.cli import build_parser
from segmently_modules.config import BUILTIN_PACKS, builtin_packs_root
from segmently_modules.skills import read_front_matter, source_problem
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
    "module-check": ("read-only", [("rules", "--files")],
                     ["No gates — read-only", "`Conflicts:`", "at most five", "no quote, no conflict"]),
    "module-sync": ("writer", [("sync-instructions",), ("registry",), ("propose",), ("sync",),
                               ("ci",)],
                    ["Autonomous by default", "two children of a split module equally well",
                     "a new top-level module or a child", "contradicts a claim in the docs",
                     "the only home for the new text is a `*.legacy.md` file",
                     "never remove one from it",
                     "git ls-files --others --exclude-standard",  # fix wave M4
                     "Skip this step when step 7 ran"]),  # fix wave M5 (P8.7 D5: step 7)
    "module-roles": ("writer", [("roles", "list"), ("roles", "add", "--dry-run"), ("roles", "add"),
                                ("lint",), ("next",)],  # P84-AC-017 (D2)
                     ["Autonomous by default", "what the role is for when unclear",
                      "never inventing components", "continue with step 1",
                      "the role is declared already — start at step 1"]),
    "module-create": ("writer", [("create", "--dry-run"), ("create",), ("code-map", "add"),
                                 ("lint",)],
                      ["Wait for an explicit yes", "at least five", "Never invent components"]),
    "module-split": ("writer", [("show",), ("create", "--parent"), ("code-map", "add"),
                                ("lint",)],
                     ["**STOP**", "copy it byte for byte to a sibling named `<name>.legacy.md`",
                      "The parent's keywords stay unchanged", "verbatim", "Three to six",
                      # fix wave M11, P8.7 D7: a child keeps only the role docs with content
                      "with only the roles whose docs receive sections"]),
    "module-lint": ("fix-up", [("ci",), ("lint",), ("registry", "set")],
                    ["Leave the judgement calls to the user", "references/lint-codes.md"]),
    "module-init": ("writer", [("init", "status"), ("init", "map"), ("init", "confirm"),
                               ("init", "fanout"), ("init", "next"), ("init", "done"),
                               ("init", "reconcile"), ("eval", "routing", "--prompt"),
                               ("init", "verify"), ("init", "finish")],  # P5B-AC-028 (D6)
                    ["Run `segmently-modules init status --json` first and continue from the recorded phase",
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
    "module-assistant": ("writer", [("next",), ("setup", "--dry-run"), ("templates", "list"),
                                    ("packs", "sync"), ("code-map", "add"), ("ci",)],
                         ["Before any write, show the plan", "stops for a new OK",
                          "Never present a command or a flag you have not seen"]),
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
    # P8.9 (D11, owner): designer-review became `designer` — prototype, rework audit, review
    "designer": ("ui", "writer", [("discover", "--task-file"), ("discover", "--from-diff"),
                                  ("discover", "--files"), ("show", "--role", "designer")],
                 ["Must fix", "Should fix", "Could improve", "What works well", "`PASS`",
                  "`BLOCKED: N must-fix`", "Design checker",
                  "a UI task is not done while a Must fix is open",
                  "git ls-files --others --exclude-standard"]),  # fix wave M4
    "qa-acceptance": ("qa", "writer", [("discover", "--task-file"), ("show", "--role", "qa"),
                                       ("show", "--role", "qa_acceptance")],
                      ["`PRE-NNN`", "`AC-NNN`", "**Given**", "**When**", "**Then**",
                       "equivalence partitioning", "boundary value analysis",
                       "decision table", "state transition", "instead of restating it"]),
    "qa-acceptance-baseline": ("qa", "writer", [("show", "--all-roles"),
                                                ("show", "--role", "qa_acceptance"), ("lint",),
                                                ("roles", "add")],  # P8.5 D2
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
_SPLIT = re.compile(r"`(segmently-modules [^`]*\n[^`]*)`")  # an inline command broken over two lines
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


def route(text: str) -> list[tuple[str, list[str]]]:
    """The Route block of a skill's `SKILL.md` (P8.4 D1): the `- **<scenario>** … →
    `references/<file>`` items of `## Steps` before step 1, each item up to its first blank
    line, as [(scenario, [the files it names])]; [] for a skill with one scenario."""
    head = section(text, "## Steps").split("\n1. ", 1)[0]
    items = [chunk.split("\n\n", 1)[0] for chunk in re.split(r"\n(?=- )", head)]
    return [(m.group(1), re.findall(r"`(references/[^`\s]+)`", item))
            for item in items if (m := re.match(r"- \*\*([a-z0-9-]+)\*\*", item))]


def route_files(directory: Path) -> dict[str, str]:
    """{name: text} of the files a skill's Route names: its scenarios' steps (P8.4 D1)."""
    text = (directory / "SKILL.md").read_text("utf-8")
    return {name: (directory / name).read_text("utf-8")
            for _, names in route(text) for name in names if (directory / name).is_file()}


def commands(text: str) -> list[str]:
    """Every `segmently-modules …` command of a text: fenced-block lines (continuations joined) and inline
    code spans."""
    out = []
    for block in _FENCE.finditer(text):
        for line in block.group(3).replace("\\\n", " ").splitlines():
            if line.strip().startswith("segmently-modules "):
                out.append(line.strip())
    out += [s.strip() for s in _INLINE.findall(_FENCE.sub("", text))
            if s.strip().startswith("segmently-modules ")]
    return out


def argv(command: str) -> list[str]:
    """A command's arguments: a comment, a heredoc or a redirect of its output cut, every `<…>`
    and `…` one value."""
    command = command.split(" #")[0].split("<<")[0].split(" > ")[0]
    return shlex.split(_PLACEHOLDER.sub("X", command).replace("…", "X"))[1:]


def to_a_file(command: str) -> bool:
    """The command's output goes to a file (`… > <order file>`): the skill hands the file on and
    never parses it (P8.2 D5: the work order's text form)."""
    return " > " in command.split(" #")[0]


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
    LINE = ("If `segmently-modules` is not found, tell the user how to install it — the "
            "`segmently-modules` plugin for Claude Code, `uv tool install "
            "git+https://github.com/segmently-ai/segmently-modules.git`, or `pipx install "
            "git+https://github.com/segmently-ai/segmently-modules.git` — and stop until it runs.")
    DESCRIPTIONS = {  # sha256[:16] of each description at f1f5e46: a body edit never moves one
        # (P8.7 X3: module-sync's moved — its trigger widened to a session that revealed knowledge)
        # (P8.8, owner: qa-acceptance's delivery sentence — shown in the conversation, not a file)
        # (P8.9, owner: designer-review renamed `designer`, its description names the three routes)
        # (the rename to Segmently Modules, owner: the product name left the verb mentions)
        "module-adopt": "c8f67a732e47681a", "module-create": "88844df447f72c53",
        "module-discover": "c94d722d31235c69", "module-init": "2bed37af36af61b7",
        "module-lint": "d19804f58e3380f7", "module-research": "be7f867931e5c0ce",
        "module-scout": "79df2d2b49d5ccb6", "module-split": "134b4160f4344630",
        "module-sync": "373a648c232de290", "module-roles": "686cf561ceb829bf",
        "module-assistant": "840b945cfa4eff76", "qa-acceptance-baseline": "a14b60b636d19605",
        "qa-acceptance": "9285192a1351f89f", "designer": "6bd3019e180a415a",
        "module-check": "c75f9a2311f21c42"}

    def test_every_body_holds_the_one_line(self):
        skills = self.all_skills()
        self.assertEqual(len(skills), 15)
        for sid, (_, directory) in skills.items():
            with self.subTest(skill=sid):
                text = (directory / "SKILL.md").read_text("utf-8")
                front, body = text.split("\n---\n", 1)
                self.assertEqual(body.splitlines().count(self.LINE), 1)
                self.assertNotIn("not found", front)  # the body, never the description
                self.assertLess(body.index(self.LINE), body.index("\n## Steps\n"))
                self.assertIn(f"\n\n{self.LINE}\n\n", body)  # its own paragraph
        urls = re.findall(r"github\.com(\S*)", self.LINE)  # the public repository only
        self.assertEqual(urls, ["/segmently-ai/segmently-modules.git`,",
                                "/segmently-ai/segmently-modules.git`"])

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
        self.assertEqual(argv('segmently-modules discover --task-file <file> --json  # the task'),
                         ["discover", "--task-file", "X", "--json"])
        self.assertEqual(argv('segmently-modules context --task "<the task in one sentence>" --json'),
                         ["context", "--task", "X", "--json"])
        self.assertEqual(argv("segmently-modules sync --from-diff <base>..HEAD --dry-run"),
                         ["sync", "--from-diff", "X..HEAD", "--dry-run"])
        self.assertEqual(argv("segmently-modules create … --dry-run"), ["create", "X", "--dry-run"])
        # P8.2 D5: the work order's text form goes to a file; the redirect is the shell's
        self.assertEqual(argv("segmently-modules choose --task-file <task file> > <order file>"),
                         ["choose", "--task-file", "X"])
        self.assertTrue(to_a_file("segmently-modules choose --task-file <task file> > <order file>"))
        self.assertFalse(to_a_file("segmently-modules choose --task-file <task file>"))
        self.assertFalse(to_a_file("segmently-modules show x --json  # a > b"))

    def test_the_guard_can_fail(self):
        planted = {"SKILL.md": "Run `segmently-modules shwo x` first.\n\n```bash\nsegmently-modules packs install ui\n"
                               "segmently-modules show x --rolee r\n```\n",
                   "references/more.md": "Then `segmently-modules match x --from-diff a..b`, and\n"
                                         "`segmently-modules show x\n--json`.\n"}
        failures = command_guard(planted)
        self.assertEqual([f.split(" — ")[0] for f in failures],
                         ["SKILL.md: segmently-modules packs install ui", "SKILL.md: segmently-modules show x --rolee r",
                          "SKILL.md: segmently-modules shwo x",
                          "references/more.md: segmently-modules match x --from-diff a..b",
                          "references/more.md: segmently-modules show x --json"])
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
        exempt, path_lists = [], []
        for sid, (_, directory) in self.all_skills().items():
            for name, text in skill_files(directory).items():
                for command in commands(text):
                    if to_a_file(command) or "<<'EOF'" in command:  # handed on as a file or
                        # through a quoted heredoc, never parsed (P8.2 D5, SI-P84-8)
                        exempt.append(argv(command))
                        continue
                    if argv(command)[:2] == ["code-map", "files"] and "--paths" in argv(command):
                        path_lists.append((sid, argv(command)))  # one path per line, nothing
                        continue  # to parse (DCP-AC-024: discover's compact code list)
                    with self.subTest(skill=sid, command=command):
                        self.assertTrue({"--json", "--dry-run"} & set(argv(command)))
        # only the work order's text form, once in each skill that chooses modules by meaning,
        # and module-sync's saved gate (P83-AC-012: `ci --base <base> --json > <ci file>`)
        saved_gate = [["ci", "--base", "X", "--json"]]
        cards = [e for e in exempt if e == ["catalog", "--plain"]]  # module-discover's step 1 (owner 2026-10-19)
        self.assertEqual(len(cards), 1)
        # owner 2026-10-19: module-discover reads every output it needs as text through a temp file, read
        # whole (the stand's readers cut every `--json` they were given with a script or `head`)
        reads = [["catalog", "--settings"], ["discover", "--task-file", "X", "--match", "lexical"],
                 ["show", "X"], ["related", "X"], ["show", "X", "--all-roles"],
                 ["discover", "--files", "X", "--task-file", "X", "--match", "lexical", "--modify", "X",
                  "--consume", "X"]]
        self.assertEqual(sorted(e for e in exempt if e in reads), sorted(reads))
        others = [e for e in exempt if e != saved_gate[0] and e[:1] != ["rules"] and e not in cards
                  and e not in reads]
        self.assertEqual(others.count(["choose", "--task-file", "-"]), 3)  # AC-015: one line in
        self.assertEqual(others.count(["choose", "--task-file", "X"]), len(others) - 3)  # each
        self.assertEqual(exempt.count(saved_gate[0]), 1)
        handoff = [e for e in exempt if e[:1] == ["rules"]]  # the rules as text, read whole: module-check's,
        # and module-discover's since c05 pilot 6 (a reader filtered `rules --json` by keyword)
        self.assertEqual(sorted(handoff), [["rules", "X"], ["rules", "XX"], ["rules", "XX"],
                                           ["rules", "XX", "--files", "XX"]])  # + discover's step 5 (2026-10-19)
        self.assertEqual(path_lists, [("module-discover",
                                       ["code-map", "files", "X", "--source-only", "--paths"])])

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


SHARED_SEARCH = ("module-discover", "module-scout", "module-research", "module-sync")


class ContractTest(SkillRules):  # P4B-AC-015, P4B-AC-016
    def test_scope_and_verbs(self):
        rows = {**{s: ("core", *r) for s, r in CORE.items()}, **PACK_SKILLS}
        for sid, (pack, scope, verbs, says) in rows.items():
            directory = builtin_packs_root() / pack / "skills" / sid
            text = "\n".join(skill_files(directory).values())
            # a routed skill's verbs may live in a route file (P84-AC-026)
            steps = "\n".join([section((directory / "SKILL.md").read_text("utf-8"), "## Steps"),
                               *route_files(directory).values()])
            if sid in SHARED_SEARCH:  # P8.6: the shared candidate search and discover's
                # change-only scenario, routed to references/ from the steps that name them (X4)
                steps += "\n".join(p.read_text("utf-8")
                                   for p in sorted((directory / "references").glob("*.md")))
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

    def test_a_verb_in_a_route_file_counts_and_one_in_a_rare_branch_does_not(self):  # P84-AC-026
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp)
            (skill / "references").mkdir()
            (skill / "SKILL.md").write_text(
                "---\nname: stock-check\ndescription: Checks the shelves.\n---\n\n## Steps\n\n"
                "**Route.** Pick one.\n\n- **restock** — more copies of a book\n"
                "  → `references/restock.md`\n- **count** — how many are left →\n"
                "  `references/count.md`\n\nIf a `segmently-modules` command exits 1 or 2, read "
                "`references/exit-codes.md`.\n\n1. Look at the shelf.\n\n## Gates\n\nNone.\n",
                encoding="utf-8")
            (skill / "references/restock.md").write_text("```bash\nsegmently-modules lint --json\n```\n")
            (skill / "references/count.md").write_text("Count them.\n")
            (skill / "references/exit-codes.md").write_text("Run `segmently-modules ci --json`.\n")
            text = (skill / "SKILL.md").read_text("utf-8")
            self.assertEqual(route(text), [("restock", ["references/restock.md"]),
                                           ("count", ["references/count.md"])])
            self.assertEqual(sorted(route_files(skill)), ["references/count.md",
                                                          "references/restock.md"])
            steps = "\n".join([section(text, "## Steps"), *route_files(skill).values()])
            self.assertTrue(uses(commands(steps), ("lint",)))
            self.assertFalse(uses(commands(steps), ("ci",)))
        self.assertEqual(route("# x\n\n## Steps\n\n1. One scenario: `references/x.md`.\n\n"
                               "## Gates\n"), [])


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
        source = "".join((ENGINE / "segmently_modules" / f).read_text(encoding="utf-8")
                         for f in ("lint.py", "rules.py", "doc_checks.py"))
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
        order = [steps.index(s) for s in ("segmently-modules adopt --dry-run --json", "**Write it.**",
                                          "segmently-modules adopt --json", "segmently-modules lint --json",
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
                       "routing ignores word endings, so one form per word; no generic word, "
                       "no thing another module owns, no word for the developer's own tools"):
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
        scaffold = (ENGINE / "segmently_modules/defaults/scaffold/SKILL.md").read_text("utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            code, _, err = run("packs", "new", "team", "--skill", "api-review", "--root",
                               str(root))
            self.assertEqual((code, err), (0, ""))
            skill = root / ".segmently-modules/packs/team/skills/api-review"
            rendered = (skill / "SKILL.md").read_text("utf-8")
            self.assertIsNone(source_problem(skill, "api-review"))
        for text in (scaffold, rendered):
            flat = " ".join(text.split())
            self.assertIn("segmently-modules discover --from-diff <base>..HEAD", flat)
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
