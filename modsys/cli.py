import argparse
import sys
from pathlib import Path

from modsys import __version__
from modsys import match, schema_cmd
from modsys.output import EXIT_USAGE, UsageError

COMMANDS: list = [schema_cmd, match]


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
