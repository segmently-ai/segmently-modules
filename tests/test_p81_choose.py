"""P8.1 task 3b, the work order and its answer: `modsys choose` (P81-AC-051…057), the
`[search]` settings (AC-069/070) and the catalog's `search` / `match.semantic` (AC-020)."""
import hashlib
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.agent_helpers import AgentRepo, picks
from tests.helpers import run, run_json

TASK = "возврат платежа за заказ"
CARDS = ["catalog", "orders", "orders/checkout", "orders/refunds", "orders/invoices",
         "payments"]
DEPTH = {"quick": "from the cards only", "standard": "up to 3 candidates",
         "deep": "confirm the choice in their code"}


def tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        h.update(p.relative_to(root).as_posix().encode())
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


class Base(AgentRepo, unittest.TestCase):
    def order(self, *extra):
        code, env, err = run_json("choose", "--task", TASK, *self.R, *extra)
        self.assertEqual((code, err), (0, ""))
        return env["data"]

    def answer_file(self, answer, name="answer.json") -> str:
        path = self.tmp / name
        path.write_text(answer if isinstance(answer, str) else json.dumps(answer),
                        encoding="utf-8")
        return str(path)


class WorkOrderTest(Base):
    def test_text_form(self):  # P81-AC-051
        code, out, err = run("choose", "--task", TASK, *self.R)
        self.assertEqual((code, err), (0, ""))
        self.assertNotIn("\x1b", out)
        self.assertIn(TASK, out)
        lines = out.splitlines()
        positions = [out.index(TASK), out.index("Rules:"), out.index("Candidates"),
                     out.index("Answer schema:"), out.index("catalog_digest:")]
        self.assertEqual(positions, sorted(positions))
        for needle in ("by meaning", "any language", "Use only module ids", "none",
                       "at most 5 picks"):
            self.assertIn(needle, out)
        cards = [ln for ln in lines if re.match(r"^[a-z/]+  ", ln) and "[" in ln]
        self.assertEqual([c.split()[0] for c in cards], CARDS)
        self.assertIn("(child of orders)", [c for c in cards if c.startswith("orders/refunds")][0])
        self.assertRegex(lines[-1], r"^catalog_digest: [0-9a-f]{64}$")

    def test_json_form(self):  # P81-AC-052
        data = self.order()
        self.assertEqual(list(data), ["task", "rules", "cards", "answer_schema",
                                      "catalog_digest", "max_picks", "search"])
        self.assertEqual(data["task"], TASK)
        self.assertEqual([c["module"] for c in data["cards"]], CARDS)
        by = {c["module"]: c for c in data["cards"]}
        self.assertEqual(by["orders/refunds"]["parent"], "orders")
        self.assertEqual(by["orders/refunds"]["description"],
                         "Returned books: refund requests, partial refunds and restocking.")
        self.assertNotIn("parent", by["orders"])
        props = data["answer_schema"]["properties"]
        self.assertEqual(props["none"], {"type": "boolean"})
        item = props["picks"]["items"]["properties"]
        self.assertEqual((item["module"]["type"], item["reason"]["type"]), ("string", "string"))
        self.assertEqual(item["confidence"], {"type": "number", "minimum": 0, "maximum": 1})
        self.assertEqual(data["max_picks"], 5)
        self.assertEqual(data["search"], {"claude_model": "sonnet", "codex_model": "gpt-5.6-luna",
                                          "effort": "standard"})

    def test_a_child_without_a_description_shows_the_parents(self):  # P81-AC-052 / SI-P81-8
        reg = self.root / "modules" / "registry.json"
        doc = json.loads(reg.read_text(encoding="utf-8"))
        del doc["modules"]["orders"]["submodules"]["refunds"]["description"]
        reg.write_text(json.dumps(doc), encoding="utf-8")
        by = {c["module"]: c for c in self.order()["cards"]}
        self.assertEqual(by["orders/refunds"]["description"], by["orders"]["description"])

    def test_deterministic_and_effort_rules(self):  # P81-AC-053
        runs = {}
        for effort in ("quick", "standard", "deep"):
            self.config(f'[search]\neffort = "{effort}"\n')
            first = run("choose", "--task", TASK, *self.R, "--json")
            self.assertEqual(first, run("choose", "--task", TASK, *self.R, "--json"))
            runs[effort] = json.loads(first[1])["data"]
        quick = runs["quick"]["rules"]
        for effort, data in runs.items():
            rules = data["rules"]
            self.assertEqual(len(rules), len(quick))
            self.assertEqual(rules[:4] + rules[5:], quick[:4] + quick[5:])  # only the depth differs
            self.assertIn(DEPTH[effort], rules[4])
        self.assertEqual(len({r["rules"][4] for r in runs.values()}), 3)
        self.assertEqual(len({d["catalog_digest"] for d in runs.values()}), 1)

    def test_digest_follows_the_cards_only(self):  # P81-AC-053
        base = self.order()
        again = self.order("--top", "2")
        self.assertEqual(base["catalog_digest"], again["catalog_digest"])
        self.config('[search]\nclaude_model = "opus"\n')
        self.assertEqual(self.order()["catalog_digest"], base["catalog_digest"])
        _, env, _ = run_json("choose", "--task", "something else", *self.R)
        self.assertEqual(env["data"]["catalog_digest"], base["catalog_digest"])
        reg = self.root / "modules" / "registry.json"
        doc = json.loads(reg.read_text(encoding="utf-8"))
        doc["modules"]["payments"]["description"] = "Payments, changed."
        reg.write_text(json.dumps(doc), encoding="utf-8")
        self.assertNotEqual(self.order()["catalog_digest"], base["catalog_digest"])

    def test_top_sets_max_picks(self):  # P81-SI-20
        data = self.order("--top", "2")
        self.assertEqual(data["max_picks"], 2)
        self.assertTrue(any("at most 2 picks" in r for r in data["rules"]))
        for bad in ("0", "-1"):
            code, out, err = run("choose", "--task", TASK, "--top", bad, *self.R)
            self.assertEqual((code, out), (2, ""))
            self.assertIn("--top", err)

    def test_needs_a_task(self):
        code, out, err = run("choose", *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("--task", err)

    def test_no_environment_dependent_value(self):  # SI-P81-17
        _, out, _ = run("choose", "--task", TASK, *self.R, "--json")
        self.assertNotIn(str(self.root), out)
        self.assertNotIn(str(self.tmp), out)


class ApplyTest(Base):
    GOOD = {"picks": [{"module": "orders/refunds", "confidence": 0.9, "reason": "r"},
                      {"module": "payments", "confidence": 0.4}], "none": False}

    def apply(self, answer, *extra, stdin=None):
        if stdin is None:
            return run("choose", "--apply", self.answer_file(answer), *self.R, *extra)
        with mock.patch("sys.stdin", __import__("io").StringIO(stdin)):
            return run("choose", "--apply", "-", *self.R, *extra)

    def test_valid_answer_file_and_stdin(self):  # P81-AC-054
        before = tree_hash(self.root)
        for extra in ((), ("--json",)):
            from_file = self.apply(self.GOOD, *extra)
            from_stdin = self.apply(None, *extra, stdin=json.dumps(self.GOOD))
            self.assertEqual(from_file[0], 0)
            self.assertEqual(from_file, from_stdin)
        code, out, _ = self.apply(self.GOOD)
        self.assertLess(out.index("orders/refunds"), out.index("payments"))
        self.assertIn("0.90  orders/refunds  r", out)
        self.assertIn("docs/orders", out.replace("modules/orders", "docs/orders"))
        data = json.loads(self.apply(self.GOOD, "--json")[1])
        self.assertEqual(data["schema"], "modsys.choose/1")
        picks_ = data["data"]["picks"]
        self.assertEqual([p["module"] for p in picks_], ["orders/refunds", "payments"])
        self.assertEqual(picks_[0]["reason"], "r")
        self.assertTrue(all(p["read"] for p in picks_))
        self.assertEqual(tree_hash(self.root), before)
        self.assertFalse(list(self.root.rglob("*.lock")))

    def test_read_sets_match_show(self):  # P81-AC-054
        data = json.loads(self.apply(self.GOOD, "--json")[1])["data"]
        _, show, _ = run_json("show", "orders/refunds", *self.R)
        self.assertEqual(data["picks"][0]["read"], show["data"]["read"])

    def test_unknown_none_and_empty_answers(self):  # P81-AC-055
        def notes(answer):
            code, out, err = self.apply(answer)
            self.assertEqual((code, err), (0, ""), answer)
            data = json.loads(self.apply(answer, "--json")[1])["data"]
            return out, data
        out, data = notes({"picks": [{"module": "orders/refunds", "confidence": 0.5},
                                     {"module": "ghost", "confidence": 0.9}]})
        self.assertEqual([p["module"] for p in data["picks"]], ["orders/refunds"])
        self.assertEqual(out.count("note:"), 1)
        self.assertIn("note: unknown module dropped: ghost", out)
        out, data = notes({"picks": [{"module": "a", "confidence": 1},
                                     {"module": "b", "confidence": 1}]})
        self.assertEqual((data["picks"], out.count("note:")), ([], 2))
        out, data = notes({"picks": [], "none": True})
        self.assertIn("no module chosen", out)
        self.assertEqual(data["notes"], [])
        out, data = notes({"picks": [{"module": "payments", "confidence": 1}], "none": True})
        self.assertEqual(data["picks"], [])
        self.assertEqual(data["notes"], ["none is true; picks ignored"])
        out, data = notes({"picks": []})
        self.assertIn("no module chosen", out)

    def test_schema_violations(self):  # P81-AC-056
        cases = [("not json", "not JSON"), ("", "empty"), ("{}", "picks"),
                 ('{"picks": 3}', "picks"), ('{"picks": [{"confidence": 1}]}', "picks[0].module"),
                 ('{"picks": [{"module": "payments", "confidence": 1.01}]}', "confidence"),
                 ('{"picks": [{"module": "payments", "confidence": -0.01}]}', "confidence"),
                 ('{"picks": [{"module": "payments", "confidence": "0.5"}]}', "confidence"),
                 ('{"picks": [{"module": "payments", "confidence": true}]}', "confidence"),
                 ('[]', "JSON object"), ('{"picks": [], "none": "no"}', "none")]
        for text, needle in cases:
            for extra in ((), ("--json",)):
                with self.subTest(text=text, json=extra):
                    code, out, err = run("choose", "--apply", self.answer_file(text), *self.R,
                                         *extra)
                    self.assertEqual((code, out), (2, ""))
                    self.assertTrue(err.startswith("modsys: error: "), err)
                    self.assertNotIn("Traceback", err)
                    self.assertIn(needle, err)
        code, out, err = run("choose", "--apply", str(self.tmp / "missing.json"), *self.R)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("missing.json", err)
        code, out, err = self.apply(None, stdin="")
        self.assertEqual((code, out), (2, ""))

    def test_boundaries_extras_and_duplicates(self):  # P81-AC-056
        for conf in (0, 1, 0.5):
            code, _, err = self.apply({"picks": [{"module": "payments", "confidence": conf}]})
            self.assertEqual((code, err), (0, ""))
        data = json.loads(self.apply({"picks": [{"module": "payments", "confidence": 0.2,
                                                 "extra": 1},
                                                {"module": "payments", "confidence": 0.7}],
                                      "whatever": True}, "--json")[1])["data"]
        self.assertEqual([(p["module"], p["confidence"]) for p in data["picks"]],
                         [("payments", 0.7)])
        self.assertEqual(len(data["notes"]), 1)
        self.assertIn("duplicate", data["notes"][0])

    def test_ties_follow_card_order_and_top_cuts(self):  # SI-P81-19/20
        answer = {"picks": [{"module": m, "confidence": 0.5}
                            for m in ("payments", "orders", "catalog")]}
        data = json.loads(self.apply(answer, "--json")[1])["data"]
        self.assertEqual([p["module"] for p in data["picks"]], ["catalog", "orders", "payments"])
        data = json.loads(self.apply(answer, "--json", "--top", "1")[1])["data"]
        self.assertEqual([p["module"] for p in data["picks"]], ["catalog"])
        self.assertEqual(len(data["notes"]), 1)

    def test_digest_echo(self):  # P81-AC-057
        digest = self.order()["catalog_digest"]
        for given, expected in ((digest, 0), (None, 0), ("0" * 64, 1)):
            answer = {**self.GOOD, **({"catalog_digest": given} if given else {})}
            code, out, err = self.apply(answer)
            self.assertEqual((code, err), (0, ""))
            self.assertEqual(out.count("catalog changed since the work order"), expected)
            self.assertIn("payments", out)


class SearchSettingsTest(Base):
    def test_validation(self):  # P81-AC-069
        for key in ("claude_model", "codex_model"):
            for ok in ("sonnet", "gpt-5.6-luna", "x" * 100):
                self.config(f'[search]\n{key} = "{ok}"\n')
                self.assertEqual(run("lint", "--fail-on", "never", *self.R)[0], 0, ok)
            for bad in ('""', '" x"', '"a b"', '"a\\u0001b"', f'"{"x" * 101}"', "3"):
                self.config(f"[search]\n{key} = {bad}\n")
                for argv in (("lint",), ("catalog",), ("choose", "--task", "t")):
                    code, out, err = run(*argv, *self.R)
                    self.assertEqual((code, out), (2, ""), (key, bad))
                    self.assertIn(f"[search] {key}", err)
                    self.assertIn("config.toml", err)
        for ok in ("quick", "standard", "deep"):
            self.config(f'[search]\neffort = "{ok}"\n')
            self.assertEqual(run("catalog", *self.R)[0], 0)
        for bad in ('"high"', '""', '"Deep"', "3"):
            self.config(f"[search]\neffort = {bad}\n", "config.user.toml")
            code, out, err = run("catalog", *self.R)
            self.assertEqual((code, out), (2, ""))
            self.assertIn("[search] effort", err)
            self.assertIn("config.user.toml", err)

    def test_defaults_without_a_section(self):  # P81-AC-069
        _, env, _ = run_json("catalog", *self.R)
        self.assertEqual(env["data"]["search"], {"claude_model": "sonnet",
                                                 "codex_model": "gpt-5.6-luna",
                                                 "effort": "standard"})

    def test_exposure_and_precedence(self):  # P81-AC-070
        self.config('[search]\neffort = "deep"\nclaude_model = "opus"\n')
        self.config('[search]\neffort = "quick"\n', "config.user.toml")
        want = {"claude_model": "opus", "codex_model": "gpt-5.6-luna", "effort": "quick"}
        _, env, _ = run_json("catalog", *self.R)
        self.assertEqual(env["data"]["search"], want)
        data = run_json("choose", "--task", "t", *self.R)[1]["data"]
        self.assertEqual(data["search"], want)
        self.assertIn(DEPTH["quick"], data["rules"][4])


class CatalogAgentTest(Base):
    def test_semantic_means_an_agent_command(self):  # P81-AC-020
        self.config('[match]\nmode = "hybrid"\n')
        _, env, _ = run_json("catalog", *self.R)
        self.assertEqual(env["data"]["match"], {"mode": "hybrid", "semantic": False})
        self.agent(answer={"picks": []})
        _, env, _ = run_json("catalog", *self.R)
        self.assertEqual(env["data"]["match"], {"mode": "hybrid", "semantic": True})
        self.assertEqual(self.calls(), [])  # catalog never runs the agent


if __name__ == "__main__":
    unittest.main()
