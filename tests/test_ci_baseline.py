"""`modsys ci --baseline FILE|-`: a finding of lint or drift that an earlier run already held is
`known`, and a step fails only on findings that are not (P83-AC-001 … 009)."""
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

from tests.helpers import NO_AUTO_MAINTENANCE, git, init_git, make_repo, mutate_registry, run

ENGINE = Path(__file__).resolve().parents[1]
GOLDEN = Path(__file__).parent / "fixtures" / "ci_baseline_golden"

CONFIG = ('[budgets]\nmodule_doc_split_signal = 3\n\n'
          '[[code_map]]\nid = "src"\npattern = "src/{module}/**"\n')
CATALOG = ("# catalog\n\nThe books on the shelves.\n\n## EXISTING Components\n\n"
           "| Path | Role |\n|---|---|\n| `src/catalog/gone.py` | the old shelf |\n")
STALE = "| `src/payments/missing.py` | a till nobody built |\n"
EXTRA = "One more sentence.\n"


def build_repo(tmp: str) -> Path:
    """The synthetic bookshop: MS030 and MS040 on `catalog` at HEAD~1, a code change in
    `payments` without docs at HEAD (MS050)."""
    root = make_repo(tmp, {"catalog": ["book", "shelf"], "payments": ["till", "receipt"]},
                     CONFIG, ("src/catalog/shelf.py", "src/payments/till.py"))
    (root / "modules/catalog/MODULE.md").write_text(CATALOG, encoding="utf-8")
    (root / "modules/payments/MODULE.md").write_text("## EXISTING Components\n", encoding="utf-8")
    init_git(root)
    with (root / "src/payments/till.py").open("a", encoding="utf-8") as fh:
        fh.write("y = 2\n")
    git(root, "commit", "-q", "-am", "payments code only")
    return root


class CiBaselineCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.root = build_repo(self._tmp.name)
        self.R = ("--root", str(self.root))
        self.work = self.tmp / "work"
        self.work.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def doc(self, module: str) -> Path:
        return self.root / f"modules/{module}/MODULE.md"

    def append(self, module: str, text: str) -> None:
        with self.doc(module).open("a", encoding="utf-8") as fh:
            fh.write(text)

    def ci(self, *argv, stdin: bytes | None = None):
        """(exit, stdout, stderr) of `ci --base HEAD~1 <argv>`; `stdin` on sys.stdin.buffer."""
        args = ("ci", "--base", "HEAD~1", *argv, *self.R)
        if stdin is None:
            return run(*args)
        fake = mock.Mock(buffer=io.BytesIO(stdin))
        with mock.patch("sys.stdin", fake):
            return run(*args)

    def ci_json(self, *argv, code=None, stdin: bytes | None = None) -> dict:
        got, out, err = self.ci(*argv, "--json", stdin=stdin)
        self.assertEqual(err, "")
        if code is not None:
            self.assertEqual(got, code)
        return json.loads(out)["data"]

    def save(self, name="b.json", *argv) -> Path:
        path = self.work / name
        _, out, _ = self.ci(*argv, "--json")
        path.write_text(out, encoding="utf-8")
        return path

    @staticmethod
    def findings(data, step):
        return next(s for s in data["steps"] if s["name"] == step)["findings"]

    @staticmethod
    def marks(data, step):
        return sorted((f["code"], f["module"], f["known"])
                      for f in CiBaselineCase.findings(data, step))

    def write_baseline(self, lint=(), drift=(), name="hand.json", extra=None) -> Path:
        data = {"steps": [{"name": "lint", "findings": list(lint)},
                          {"name": "drift", "findings": list(drift)}]}
        data.update(extra or {})
        path = self.work / name
        path.write_text(json.dumps({"schema": "modsys.ci/1", "data": data}), encoding="utf-8")
        return path


def fnd(code, module, message, path=None, severity="warning"):
    return {"code": code, "severity": severity, "module": module, "message": message,
            "path": path}


CATALOG_DOC = "modules/catalog/MODULE.md"
MS030_9 = fnd("MS030", "catalog", "9 lines > split signal 3", CATALOG_DOC)
MS040 = fnd("MS040", "catalog", "component path missing on disk: src/catalog/gone.py",
            CATALOG_DOC)


class KnownTest(CiBaselineCase):  # P83-AC-001
    def test_the_same_key_in_lint_findings_is_known(self):  # row 1
        data = self.ci_json("--baseline", str(self.write_baseline(lint=[MS030_9, MS040])))
        self.assertEqual(self.marks(data, "lint"), [("MS030", "catalog", True),
                                                    ("MS040", "catalog", True)])

    def test_the_same_key_in_the_other_step_is_known(self):  # row 2
        data = self.ci_json("--baseline", str(self.write_baseline(drift=[MS030_9, MS040])))
        self.assertEqual({m[2] for m in self.marks(data, "lint")}, {True})
        data = self.ci_json("--baseline", str(self.write_baseline(lint=[MS030_9, MS040])))
        self.assertEqual({m[2] for m in self.marks(data, "lint")}, {True})
        self.append("catalog", EXTRA)  # catalog is now a changed module: drift holds its findings
        data = self.ci_json("--baseline", str(self.write_baseline(lint=[fnd(
            "MS030", "catalog", "10 lines > split signal 3", CATALOG_DOC), MS040])))
        self.assertEqual({m[2] for m in self.marks(data, "drift") if m[0] != "MS050"}, {True})
        data = self.ci_json("--baseline", str(self.write_baseline(drift=[fnd(
            "MS030", "catalog", "10 lines > split signal 3", CATALOG_DOC), MS040])))
        self.assertEqual({m[2] for m in self.marks(data, "lint")}, {True})

    def test_another_path_or_null_is_not_known(self):  # row 3
        other = dict(MS040, path="modules/catalog/OTHER.md")
        nulled = dict(MS040, path=None)
        for var in (other, nulled):
            with self.subTest(path=var["path"]):
                data = self.ci_json("--baseline",
                                    str(self.write_baseline(lint=[MS030_9, var])))
                self.assertEqual(self.marks(data, "lint"), [("MS030", "catalog", True),
                                                            ("MS040", "catalog", False)])

    def test_a_null_path_against_a_baseline_path_is_not_known(self):  # row 3, reversed (review M-3)
        (self.root / ".modsys/config.toml").write_text(
            CONFIG + '\n[[code_map]]\nid = "x"\nglobs = ["lib/**"]\nmodule = "nosuch"\n',
            encoding="utf-8")  # MS052: a config-level finding, its path null
        ms052 = next(f for f in self.findings(self.ci_json(), "lint") if f["code"] == "MS052")
        self.assertIsNone(ms052["path"])
        with_path = dict(ms052, path=".modsys/config.toml")
        for held, want in ((with_path, False), (ms052, True)):
            with self.subTest(baseline_path=held["path"]):
                data = self.ci_json("--baseline", str(self.write_baseline(lint=[held])))
                self.assertEqual([f["known"] for f in self.findings(data, "lint")
                                  if f["code"] == "MS052"], [want])

    def test_digits_in_the_message_do_not_matter(self):  # row 4
        self.append("catalog", EXTRA)
        data = self.ci_json("--baseline", str(self.write_baseline(lint=[MS030_9, MS040])))
        lint = {f["code"]: f for f in self.findings(data, "lint")}
        self.assertEqual(lint["MS030"]["message"], "10 lines > split signal 3")  # real message
        self.assertEqual([lint["MS030"]["known"], lint["MS040"]["known"]], [True, True])

    def test_another_code_is_not_known(self):  # row 5
        hard = fnd("MS031", "catalog", "9 lines > split signal 3", CATALOG_DOC)
        data = self.ci_json("--baseline", str(self.write_baseline(lint=[hard, MS040])))
        self.assertEqual(self.marks(data, "lint"), [("MS030", "catalog", False),
                                                    ("MS040", "catalog", True)])

    def test_ms050_and_ms051_are_never_known(self):  # row 6
        ms050 = fnd("MS050", "payments", self._ms050_message(), None)
        saved = self.save("own.json")
        own = json.loads(saved.read_text(encoding="utf-8"))["data"]
        held = self.findings(own, "drift")
        self.assertEqual([f["code"] for f in held], ["MS050"])
        data = self.ci_json("--baseline", str(saved), code=1)
        self.assertEqual(self.marks(data, "drift"), [("MS050", "payments", False)])
        ms051 = fnd("MS051", "payments", "x", None, "error")
        data = self.ci_json("--baseline", str(self.write_baseline(drift=[ms050, ms051, *held])))
        self.assertEqual(self.marks(data, "drift"), [("MS050", "payments", False)])

    def _ms050_message(self):
        return self.findings(self.ci_json(), "drift")[0]["message"]

    def test_a_duplicate_is_known_both_times(self):  # row 7
        self.append("catalog", "| `src/catalog/gone.py` | the same missing path again |\n")
        data = self.ci_json("--baseline", str(self.write_baseline(lint=[MS030_9, MS040])))
        self.assertEqual(self.marks(data, "lint"), [("MS030", "catalog", True),
                                                    ("MS040", "catalog", True),
                                                    ("MS040", "catalog", True)])

    def test_no_equal_key_is_not_known(self):  # row 8
        data = self.ci_json("--baseline", str(self.write_baseline()))
        self.assertEqual(self.marks(data, "lint"), [("MS030", "catalog", False),
                                                    ("MS040", "catalog", False)])

    def test_severity_fail_on_known_flags_and_base_never_enter(self):
        noisy = dict(MS040, severity="error", known=False)
        data = self.ci_json("--baseline", str(self.write_baseline(
            lint=[MS030_9, noisy], extra={"base": "elsewhere", "fail_on": "never"})))
        self.assertEqual({m[2] for m in self.marks(data, "lint")}, {True})


class FailTest(CiBaselineCase):  # P83-AC-002
    def test_known_findings_only_pass_even_with_errors(self):
        (self.root / ".modsys/config.toml").write_text(
            CONFIG.replace("module_doc_split_signal = 3",
                           "module_doc_split_signal = 3\nmodule_doc_hard_stop = 5"),
            encoding="utf-8")  # catalog's 9 lines: MS031, an error
        hard = fnd("MS031", "catalog", "9 lines > hard stop 5: split into submodules",
                   CATALOG_DOC, "error")
        for fail_on in ("error", "warning", "never"):
            with self.subTest(fail_on=fail_on):
                data = self.ci_json("--baseline", str(self.write_baseline(lint=[hard, MS040])),
                                    "--fail-on", fail_on, "--base", "HEAD", code=0)
                self.assertEqual([s["status"] for s in data["steps"][:2]],
                                 ["passed", "passed"])
                self.assertEqual((data["failed"], data["steps"][0]["summary"]["known"],
                                  data["steps"][0]["summary"]["error"]), (False, 2, 1))

    def test_unknown_warning_fails_at_warning_only(self):
        base = str(self.write_baseline(lint=[MS030_9]))
        for fail_on, want, code in (("warning", "failed", 1), ("error", "passed", 0),
                                    ("never", "passed", 0)):
            with self.subTest(fail_on=fail_on):
                data = self.ci_json("--baseline", base, "--fail-on", fail_on, code=code)
                self.assertEqual(data["steps"][0]["status"], want)
                self.assertEqual(data["failed"], want == "failed")

    def test_unknown_error_fails_at_error_and_warning(self):
        (self.root / ".modsys/config.toml").write_text(
            CONFIG.replace("module_doc_split_signal = 3",
                           "module_doc_split_signal = 3\nmodule_doc_hard_stop = 5"),
            encoding="utf-8")  # catalog's 9 lines is now MS031, an error
        base = str(self.write_baseline(lint=[MS040]))
        for fail_on, want, code in (("error", "failed", 1), ("warning", "failed", 1),
                                    ("never", "passed", 0)):
            with self.subTest(fail_on=fail_on):
                data = self.ci_json("--baseline", base, "--fail-on", fail_on, code=code)
                self.assertEqual(data["steps"][0]["status"], want)

    def test_unknown_info_never_fails(self):
        (self.root / ".modsys/config.toml").write_text(
            CONFIG.replace("module_doc_split_signal = 3",
                           "module_doc_split_signal = 30\nkeyword_shared_warn = 2"),
            encoding="utf-8")
        mutate_registry(self.root, lambda d: d["modules"]["payments"]["keywords"].append("book"))
        base = str(self.write_baseline(lint=[MS040]))
        data = self.ci_json("--baseline", base, "--fail-on", "never")
        self.assertEqual([(f["code"], f["known"]) for f in self.findings(data, "lint")],
                         [("MS021", False), ("MS040", True)])
        data = self.ci_json("--baseline", base, "--fail-on", "warning", "--base", "HEAD",
                            code=0)
        self.assertEqual((data["steps"][0]["status"], data["steps"][0]["summary"]["known"]),
                         ("passed", 1))

    def test_no_changed_file_stays_no_changes(self):
        data = self.ci_json("--baseline", str(self.write_baseline()), "--base", "HEAD")
        drift = data["steps"][1]
        self.assertEqual((drift["status"], drift["summary"]["known"]), ("no-changes", 0))
        self.assertEqual(data["steps"][2]["status"], "report-only")

    def test_coverage_and_fail_under_behave_as_before(self):
        (self.root / "tools").mkdir()
        (self.root / "tools/t.py").write_text("x = 1\n", encoding="utf-8")  # unmapped
        base = str(self.write_baseline(lint=[MS030_9, MS040]))
        data = self.ci_json("--baseline", base, "--fail-under", "100", code=1)
        self.assertEqual(data["steps"][2]["status"], "failed")
        self.assertNotIn("known", data["steps"][2]["summary"])
        self.assertTrue(data["failed"])


class JsonFormTest(CiBaselineCase):  # P83-AC-003, P83-AC-005
    def test_shapes_and_the_baseline_key(self):
        data = self.ci_json("--baseline", str(self.write_baseline(lint=[MS030_9, MS040])))
        lint, drift, cov = data["steps"]
        self.assertEqual(list(lint["findings"][0]),
                         ["code", "severity", "module", "message", "path", "known"])
        self.assertEqual(list(lint["summary"]), ["error", "warning", "info", "known"])
        self.assertEqual(list(drift["summary"]),
                         ["base", "files", "committed", "uncommitted", "modules", "error",
                          "warning", "info", "known"])
        self.assertEqual(list(cov["summary"]),
                         ["share", "mapped", "total", "unmapped", "fail_under"])
        self.assertEqual(list(data)[-1], "baseline")
        # severity counts count every finding, known included
        self.assertEqual((lint["summary"]["warning"], lint["summary"]["known"]), (2, 2))

    def test_the_file_as_given(self):
        path = self.write_baseline(lint=[MS030_9, MS040])
        relative = os.path.relpath(path)
        for given in ("b.json", str(path), "-"):
            with self.subTest(given=given):
                if given == "-":
                    data = self.ci_json("--baseline", "-", stdin=path.read_bytes())
                elif given == "b.json":
                    with mock.patch("modsys.pipeline.Path") as P:  # the shared reader
                        P.return_value.read_bytes.return_value = path.read_bytes()
                        data = self.ci_json("--baseline", "b.json")
                else:
                    data = self.ci_json("--baseline", given)
                self.assertEqual(data["baseline"], given)
        self.assertEqual(self.ci_json("--baseline", relative)["baseline"], relative)

    def test_every_source_gives_the_same_flags(self):
        want = self.marks(self.ci_json("--baseline", str(self.save())), "lint")
        own = self.save("again.json", "--baseline", str(self.save()))  # a --baseline run's output
        extra = json.loads(self.save("extra.json").read_text(encoding="utf-8"))
        extra["data"]["steps"].append({"name": "other", "findings": "x", "more": 1})
        extra["more"] = True
        extra_path = self.work / "extra2.json"
        extra_path.write_text(json.dumps(extra), encoding="utf-8")
        other = self.save("other.json", "--fail-on", "never", "--base", "HEAD")
        raw = (self.work / "b.json").read_bytes()
        for path in (own, extra_path, other):
            with self.subTest(path=path.name):
                self.assertEqual(self.marks(self.ci_json("--baseline", str(path)), "lint"),
                                 want)
        self.assertEqual(self.marks(self.ci_json("--baseline", "-", stdin=raw), "lint"), want)

    def test_a_path_never_reads_stdin(self):
        path = self.save()
        fake = mock.Mock()
        fake.buffer.read.side_effect = AssertionError("stdin was read")
        with mock.patch("sys.stdin", fake):
            code, out, err = run("ci", "--base", "HEAD~1", "--baseline", str(path), "--json",
                                 *self.R)
        self.assertEqual((code, err), (1, ""))

    def test_the_baseline_is_read_before_any_step(self):
        with mock.patch("modsys.ci_cmd.lint_registry") as lint, \
                mock.patch("modsys.ci_cmd.require_work_tree") as tree:
            code, out, err = run("ci", "--baseline", str(self.work / "none.json"), *self.R)
        self.assertEqual((code, out), (2, ""))
        lint.assert_not_called()
        tree.assert_not_called()


class TextFormTest(CiBaselineCase):  # P83-AC-004
    def test_failed_step_lines(self):
        base = self.save()
        self.append("payments", STALE)
        self.append("catalog", EXTRA)
        code, out, err = self.ci("--baseline", str(base))
        self.assertEqual((code, err), (1, ""))
        self.assertIn(
            "  WARNING MS030 catalog: 10 lines > split signal 3  "
            "(modules/catalog/MODULE.md) (known)\n", out)
        self.assertIn("  WARNING MS040 payments: component path missing on disk: "
                      "src/payments/missing.py  (modules/payments/MODULE.md)\n", out)
        self.assertTrue(out.rstrip().endswith("ci: failed"))
        lint_line = next(line for line in out.splitlines() if line.startswith("lint"))
        self.assertTrue(lint_line.endswith("(2 known from the baseline)"), lint_line)
        # the drift step marks the same way (review M-2): its line and its own finding lines
        lines = out.splitlines()
        at = next(i for i, line in enumerate(lines) if line.startswith("drift"))
        self.assertTrue(lines[at].startswith("drift     failed"), lines[at])
        self.assertTrue(lines[at].endswith("(2 known from the baseline)"), lines[at])
        under = [line for line in lines[at + 1:] if line.startswith("  ")][:3]
        self.assertEqual(lines[at + 1:at + 4], under)
        self.assertIn("  WARNING MS030 catalog: 10 lines > split signal 3  "
                      "(modules/catalog/MODULE.md) (known)", under)
        self.assertIn("  WARNING MS040 payments: component path missing on disk: "
                      "src/payments/missing.py  (modules/payments/MODULE.md)", under)

    def test_a_passing_step_line(self):
        base = self.save()
        code, out, err = self.ci("--baseline", str(base), "--fail-on", "never")
        self.assertEqual(code, 0)
        self.assertIn("lint      passed       0 error(s), 2 warning(s), 0 info "
                      "(2 known from the baseline)\n", out)
        self.assertEqual([line for line in out.splitlines() if line.startswith("  ")], [])
        self.assertIn("coverage  report-only", out)

    def test_no_suffix_when_nothing_is_known(self):
        code, out, err = self.ci("--baseline", str(self.write_baseline()))
        self.assertNotIn("known from the baseline", out)
        self.assertNotIn("(known)", out)


class StoryTest(CiBaselineCase):  # P83-AC-007
    def test_the_f26_case_end_to_end(self):
        saved = self.save()
        first = json.loads(saved.read_text(encoding="utf-8"))["data"]
        self.assertEqual(sorted(f["code"] for f in self.findings(first, "lint")),
                         ["MS030", "MS040"])
        self.assertEqual([f["code"] for f in self.findings(first, "drift")], ["MS050"])
        self.assertTrue(first["failed"])
        payments = self.doc("payments").read_text(encoding="utf-8")
        self.append("payments", EXTRA)
        self.append("catalog", EXTRA)
        self.append("payments", STALE)
        data = self.ci_json("--baseline", str(saved), code=1)
        lint, drift = (self.marks(data, s) for s in ("lint", "drift"))
        self.assertEqual(lint, [("MS030", "catalog", True), ("MS040", "catalog", True),
                                ("MS040", "payments", False)])
        self.assertIn(("MS040", "payments", False), drift)
        self.assertEqual([s["status"] for s in data["steps"][:2]], ["failed", "failed"])
        # step 4: the stale path goes
        text = self.doc("payments").read_text(encoding="utf-8").replace(STALE, "")
        self.doc("payments").write_text(text, encoding="utf-8")
        data = self.ci_json("--baseline", str(saved), code=0)
        self.assertEqual((data["steps"][0]["status"], data["steps"][0]["summary"]["known"]),
                         ("passed", 2))
        _, out, _ = self.ci("--baseline", str(saved))
        self.assertIn("(2 known from the baseline)", out)
        # step 5: the payments doc line goes too: MS050 is new again
        self.doc("payments").write_text(payments, encoding="utf-8")
        data = self.ci_json("--baseline", str(saved), code=1)
        self.assertEqual(self.marks(data, "drift"), [("MS030", "catalog", True),
                                                     ("MS040", "catalog", True),
                                                     ("MS050", "payments", False)])


class RefusalTest(CiBaselineCase):  # P83-AC-006
    def refuse(self, source, stdin=None, expect=None):
        for extra in ((), ("--json",)):
            with self.subTest(source=source, extra=extra):
                git_calls = []
                real = subprocess.run

                def spy(*a, **k):
                    git_calls.append(a)
                    return real(*a, **k)
                with mock.patch("subprocess.run", spy), mock.patch("subprocess.Popen",
                                                                   side_effect=spy):
                    code, out, err = self.ci("--baseline", source, *extra, stdin=stdin)
                self.assertEqual((code, out, git_calls), (2, "", []))
                self.assertEqual(err, f"modsys: error: {expect}\n")
                self.assertNotIn("Traceback", err)

    def not_ci(self, source):
        return f"--baseline {source}: not the --json output of modsys ci (schema modsys.ci/1)"

    def test_unreadable(self):
        missing = str(self.work / "none.json")
        self.refuse(missing, expect=f"cannot read {missing}: No such file or directory")
        self.refuse(str(self.work), expect=f"cannot read {self.work}: Is a directory")
        bad = self.work / "latin.json"
        bad.write_bytes(b'{"x": "r\xe9fund"}')
        self.refuse(str(bad), expect=f"cannot read {bad}: not valid UTF-8")
        self.refuse("-", stdin=b"\xff\xfe", expect="cannot read <stdin>: not valid UTF-8")

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root reads mode 000")
    def test_mode_000(self):
        path = self.work / "locked.json"
        path.write_text("{}", encoding="utf-8")
        path.chmod(0)
        try:
            self.refuse(str(path), expect=f"cannot read {path}: Permission denied")
        finally:
            path.chmod(0o600)

    def test_not_a_ci_document(self):
        def put(name, content):
            path = self.work / name
            path.write_text(content if isinstance(content, str) else json.dumps(content),
                            encoding="utf-8")
            return str(path)

        ci = "modsys.ci/1"
        finding_no_path = {"code": "MS040", "severity": "warning", "module": "m", "message": "x"}
        cases = {
            "empty": "", "bracket": "[", "lint-schema": {"schema": "modsys.lint/1", "data": {}},
            "no-data": {"schema": ci}, "data-list": {"schema": ci, "data": []},
            "no-steps": {"schema": ci, "data": {}},
            "steps-object": {"schema": ci, "data": {"steps": {}}},
            "no-path": {"schema": ci, "data": {"steps": [
                {"name": "lint", "findings": [finding_no_path]}]}},
            "findings-string": {"schema": ci, "data": {"steps": [
                {"name": "drift", "findings": "none"}]}},
            "findings-missing": {"schema": ci, "data": {"steps": [{"name": "lint"}]}},
            "message-number": {"schema": ci, "data": {"steps": [{"name": "lint", "findings": [
                {"code": "MS040", "module": "m", "message": 3, "path": None}]}]}},
            "finding-not-object": {"schema": ci, "data": {"steps": [
                {"name": "lint", "findings": ["x"]}]}},
            "top-list": [1],
        }
        for name, content in cases.items():
            path = put(name + ".json", content)
            self.refuse(path, expect=self.not_ci(path))
        self.refuse("-", stdin=b"[", expect=self.not_ci("-"))


class SubprocessTest(CiBaselineCase):  # P83-AC-005, P83-AC-035 (real pipes)
    def cli(self, *argv, stdin=b""):
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
                   GIT_CEILING_DIRECTORIES=os.environ["GIT_CEILING_DIRECTORIES"],
                   PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(ENGINE), **NO_AUTO_MAINTENANCE)
        return subprocess.run([sys.executable, "-m", "modsys", *argv], input=stdin,
                              capture_output=True, env=env, cwd=str(ENGINE))

    def test_stdin_and_refusals_with_real_pipes(self):
        saved = self.save()
        done = self.cli("ci", "--base", "HEAD~1", "--baseline", "-", "--json", *self.R,
                        stdin=saved.read_bytes())
        data = json.loads(done.stdout)["data"]
        self.assertEqual((done.returncode, done.stderr, data["baseline"]), (1, b"", "-"))
        self.assertEqual(self.marks(data, "lint"), [("MS030", "catalog", True),
                                                    ("MS040", "catalog", True)])
        for stdin, line in ((b"\xff", b"modsys: error: cannot read <stdin>: not valid UTF-8\n"),
                            (b"[", b"modsys: error: --baseline -: not the --json output of "
                                   b"modsys ci (schema modsys.ci/1)\n")):
            done = self.cli("ci", "--base", "HEAD~1", "--baseline", "-", "--json", *self.R,
                            stdin=stdin)
            self.assertEqual((done.returncode, done.stdout, done.stderr), (2, b"", line))

    def test_stdin_closed_at_start_reads_as_the_other_readers_say(self):  # final review M-1
        env = dict(os.environ, PYTHONPATH=str(ENGINE), PYTHONDONTWRITEBYTECODE="1")
        got = {}
        for argv in (("ci", "--baseline", "-"),
                     ("context", "--task-file", "-", "--match", "lexical")):
            done = subprocess.run(["/bin/sh", "-c", 'exec "$@" 0<&-', "sh", sys.executable, "-m",
                                   "modsys", *argv, *self.R],
                                  capture_output=True, env=env, cwd=str(ENGINE))
            self.assertEqual((done.returncode, done.stdout), (2, b""), argv)
            got[argv[0]] = done.stderr
        self.assertTrue(got["ci"].startswith(b"modsys: error: cannot read <stdin>: "), got)
        self.assertEqual(got["ci"].count(b"\n"), 1)
        self.assertNotIn(b"internal error", got["ci"])
        self.assertEqual(got["ci"], got["context"])  # the same words as every `-` reader

    def test_a_swapped_text_stdin(self):  # final review M-1: an in-process caller's stream
        saved = self.save().read_text(encoding="utf-8")
        for text, code in ((saved, 1), ("[", 2)):
            with self.subTest(text=text[:10]):
                with mock.patch("sys.stdin", io.StringIO(text)):
                    got, out, err = run("ci", "--base", "HEAD~1", "--baseline", "-", "--json",
                                        *self.R)
                self.assertEqual(got, code, err)
                self.assertNotIn("internal error", err)
                if code == 1:
                    self.assertEqual(self.marks(json.loads(out)["data"], "lint"),
                                     [("MS030", "catalog", True), ("MS040", "catalog", True)])
                else:
                    self.assertEqual((out, err), ("", "modsys: error: --baseline -: not the "
                                                      "--json output of modsys ci (schema "
                                                      "modsys.ci/1)\n"))

    def test_a_closed_stdin(self):
        env = dict(os.environ, PYTHONPATH=str(ENGINE), PYTHONDONTWRITEBYTECODE="1")
        done = subprocess.run(
            [sys.executable, "-m", "modsys", "ci", "--baseline", "-", *self.R],
            stdin=subprocess.DEVNULL, capture_output=True, env=env, cwd=str(ENGINE))
        self.assertEqual((done.returncode, done.stdout), (2, b""))
        self.assertEqual(done.stderr.count(b"\n"), 1)
        self.assertNotIn(b"Traceback", done.stderr)


class IdenticalWithoutTheFlagTest(CiBaselineCase):  # P83-AC-008
    """The outputs recorded from the engine before the flag existed (one commit hash is masked)."""

    def states(self):
        yield "clean-head", ("--base", "HEAD")
        yield "since-base", ("--base", "HEAD~1")
        yield "since-base-never", ("--base", "HEAD~1", "--fail-on", "never")
        yield "since-base-error-under", ("--base", "HEAD~1", "--fail-on", "error",
                                         "--fail-under", "100")
        self.append("payments", STALE)
        self.append("catalog", EXTRA)
        yield "edited", ("--base", "HEAD~1")

    def test_text_and_json_match_the_recording(self):
        sha = re.compile(r"\b[0-9a-f]{40}\b")
        for name, argv in self.states():
            for form, extra in (("txt", ()), ("json", ("--json",))):
                with self.subTest(state=name, form=form):
                    code, out, err = run("ci", *argv, *extra, *self.R)
                    got = f"exit {code}\n{sha.sub('<sha>', out)}stderr {err!r}\n"
                    want = (GOLDEN / f"{name}.{form}").read_text(encoding="utf-8")
                    self.assertEqual(got, want)
                    self.assertNotIn('"known"', out)
                    self.assertNotIn("baseline", out)

    def test_help_gains_only_the_baseline_option(self):
        code, out, err = run("ci", "--help")
        flat = " ".join(out.split())
        self.assertEqual(code, 0)
        option = ("--baseline FILE|- the --json output of an earlier ci run ('-' = stdin): a "
                  "lint or drift finding it already holds is known, and a step fails only on "
                  "findings that are not (MS050 / MS051 are never known)")
        self.assertIn(option, flat)
        flat = flat.replace(" [--baseline FILE|-]", "").replace(" " + option, "")
        self.assertEqual(flat + "\n", (GOLDEN / "help.txt").read_text(encoding="utf-8"))


class DocsTest(unittest.TestCase):  # P83-AC-009
    def test_the_contract_row_and_the_changelog(self):
        doc = (ENGINE / "docs/cli-contract.md").read_text(encoding="utf-8")
        row = next(line for line in doc.splitlines() if line.startswith("| `ci` |"))
        for needle in ("`--baseline FILE\\|-`", "modsys.ci/1", "MS050 and MS051 are never known",
                       "`known: true\\|false`", "`known: <n>`", 'baseline: "<FILE as given>"',
                       "(<n> known from the baseline)", "(known)",
                       "`cannot read <FILE>: <reason>`", "`<stdin>`", "not valid UTF-8",
                       "--baseline <FILE>: not the --json output of modsys ci "
                       "(schema modsys.ci/1)", "same `code`, `module`, `path` and `message`",
                       "run of ASCII digits"):
            self.assertIn(needle, row)
        log = (ENGINE / "CHANGELOG.md").read_text(encoding="utf-8")
        unreleased = log.split("## [Unreleased]")[1].split("\n## [")[0]
        self.assertIn("ci --baseline", unreleased)

    def test_the_readme_ci_gate_names_the_flag(self):  # final review M-2 (1)
        readme = (ENGINE / "README.md").read_text(encoding="utf-8")
        gate = " ".join(readme.split("\n## CI gate\n", 1)[1].split("\n## ", 1)[0].split())
        for needle in ("`--baseline FILE|-`", "`known`", "fails only on", "MS050 / MS051",
                       "`module-sync` saves the gate"):
            self.assertIn(needle, gate)


if __name__ == "__main__":
    unittest.main()
