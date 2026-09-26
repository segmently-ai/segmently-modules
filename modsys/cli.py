import argparse
import os
import sys
from pathlib import Path

from modsys import __version__
from modsys import (ci_cmd, code_map_cmd, coverage_cmd, create_cmd, hooks_cmd, index_cmd,
                    init_cmd, lint, match, migrate_cmd, pipeline, proposals_cmd, query,
                    registry_cmd, schema_cmd, sync_cmd)
from modsys.output import EXIT_INTERRUPTED, EXIT_USAGE, UsageError

COMMANDS: list = [init_cmd, schema_cmd, match, query, lint, registry_cmd, index_cmd,
                  proposals_cmd, hooks_cmd, sync_cmd, create_cmd, migrate_cmd, pipeline,
                  coverage_cmd, code_map_cmd, ci_cmd]


def common_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", type=Path, help="repository root (default: auto-detect)")
    common.add_argument("--config-dir", type=Path, help="config dir (default: <root>/.modsys)")
    common.add_argument("--json", action="store_true", help="JSON envelope on stdout")
    return common


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="modsys", description="Module-system engine")
    p.add_argument("--version", action="version", version=f"modsys {__version__}")
    sub = p.add_subparsers(dest="verb", required=True)
    common = common_parser()
    for command in COMMANDS:
        command.register(sub, common)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except UsageError as e:
        print(f"modsys: error: {e}", file=sys.stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:  # Ctrl-C (lock wait, `create` prompt): no traceback either
        print("modsys: interrupted", file=sys.stderr)
        return EXIT_INTERRUPTED
    except Exception as e:  # headless contract: exit 2, never a traceback
        if os.environ.get("MODSYS_DEBUG"):
            raise
        print(f"modsys: internal error: {type(e).__name__}: {e} "
              f"(set MODSYS_DEBUG=1 for a traceback)", file=sys.stderr)
        return EXIT_USAGE
