"""`create --keywords a,b,c`: comma-separated keywords, merged after --keyword values."""
import json
import shutil
import tempfile
import unittest
from unittest import mock

from tests.helpers import copy_fixture, run, run_json

DESC = ["--description", "Customer reviews of books: ratings, comments and moderation."]


class CreateKeywordsTest(unittest.TestCase):  # P32-AC-017
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        self.R = ("--root", str(self.root), "--non-interactive")

    def tearDown(self):
        self._tmp.cleanup()

    def keywords(self, *argv, name="reviews"):
        code, env, err = run_json("create", name, *argv, "--dry-run", *self.R)
        self.assertEqual((code, err), (0, ""))
        return env["data"]["entry"]["keywords"]

    def refused(self, *argv) -> str:
        code, out, err = run("create", "reviews", *DESC, *argv, "--dry-run", *self.R)
        self.assertEqual((code, out), (2, ""))
        return err

    def test_split_stripped_and_empties_dropped(self):
        self.assertEqual(self.keywords(*DESC, "--keywords", "books, isbn,,authors, shelves, loans"),
                         ["books", "isbn", "authors", "shelves", "loans"])

    def test_merged_after_keyword_values_without_duplicates(self):
        self.assertEqual(self.keywords(*DESC, "--keyword", "alpha", "--keywords", "beta,gamma",
                                       "--keywords", "beta,delta", "--keyword", "epsilon"),
                         ["alpha", "epsilon", "beta", "gamma", "delta"])

    def test_the_distinct_minimum_still_applies(self):
        self.assertIn("at least 5 distinct", self.refused("--keywords", "a,b,c,d"))
        self.assertIn("at least 5 distinct", self.refused("--keywords", "a,a,b,c,d"))
        self.assertEqual(self.keywords(*DESC, "--keywords", "a,b,c,d,e"), ["a", "b", "c", "d", "e"])
        self.assertEqual(self.keywords("--description", "Refund requests by customers.",
                                       "--parent", "checkout", "--keywords", "due", name="due"),
                         ["due"])

    def test_nothing_left_is_a_missing_answer(self):
        self.assertIn("missing answers: keywords", self.refused("--keywords", ","))

    def test_flags_replace_the_answers_file(self):
        answers = self.root / "answers.json"
        answers.write_text(json.dumps({"description": DESC[1],
                                       "keywords": ["x1", "x2", "x3", "x4", "x5"]}))
        self.assertEqual(self.keywords("--answers", str(answers), "--keywords", "k1,k2,k3,k4,k5"),
                         ["k1", "k2", "k3", "k4", "k5"])

    def test_help_names_the_comma_rule(self):
        out = " ".join(run("create", "--help")[1].split())
        self.assertIn("--keywords A,B,C", out)
        self.assertIn("a keyword that contains a comma needs --keyword", out)


NEUTRAL = ["shelf mark", "loan period", "reading room", "due date", "front desk"]


EXACT = "[match]\nnormalize = \"none\"\n"  # the plural hints: exact matching only


def exact(root):
    (root / ".segmently-modules" / "config.toml").write_text(EXACT, encoding="utf-8")


class KeywordWarningsTest(unittest.TestCase):  # P5A-AC-006 (D0b)
    TABLE = [  # (keywords, [a needle of each warning, in keyword order]) — under `none`
        (["book"], ["has no plural 'books'"]),
        (["books"], ["has no singular 'book'"]),
        (["categories"], ["has no singular 'category'"]),
        (["boxes"], ["has no singular 'box'"]),
        (["category"], ["has no plural 'categories'"]),
        (["class"], ["has no plural 'classes'"]),
        (["book", "books"], []),
        (["api"], ["'api' is short (3 characters)"]),
        (["ui"], ["'ui' is short (2 characters)"]),
        (["isbn"], ["has no plural 'isbns'"]),
        (["data"], ["'data' is a generic word"]),
        (["Data"], ["'Data' is a generic word"]),
        ([" list "], ["' list ' is a generic word"]),
        (["helper"], ["'helper' is a generic word"]),
        (["stuff"], ["'stuff' is a generic word"]),
        (["partial refund", "BookRepository", ".epub", "v2api"], []),
    ]

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def argv(self, keywords, name="reviews", parent=None) -> list[str]:
        out = ["create", name, *DESC, *[a for k in keywords for a in ("--keyword", k)]]
        return out + (["--parent", parent] if parent else [])

    def test_the_table(self):
        exact(self.root)
        for keywords, needles in self.TABLE:
            with self.subTest(keywords=keywords):
                code, env, err = run_json(*self.argv(keywords + NEUTRAL), "--dry-run",
                                          "--non-interactive", *self.R)
                self.assertEqual((code, err), (0, ""))
                warnings = env["data"]["warnings"]
                self.assertEqual(len(warnings), len(needles), warnings)
                for warning, needle in zip(warnings, needles):
                    self.assertIn(needle, warning)
                    self.assertIn("keyword '", warning)

    GENERIC_COUNTERPARTS = [  # the plural hint never suggests a word flagged as generic
        (["utils"], []), (["helpers"], []), (["items"], []), (["lists"], []),
        (["utils", "util"], ["'util' is a generic word"]),
    ]

    def test_no_plural_hint_to_a_generic_word(self):
        exact(self.root)
        for keywords, needles in self.GENERIC_COUNTERPARTS:
            with self.subTest(keywords=keywords):
                code, env, err = run_json(*self.argv(keywords + NEUTRAL), "--dry-run",
                                          "--non-interactive", *self.R)
                self.assertEqual((code, err), (0, ""))
                warnings = env["data"]["warnings"]
                self.assertEqual(len(warnings), len(needles), warnings)
                for warning, needle in zip(warnings, needles):
                    self.assertIn(needle, warning)

    def test_warnings_never_block(self):
        keywords = ["api", "book", "data"] + NEUTRAL
        code, env, err = run_json(*self.argv(NEUTRAL), "--dry-run", "--non-interactive", *self.R)
        self.assertEqual((code, err, env["data"]["warnings"]), (0, "", []))
        for mode in (["--non-interactive"], ["--dry-run"], []):
            with self.subTest(mode=mode):
                code, out, err = run(*self.argv(keywords, name="loans"), *mode, *self.R)
                self.assertEqual(code, 0)
                self.assertEqual(err.splitlines(), [
                    l for l in err.splitlines() if l.startswith("segmently-modules: warning: ")])
                self.assertEqual(len(err.splitlines()), 2)  # short, generic: `book` is enough
                self.assertIn("loans", out)
                if "--dry-run" not in mode:
                    reg = json.loads((self.root / "modules/registry.json").read_text())
                    self.assertEqual(reg["modules"]["loans"]["keywords"], keywords)
                    (self.root / "modules/registry.json").write_text(json.dumps(
                        {**reg, "modules": {k: v for k, v in reg["modules"].items()
                                            if k != "loans"}}, indent=2) + "\n")
                    shutil.rmtree(self.root / "modules/loans")
        code, env, err = run_json(*self.argv(["api"], name="fines", parent="checkout"),
                                  "--non-interactive", *self.R)
        self.assertEqual((code, err, len(env["data"]["warnings"])), (0, "", 1))
        self.assertEqual(env["data"]["module"], "checkout/fines")

    def test_an_interactive_run_warns_after_the_prompts(self):
        answers = iter([DESC[1]])
        with mock.patch("segmently_modules.create.interactive", return_value=True), \
                mock.patch("builtins.input", lambda prompt: next(answers)):
            code, out, err = run("create", "loans", *[a for k in ["api"] + NEUTRAL
                                                       for a in ("--keyword", k)], *self.R)
        self.assertEqual(code, 0)
        self.assertEqual(err, "segmently-modules: warning: keyword 'api' is short (3 characters): it "
                              "matches many tasks — prefer a longer domain word\n")


class OneLineHintsTest(unittest.TestCase):  # P5B-AC-045 (D15(c))
    SUMMARY = ("segmently-modules: warning: {n} keyword(s) without their singular / plural form (matching "
               "is exact: add the form tasks use): {pairs} — --json lists each")
    TABLE = [  # (keywords, stderr lines, data.warnings count)
        (["books", "book"], [], 0),
        (["loans"], [SUMMARY.format(n=1, pairs="loans → loan")], 1),
        (["loans", "reviews"], [SUMMARY.format(n=2, pairs="loans → loan, reviews → review")],
         2),
        (["loans", "reviews", "fines", "shelves", "authors", "genres"],
         [SUMMARY.format(n=6, pairs="loans → loan, reviews → review, fines → fine and 3 more")],
         6),
        (["ui", "data", "loans", "reviews"],
         ["segmently-modules: warning: keyword 'ui' is short (2 characters): it matches many tasks — prefer "
          "a longer domain word",
          "segmently-modules: warning: keyword 'data' is a generic word: it matches many tasks — prefer a "
          "domain word", SUMMARY.format(n=2, pairs="loans → loan, reviews → review")], 4),
    ]

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        exact(self.root)
        self.R = ("--root", str(self.root), "--dry-run", "--non-interactive")

    def tearDown(self):
        self._tmp.cleanup()

    def test_the_table(self):
        for keywords, lines, count in self.TABLE:
            argv = ["create", "loans", *DESC,
                    *[a for k in keywords + NEUTRAL for a in ("--keyword", k)]]
            with self.subTest(keywords=keywords):
                code, out, err = run(*argv, *self.R)
                self.assertEqual((code, err.splitlines()), (0, lines))
                self.assertIn("would register  loans", out)
                code, env, err = run_json(*argv, *self.R)
                self.assertEqual((code, err, len(env["data"]["warnings"])), (0, "", count))

    def test_data_warnings_keep_one_entry_per_keyword(self):
        keywords = ["ui", "data", "loans", "reviews"] + NEUTRAL
        argv = ["create", "loans", *DESC, *[a for k in keywords for a in ("--keyword", k)]]
        warnings = run_json(*argv, *self.R)[1]["data"]["warnings"]
        self.assertEqual(warnings, [
            "keyword 'ui' is short (2 characters): it matches many tasks — prefer a longer "
            "domain word",
            "keyword 'data' is a generic word: it matches many tasks — prefer a domain word",
            "keyword 'loans' has no singular 'loan': matching is exact, so a task that says "
            "'loan' does not match it — add it if tasks use it",
            "keyword 'reviews' has no singular 'review': matching is exact, so a task that says "
            "'review' does not match it — add it if tasks use it"])


class NormalizedHintsTest(unittest.TestCase):  # 0.3.0: routing ignores word endings
    """Under `[match] normalize = "suffix"` (the default) `create` never asks for another form:
    it says when a keyword is a form of an earlier one, warns about a generic word in any of its
    forms (never a word of the module's own name) and about more distinct words than `[create]
    max_keywords`."""
    FORMS = ("segmently-modules: warning: {n} keyword(s) that are a form of another keyword "
             "(matching ignores word endings: one form is enough): {pairs} — --json lists each")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = copy_fixture(self._tmp.name)
        self.R = ("--root", str(self.root), "--dry-run", "--non-interactive")

    def tearDown(self):
        self._tmp.cleanup()

    def create(self, name, keywords, json_out=True):
        argv = ["create", name, *DESC, *[a for k in keywords + NEUTRAL for a in ("--keyword", k)]]
        if json_out:
            code, env, err = run_json(*argv, *self.R)
            self.assertEqual((code, err), (0, ""))
            return env["data"]["warnings"]
        code, _, err = run(*argv, *self.R)
        self.assertEqual(code, 0)
        return err.splitlines()

    def test_one_form_is_enough(self):
        self.assertEqual(self.create("loans", ["book", "loan", "fine"]), [])
        self.assertEqual(self.create("loans", ["loan", "loans", "loaned", "lending"]), [
            "keyword 'loans' is a form of 'loan': matching ignores word endings — one form is "
            "enough",
            "keyword 'loaned' is a form of 'loan': matching ignores word endings — one form is "
            "enough"])
        self.assertEqual(self.create("loans", ["loan", "loans", "loaned"], json_out=False),
                         [self.FORMS.format(n=2, pairs="loans → loan, loaned → loan")])

    def test_generic_in_any_form_but_not_in_the_own_name(self):
        warnings = self.create("loans", ["deletes", "users", "module"])
        self.assertEqual([w.split("'")[1] for w in warnings], ["deletes", "users", "module"])
        self.assertTrue(all("is a generic word" in w for w in warnings))
        self.assertEqual(self.create("module-tools", ["module", "modules"]), [
            "keyword 'modules' is a form of 'module': matching ignores word endings — one form "
            "is enough"])

    def test_more_words_than_max_keywords(self):
        words = [f"shelf{chr(97 + i // 26)}{chr(97 + i % 26)}" for i in range(36)]
        self.assertEqual(self.create("loans", words[:35]), [])  # + 5 neutral phrases: 40
        (self.root / ".segmently-modules" / "config.toml").write_text(
            "[create]\nmax_keywords = 41\n", encoding="utf-8")
        self.assertEqual(self.create("loans", words), [])
        (self.root / ".segmently-modules" / "config.toml").write_text(
            "[create]\nmax_keywords = 40\n", encoding="utf-8")
        self.assertEqual(self.create("loans", words), [
            "41 keywords > [create] max_keywords 40: keep the words that point to this module "
            "and no other"])
        self.assertEqual(self.create("loans", words + [w + "s" for w in words[:3]])[-1][:3],
                         "41 ")  # forms of one word count once

    def test_a_bad_max_keywords_is_refused(self):
        (self.root / ".segmently-modules" / "config.toml").write_text(
            "[create]\nmax_keywords = 0\n", encoding="utf-8")
        code, _, err = run("create", "loans", *DESC, "--keyword", "loan", *self.R)
        self.assertEqual(code, 2)
        self.assertIn("[create] max_keywords: expected an integer >= 1, got 0", err)


if __name__ == "__main__":
    unittest.main()
