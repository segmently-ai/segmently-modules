"""P8.2 task 1b: `[search] card_keywords` caps the keywords of each work-order card (D2) and
`choose --effort` overrides `[search] effort` for one run (D8) (P82-AC-009…012, 014, 057)."""
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.agent_helpers import AgentRepo, picks
from tests.helpers import run, run_json

TASK = "refund payment catalog"
KW12 = [f"book-kw{i:02d}" for i in (7, 3, 11, 1, 9, 2, 12, 5, 4, 10, 6, 8)]  # not sorted
KW11 = [f"area-kw{i:02d}" for i in (9, 2, 11, 4, 1, 8, 3, 10, 5, 7, 6)]
DEPTH = {
    "quick": "Choose from the cards only; do not open any file.",
    "standard": "Choose from the cards, and also open the INDEX or the head of MODULE.md of up "
                "to 3 candidates before you answer.",
    "deep": "Choose from the cards, and also read the candidates' docs and confirm the choice "
            "in their code before you answer.",
}
REASONING = {"quick": "low", "standard": "medium", "deep": "high"}
SEARCH_KEYS = {"claude_model", "codex_model", "effort"}


class Base(AgentRepo, unittest.TestCase):
    def setUp(self):
        super().setUp()
        reg = self.root / "modules" / "registry.json"
        data = json.loads(reg.read_text(encoding="utf-8"))
        data["modules"]["catalog"]["keywords"] = KW12
        data["modules"]["orders"]["submodules"]["checkout"]["keywords"] = KW11
        reg.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self.task = self.tmp / "t.txt"
        self.task.write_text(TASK, encoding="utf-8")

    def cap(self, value, name="config.toml") -> None:
        self.config(f"[search]\ncard_keywords = {value}\n", name)

    def order(self, *extra) -> dict:
        code, env, err = run_json("choose", "--task-file", str(self.task), *extra, *self.R)
        self.assertEqual((code, err), (0, ""))
        return env["data"]

    def card(self, order, name) -> dict:
        return next(c for c in order["cards"] if c["module"] == name)

    def catalog(self) -> tuple:
        return run("catalog", *self.R), run("catalog", "--json", *self.R)


class ValuesTest(Base):
    def test_accepted_values(self):  # P82-AC-009
        for value, want in ((0, 0), (1, 1), (10, 10), (12, 12), (13, 12), (1000000, 12)):
            with self.subTest(value=value):
                self.cap(value)
                self.assertEqual(self.card(self.order(), "catalog")["keywords"], KW12[:want])
                self.assertEqual(run("lint", *self.R)[0], 0)
        self.root.joinpath(".modsys/config.toml").write_text("", encoding="utf-8")
        self.assertEqual(self.card(self.order(), "catalog")["keywords"], KW12[:10])
        self.assertEqual(run("lint", *self.R)[0], 0)

    def refused(self, argv, tail: str) -> None:
        code, out, err = run(*argv, *self.R)
        self.assertEqual((code, out), (2, ""))
        lines = err.strip().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("modsys: error: "))
        self.assertTrue(lines[0].endswith(tail), lines[0])

    def test_refused_values(self):  # P82-AC-009
        for value, shown in (("-1", "-1"), ('"10"', "'10'"), ("1.5", "1.5"),
                             ("true", "True"), ("false", "False")):
            for form in (("choose", "--task-file", str(self.task)), ("lint",)):
                for js in ((), ("--json",)):
                    with self.subTest(value=value, form=form[0], json=bool(js)):
                        self.cap(value)
                        self.refused((*form, *js), f"/.modsys/config.toml: [search] "
                                     f"card_keywords: expected an integer >= 0, got {shown}")

    def test_layers_and_pack(self):  # P82-AC-009
        self.cap(5)
        self.assertEqual(len(self.card(self.order(), "catalog")["keywords"]), 5)
        self.cap(2, "config.user.toml")  # the user's value wins
        self.assertEqual(len(self.card(self.order(), "catalog")["keywords"]), 2)
        self.cap(-1, "config.user.toml")
        for argv in (("choose", "--task-file", str(self.task)), ("lint",)):
            self.refused(argv, "/.modsys/config.user.toml: [search] card_keywords: expected "
                               "an integer >= 0, got -1")
        (self.root / ".modsys/config.user.toml").unlink()
        (self.root / ".modsys/config.toml").unlink()
        pack = self.root / ".modsys/packs/capper"
        pack.mkdir(parents=True)
        head = 'id = "capper"\nversion = "0.1.0"\npriority = 50\n\n[search]\n'
        (pack / "pack.toml").write_text(head + "card_keywords = 4\n", encoding="utf-8")
        self.assertEqual(len(self.card(self.order(), "catalog")["keywords"]), 4)
        (pack / "pack.toml").write_text(head + "card_keywords = true\n", encoding="utf-8")
        for argv in (("choose", "--task-file", str(self.task)), ("lint",)):
            self.refused(argv, "/.modsys/packs/capper/pack.toml: [search] card_keywords: "
                               "expected an integer >= 0, got True")


class WorkOrderOnlyTest(Base):
    def test_cap_three_in_the_order(self):  # P82-AC-010
        self.cap(3)
        order = self.order()
        self.assertEqual(self.card(order, "catalog")["keywords"], KW12[:3])
        self.assertEqual(self.card(order, "orders/checkout")["keywords"], KW11[:3])
        self.assertEqual(self.card(order, "payments")["keywords"],
                         ["payment", "charge", "PaymentGateway"])
        self.assertEqual(set(order["search"]), SEARCH_KEYS)
        out = run("choose", "--task-file", str(self.task), *self.R)[1]
        self.assertIn(f"[{', '.join(KW12[:3])}]", out)
        self.assertNotIn(KW12[3], out)

    def test_cap_zero(self):  # P82-AC-010
        self.cap(0)
        order = self.order()
        self.assertTrue(all(c["keywords"] == [] for c in order["cards"]))
        out = run("choose", "--task-file", str(self.task), *self.R)[1]
        cand = out.split("Candidates")[1].split("Answer schema:")[0].splitlines()[1:-1]
        self.assertTrue(cand and all(ln.endswith("  []") or "  []  (child of" in ln
                                     for ln in cand))

    def test_catalog_keeps_every_keyword_and_is_unchanged(self):  # P82-AC-010
        base = self.catalog()
        for value in (0, 3, 10):
            with self.subTest(value=value):
                self.cap(value)
                self.assertEqual(self.catalog(), base)
        data = json.loads(base[1][1])["data"]
        self.assertEqual(set(data["search"]), SEARCH_KEYS)
        self.assertEqual(next(c for c in data["modules"] if c["name"] == "catalog")["keywords"],
                         KW12)

    def test_run_and_semantic_send_the_capped_cards(self):  # P82-AC-010
        self.cap(3)
        self.agent(answer=picks(("payments", 0.9)))
        self.assertEqual(run("choose", "--task-file", str(self.task), "--run", *self.R)[0], 0)
        self.assertEqual(run("match", TASK, "--match", "semantic", *self.R)[0], 0)
        self.assertEqual(run("match", TASK, "--match", "hybrid", *self.R)[0], 0)
        calls = self.calls()
        self.assertEqual(len(calls), 3)
        for call in calls:
            order = json.loads(call["stdin"])
            self.assertEqual(self.card(order, "catalog")["keywords"], KW12[:3])
            self.assertEqual(self.card(order, "orders/checkout")["keywords"], KW11[:3])
            self.assertEqual(set(order["search"]), SEARCH_KEYS)

    def test_deterministic(self):  # P82-AC-012
        for value in (0, 3, 10):
            self.cap(value)
            outputs = []
            for tmpdir in (self.tmp, Path(tempfile.mkdtemp(dir=self.tmp))):
                cwd = os.getcwd()
                os.chdir(tmpdir)
                try:
                    with mock.patch.dict(os.environ, {"TMPDIR": str(tmpdir)}):
                        outputs.append(tuple(
                            run("choose", "--task-file", str(self.task), *form, *self.R)
                            for form in ((), ("--json",))))
                finally:
                    os.chdir(cwd)
            self.assertEqual(outputs[0], outputs[1])
            for form in outputs[0]:
                for text in form[1:2]:
                    self.assertNotIn(str(self.tmp), text)
                    self.assertNotIn("TMPDIR", text)


class DigestTest(Base):
    def digest(self, *extra) -> str:
        return self.order(*extra)["catalog_digest"]

    def test_digest_is_over_the_capped_cards(self):  # P82-AC-011
        self.cap(3)
        order = self.order()
        canonical = json.dumps(order["cards"], sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False)
        self.assertEqual(order["catalog_digest"],
                         hashlib.sha256(canonical.encode("utf-8")).hexdigest())
        d3 = order["catalog_digest"]
        self.cap(10)
        self.assertNotEqual(self.digest(), d3)  # (a)
        self.cap(12)
        d12 = self.digest()
        self.cap(20)
        self.assertEqual(self.digest(), d12)  # (b)

    def test_digest_ignores_task_top_effort_model_and_override(self):  # P82-AC-011
        self.cap(3)
        base = self.digest()
        self.task.write_text("something else entirely", encoding="utf-8")
        self.assertEqual(self.digest("--top", "2"), base)
        self.config('[search]\ncard_keywords = 3\neffort = "deep"\nclaude_model = "opus"\n',
                    "config.user.toml")
        self.assertEqual(self.digest(), base)
        override = self.root / ".modsys/overrides/templates/choose/rules.md"
        override.parent.mkdir(parents=True)
        override.write_text("- only rule\n", encoding="utf-8")
        self.assertEqual(self.digest(), base)

    def test_apply_digest_note(self):  # P82-AC-011
        self.cap(3)
        d3 = self.digest()
        self.cap(10)
        d10 = self.digest()
        for digest, notes in ((d10, []), (d3, ["catalog changed since the work order"])):
            with self.subTest(digest=digest == d10):
                ans = self.tmp / "a.json"
                ans.write_text(json.dumps({**picks(("payments", 0.9)), "catalog_digest": digest}),
                               encoding="utf-8")
                code, env, err = run_json("choose", "--apply", str(ans), *self.R)
                self.assertEqual((code, err), (0, ""))
                self.assertEqual(env["data"]["notes"], notes)
                self.assertEqual([p["module"] for p in env["data"]["picks"]], ["payments"])


class EffortTest(Base):
    def assertDepth(self, order, effort) -> None:
        self.assertIn(DEPTH[effort], order["rules"])
        for other, sentence in DEPTH.items():
            if other != effort:
                self.assertNotIn(sentence, order["rules"])

    def test_flag_overrides_config(self):  # P82-AC-057
        for cfg in (None, "quick", "deep"):
            if cfg:
                self.config(f'[search]\neffort = "{cfg}"\n', "config.user.toml")
            plain = self.order()
            self.assertEqual(plain["search"]["effort"], cfg or "standard")
            self.assertDepth(plain, cfg or "standard")
            for effort in DEPTH:
                with self.subTest(config=cfg, effort=effort):
                    order = self.order("--effort", effort)
                    self.assertEqual(order["search"], {**plain["search"], "effort": effort})
                    self.assertDepth(order, effort)
                    self.assertEqual([r for r in order["rules"] if r not in DEPTH.values()],
                                     [r for r in plain["rules"] if r not in DEPTH.values()])
                    self.assertEqual(order["catalog_digest"], plain["catalog_digest"])
        out = run("choose", "--task-file", str(self.task), "--effort", "deep", *self.R)[1]
        self.assertIn(f"- {DEPTH['deep']}", out)

    def test_run_placeholders_follow_the_flag(self):  # P82-AC-057
        for cfg in ("quick", "deep"):
            self.config(f'[search]\neffort = "{cfg}"\n', "config.user.toml")
            for effort in DEPTH:
                with self.subTest(config=cfg, effort=effort):
                    self.calls_log.unlink(missing_ok=True)
                    self.agent(extra_argv=["{effort}", "{reasoning}"],
                               answer=picks(("payments", 0.9)))
                    code = run("choose", "--task-file", str(self.task), "--run",
                               "--effort", effort, *self.R)[0]
                    self.assertEqual(code, 0)
                    call = self.calls()[0]
                    self.assertEqual(call["argv"], [effort, REASONING[effort]])
                    self.assertEqual(json.loads(call["stdin"])["search"]["effort"], effort)
            self.calls_log.unlink(missing_ok=True)
            self.agent(extra_argv=["{effort}", "{reasoning}"], answer=picks(("payments", 0.9)))
            run("choose", "--task-file", str(self.task), "--run", *self.R)
            self.assertEqual(self.calls()[0]["argv"], [cfg, REASONING[cfg]])

    def test_match_uses_the_config_effort(self):  # P82-AC-057
        self.config('[search]\neffort = "deep"\n', "config.user.toml")
        self.agent(extra_argv=["{effort}", "{reasoning}"], answer=picks(("payments", 0.9)))
        run("match", TASK, "--match", "semantic", *self.R)
        self.assertEqual(self.calls()[0]["argv"], ["deep", "high"])
        for verb in (("match", TASK), ("context", "--task", TASK), ("discover", "--task", TASK)):
            code, out, err = run(*verb, "--effort", "deep", *self.R)
            self.assertEqual((code, out), (2, ""))

    def test_apply_ignores_effort(self):  # P82-AC-057
        ans = self.tmp / "a.json"
        ans.write_text(json.dumps(picks(("payments", 0.9))), encoding="utf-8")
        flagged = run("choose", "--apply", str(ans), "--effort", "deep", *self.R)
        self.assertEqual(flagged[0], 0)
        self.assertEqual(flagged, run("choose", "--apply", str(ans), *self.R))
        code, env, err = run_json("choose", "--apply", str(ans), "--effort", "deep", *self.R)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual([p["module"] for p in env["data"]["picks"]], ["payments"])
        self.assertEqual(run("choose", "--apply", str(ans), "--effort", "deep", "--json",
                             *self.R),
                         run("choose", "--apply", str(ans), "--json", *self.R))

    def test_invalid_effort(self):  # P82-AC-057
        for js in ((), ("--json",)):
            code, out, err = run("choose", "--task-file", str(self.task), "--effort", "fast",
                                 *js, *self.R)
            self.assertEqual((code, out), (2, ""))
            self.assertIn("invalid choice", err)


class DocsTest(unittest.TestCase):  # P82-AC-014 (the cap and --effort items)
    ROOT = Path(__file__).resolve().parents[1]

    def doc(self, name: str) -> str:
        return (self.ROOT / name).read_text(encoding="utf-8")

    def test_configuration_documents_the_cap(self):
        text = self.doc("docs/configuration.md")
        row = next(ln for ln in text.splitlines() if ln.startswith("| `[search] card_keywords`"))
        for needle in ("`10`", "integer >= 0", "personal", "work order only", "`catalog`",
                       "digest", "--effort"):
            self.assertIn(needle, row)
        effort = next(ln for ln in text.splitlines() if ln.startswith("| `[search] effort`"))
        self.assertIn("choose --effort", effort)

    def test_cli_contract_documents_effort(self):
        choose = next(ln for ln in self.doc("docs/cli-contract.md").splitlines()
                      if ln.startswith("| `choose "))
        self.assertIn("[--effort quick\\|standard\\|deep]", choose)
        for needle in ("card_keywords", "capped", "catalog_digest"):
            self.assertIn(needle, choose)
        text = self.doc("docs/cli-contract.md")
        self.assertIn("three keys (`card_keywords` is not shown)", text)
        flat = " ".join(text.split())  # final review, deferred 2: one sentence, no two parentheses
        self.assertIn("prints the cards an agent reads (`match.mode`, `match.semantic`, "
                      "`search`), with every keyword — the work order caps them at "
                      "`[search] card_keywords`", flat)
        self.assertIn("`choose --effort` overrides `effort` for one run",
                      self.doc("README.md"))
        self.assertIn("or of `choose --effort` when given", self.doc("docs/configuration.md"))

    def test_the_changelog_names_both(self):
        text = self.doc("CHANGELOG.md")
        unreleased = text.split("## [Unreleased]", 1)[1].split("\n## [", 1)[0]
        self.assertIn("card_keywords", unreleased)
        self.assertIn("choose --effort", unreleased)
