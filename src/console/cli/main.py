from __future__ import annotations

import argparse  # noqa: TC003
import sys

from src.console.cli import CLI_VERSION
from src.console.cli.commands import deploy_cmd, doctor, ext_cmd, lifecycle, sync_cmd, update_cmd


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pallas",
        description="Pallas Bot 统一运维：依赖同步、官方扩展、启停与更新",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {CLI_VERSION}",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    doctor.register(sub)
    sync_cmd.register(sub)
    ext_cmd.register(sub)
    update_cmd.register(sub)
    lifecycle.register_run(sub)
    lifecycle.register_lifecycle(sub)
    deploy_cmd.register(sub)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 2
    return int(handler(args))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
