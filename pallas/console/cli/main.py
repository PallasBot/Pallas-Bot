from __future__ import annotations

import argparse  # noqa: TC003
import sys
from importlib import import_module

from pallas.console.cli import CLI_VERSION

_COMMAND_MODULES = (
    "pallas.console.cli.commands.doctor",
    "pallas.console.cli.commands.sync_cmd",
    "pallas.console.cli.commands.ext_cmd",
    "pallas.console.cli.commands.plugin_cmd",
    "pallas.console.cli.commands.update_cmd",
    "pallas.console.cli.commands.lifecycle",
    "pallas.console.cli.commands.maintenance_cmd",
    "pallas.console.cli.commands.deploy_cmd",
    "pallas.console.cli.commands.ai_cmd",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pallas",
        description="Pallas Bot 统一运维：依赖同步、官方插件、启停与更新（无子命令时默认启动单进程 Bot）",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {CLI_VERSION}",
    )
    sub = parser.add_subparsers(dest="command", required=False)
    for module_name in _COMMAND_MODULES:
        module = import_module(module_name)
        if hasattr(module, "register"):
            module.register(sub)
        if hasattr(module, "register_run"):
            module.register_run(sub)
        if hasattr(module, "register_lifecycle"):
            module.register_lifecycle(sub)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is not None:
        return int(handler(args))
    if args.command is None:
        from pallas.console.cli.commands.lifecycle import run_unified

        return int(run_unified(argparse.Namespace(skip_port_sync=False)))
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
