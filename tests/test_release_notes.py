"""`tools/release.py`: only our sections of the publish README and CHANGELOG change
(P6-AC-016); the release notes (P6.1 D6) — the pure parts, whole runs, and the engine's
own CHANGELOG.md. Split from `test_release.py` (P8.3 D5 R-3)."""
import datetime
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import git
from tests.plugin_helpers import ENGINE, load_tool
from tests.release_helpers import (CHANGELOG, DATE, LOG_BEGIN, LOG_END, MACHINE_PATHS, MARKER,
                                   NO_FILE, NO_HEADING, NO_NOTE, NXT, REL, ReleaseRepo, UNTRACKED,
                                   two_headings)


class SectionsTest(unittest.TestCase):  # P6-AC-016: only our sections change
    def test_the_readme_and_the_changelog(self):
        release = load_tool("release")
        begin, end = release.README_BEGIN, release.README_END
        self.assertEqual(release.replace_section("", begin, end, "body\n"),
                         f"{begin}\nbody\n{end}\n")
        self.assertEqual(release.replace_section("Intro.", begin, end, "body\n"),
                         f"Intro.\n\n{begin}\nbody\n{end}\n")
        self.assertEqual(release.replace_section(f"a\n{begin}\nold\n{end}\nz\n", begin, end,
                                                 "new\n"), f"a\n{begin}\nnew\n{end}\nz\n")
        log = release.changelog("# Changes\n\n- theirs\n", f"- {REL} (stable): engine abc")
        self.assertTrue(log.startswith("# Changes\n\n- theirs\n\n"))
        log = release.changelog(log, f"- {NXT} (stable): engine def")
        self.assertIn(f"## modsys\n\n- {NXT} (stable): engine def\n- {REL} (stable): engine "
                      "abc\n", log)
        self.assertEqual(log.count(release.LOG_BEGIN), 1)

    def test_a_crlf_file_keeps_its_line_endings(self):
        release = load_tool("release")
        begin, end = release.README_BEGIN, release.README_END
        self.assertEqual(release.replace_section("Intro.\r\n", begin, end, "a\n\nb\n"),
                         f"Intro.\r\n\r\n{begin}\r\na\r\n\r\nb\r\n{end}\r\n")
        self.assertEqual(release.replace_section(f"a\r\n{begin}\r\nold\r\n{end}\r\nz\r\n",
                                                 begin, end, "new\n"),
                         f"a\r\n{begin}\r\nnew\r\n{end}\r\nz\r\n")
        log = release.changelog("# Changes\r\n\r\n- theirs\r\n", f"- {REL} (dev): engine abc")
        log = release.changelog(log, f"- {NXT} (dev): engine def")
        self.assertEqual(log, "# Changes\r\n\r\n- theirs\r\n\r\n"
                              f"{release.LOG_BEGIN}\r\n## modsys\r\n\r\n- {NXT} (dev): engine "
                              f"def\r\n- {REL} (dev): engine abc\r\n{release.LOG_END}\r\n")

    def test_damaged_markers_fail_naming_the_file(self):
        release = load_tool("release")
        for begin, end, where in ((release.README_BEGIN, release.README_END, "README.md"),
                                  (release.LOG_BEGIN, release.LOG_END, "CHANGELOG.md")):
            for text in (f"a\n{begin}\nold\n\n## theirs\n", f"a\nold\n{end}\n## theirs\n",
                         f"{begin}\nx\n{end}\n\n{begin}\ny\n{end}\n",
                         f"{begin}\nx\n{end}\ny\n{end}\n", f"{end}\nintro\n{begin}\nx\n"):
                with self.subTest(file=where, text=text):
                    with self.assertRaises(release.Failed) as caught:
                        if where == "README.md":
                            release.replace_section(text, begin, end, "new\n")
                        else:
                            release.changelog(text, f"- {REL} (dev): engine abc")
                    self.assertIn(f"{where}: the markers of the modsys section are damaged",
                                  str(caught.exception))


class NotesTest(unittest.TestCase):  # P61-AC-021, 022, 031, 036 (D6, SI-P61-9/10): pure parts
    def setUp(self):
        self.r = load_tool("release")

    def refused(self, text: str | None, channel: str = "stable") -> str:
        with self.assertRaises(self.r.Refused) as caught:
            self.r.pending_notes(text, channel)
        return str(caught.exception)

    def test_the_unreleased_section(self):
        text = ("# Changelog\n\n## [Unreleased]\n\n### Added\n\n- One.\n  more of one\n"
                "<!-- a comment\n- not a note\n-->\n* Two. <!-- why -->\n\n"
                "## [0.0.1] - 2026-01-01\n\n- Old.\n")
        notes = ["### Added", "- One.", "  more of one", "* Two. <!-- why -->"]  # the comment
        self.assertEqual(self.r.unreleased(text), (2, notes))  # LINES gone, inline text kept
        for channel in ("stable", "dev"):
            self.assertEqual(self.r.pending_notes(text, channel), notes)
        probe = ["- `lint` skips lines that start with `<!--`.",  # fix round 1: a `<!--` inside
                 "- `agents-md` keeps text outside its `<!-- modsys:begin -->` marker.",  # text
                 "- Second fix."]  # opens no comment — three notes, verbatim
        text = "## [Unreleased]\n\n" + "\n".join(probe) + "\n\n## [0.0.1] - 2026-01-01\n"
        for channel in ("stable", "dev"):
            self.assertEqual(self.r.pending_notes(text, channel), probe)
        block = ("## [Unreleased]\n\n  <!--\n- not a note\n  still the comment\n-->\n"
                 "- Kept.\n<!-- one line --> \n<!-- open to the end\n- gone\n")
        self.assertEqual(self.r.unreleased(block), (0, ["- Kept."]))  # comment lines, dropped
        self.assertEqual(self.r.unreleased("## [Unreleased]\r\n- a\r\n### Sub\r\n- b"),
                         (0, ["- a", "### Sub", "- b"]))  # `### ` does not end it; the file does
        self.assertEqual(self.r.unreleased("# Changelog\n\n## [0.0.1] - 2026-01-01\n\n- a\n"),
                         (None, []))

    def test_empty_is_no_item_line(self):  # SI-P61-10
        for body in ("", "\n\n\n", "\n<!-- the notes of the next release -->\n\n",
                     "\n<!--\n- a template line\n-->\n\n", "\n### Added\n\n### Fixed\n\n",
                     "\n### Added\n<!-- none yet -->\n\n"):
            text = f"# Changelog\n\n## [Unreleased]\n{body}## [0.0.1] - 2026-01-01\n\n- Old.\n"
            with self.subTest(body=body):
                self.assertEqual(self.refused(text), NO_NOTE)
                self.assertEqual(self.r.pending_notes(text, "dev"), [])  # dev: no notes yet
        for item in ("- One.", "* One."):
            text = f"## [Unreleased]\n\n{item}\n\n## [0.0.1] - 2026-01-01\n"
            self.assertEqual(self.r.pending_notes(text, "stable"), [item])

    def test_no_heading_two_headings_no_file(self):  # P61-AC-031
        self.assertEqual(self.refused("# Changelog\n\n## [0.0.1] - 2026-01-01\n\n- a\n"),
                         NO_HEADING)
        self.assertEqual(self.r.pending_notes("# Changelog\n", "dev"), [])
        two = "# Changelog\n\n## [Unreleased]\n\n- a\n\n## [Unreleased]\r\n\n- b\n"
        three = "## [Unreleased]\n- a\n## [Unreleased]\n- b\n## [Unreleased]\n"
        for channel in ("stable", "dev"):  # ambiguous on either channel: never a guess
            self.assertEqual(self.refused(two, channel), two_headings(2, "3 and 7"))
            self.assertEqual(self.refused(three, channel), two_headings(3, "1, 3 and 5"))
        self.assertEqual(self.refused(None), NO_FILE)
        self.assertEqual(self.r.pending_notes(None, "dev"), [])
        marked = ("## [Unreleased]\n\n- One.\n- `<!-- modsys:changelog:end -->` closes our "
                  "section.\n")
        for channel in ("stable", "dev"):  # fix round 1: never a damaged publish section
            self.assertEqual(self.refused(marked, channel), MARKER)
        self.assertEqual(self.r.pending_notes(  # a comment LINE holding it is dropped, never
            "## [Unreleased]\n<!-- modsys:changelog:end -->\n- One.\n", "stable"),  # published
            ["- One."])
        for message in (NO_NOTE, NO_HEADING, NO_FILE, UNTRACKED, MARKER,
                        two_headings(2, "3 and 7")):
            self.assertIn("CHANGELOG.md", message)  # P61-AC-036: both named
            self.assertIn("[Unreleased]", message)

    def test_the_release_commit_dates_the_section(self):  # P61-AC-021, AC-031 (CRLF)
        text = ("# Changelog\n\nIntro.\n\n## [Unreleased]\n\n- One.\n- Two.\n\n"
                "## [0.0.1] - 2026-01-01\n\n- Old.\n")
        want = text.replace("## [Unreleased]\n\n", f"## [Unreleased]\n\n## [{REL}] - {DATE}\n\n")
        self.assertEqual(self.r.dated(text, REL, DATE), want)
        self.assertEqual(self.r.dated(text.replace("\n", "\r\n"), REL, DATE),
                         want.replace("\n", "\r\n"))
        with tempfile.TemporaryDirectory() as tmp:  # the release's own read and write, as bytes
            root = Path(tmp)
            (root / "CHANGELOG.md").write_bytes(text.replace("\n", "\r\n").encode())
            self.assertEqual(self.r.date_notes(root, REL, DATE), ["- One.", "- Two."])
            self.assertEqual((root / "CHANGELOG.md").read_bytes(),
                             want.replace("\n", "\r\n").encode())

    def test_the_publish_entry(self):  # P61-AC-021, AC-022
        r, dev = self.r, f"{REL}-dev.h0123abcd"
        self.assertEqual(r.log_entry(REL, "stable", "abc1234", ["- One.", "- Two."]),
                         f"- {REL} (stable): engine abc1234\n  - One.\n  - Two.")
        self.assertEqual(r.log_entry(dev, "dev", "abc1234", ["- One."]),
                         f"- {dev} (dev): engine abc1234\n  - One.")
        self.assertEqual(r.log_entry(dev, "dev", "abc1234", []),
                         f"- {dev} (dev): engine abc1234\n  no notes yet")
        log = r.changelog("# Changes\r\n\r\n- theirs\r\n",
                          r.log_entry(REL, "stable", "abc", ["- One.", "### Fixed", "- Two."]))
        log = r.changelog(log, r.log_entry(NXT, "stable", "def", ["- Three."]))
        self.assertEqual(log, "# Changes\r\n\r\n- theirs\r\n\r\n"  # the newest first, CRLF kept
                              f"{LOG_BEGIN}\r\n## modsys\r\n\r\n- {NXT} (stable): engine def\r\n"
                              f"  - Three.\r\n- {REL} (stable): engine abc\r\n  - One.\r\n"
                              f"  ### Fixed\r\n  - Two.\r\n{LOG_END}\r\n")

    def test_the_date(self):  # SI-P61-9
        r = self.r
        with mock.patch.dict(os.environ, {"MODSYS_RELEASE_DATE": DATE}):
            self.assertEqual(r.release_date(), DATE)
        for bad in ("2026-02-30", "2026-13-01", "20261015", "2026-1-5", "2026-10-15T00:00",
                    "tomorrow"):
            with self.subTest(value=bad), mock.patch.dict(os.environ,
                                                          {"MODSYS_RELEASE_DATE": bad}):
                with self.assertRaises(r.Refused) as caught:
                    r.release_date()
                self.assertEqual(str(caught.exception),
                                 f"MODSYS_RELEASE_DATE={bad!r}: not a date YYYY-MM-DD")
        for unset in ({"MODSYS_RELEASE_DATE": ""}, {}):
            with mock.patch.dict(os.environ, unset):
                if not unset:
                    os.environ.pop("MODSYS_RELEASE_DATE", None)
                before = datetime.date.today().isoformat()
                got = r.release_date()
                after = datetime.date.today().isoformat()
            self.assertIn(got, (before, after))  # the local date (across midnight: either)


class NotesRunTest(ReleaseRepo):  # P61-AC-022, 031, 036: the notes through whole runs
    def test_a_dev_release_writes_the_pending_notes(self):  # P61-AC-022, AC-031 (no file)
        one = CHANGELOG.replace("- Second planted note.\n", "")
        self.commit(self.engine, "CHANGELOG.md", one, "one note")
        want = []
        for case in ("one line", "empty", "no file"):
            if case != "one line":
                self.change_a_skill()  # a new build: the same one is nothing to release
            if case == "empty":
                self.commit(self.engine, "CHANGELOG.md",
                            one.replace("- First planted note.\n", ""), "no note")
            if case == "no file":
                git(self.engine, "rm", "-q", "--", "CHANGELOG.md")
                git(self.engine, "commit", "-q", "-m", "no changelog")
            path = self.engine / "CHANGELOG.md"
            notes = path.read_bytes() if path.exists() else None
            engine = self.state(self.engine)
            proc = self.release("dev")
            self.assert_ok(proc)
            self.assertEqual(self.state(self.engine), engine)  # dev changes nothing here
            self.assertEqual(path.read_bytes() if path.exists() else None, notes)
            self.assertIn("; CHANGELOG.md [Unreleased]: " + (
                "1 line\n" if case == "one line" else "no notes yet\n"), proc.stdout)
            version = re.search(r"done: modsys (\S+) \(dev\)", proc.stdout).group(1)
            want.insert(0, (version, "dev", git(self.engine, "rev-parse", "HEAD"),
                            ["- First planted note."] if case == "one line"
                            else ["no notes yet"]))
        self.assertEqual(self.entries("dev"), want)

    def index(self) -> list:
        return [(repo / ".git/index").read_bytes() if (repo / ".git/index").exists() else None
                for repo in (self.engine, self.pub)]

    def refused_at_step_1(self, message: str, env: dict | None = None,
                          channel: str = "stable") -> None:
        before, index = self.both(), self.index()
        proc = self.release(channel, env={"FAKE_GUARD_ERROR": "1", **(env or {})})
        self.assertEqual((proc.returncode, proc.stderr), (2, f"release.py: error: {message}\n"))
        market = "modsys" if channel == "stable" else "modsys-dev"
        self.assertEqual(proc.stdout, f"release modsys: channel {channel} (marketplace {market}), "
                                      f"publish repo {self.pub}\n")  # no step finished
        self.assertEqual((self.both(), self.index()), (before, index))
        self.assertEqual(list(self.tmpdir.iterdir()), [])
        self.assertFalse((self.base / "claude.log").exists())  # no build, no validate

    def test_stable_without_notes_is_refused_before_any_work(self):  # P61-AC-036, AC-031
        # FAKE_GUARD_ERROR: had the guard run (or the suite after it), stderr would say so
        self.refused_at_step_1("MODSYS_RELEASE_DATE='2026-02-30': not a date YYYY-MM-DD",
                               env={"MODSYS_RELEASE_DATE": "2026-02-30"})
        head = "# Changelog\n\nAll notable changes to this copy are documented in this file.\n\n"
        old = "## [0.0.1] - 2026-01-01\n\n- The first planted release.\n"
        for case, text, message in (
                ("blank lines and a comment",
                 head + "## [Unreleased]\n\n\n<!-- the notes of the next release -->\n\n" + old,
                 NO_NOTE),
                ("two headings", head + "## [Unreleased]\n\n- a\n\n## [Unreleased]\n\n- b\n\n"
                 + old, two_headings(2, "5 and 9")),
                ("no heading", head + old, NO_HEADING),
                ("no file", None, NO_FILE)):
            with self.subTest(case=case):
                if text is None:
                    git(self.engine, "rm", "-q", "--", "CHANGELOG.md")
                    git(self.engine, "commit", "-q", "-m", case)
                else:
                    self.commit(self.engine, "CHANGELOG.md", text, case)
                self.refused_at_step_1(message)
        self.commit(self.engine, "CHANGELOG.md", CHANGELOG.replace(  # fix round 1: a note
            "- Second planted note.\n", "- `<!-- modsys:changelog:end -->` closes our "
            "section.\n"), "a note holding the marker")
        for channel in ("stable", "dev"):  # either would write it into the publish section
            self.refused_at_step_1(MARKER, channel=channel)
        git(self.engine, "rm", "-q", "--cached", "--", "CHANGELOG.md")
        git(self.engine, "commit", "-q", "-m", "untracked")
        (self.engine / "CHANGELOG.md").write_text(CHANGELOG)  # notes, but git ignores the file
        (self.engine / ".git/info/exclude").write_text("CHANGELOG.md\n")
        self.refused_at_step_1(UNTRACKED)

    def test_a_crlf_changelog_stays_crlf(self):  # P61-AC-031
        crlf = CHANGELOG.replace("\n", "\r\n")
        (self.engine / "CHANGELOG.md").write_bytes(crlf.encode())
        git(self.engine, "commit", "-q", "-am", "CRLF")
        self.assert_ok(self.release("stable"))
        dated = crlf.replace("## [Unreleased]\r\n\r\n",
                             f"## [Unreleased]\r\n\r\n## [{REL}] - {DATE}\r\n\r\n", 1).encode()
        blob = subprocess.run(  # bytes: the helper's text mode would turn CRLF into LF
            ["git", "-C", str(self.engine), "show", "HEAD~1:CHANGELOG.md"], capture_output=True,
            check=True, env={k: v for k, v in os.environ.items()
                             if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}).stdout
        self.assertEqual((blob, (self.engine / "CHANGELOG.md").read_bytes()), (dated, dated))
        self.assertNotIn(b"\r", (self.pub / "CHANGELOG.md").read_bytes())  # the publish file's
        self.assertEqual(self.entries("stable")[0][3],  # own line endings, no CR in a note
                         ["- First planted note.", "- Second planted note."])


class ChangelogFileTest(unittest.TestCase):  # P61-AC-020: the engine's own CHANGELOG.md
    HEADER = ("# Changelog\n\nAll notable changes to this project will be documented in this "
              "file.\n\nThe format is based on [Keep a Changelog]"
              "(https://keepachangelog.com/en/1.1.0/),\nand this project adheres to [Semantic "
              "Versioning](https://semver.org/spec/v2.0.0.html).\n\n")
    BACKFILL = "## [0.1.0] - 2026-10-01"  # the first release (D6): always the last section

    def setUp(self):
        self.text = (ENGINE / "CHANGELOG.md").read_text(encoding="utf-8")

    def test_keep_a_changelog_down_to_the_first_release(self):
        self.assertTrue(self.text.startswith(self.HEADER + "## [Unreleased]\n"),
                        self.text[:400])
        heads = [line for line in self.text.split("\n") if line.startswith("## ")]
        self.assertEqual((heads[0], heads[-1]), ("## [Unreleased]", self.BACKFILL))
        for head in heads[1:]:  # every release after it, dated by its release commit
            self.assertRegex(head, r"^## \[\d+\.\d+\.\d+\] - \d{4}-\d{2}-\d{2}$")
        first = self.text.split(self.BACKFILL + "\n", 1)[1].split("\n")
        self.assertTrue(any(line.startswith("- ") for line in first), first)
        self.assertEqual(load_tool("release").unreleased(self.text)[0],
                         self.HEADER.count("\n"))  # the one the release reads
        self.assertNotIn("\r", self.text)

    def test_no_host_organisation_slug_or_machine_path(self):  # D13
        self.assertEqual(sorted(set(re.findall(r"https?://[^\s)]+", self.text))),
                         ["https://keepachangelog.com/en/1.1.0/",
                          "https://semver.org/spec/v2.0.0.html"])
        for bad in (*MACHINE_PATHS, "github.com", "example-org", "<owner>"):
            self.assertNotIn(bad, self.text)


if __name__ == "__main__":
    unittest.main()
