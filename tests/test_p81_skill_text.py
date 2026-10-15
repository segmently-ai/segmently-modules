"""The text of the four skills that find modules (P8.1 task 5, rewritten by P8.2 task 5: D1, D5,
D8, F20). The shared "choose modules" step — `segmently-modules catalog`, the mode, the work order of
`segmently-modules choose` handed to the shipped `segmently-modules:module-chooser` agent (Claude Code), to
`codex exec` (Codex) or answered in the session (elsewhere), `segmently-modules choose --apply`, the keyword
half, the merge — is word for word the same in module-discover, module-sync, module-scout and
module-research (P82-AC-034…039). A `lexical` config never skips the search by meaning (D1); the
depth sentences live in the order's rules, the user's depth travels as `choose --effort` (D8);
module-discover passes `--files` as separate arguments (F20, P82-AC-040), and the commands of the
step run on the split fixture with a canned chooser reply (P82-AC-038, P82-AC-040). Sizes and
descriptions are pinned by `test_budgets` and `test_builtin_skills` (P82-AC-041). Every task text
goes to segmently-modules through a file (final review M-6), and every `match` / `context` / `discover`
given a task in a shipped skill, reference or template runs `--match lexical` (final review I-1,
P8.2 ruling M-6): a repository's `[match] mode` never turns a skill's keyword check into an agent
run. The chooser setting changed module-discover's half of the step: it reads `segmently-modules
catalog --settings --json` and decides the mode in one table (`test_discover_choose_text`); its
by-meaning bullet, the keyword half and the merge stay word for word the shared ones."""
from __future__ import annotations

import io
import json
import re
import shlex
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from segmently_modules.config import builtin_packs_root
from segmently_modules.packs_cmd import scaffold_files
from tests.helpers import (SPLIT_FIXTURE, changelog_since_first_release, copy_fixture, init_git,
                           run, run_json)
from tests.test_builtin_skills import argv, commands, section, uses

ENGINE = Path(__file__).resolve().parents[1]
SKILLS = ("module-discover", "module-sync", "module-scout", "module-research")
MODE = "The mode:"  # the shared text starts here …
MEANING = "- By meaning (`semantic`, `hybrid`):"
KEYWORD = "- By keyword (`lexical`, `hybrid`):"  # … the skill's own keyword half sits here …
HYBRID = "- `hybrid`: merge the lists; a module found both ways ranks first."  # … then the merge
AGENT = "segmently-modules:module-chooser"
CLAUDE_CODE = "segmently-modules choose --task-file <task file> > <order file>"
CODEX = ("codex exec -m <search.codex_model> -c model_reasoning_effort=<reasoning> "
         "--sandbox read-only --output-schema <schema file> - < <order file>")  # AC-038 amended
APPLY = "segmently-modules choose --apply - --json"
F20 = ("`--files` takes the paths as separate arguments (`--files a.ts b/c.ts`); one quoted string "
       "is one path.")
SHARED = ("module-sync", "module-scout", "module-research")  # the mode sentence as P8.2 wrote it


def text(skill: str) -> str:
    """The skill's `SKILL.md` as an agent reads it (P8.6 D1: the finding skills hold their steps
    again): the shared choice of candidates, routed to `references/choose.md` (X4: the core pack's
    size), stands indented under the step line that names that file."""
    root = builtin_packs_root() / "core/skills" / skill
    body = (root / "SKILL.md").read_bytes().decode("utf-8")
    choose = root / "references/choose.md"
    if not choose.is_file():
        return body
    lines = choose.read_bytes().decode("utf-8").split("\n")[2:]  # after its title and blank line
    inset = "\n".join(f"   {line}" if line else "" for line in lines).rstrip("\n")
    head, sep, tail = body.partition("`references/choose.md`")
    line_end = tail.index("\n") + 1
    return head + sep + tail[:line_end] + "\n" + inset + "\n" + tail[line_end:]


def flat(s: str) -> str:
    return " ".join(s.split())


def between(s: str, start: str, end: str) -> str:
    """The flat text from `start` up to `end` (excluded); '' when either is missing."""
    s = flat(s)
    if start not in s:
        return ""
    rest = s[s.index(start):]
    return rest[:rest.index(end)] if end in rest else ""


def in_order(body: str, phrases: list[str]) -> list[int]:
    """The position of each phrase in `body`, each searched after the previous one (-1: not
    found there)."""
    out, at = [], 0
    for p in phrases:
        i = body.find(p, at)
        out.append(i)
        at = i + len(p) if i >= 0 else at
    return out


def command(skill: str, start: str) -> str:
    """The one command of the skill's steps that starts with `start`."""
    found = [c for c in commands(section(text(skill), "## Steps")) if c.startswith(start)]
    assert len(found) == 1, (skill, start, found)
    return found[0]


def filled(cmd: str, values: dict[str, str]) -> tuple[list[str], str | None]:
    """A skill command as the agent runs it: each `<placeholder>` replaced by its value (a value
    with spaces stays several words, as the shell splits it), the output's file cut off.
    Returns (the verb's argv, the file the output goes to or None)."""
    cmd, _, target = cmd.partition(" > ")
    for key, value in values.items():
        cmd, target = cmd.replace(key, value), target.replace(key, value)
    left = re.search(r"<[^<>]*>", cmd)
    assert left is None, f"unfilled placeholder in {cmd!r}"
    return shlex.split(cmd)[1:], (target or None)


def strict_problems(node, path: str, objects: list[str]) -> list[str]:
    """Why a JSON schema is not strict-mode ready: every object node closed
    (`additionalProperties: false`) with every property required. `objects` collects the object
    nodes' paths."""
    out = []
    if isinstance(node, dict):
        if node.get("type") == "object" or "properties" in node:
            objects.append(path)
            if node.get("additionalProperties") is not False:
                out.append(f"{path}: additionalProperties is not false")
            keys = sorted(node.get("properties", {}))
            if sorted(node.get("required", [])) != keys:
                out.append(f"{path}: required {keys} != {sorted(node.get('required', []))}")
        for key, value in node.items():
            out += strict_problems(value, f"{path}.{key}", objects)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            out += strict_problems(value, f"{path}[{i}]", objects)
    return out


class SharedStepTest(unittest.TestCase):  # P82-AC-034…039
    PHRASES = [
        # fix 1 I-1: the mode key only; `match.semantic` is the CLI's agent command, not the skill's
        "segmently-modules catalog --json", "read `match.mode` and `search`.",
        # D1 (P82-AC-035): hybrid, whatever a lexical config says; English examples (SI-P82-21)
        "The mode: `hybrid` unless the user says otherwise",
        '("only lexical", "by meaning", in any language)',
        "or `match.mode` is `semantic`;",
        "a `lexical` config is only the command line's default and never skips the search by "
        "meaning, which needs no setting;",
        "the keyword commands always pass `--match lexical`.",
        # SI-P82-14 ruling (b), D8 (P82-AC-039): the user's model and depth
        'The user may set the model ("use opus")',
        # fix 1 I-2: the command named, so the flag never lands on `discover` / `context`
        'and the depth ("search deep": `choose --effort deep`; `<reasoning>` follows it).',
        MEANING,
        # D5 (P82-AC-036): the Claude Code path
        "write the text, verbatim, to `<task file>`.",
        f"**Claude Code:** `{CLAUDE_CODE}`;",
        f"give `<order file>`'s path to the `{AGENT}` agent with `model: <search.claude_model>`",
        # SI-P82-15 (P82-AC-037): the fallback without the plugin names its condition (fix 1
        # M-1: the agent, never the model it was just given)
        '(without that agent: a subagent told "this file is your whole task; answer with its '
        'JSON only; change nothing");',
        "its reply is the answer.",
        # P82-AC-038: the Codex path, the file form
        "**Codex:** the same with `--json`, its `answer_schema` written to `<schema file>`, then "
        f"`{CODEX}`",
        "(`low`, `medium`, `high` for `quick`, `standard`, `deep`).",
        # P82-AC-037: the fallback elsewhere
        "**Elsewhere** (no subagent, no `codex exec`, or it fails, as inside a sandbox): answer "
        "the order yourself, every card "
        "read, by its rules.",
        f"Pipe the answer to `{APPLY}`.",  # every path ends in the same --apply
        KEYWORD, HYBRID,
    ]
    GONE = [  # the P8.1 wording D1 / D5 / D8 replace (P82-AC-034, 036, 039)
        "only when `match.semantic` is true", "Pass `--match semantic`",
        "else `match.mode` unless `lexical`", "match.semantic",
        "Answer it whole (never a preview)", "a subagent (`model: <search.claude_model>`)",
        "`quick` the cards only", "`standard` also the INDEX", "`deep` also their docs and code",
        "at the depth its rules set",
        "read `match` and `search`", "when it is not available",  # fix 1 I-1, M-1
        "model_reasoning_effort=<reasoning> --output-schema",  # final review M-2: read-only
    ]

    # module-discover under the chooser setting: the settings from `catalog --settings`, the mode
    # sentence replaced by the routing table (pinned by test_discover_choose_text)
    DISCOVER_SAYS = {
        "segmently-modules catalog --json": "segmently-modules catalog --settings --json"}
    NOT_IN_DISCOVER = (
        "The mode: `hybrid` unless the user says otherwise",
        '("only lexical", "by meaning", in any language)', "or `match.mode` is `semantic`;",
        "a `lexical` config is only the command line's default and never skips the search by "
        "meaning, which needs no setting;", "the keyword commands always pass `--match lexical`.")

    def phrases(self, skill: str) -> list[str]:
        if skill in SHARED:
            return self.PHRASES
        return [self.DISCOVER_SAYS.get(p, p) for p in self.PHRASES if p not in self.NOT_IN_DISCOVER]

    def test_every_skill_says_it_once_and_in_order(self):
        for skill in SKILLS:
            with self.subTest(skill=skill):
                body, phrases = flat(text(skill)), self.phrases(skill)
                self.assertEqual([p for p in phrases if body.count(p) != 1], [])
                found = in_order(body, phrases)
                self.assertEqual([p for p, i in zip(phrases, found) if i < 0], [])

    def test_module_discover_drops_only_the_mode_sentence(self):
        body = flat(text("module-discover"))
        self.assertEqual([p for p in self.NOT_IN_DISCOVER if p in body], [])
        self.assertNotIn("segmently-modules catalog --json", body)

    def test_the_p81_wording_is_gone(self):
        for skill in SKILLS:
            with self.subTest(skill=skill):
                body = flat(text(skill))
                self.assertEqual([p for p in self.GONE if p in body], [])

    def test_no_skill_names_match_semantic(self):  # fix 1 I-1: round 3 read it as "off"
        root = builtin_packs_root()
        found = [p.relative_to(root).as_posix() for p in sorted(root.rglob("*.md"))
                 if "match.semantic" in p.read_bytes().decode("utf-8")]
        self.assertEqual(found, [])

    def test_the_depth_goes_to_choose_only(self):  # fix 1 I-2: never on discover / context
        for skill in SKILLS:
            with self.subTest(skill=skill):
                body = flat(text(skill))
                self.assertEqual(body.count("`choose --effort deep`"), 1)
                self.assertEqual(body.count("--effort"), 1)
                for a in (argv(c) for c in commands(text(skill))):
                    self.assertNotIn("--effort", a)

    def test_word_for_word_the_same(self):
        parts = {s: between(text(s), MODE, KEYWORD) for s in SHARED}
        self.assertTrue(all(parts.values()), parts)
        self.assertEqual(len(set(parts.values())), 1, parts)
        meaning = {s: between(text(s), MEANING, KEYWORD) for s in SKILLS}  # module-discover too
        self.assertTrue(all(meaning.values()), meaning)
        self.assertEqual(len(set(meaning.values())), 1, meaning)
        for skill in SKILLS:
            with self.subTest(skill=skill):  # the merge is one line, the same in all four
                self.assertEqual(text(skill).count(f"\n   {HYBRID}\n"), 1)

    def test_the_steps_run_the_verbs(self):
        for skill in SKILLS:
            with self.subTest(skill=skill):
                cmds = commands(section(text(skill), "## Steps"))
                for verb in (("catalog",), ("choose", "--task-file"), ("choose", "--apply")):
                    self.assertTrue(uses(cmds, verb), verb)
                self.assertEqual(command(skill, "segmently-modules choose --task-file <task file>"), CLAUDE_CODE)

    def test_the_agent_is_the_shipped_one(self):  # D4 / D5: the name the skills hand work to
        agent = (ENGINE / "segmently_modules/defaults/agents/module-chooser.md").read_text("utf-8")
        name = re.search(r"^name: (\S+)$", agent, re.M).group(1)
        self.assertEqual(AGENT, f"segmently-modules:{name}")

    def test_keyword_commands_are_lexical(self):  # review I-1, ruling M-6
        for skill in SKILLS:
            with self.subTest(skill=skill):
                body = flat(text(skill))
                self.assertNotIn("has no agent to ask", body)
                keyword = [argv(c) for c in commands(text(skill))
                           if argv(c)[:1] in (["discover"], ["context"])]
                self.assertTrue(keyword)
                for a in keyword:
                    self.assertIn("--match", a, a)
                for a in (argv(c) for c in commands(text(skill))):
                    if "--match" in a:  # never semantic or hybrid: the skill is the agent
                        self.assertEqual(a[a.index("--match") + 1], "lexical", a)

    def test_every_task_text_goes_through_a_file(self):  # final review M-6, deferred 3
        for skill in SKILLS:
            with self.subTest(skill=skill):
                for a in (argv(c) for c in commands(text(skill))):
                    self.assertNotIn("--task", a, a)
                self.assertTrue(any("--task-file" in argv(c) for c in commands(text(skill))))

    def test_no_cyrillic_in_shipped_text(self):  # SI-P82-21: English user words only
        root = builtin_packs_root().parent
        found = [p.relative_to(root).as_posix() for p in sorted(root.rglob("*"))
                 if p.is_file() and p.suffix in (".md", ".toml", ".json")
                 and re.search("[Ѐ-ӿ]", p.read_bytes().decode("utf-8"))]
        self.assertEqual(found, [])

    def test_the_keys_it_names_are_printed(self):  # P82-AC-039: the text and the engine agree
        named = {s: set(re.findall(r"\b(?:match|search)\.[a-z_]+\b", text(s))) for s in SKILLS}
        self.assertLessEqual({"match.mode", "search.claude_model", "search.codex_model"},
                             set().union(*named.values()))
        self.assertIn("search.chooser", named["module-discover"])
        with tempfile.TemporaryDirectory() as tmp:
            R = ("--root", str(copy_fixture(tmp, SPLIT_FIXTURE)))
            printed = {}
            for argv in (("catalog", "--json"), ("catalog", "--settings", "--json")):
                code, out, err = run(*argv, *R)
                self.assertEqual((code, err), (0, ""))
                catalog = json.loads(out)["data"]
                printed[argv] = {f"{group}.{key}" for group in ("match", "search")
                                 for key in catalog[group]}
                self.assertIn(catalog["search"]["effort"], ("quick", "standard", "deep"))
            for skill in SKILLS:  # module-discover reads `catalog --settings`, the others `catalog`
                with self.subTest(skill=skill):
                    argv = ("catalog", "--settings", "--json") if skill == "module-discover" \
                        else ("catalog", "--json")
                    self.assertEqual(sorted(named[skill] - printed[argv]), [])


class CommandsRunTest(unittest.TestCase):  # P82-AC-036, 038, 039, 040
    """The skills' by-meaning commands, filled in as an agent fills them, run on the split
    fixture: the task file, the work order's text form to a file, a canned chooser reply through
    `--apply`; the Codex form's `<schema file>`; the user's depth; then module-discover's
    `code-map files` and `discover --files a b` (F20)."""
    TASK = "Customers' money back for a returned book — `refund` $now"  # written verbatim

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = copy_fixture(self._tmp.name, SPLIT_FIXTURE)
        init_git(self.root)
        self.files = Path(self._tmp.name) / "files"  # temporary files outside the repository
        self.files.mkdir()
        self.task = self.files / "task.txt"
        self.task.write_text(self.TASK, encoding="utf-8")
        self.values = {"<task file>": str(self.task), "<order file>": str(self.files / "order.txt")}

    def cli(self, args: list[str], stdin: str | None = None) -> str:
        with mock.patch("sys.stdin", io.StringIO(stdin or "")):
            code, out, err = run(*args, "--root", str(self.root))
        self.assertEqual((code, err), (0, ""), args)
        return out

    def order(self, skill: str, *extra: str) -> tuple[str, Path]:
        """The skill's `choose` command, filled in and run; its output in `<order file>`."""
        args, target = filled(command(skill, "segmently-modules choose --task-file <task file>"), self.values)
        out = self.cli([*args, *extra])
        Path(target).write_text(out, encoding="utf-8")
        return out, Path(target)

    def test_claude_code_path(self):  # P82-AC-036: text form, the agent's reply, --apply
        for skill in SKILLS:
            with self.subTest(skill=skill):
                out, order = self.order(skill)
                self.assertTrue(out.startswith(f"Task:\n{self.TASK}\n"))  # verbatim
                self.assertIn("Candidates (one per line: module, description, keywords):", out)
                self.assertFalse(out.lstrip().startswith("{"))  # the text form, not JSON
                digest = re.search(r"^catalog_digest: (\S+)$",
                                   order.read_text(encoding="utf-8"), re.M).group(1)
                reply = json.dumps({"picks": [{"module": "orders/refunds", "confidence": 0.9,
                                               "reason": "returned books"}],
                                    "none": False, "catalog_digest": digest})
                args, target = filled(command(skill, "segmently-modules choose --apply"), {})
                self.assertIsNone(target)
                applied = json.loads(self.cli(args, stdin=reply))
                self.assertEqual(applied["schema"], "segmently-modules.choose/1")
                pick = applied["data"]["picks"][0]
                self.assertEqual(pick["module"], "orders/refunds")
                self.assertTrue(pick["read"])

    def test_codex_path_writes_the_schema_file(self):  # P82-AC-038
        args, _ = filled(command("module-sync", "segmently-modules choose --task-file <task file>"), self.values)
        envelope = json.loads(self.cli([*args, "--json"]))  # "the same with `--json`"
        (self.files / "order.json").write_text(json.dumps(envelope), encoding="utf-8")
        schema_file = self.files / "schema.json"  # "its `answer_schema` written to <schema file>"
        schema_file.write_text(json.dumps(envelope["data"]["answer_schema"], indent=2),
                               encoding="utf-8")
        schema = json.loads(schema_file.read_text(encoding="utf-8"))  # valid JSON
        self.assertEqual(schema, envelope["data"]["answer_schema"])
        self.assertEqual(schema["type"], "object")
        self.assertEqual(envelope["data"]["task"], self.TASK)
        # fix 1 M-4: what `--output-schema` needs (strict structured outputs)
        objects = []
        self.assertEqual(strict_problems(schema, "$", objects), [])
        self.assertEqual(objects, ["$", "$.properties.picks.items"])

    def test_the_strict_check_can_fail(self):
        open_object = {"type": "object", "properties": {"a": {"type": "object", "properties": {
            "b": {"type": "string"}}, "required": [], "additionalProperties": False}},
            "required": ["a"]}
        self.assertEqual(strict_problems(open_object, "$", []),
                         ["$: additionalProperties is not false",
                          "$.properties.a: required ['b'] != []"])

    def test_the_users_depth(self):  # D8, SI-P82-14 ruling (b): "search deep" -> --effort deep
        default = json.loads(self.cli(["choose", "--task-file", str(self.task), "--json"]))
        args, _ = filled(command("module-scout", "segmently-modules choose --task-file <task file>"), self.values)
        deep = json.loads(self.cli([*args, "--effort", "deep", "--json"]))
        self.assertEqual(deep["data"]["search"]["effort"], "deep")
        self.assertNotEqual(deep["data"]["rules"], default["data"]["rules"])
        out, _ = self.order("module-scout", "--effort", "deep")
        self.assertIn("also read the candidates' docs and confirm the choice in their code", out)

    def test_discover_commands_in_order(self):  # P82-AC-040
        self.order("module-discover")  # the task file, then the order to <order file>
        args, _ = filled(command("module-discover", "segmently-modules choose --apply"), {})
        reply = json.dumps({"picks": [{"module": "orders", "confidence": 0.8, "reason": "r"}],
                            "none": False, "catalog_digest": None})
        self.assertEqual(json.loads(self.cli(args, stdin=reply))["data"]["picks"][0]["module"],
                         "orders")
        args, _ = filled(command("module-discover", "segmently-modules code-map files"),
                         {"<module>": "orders"})
        self.assertIn("src/orders/service.py", self.cli(args).splitlines())  # DCP-AC-024
        keywords = self.files / "queries.txt"  # the keyword half's `<file>`
        keywords.write_text("refund\norder service\n", encoding="utf-8")
        found = "src/orders/service.py src/payments/gateway.py"  # separate arguments (F20)
        args, _ = filled(command("module-discover", "segmently-modules discover --files"),
                         {"<edit files>": found, "<file>": str(keywords)})
        self.assertEqual(args[:3], ["discover", "--files", "src/orders/service.py"])
        data = json.loads(self.cli(args))["data"]
        self.assertEqual([f["path"] for f in data["files"]],
                         ["src/orders/service.py", "src/payments/gateway.py"])
        self.assertEqual(data["missing_files"], [])
        # one quoted string is one path: a file that does not exist
        data = json.loads(self.cli(["discover", "--files", found, *args[4:]]))["data"]
        self.assertEqual(data["missing_files"], [found])


class EveryShippedTextIsLexicalTest(unittest.TestCase):  # final review I-1 (and 5 D-4)
    """A `match`, a `context` or a `discover` given a task, anywhere the engine ships text an
    agent follows (every pack's skills and references, the templates, the skill `packs new`
    scaffolds), passes `--match lexical`: under a committed `[match] mode = "semantic"` none of
    them exits 2 for want of an agent command, and none starts the user's agent for a keyword
    check. And none takes its task as a quoted `--task` argument (M-6): always `--task-file`."""

    def shipped(self) -> dict[str, str]:
        root = builtin_packs_root().parent
        out = {p.relative_to(root).as_posix(): p.read_bytes().decode("utf-8")
               for p in sorted(root.rglob("*.md"))}
        for roles in (["reviewer", "auditor"], []):  # what `packs new` writes, with roles or none
            for path, body in scaffold_files("team", roles, ["api-review"], None, None).items():
                out[f"packs new ({len(roles)} roles): {path}"] = body
        return out

    def test_every_keyword_command_is_lexical(self):
        found = set()
        for name, body in self.shipped().items():
            for a in (argv(c) for c in commands(body)):
                if a[:1] in (["match"], ["context"]) or (
                        a[:1] == ["discover"] and {"--task", "--task-file"} & set(a)):
                    found.add(name)
                    with self.subTest(file=name, argv=a):
                        self.assertIn("--match", a)
                        self.assertEqual(a[a.index("--match") + 1], "lexical")
        for name in ("templates/agents-md.md", "packs/core/skills/module-create/SKILL.md",
                     "packs/qa/skills/qa-acceptance/SKILL.md",
                     "packs/core/skills/module-discover/SKILL.md",
                     "packs/core/skills/module-sync/references/choose.md",
                     "packs/core/skills/module-scout/references/choose.md",
                     "packs/core/skills/module-research/references/choose.md",
                     "packs new (2 roles): skills/api-review/SKILL.md",
                     "packs new (0 roles): skills/api-review/SKILL.md"):
            self.assertIn(name, found)  # the scan reaches what the reviews named

    def test_no_task_is_a_quoted_argument(self):  # final review M-6
        for name, body in self.shipped().items():
            for a in (argv(c) for c in commands(body)):
                with self.subTest(file=name, argv=a):
                    self.assertNotIn("--task", a)

    def test_the_scan_sees_a_missing_flag(self):
        for body in ('`segmently-modules context --task "<t>" --role <r>`',
                     "```bash\nsegmently-modules match x --json\n```",
                     "`segmently-modules discover --task-file <f> --match hybrid --json`"):
            a = argv(commands(body)[0])
            self.assertFalse("--match" in a and a[a.index("--match") + 1] == "lexical", body)


class OtherKeysTest(unittest.TestCase):  # review M-9: the keys the steps read, next to the text
    def test_children_submodules_near_misses_and_code_map_via(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp, SPLIT_FIXTURE)
            init_git(root)
            R = ("--root", str(root))
            found = run_json("discover", "--files", "src/orders/service.py", "--match",
                             "lexical", *R)[1]["data"]
            row = {m["module"]: m for m in found["modules"]}["orders"]
            self.assertEqual(row["usage"], "modify")
            self.assertEqual(sorted(row["children"][1]), ["description", "doc", "module"])
            shown = run_json("show", "orders", *R)[1]["data"]
            self.assertIn("refunds", shown["submodules"])
            near = run_json("context", "--task", "refundz", "--match", "lexical", *R)[1]["data"]
            self.assertEqual((near["modules"], near["near_misses"][0]["module"]),
                             ([], "orders/refunds"))
            child = run_json("code-map", "files", "orders/refunds", *R)[1]["data"]["files"]
            self.assertEqual({tuple(f["via"]) for f in child}, {("docs",)})  # no code: parent's
            parent = run_json("code-map", "files", "orders", *R)[1]["data"]["files"]
            self.assertIn("src/orders/service.py",
                          [f["path"] for f in parent if f["via"] != ["docs"]])


class DiscoverTest(unittest.TestCase):  # P81-AC-041 (F6a, F6b), P82-AC-040 (F20)
    ORDER = [  # P8.6 D2: the complete context pull of the host original
        "segmently-modules catalog --settings --json",  # the chooser setting (DCP-AC-023)
        "1–3 short English queries",  # F6a: the registry's language, domain terms, identifiers
        "(steps 6 and 7 use it too)",  # review M-4
        "the domain terms and code identifiers",
        "**The mode.** One table decides",  # the chooser setting (DCP-AC-006)
        '"only lexical"',
        MEANING,
        f"`{APPLY}`",
        f"{KEYWORD} `segmently-modules discover --task-file <file> --match lexical --json`",
        HYBRID,
        "Modules the user named join the list with a boost",
        "**Verify.**", "the child the task is in",
        "Score the rest on four questions, 0–10 each, and keep a module whose average is ≥ 5",
        "**One hop out.**", "forward `depends-on`, `implemented-in` and `shares-contract` edges",
        "**Usage.**", "`modify` — the task changes its code or its contracts",
        "`consume` — the task calls its API as it is", "`reference` — the task only follows",
        "**Docs for every role.**", "segmently-modules show <module> --all-roles --json",
        "read, nothing for this task",
        "**Code touch points.**",
        "segmently-modules code-map files <module> --source-only --paths",  # DCP-AC-024
        "its source files, one per line, docs and tests left out",  # review I-2: a doc is not code
        "source files first, tests last — searched in the module's test paths only for the "
        "behaviour the task changes, found with `git grep -l -e <term> -- <the module's code paths>` "
        "(its test hits); the rest of the repository only after an empty module search",  # task-3 review M-6: the hits, never the whole list

        "`<edit | read> — file:line — symbol — why`",  # DCP-AC-011: the tag first
        "it never guesses the files the work will create",
        "**Owners and docs to update.**",
        "segmently-modules discover --files <edit files> --task-file <file> --match lexical --json",
        F20,  # P82-AC-040
        "**Report**", "`references/report.md`",
    ]

    def test_the_steps_in_order(self):
        body = flat(section(text("module-discover"), "## Steps"))
        found = in_order(body, self.ORDER)
        self.assertEqual([p for p, i in zip(self.ORDER, found) if i < 0], [])

    def test_step_7_says_how_files_are_passed(self):  # P82-AC-040 (F20)
        step7 = between(section(text("module-discover"), "## Steps"),
                        "7. **Owners and docs to update.**", "8. **Report**")
        self.assertEqual(flat(step7).count(F20), 1)


class SyncTest(unittest.TestCase):  # P81-AC-042 (F10, F13, F15)
    ORDER = [
        "segmently-modules sync-instructions --from-diff <base>..HEAD --json",
        "`children` on a split parent: pick the child the change is in",  # F10
        "segmently-modules catalog --json",  # F13: the docs that describe the change, in the mode
        "The text: a summary of the change with its identifiers",
        "joins the modules to update, with the docs the search listed",  # review M-6
        "segmently-modules registry append <module> keywords",
        "Add one only for a new feature, command or concept that people will name in later tasks",  # P84-AC-020
        "never a code identifier",
    ]

    def test_the_steps_in_order(self):
        body = flat(section(text("module-sync"), "## Steps"))
        found = in_order(body, self.ORDER)
        self.assertEqual([p for p, i in zip(self.ORDER, found) if i < 0], [])

    def test_the_keyword_half_is_discover(self):
        body = flat(text("module-sync"))
        self.assertIn(f'{KEYWORD} `segmently-modules discover --task-file <', body)

    def test_temporary_files_go_outside_the_repository(self):  # fix 1 M-3: the order files
        scope = flat(section(text("module-sync"), "## Scope"))
        self.assertIn("Temporary files go outside the repository.", scope)


class ScoutAndResearchTest(unittest.TestCase):  # P81-AC-043
    START, END = "No module named? Choose the candidates.", "never widen the list on your own."

    def test_the_same_search_for_a_topic_without_modules(self):
        parts = {s: between(text(s), self.START, self.END)
                 for s in ("module-scout", "module-research")}
        self.assertTrue(all(parts.values()), parts)
        self.assertEqual(parts["module-scout"], parts["module-research"])
        self.assertIn("The mode: `hybrid` unless", parts["module-scout"])
        self.assertIn(f'{KEYWORD} `segmently-modules context --task-file <', parts["module-scout"])
        self.assertIn("Keep the top 3;", parts["module-scout"])  # review M-7

    def test_scout_keeps_the_retry_rule(self):  # review M-8
        exits = section(text("module-scout"), "## Exit codes")
        self.assertIn("do not retry the same command", flat(exits))

    def test_it_is_part_of_the_steps(self):
        for skill in ("module-scout", "module-research"):
            with self.subTest(skill=skill):
                self.assertIn(self.START, flat(section(text(skill), "## Steps")))


class DocsTest(unittest.TestCase):  # P8.2 task 5: docs/skills.md follows the shared step
    def test_skills_doc(self):
        doc = flat((ENGINE / "docs/skills.md").read_text(encoding="utf-8"))
        part = doc.split("## Choosing modules by meaning", 1)[1].split(" ## ", 1)[0]
        for needle in (f"`{CLAUDE_CODE}`", f"`{AGENT}`", f"`{CODEX}`",
                       "reads `match.mode` and `search`", "`--effort deep` to `segmently-modules choose`",
                       "A `lexical` config",
                       "is only the command line's default and never skips the search by meaning",
                       "always pass `--match lexical`",
                       "this file is your whole task; answer with its JSON only",
                       "every card read, by its rules"):
            self.assertIn(needle, part)
        for gone in ("only when `match.semantic` is true", "never a preview",
                     "`quick` the cards only",
                     "model_reasoning_effort=<reasoning> --output-schema"):  # final review M-2
            self.assertNotIn(gone, doc)

    def test_changelog(self):  # fix 1 M-2: the mode said the right way round
        log = (ENGINE / "CHANGELOG.md").read_text(encoding="utf-8")
        unreleased = flat(changelog_since_first_release(log))
        self.assertIn("search both ways (`hybrid`) unless the user says otherwise or `match.mode` "
                      "is `semantic`", unreleased)
        self.assertNotIn("search by meaning unless the user says otherwise", unreleased)


if __name__ == "__main__":
    unittest.main()
