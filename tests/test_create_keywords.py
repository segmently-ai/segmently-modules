"""`create --keywords a,b,c`: comma-separated keywords, merged after --keyword values."""
import json
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
