"""P8.1 tasks 3a/3b: `modsys catalog` (S2), `[match] mode` and `--match` (S1), the no-agent
refusal and note (S4), the config shape of `[match]` (an invalid mode)."""
import contextlib
import hashlib
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

from tests.agent_helpers import AgentRepo
from tests.helpers import run, run_json

NO_AGENT = ("semantic matching needs your agent: set MODSYS_AGENT_COMMAND (a JSON array); "
               "in Claude Code / Codex the skills do it with modsys choose")
NOTE = "semantic part skipped: no agent command configured"
TASK = "partial refund for a returned book"
MODES = ("lexical", "semantic", "hybrid")


def tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        h.update(p.relative_to(root).as_posix().encode())
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


class Repo(AgentRepo, unittest.TestCase):
    """The split fixture; `with_agent()` sets a fake agent command (its marker = a logged call)
    that would answer if it ever ran."""

    @property
    def marker(self):
        return self.calls_log

    def with_agent(self, mode: str | None = None) -> None:
        self.agent(answer={"picks": [], "none": True})
        if mode:
            self.config(f'[match]\nmode = "{mode}"\n')


class CatalogTest(Repo):
    def test_text_one_line_per_module_and_child(self):  # P81-AC-019
        code, out, err = run("catalog", *self.R)
        self.assertEqual((code, err), (0, ""))
        lines = out.splitlines()
        self.assertEqual(len(lines), 6)
        by_name = {line.split()[0]: line for line in lines}
        self.assertEqual(set(by_name), {"catalog", "orders", "payments", "orders/checkout",
                                        "orders/refunds", "orders/invoices"})
        refunds = by_name["orders/refunds"]
        self.assertIn("active", refunds)
        self.assertIn("Returned books: refund requests, partial refunds and restocking.", refunds)
        self.assertNotIn("Start here", refunds)  # the child's OWN description
        self.assertIn("partial refund", refunds)  # keywords
        self.assertIn("(child of orders)", refunds)
        self.assertNotIn("child of", by_name["orders"])
        self.assertIn("Start here for anything about a placed order.", by_name["orders"])

    def test_json_default_config(self):  # P81-AC-020
        code, env, err = run_json("catalog", *self.R)
        self.assertEqual((code, err, env["schema"]), (0, "", "modsys.catalog/1"))
        data = env["data"]
        self.assertEqual(data["match"], {"mode": "lexical", "semantic": False})
        self.assertEqual(data["search"], {"claude_model": "sonnet", "codex_model": "gpt-5.6-luna",
                                          "effort": "standard"})  # S9
        cards = {c["name"]: c for c in data["modules"]}
        self.assertEqual(list(cards), ["catalog", "orders", "orders/checkout", "orders/refunds",
                                       "orders/invoices", "payments"])
        for c in cards.values():
            self.assertTrue({"name", "status", "description", "keywords"} <= set(c))
        self.assertNotIn("parent", cards["orders"])
        self.assertEqual(cards["orders/refunds"]["parent"], "orders")
        self.assertEqual(cards["orders/refunds"]["status"], "active")
        self.assertEqual(cards["orders/refunds"]["keywords"],
                         ["refund", "partial refund", "restocking", "return request"])
        self.assertEqual(cards["orders/refunds"]["description"],
                         "Returned books: refund requests, partial refunds and restocking.")

    def test_json_reports_the_configured_mode_and_agent(self):  # P81-AC-020
        self.with_agent("hybrid")
        _, env, _ = run_json("catalog", *self.R)
        self.assertEqual(env["data"]["match"], {"mode": "hybrid", "semantic": True})
        self.no_agent()
        _, env, _ = run_json("catalog", *self.R)  # catalog itself never refuses
        self.assertEqual(env["data"]["match"], {"mode": "hybrid", "semantic": False})

    def test_read_only_with_an_agent_configured(self):  # P81-AC-021
        self.with_agent("hybrid")
        before = tree_hash(self.root)
        for args in ((), ("--json",)):
            for _ in range(2):
                code, _, err = run("catalog", *self.R, *args)
                self.assertEqual((code, err), (0, ""))
        self.assertEqual(tree_hash(self.root), before)
        self.assertFalse(self.marker.exists())
        self.assertFalse((self.root / ".modsys" / "cache").exists())
        self.assertFalse(list(self.root.rglob("*.lock")))

    def test_read_only_directory(self):  # P81-AC-021
        self.with_agent()
        before = tree_hash(self.root)
        dirs = [self.root, *[p for p in self.root.rglob("*") if p.is_dir()]]
        try:
            for d in dirs:
                os.chmod(d, stat.S_IRUSR | stat.S_IXUSR)
            code, _, err = run("catalog", *self.R)
        finally:
            for d in dirs:
                os.chmod(d, stat.S_IRWXU)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(tree_hash(self.root), before)


class ModeResolutionTest(Repo):
    VERBS = {"match": ("match", TASK), "context": ("context", "--task", TASK),
             "discover": ("discover", "--task", TASK)}

    def test_every_verb_accepts_the_flag(self):  # P81-AC-022
        for name, argv in self.VERBS.items():
            for mode in MODES:
                with self.subTest(verb=name, mode=mode):
                    code, out, err = run(*argv, "--match", mode, *self.R)
                    if mode == "semantic":
                        self.assertEqual((code, out), (2, ""))
                    else:
                        self.assertEqual((code, err), (0, ""))

    def test_flag_beats_config_beats_default(self):  # P81-AC-022
        os.environ["MODSYS_AGENT_ALLOW_REPO_MODE"] = "1"  # D6: a config mode runs only opted in
        for cfg in (None, *MODES):
            for flag in (None, *MODES):
                self.config("" if cfg is None else f'[match]\nmode = "{cfg}"\n')
                effective = flag or cfg or "lexical"
                with self.subTest(config=cfg, flag=flag):
                    argv = ("match", TASK, *self.R, *(("--match", flag) if flag else ()))
                    code, out, err = run(*argv, "--json")
                    if effective == "semantic":
                        self.assertEqual((code, out, err),
                                         (2, "", f"modsys: error: {NO_AGENT}\n"))
                        continue
                    self.assertEqual((code, err), (0, ""))
                    data = json.loads(out)["data"]
                    if effective == "lexical":
                        self.assertIsInstance(data, list)  # the plain list, as ever
                    else:
                        self.assertEqual(data["mode"], effective)

    def test_hybrid_and_semantic_by_config_for_context_and_discover(self):  # P81-AC-022
        os.environ["MODSYS_AGENT_ALLOW_REPO_MODE"] = "1"  # D6: a config mode runs only opted in
        self.config('[match]\nmode = "hybrid"\n')
        for argv in (("context", "--task", TASK), ("discover", "--task", TASK)):
            _, env, _ = run_json(*argv, *self.R)
            self.assertEqual(env["data"]["mode"], "hybrid")
            self.assertEqual(env["data"]["notes"], [NOTE])
            self.assertEqual(run(*argv, "--match", "lexical", *self.R)[0], 0)
        self.config('[match]\nmode = "semantic"\n')
        for argv in (("context", "--task", TASK), ("discover", "--task", TASK)):
            self.assertEqual(run(*argv, *self.R)[0], 2)

    def test_discover_without_a_task_ignores_the_mode(self):  # P81-AC-022
        self.config('[match]\nmode = "semantic"\n')
        code, _, err = run("discover", "--files", "src/orders/service.py", *self.R)
        self.assertEqual((code, err), (0, ""))

    def test_an_unknown_flag_value_is_a_usage_error(self):  # P81-AC-026
        for verb in self.VERBS.values():
            code, out, err = run(*verb, "--match", "fuzzy", *self.R)
            self.assertEqual((code, out), (2, ""))
            self.assertIn("--match", err)
            self.assertNotIn("Traceback", err)


class LexicalIdenticalTest(Repo):
    def snapshot(self):
        out = {}
        for argv in (("match", TASK), ("context", "--task", TASK),
                     ("discover", "--task", TASK), ("match", "zzz nothing")):
            for json_flag in ((), ("--json",)):
                out[(argv, json_flag)] = run(*argv, *self.R, *json_flag)
        return out

    def test_bytes_do_not_change(self):  # P81-AC-023
        base = self.snapshot()
        self.with_agent()
        self.assertEqual(self.snapshot(), base)
        self.config('[match]\nmode = "lexical"\n')
        self.assertEqual(self.snapshot(), base)
        self.with_agent("lexical")
        for argv in (("match", TASK), ("context", "--task", TASK), ("discover", "--task", TASK)):
            for json_flag in ((), ("--json",)):
                self.assertEqual(run(*argv, "--match", "lexical", *self.R, *json_flag),
                                 base[(argv, json_flag)])
        self.assertFalse(self.marker.exists())
        self.assertFalse((self.root / ".modsys" / "cache").exists())

    def test_no_sources_or_similarity_keys(self):  # P81-AC-023
        for argv in (("match", TASK), ("context", "--task", TASK), ("discover", "--task", TASK)):
            _, out, _ = run(*argv, "--match", "lexical", *self.R, "--json")
            self.assertNotIn("similarity", out)
            self.assertNotIn('"notes"', out)
            self.assertNotIn('"mode"', out)
        _, out, _ = run("match", TASK, *self.R, "--json")
        self.assertNotIn('"sources"', out)


class NoAgentTest(Repo):
    def test_semantic_refuses(self):  # P81-AC-024
        os.environ["MODSYS_AGENT_ALLOW_REPO_MODE"] = "1"  # D6: a config mode runs only opted in
        for cfg_mode in (False, True):
            if cfg_mode:
                self.config('[match]\nmode = "semantic"\n')
            before = tree_hash(self.root)
            flag = () if cfg_mode else ("--match", "semantic")
            for argv in (("match", TASK), ("context", "--task", TASK),
                         ("discover", "--task", TASK)):
                for json_flag in ((), ("--json",)):
                    with self.subTest(argv=argv, cfg=cfg_mode, json=json_flag):
                        code, out, err = run(*argv, *flag, *self.R, *json_flag)
                        self.assertEqual((code, out), (2, ""))
                        self.assertEqual(err, f"modsys: error: {NO_AGENT}\n")
                        self.assertEqual(tree_hash(self.root), before)

    def test_hybrid_degrades_to_the_lexical_rows_with_one_note(self):  # P81-AC-025
        before = tree_hash(self.root)
        _, lexical, _ = run("match", TASK, *self.R)
        code, out, err = run("match", TASK, "--match", "hybrid", *self.R)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.splitlines()[:-1], lexical.splitlines())
        self.assertEqual(out.splitlines()[-1], NOTE)
        self.assertEqual(out.count(NOTE), 1)
        _, env, _ = run_json("match", TASK, "--match", "hybrid", *self.R)
        _, plain, _ = run_json("match", TASK, *self.R)
        self.assertEqual(env["data"], {"mode": "hybrid", "rows": plain["data"], "notes": [NOTE]})
        for argv in (("context", "--task", TASK), ("discover", "--task", TASK)):
            code, out, _ = run(*argv, "--match", "hybrid", *self.R)
            self.assertEqual(code, 0)
            self.assertEqual(out.count(NOTE), 1)
            self.assertEqual(out.splitlines()[-1], NOTE)
        self.assertEqual(tree_hash(self.root), before)  # nothing written, no cache


class ConfigShapeTest(Repo):
    def refused(self, text: str, *needles: str):
        self.config(text)
        for argv in (("match", TASK), ("lint",), ("catalog",)):
            code, out, err = run(*argv, *self.R)
            self.assertEqual((code, out), (2, ""), argv)
            self.assertTrue(err.startswith("modsys: error: "), err)
            self.assertIn("config.toml", err)
            self.assertNotIn("Traceback", err)
            for n in needles:
                self.assertIn(n, err)

    def test_invalid_mode(self):  # P81-AC-026
        self.refused('[match]\nmode = "fuzzy"\n', "[match] mode", "fuzzy")
        self.refused('[match]\nmode = 3\n', "[match] mode")

    def test_catalog_is_a_documented_verb(self):  # headless contract on the new path
        code, out, err = run("catalog", *self.R, "--root", str(self.root / "nope"))
        self.assertEqual((code, out), (2, ""))
        self.assertNotIn("Traceback", err)


if __name__ == "__main__":
    unittest.main()
