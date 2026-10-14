import tempfile
import unittest

from tests.helpers import FIXTURE, copy_fixture, mutate_registry, run, run_json

R = ("--root", str(FIXTURE))


def rows(text, *extra, root=R):
    code, env, _ = run_json("match", text, *root, *extra)
    return code, env["data"]


class MatchTest(unittest.TestCase):
    def test_keywords_plus_combination_bonus(self):
        self.assertEqual(rows("add isbn to book listing"),
                         (0, [{"module": "catalog", "score": 8,
                               "keywords": ["book", "isbn"], "negative": []}]))

    def test_submodule_rows_and_tie_ordering(self):
        _, data = rows("refund a partial refund for an order")
        self.assertEqual([(r["module"], r["score"]) for r in data],
                         [("payments", 6), ("payments/refunds", 6), ("checkout", 3)])

    def test_negative_phrase_suppresses_module(self):
        self.assertEqual(rows("book search via elasticsearch"), (0, []))

    def test_legacy_flat_negative_list(self):
        self.assertEqual(rows("order of operations bug in cart"), (0, []))

    def test_non_word_edge_keyword_matches(self):
        _, data = rows("convert the book to .epub")
        self.assertEqual(data[0]["keywords"], ["book", ".epub"])

    def test_cyrillic_text(self):
        _, data = rows("добавить isbn в каталог")
        self.assertEqual([r["module"] for r in data], ["catalog"])
        self.assertEqual(rows("только русский текст без ключей"), (0, []))

    def test_flat_required_combinations_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            mutate_registry(root, lambda d: d["modules"]["checkout"].update(
                {"required_combinations": ["total"]}))
            _, data = rows("fix cart total", root=("--root", str(root)))
        self.assertEqual(data[0], {"module": "checkout", "score": 5,
                                   "keywords": ["cart"], "negative": []})

    def test_top_and_text_output(self):
        _, data = rows("refund a partial refund for an order", "--top", "1")
        self.assertEqual([r["module"] for r in data], ["payments"])
        code, out, _ = run("match", "add isbn to book listing", *R)
        self.assertEqual(code, 0)
        self.assertIn("catalog", out)


class MatchGapTest(unittest.TestCase):  # AC-016 … AC-019
    def _root(self, tmp, config=None, mutation=None):
        root = copy_fixture(tmp)
        if config:
            (root / ".segmently-modules" / "config.toml").write_text(config, encoding="utf-8")
        if mutation:
            mutate_registry(root, mutation)
        return ("--root", str(root))

    def test_keyword_weight_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp, "[match]\nkeyword_weight = 5\n")
            _, data = rows("add isbn to book listing", root=root)
        self.assertEqual(data[0]["score"], 12)

    def test_negative_weight_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp, "[match]\nnegative_weight = -1\n")
            _, data = rows("book search via elasticsearch", "--min-score", "2", root=root)
        self.assertEqual(data, [{"module": "catalog", "score": 2, "keywords": ["book"],
                                 "negative": ["elasticsearch"]}])

    def test_min_score_boundary(self):
        self.assertEqual([r["score"] for r in rows("добавить isbn")[1]], [3])
        self.assertEqual(rows("добавить isbn", "--min-score", "4"), (0, []))

    def test_combination_without_keyword_hit_is_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp, mutation=lambda d: d["modules"]["checkout"].update(
                required_combinations=[["total", "tax"]]))
            self.assertEqual(rows("total tax", "--min-score", "0", root=root), (0, []))

    def test_top_boundaries(self):
        q = "refund a partial refund for an order"
        self.assertEqual(rows(q, "--top", "0"), (0, []))
        self.assertEqual(len(rows(q, "--top", "100")[1]), 3)

    def test_non_word_edge_terms_are_edge_aware(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp, mutation=lambda d: d["modules"]["catalog"]["keywords"].extend(
                ["c++", "shop/"]))
            _, data = rows("port to c++ now", root=root)
            self.assertEqual(data[0]["keywords"], ["c++"])
            _, data = rows("see shop/catalog page", root=root)
            self.assertEqual(data[0]["keywords"], ["catalog", "shop/"])

    def test_word_boundary_and_case(self):
        self.assertEqual(rows("list all bookshelves"), (0, []))  # a longer word never matches
        self.assertEqual([r["module"] for r in rows("ISBN lookup")[1]], ["catalog"])


class NormalizeTest(unittest.TestCase):
    """`[match] normalize = "suffix"` (the default): routing ignores the endings -s, -es, -ies,
    -ed and -ing on both sides, so one form of a word is enough (FoodMate init, 2026-10-14:
    writers listed every form and drowned the registry in noise)."""

    def _root(self, tmp, config=None, mutation=None):
        root = copy_fixture(tmp)
        if config:
            (root / ".segmently-modules" / "config.toml").write_text(config, encoding="utf-8")
        if mutation:
            mutate_registry(root, mutation)
        return ("--root", str(root))

    def test_word_keys_meet_for_the_forms_of_one_word(self):
        from segmently_modules.words import word_keys
        for forms in (("save", "saves", "saved", "saving"),
                      ("charge", "charges", "charged", "charging"),
                      ("stop", "stops", "stopped", "stopping"),
                      ("copy", "copies", "copied", "copying"), ("movie", "movies"),
                      ("entry", "entries"), ("status", "statuses"), ("class", "classes"),
                      ("box", "boxes"), ("match", "matches", "matching"),
                      ("add", "adds", "added", "adding"), ("rate", "rating", "ratings"),
                      ("setting", "settings"), ("Book", "books", "booking"),
                      ("bill", "billing"), ("plan", "plans", "planning"), ("log", "logged")):
            with self.subTest(forms=forms):
                for form in forms[1:]:
                    self.assertTrue(word_keys(form) & word_keys(forms[0]), form)
        for a, b in (("set", "settings"), ("theme", "them"), ("themes", "them"),
                     ("note", "not"), ("stripe", "strip"), ("state", "stats"),
                     ("locale", "local"), ("news", "new"), ("string", "str"),
                     ("plane", "planning"), ("hope", "hopping"), ("evening", "even")):
            with self.subTest(apart=(a, b)):
                self.assertFalse(word_keys(a) & word_keys(b))
        for word in ("isbn", "e2e", "user_id", "каталоги", "c++", "ISBN"):  # not cut: as is
            self.assertEqual(word_keys(word), {word.lower()})

    def test_a_form_the_module_did_not_list_matches(self):
        _, data = rows("list all books")
        self.assertEqual([(r["module"], r["keywords"]) for r in data], [("catalog", ["book"])])
        _, data = rows("charging a card twice")
        self.assertEqual([r["module"] for r in data], ["payments"])
        _, data = rows("refunding the partial refunds")
        self.assertEqual([(r["module"], r["score"]) for r in data],
                         [("payments", 6), ("payments/refunds", 6)])

    def test_phrase_keywords_match_word_by_word(self):
        _, data = rows("partial refunds for an order")
        self.assertEqual(data[0]["keywords"], ["refund", "partial refund"])
        self.assertEqual(data[0]["score"], 6)

    def test_every_form_of_one_word_scores_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp, mutation=lambda d: d["modules"]["payments"].update(
                keywords=["payment", "charge", "charges", "charged", "charging"]))
            _, data = rows("charged a payment", root=root)
        self.assertEqual(data[0]["module"], "payments")
        self.assertEqual(data[0]["keywords"], ["payment", "charge", "charges", "charged",
                                               "charging"])
        self.assertEqual(data[0]["score"], 6)  # two words: payment, charge

    def test_negative_phrases_and_combinations_use_it_too(self):
        self.assertEqual(rows("books search via elasticsearch"), (0, []))
        _, data = rows("add isbn to books listings")
        self.assertEqual(data[0]["score"], 8)  # the combination book + listing still fires

    def test_non_word_keywords_stay_exact(self):
        _, data = rows("convert the books to .epub")
        self.assertEqual(data[0]["keywords"], ["book", ".epub"])
        self.assertEqual(rows("convert to .epubs"), (0, []))

    def test_normalize_none_is_the_exact_match_of_0_2_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp, "[match]\nnormalize = \"none\"\n")
            self.assertEqual(rows("list all books", root=root), (0, []))
            self.assertEqual(rows("charging a card", root=root), (0, []))
            _, data = rows("add isbn to book listing", root=root)
            self.assertEqual(data[0]["score"], 8)

    def test_a_bad_normalize_value_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp, "[match]\nnormalize = \"porter\"\n")
            code, _, err = run("match", "book", *root)
        self.assertEqual(code, 2)
        self.assertIn("[match] normalize: expected one of suffix, none", err)


if __name__ == "__main__":
    unittest.main()
