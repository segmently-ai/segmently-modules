"""The verbs the chooser setting touches print what they printed before it, byte for byte:
`catalog` and `catalog --json`, `choose` without `--cards` (the text and the JSON order,
`--effort`, `--top`, `--apply`), the nested-agent refusal, `discover` text, `discover --files`
JSON, `discover --json` but for its last key `lexical_confidence`, and `context`. The golden
outputs in
`tests/fixtures/search_base_outputs/` were captured from the engine before the setting existed,
on a copy of the split fixture, by `outputs()` below."""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import SPLIT_FIXTURE, copy_fixture, init_git, run

GOLDEN = Path(__file__).parent / "fixtures" / "search_base_outputs"
TASK = "Customers' money back for a returned book, a partial refund on the order\n"
QUERIES = "refund\norder service\npartial refund\n"
ANSWER = {"picks": [{"module": "orders/refunds", "confidence": 0.9, "reason": "returned books"},
                    {"module": "payments", "confidence": 0.4}],
          "none": False, "catalog_digest": None}
NESTED = {"SEGMENTLY_MODULES_WORK_ORDER": "1",
          "SEGMENTLY_MODULES_AGENT_COMMAND": json.dumps([sys.executable, "-c", "pass"])}
# name -> (argv with {task} / {queries} / {answer} files, environment, stdin)
CASES = {
    "catalog.txt": (["catalog"], {}, None),
    "catalog.json": (["catalog", "--json"], {}, None),
    "choose.txt": (["choose", "--task-file", "{task}"], {}, None),
    "choose.json": (["choose", "--task-file", "{task}", "--json"], {}, None),
    "choose-deep.json": (["choose", "--task-file", "{task}", "--effort", "deep", "--json"], {},
                         None),
    "choose-top.txt": (["choose", "--task-file", "{task}", "--top", "2"], {}, None),
    "choose-apply.txt": (["choose", "--apply", "{answer}"], {}, None),
    "choose-apply.json": (["choose", "--apply", "-", "--json"], {}, json.dumps(ANSWER)),
    "choose-run-nested.txt": (["choose", "--task-file", "{task}", "--run"], NESTED, None),
    "discover.txt": (["discover", "--task-file", "{queries}", "--match", "lexical"], {}, None),
    "discover.json": (["discover", "--task-file", "{queries}", "--match", "lexical", "--json"],
                      {}, None),
    "discover-hybrid.json": (["discover", "--task-file", "{queries}", "--match", "hybrid",
                              "--json"], {}, None),
    "discover-top.json": (["discover", "--task-file", "{queries}", "--match", "lexical",
                           "--top", "1", "--json"], {}, None),
    "discover-files.json": (["discover", "--files", "src/orders/service.py", "--json"], {},
                            None),
    "discover-files-task.txt": (["discover", "--files", "src/orders/service.py", "--task-file",
                                 "{queries}", "--match", "lexical"], {}, None),
    "context.txt": (["context", "--task-file", "{queries}", "--match", "lexical"], {}, None),
    "context.json": (["context", "--task-file", "{queries}", "--match", "lexical", "--json"], {},
                     None),
}
WITH_CONFIDENCE = ("discover.json", "discover-hybrid.json", "discover-top.json")


def outputs(tmp: Path) -> dict[str, str]:
    """{case name: what the case printed} on a fresh copy of the split fixture under `tmp`:
    stdout and, after a `--- exit N, stderr:` line, the exit code and stderr."""
    root = copy_fixture(tmp, SPLIT_FIXTURE)
    init_git(root)
    files = Path(tmp) / "inputs"
    files.mkdir()
    values = {"{task}": files / "task.txt", "{queries}": files / "queries.txt",
              "{answer}": files / "answer.json"}
    values["{task}"].write_text(TASK, encoding="utf-8")
    values["{queries}"].write_text(QUERIES, encoding="utf-8")
    values["{answer}"].write_text(json.dumps(ANSWER), encoding="utf-8")
    out = {}
    for name, (argv, env, stdin) in CASES.items():
        args = [str(values.get(a, a)) for a in argv]
        clean = {k: v for k, v in os.environ.items()
                 if not k.startswith("SEGMENTLY_MODULES_")}
        with mock.patch.dict(os.environ, {**clean, **env}, clear=True), \
                mock.patch("sys.stdin", io.StringIO(stdin or "")):
            code, stdout, stderr = run(*args, "--root", str(root))
        out[name] = f"{stdout}--- exit {code}, stderr:\n{stderr}"
    return out


def without_confidence(printed: str) -> tuple[str, str]:
    """(the last key of `data`, the output with `data.lexical_confidence` taken out and printed
    again as the verb prints it) of a `discover --json` output."""
    body, sep, tail = printed.partition("--- exit ")
    envelope = json.loads(body)
    last = list(envelope["data"])[-1]
    envelope["data"].pop("lexical_confidence", None)
    return last, json.dumps(envelope, indent=2, ensure_ascii=False) + "\n" + sep + tail


class BaseOutputsTest(unittest.TestCase):
    def test_every_case_prints_what_the_base_printed(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = outputs(Path(tmp))
        self.assertEqual(sorted(p.name for p in GOLDEN.iterdir()), sorted(CASES))
        for name in CASES:
            with self.subTest(case=name):
                golden = (GOLDEN / name).read_bytes().decode("utf-8")
                got = now[name]
                if name in WITH_CONFIDENCE:  # the one addition: the last key of `data`
                    last, got = without_confidence(got)
                    self.assertEqual(last, "lexical_confidence")
                self.assertEqual(got, golden)

    def test_the_golden_outputs_hold_no_temporary_path(self):
        for path in sorted(GOLDEN.iterdir()):
            with self.subTest(case=path.name):
                text = path.read_bytes().decode("utf-8")
                self.assertNotIn(tempfile.gettempdir(), text)
                self.assertNotIn("inputs/", text)


if __name__ == "__main__":
    unittest.main()
