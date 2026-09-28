"""`modsys ci`: one CI gate in three steps that ALWAYS all run, so one failing step never hides
another — lint (plain: config-level findings included), drift (`lint --changed` against the
base) and coverage. Settings: flag, else `[ci]`, else the default (fail_on "warning", base
"HEAD", no coverage threshold = report-only). Exit 1 when a step failed; exit 2 before any step
for a usage error (an unknown or option-like --base, a threshold outside 0–100, no git)."""
from dataclasses import asdict

from modsys.changes import changed_files, commit_ref, diff_names, repo_files, require_work_tree
from modsys.coverage_cmd import coverage_report, percent
from modsys.lint import FAIL_ON, drift_report, failing, lint_registry, severity_counts
from modsys.output import EXIT_FINDINGS, EXIT_OK, UsageError, emit
from modsys.workspace import Workspace

NOTHING_TO_COMPARE = ("nothing to compare: the working tree equals HEAD — in CI pass --base "
                      "<target branch>")


def register(sub, common) -> None:
    p = sub.add_parser("ci", parents=[common],
                       help="one CI gate: lint, drift since --base, coverage (all three run)",
                       description="Runs lint (plain), drift (lint --changed against --base) "
                                   "and coverage; exit 1 when any step failed. Each setting: "
                                   "the flag, else [ci] in the config, else the default.")
    p.add_argument("--base", help="drift: compare the working tree (+ untracked files) with this "
                                  "ref (default: [ci] base, else HEAD) — in CI the target "
                                  "branch, e.g. origin/main")
    p.add_argument("--fail-on", choices=sorted(FAIL_ON),
                   help="lint and drift fail at this severity (default: [ci] fail_on, else "
                        "warning)")
    p.add_argument("--fail-under", type=float, metavar="PCT",
                   help="coverage fails below PCT %% (default: [ci] coverage_fail_under, else "
                        "report-only)")
    p.set_defaults(func=run)


def split_change(root, base: str, files: list[str]) -> tuple[int, int]:
    """(committed, uncommitted) of the files changed since `base`: those that differ between
    `base` and HEAD, and those that differ between HEAD and the working tree (untracked files
    included). A file changed in both counts in both; `files` stays their union."""
    if not files:
        return 0, 0
    wanted = set(files)
    committed = wanted & set(diff_names(root, f"{base}..HEAD"))
    uncommitted = wanted & set(changed_files(root, base="HEAD"))
    return len(committed), len(uncommitted)


def run(args) -> int:
    ws = Workspace.from_args(args)
    cfg = ws.config["ci"]
    fail_on = args.fail_on or cfg["fail_on"]
    base = args.base if args.base is not None else cfg["base"]
    threshold = args.fail_under if args.fail_under is not None else cfg.get("coverage_fail_under")
    if threshold is not None and not 0 <= threshold <= 100:
        raise UsageError("--fail-under must be between 0 and 100")
    require_work_tree(ws.root, "ci")
    base = commit_ref(ws.root, base, origin="flag" if args.base is not None else "config")

    findings = lint_registry(ws)
    steps = [{"name": "lint", "status": "failed" if failing(findings, fail_on) else "passed",
              "summary": severity_counts(findings), "findings": [asdict(f) for f in findings]}]
    drift, changed = drift_report(ws, base, findings)
    status = ("no-changes" if not changed["files"] else
              "failed" if failing(drift, fail_on) else "passed")
    committed, uncommitted = split_change(ws.root, base, changed["files"])
    steps.append({"name": "drift", "status": status,
                  "summary": {"base": base, "files": len(changed["files"]),
                              "committed": committed, "uncommitted": uncommitted,
                              "modules": changed["modules"], **severity_counts(drift)},
                  "findings": [asdict(f) for f in drift]})
    report = coverage_report(ws, repo_files(ws.root))
    status = ("report-only" if threshold is None else
              "failed" if percent(report["share"]) < threshold else "passed")
    steps.append({"name": "coverage", "status": status,
                  "summary": {"share": report["share"], "mapped": report["mapped"],
                              "total": report["total"], "unmapped": len(report["unmapped"]),
                              "fail_under": threshold}})
    notes = [NOTHING_TO_COMPARE] if not changed["files"] and base == "HEAD" else []
    failed = any(s["status"] == "failed" for s in steps)
    data = {"base": base, "fail_on": fail_on, "steps": steps, "failed": failed, "notes": notes}
    emit("ci", data, args.json, lambda d: _render(d, report["unmapped"]))
    return EXIT_FINDINGS if failed else EXIT_OK


def _summary(step: dict) -> str:
    s = step["summary"]
    counts = f"{s.get('error')} error(s), {s.get('warning')} warning(s), {s.get('info')} info"
    if step["name"] == "lint":
        return counts
    if step["name"] == "drift":
        if step["status"] == "no-changes":
            return f"no changed files since {s['base']}"
        return (f"{s['files']} file(s) changed since {s['base']} ({s['committed']} committed, "
                f"{s['uncommitted']} uncommitted): {counts}")
    gate = "" if s["fail_under"] is None else f", fail-under {s['fail_under']:g} %"
    return f"share {s['share']} ({percent(s['share'])} %), {s['unmapped']} unmapped{gate}"


UNMAPPED_SHOWN = 5


def _render(d, unmapped: list[str]) -> None:
    for step in d["steps"]:
        print(f"{step['name']:<9} {step['status']:<12} {_summary(step)}")
        if step["status"] == "failed":
            if step["name"] == "coverage":
                for f in unmapped[:UNMAPPED_SHOWN]:
                    print(f"  {f}")
                print("  run modsys coverage for the full list")
            else:
                for f in step.get("findings", []):
                    where = f"  ({f['path']})" if f["path"] else ""
                    print(f"  {f['severity'].upper():<7} {f['code']} {f['module']}: "
                          f"{f['message']}{where}")
    for note in d["notes"]:
        print(f"note: {note}")
    print(f"ci: {'failed' if d['failed'] else 'passed'}")
