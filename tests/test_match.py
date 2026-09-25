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
            (root / ".modsys" / "config.toml").write_text(config, encoding="utf-8")
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
        self.assertEqual(rows("list all books"), (0, []))
        self.assertEqual([r["module"] for r in rows("ISBN lookup")[1]], ["catalog"])


if __name__ == "__main__":
    unittest.main()
