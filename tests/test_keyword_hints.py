"""Keyword hints: near misses when no module reaches min_score (`context`, `match` text), and
`show` listing a target's own keywords."""
import tempfile
import unittest

from segmently_modules.match import near_misses
from tests.helpers import make_repo, run, run_json

WEIGHTS = {"keyword_weight": 3, "combination_weight": 2, "negative_weight": -5,
           "normalize": "none"}  # the loose rule itself: forms are exact hits by default
EXACT = "[match]\nnormalize = \"none\"\n"
# (registry keyword, task text, the near entry expected for module `todo`, or None)
LOOSE = [
    ("reminder", "send reminders daily", {"keyword": "reminder", "task_word": "reminders"}),
    ("schedule", "scheduling jobs", {"keyword": "schedule", "task_word": "scheduling"}),
    ("auth", "authentication flow", {"keyword": "auth", "task_word": "authentication"}),
    ("task", "tasks list", {"keyword": "task", "task_word": "tasks"}),
    ("remove", "remote backups", None),
    ("user", "useful output", None),
    ("api", "apis", None),
    ("tags", "tag the item", None),
    ("due date", "overdue dates", {"keyword": "due date", "task_word": "dates"}),
    ("Reminder", "REMINDERS", {"keyword": "Reminder", "task_word": "reminders"}),
    (".epub", "export epubs", {"keyword": ".epub", "task_word": "epubs"}),
]


class LooseMatchTest(unittest.TestCase):  # P32-AC-001
    def test_loose_match_table(self):
        for keyword, text, expected in LOOSE:
            with self.subTest(keyword=keyword, text=text), tempfile.TemporaryDirectory() as tmp:
                root = make_repo(tmp, {"todo": [keyword]}, config=EXACT)
                code, env, err = run_json("context", "--task", text, "--root", str(root))
                self.assertEqual((code, err, env["data"]["modules"]), (0, "", []))
                rows = env["data"]["near_misses"]
                if expected is None:
                    self.assertEqual(rows, [])
                else:
                    self.assertEqual(rows, [{"module": "todo", "score": 0, "keywords": [],
                                             "near": [expected]}])

    def test_an_exact_hit_is_never_also_a_near_miss(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp, {"todo": ["reminder", "reminders"]},
                             config=EXACT + "min_score = 4\n")
            _, env, _ = run_json("context", "--task", "reminder at noon", "--root", str(root))
        self.assertEqual(env["data"]["near_misses"],
                         [{"module": "todo", "score": 3, "keywords": ["reminder"],
                           "near": [{"keyword": "reminders", "task_word": "reminder"}]}])


    def test_under_the_default_a_form_is_a_hit_and_a_prefix_still_a_hint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp, {"todo": ["reminder"], "auth": ["auth"]})
            _, env, _ = run_json("context", "--task", "send reminders daily", "--root", str(root))
            self.assertEqual(([m["module"] for m in env["data"]["modules"]],
                              env["data"]["near_misses"]), (["todo"], []))
            _, env, _ = run_json("context", "--task", "authentication flow", "--root", str(root))
            self.assertEqual(env["data"]["near_misses"],
                             [{"module": "auth", "score": 0, "keywords": [],
                               "near": [{"keyword": "auth", "task_word": "authentication"}]}])


class NearMissRowsTest(unittest.TestCase):  # P32-AC-002
    def rows(self, modules, text, top=8, min_score=3):
        return near_misses(modules, text, WEIGHTS, top, min_score)

    def test_nothing_when_a_target_matched(self):
        modules = {"todo": {"keywords": ["reminder", "task"]}}
        self.assertEqual(self.rows(modules, "a reminder for tasks"), [])

    def test_negative_keyword_pulls_an_exact_hit_below_min_score(self):
        modules = {"todo": {"keywords": ["reminder"], "negative_keywords": ["reminder spam"]}}
        self.assertEqual(self.rows(modules, "reminder spam filter"),
                         [{"module": "todo", "score": -2, "keywords": ["reminder"], "near": []}])

    def test_no_exact_and_no_loose_match(self):
        self.assertEqual(self.rows({"todo": {"keywords": ["reminder"]}}, "billing export"), [])

    def test_a_child_is_its_own_row(self):
        modules = {"payments": {"keywords": ["payment", "charge", "invoice"],
                                "submodules": {"refunds": {"keywords": ["refund"]}}}}
        self.assertEqual(self.rows(modules, "refunding customers"),
                         [{"module": "payments/refunds", "score": 0, "keywords": [],
                           "near": [{"keyword": "refund", "task_word": "refunding"}]}])

    def test_top_and_order(self):
        modules = {f"m{i}": {"keywords": ["reminder"]} for i in range(1, 9)}
        modules["m9"] = {"keywords": ["reminder", "schedule"]}
        rows = self.rows(modules, "reminders and scheduling")
        self.assertEqual([r["module"] for r in rows],
                         ["m9", "m1", "m2", "m3", "m4", "m5", "m6", "m7"])
        self.assertEqual(self.rows(modules, "reminders and scheduling", top=0), [])

    def test_garbage_keywords_are_ignored(self):
        modules = {"todo": {"keywords": ["reminder", 5, None]}, "bad": "oops",
                   "lists": {"keywords": "reminder"}}
        self.assertEqual([r["module"] for r in self.rows(modules, "reminders")], ["todo"])


class WhereTheHintAppearsTest(unittest.TestCase):  # P32-AC-003
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_repo(self._tmp.name, {"todo": ["reminder", "task"]}, config=EXACT)
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def test_context_json_and_text(self):
        _, env, _ = run_json("context", "--task", "send reminders", *self.R)
        self.assertEqual(env["data"]["near_misses"][0]["module"], "todo")
        _, env, _ = run_json("context", "--task", "send a reminder", *self.R)
        self.assertEqual(env["data"]["near_misses"], [])
        code, out, _ = run("context", "--task", "send reminders", *self.R)
        lines = out.splitlines()
        self.assertEqual(code, 0)
        self.assertEqual(lines[0], "no module matched (try domain terms, or: segmently-modules list)")
        self.assertTrue(lines[1].startswith("near  todo"), lines)
        self.assertIn("reminder ~ reminders", lines[1])
        self.assertIn("segmently-modules show todo", lines[2])

    def test_match_text_hint_and_json_unchanged(self):
        code, out, _ = run("match", "send reminders", *self.R)
        lines = out.splitlines()
        self.assertEqual(code, 0)
        self.assertEqual(lines[0], "no keyword matches (try rephrasing with domain terms, or use: "
                                   "list)")
        self.assertIn("reminder ~ reminders", lines[1])
        self.assertIn("segmently-modules show todo", lines[2])
        self.assertEqual(run_json("match", "send reminders", *self.R)[1],
                         {"schema": "segmently-modules.match/1", "data": []})


class ShowKeywordsTest(unittest.TestCase):  # P32-AC-004
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_repo(self._tmp.name, {
            "books": ["books", "isbn", "authors"], "payments": ["payment", "charge"],
            "payments/refunds": ["refund"], "plain": []})
        self.R = ("--root", str(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def keywords(self, target):
        code, env, err = run_json("show", target, *self.R)
        self.assertEqual((code, err), (0, ""))
        return env["data"]["keywords"]

    def test_each_target_shows_its_own_keywords(self):
        self.assertEqual(self.keywords("books"), ["books", "isbn", "authors"])
        self.assertEqual(self.keywords("payments/refunds"), ["refund"])
        self.assertEqual(self.keywords("payments"), ["payment", "charge"])
        self.assertEqual(self.keywords("plain"), [])

    def test_text_line_after_the_description(self):
        lines = run("show", "books", *self.R)[1].splitlines()
        self.assertEqual(lines[1:3], ["  The books module.", "  keys  books, isbn, authors"])
        self.assertNotIn("keys", run("show", "plain", *self.R)[1])

    def test_garbage_keywords_read_as_empty(self):
        import json
        path = self.root / "modules" / "registry.json"
        data = json.loads(path.read_text())
        data["modules"]["books"]["keywords"] = "books"
        data["modules"]["plain"]["keywords"] = ["ok", 5]
        path.write_text(json.dumps(data))
        self.assertEqual(self.keywords("books"), [])
        self.assertEqual(self.keywords("plain"), ["ok"])

    def test_pointer_stub_data_is_unchanged(self):
        stub = self.root / "modules" / "old-search" / "MODULE.md"
        stub.parent.mkdir()
        stub.write_text("# Old search\n\nStatus: retired — see books.\n")
        code, env, _ = run_json("show", "old-search", *self.R)
        self.assertEqual((code, set(env["data"])), (1, {"module", "stub"}))


if __name__ == "__main__":
    unittest.main()
