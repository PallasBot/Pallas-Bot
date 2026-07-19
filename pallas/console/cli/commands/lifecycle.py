from __future__ import annotations

import argparse  # noqa: TC003
import sys

from pallas.console.cli.bot_process import bot_lifecycle_available, run_bot_lifecycle


def add_mode_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--mode",
        choices=("auto", "unified", "shard"),
        default="auto",
        help="运行编排（默认 auto：按 pid 或环境推断）",
    )


def register_run(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("run", help="启动 Bot（单进程或分片）")
    run_sub = parser.add_subparsers(dest="run_mode", required=True)

    unified = run_sub.add_parser("unified", help="单进程 unified")
    unified.add_argument(
        "--skip-port-sync",
        action="store_true",
        help="启动前不同步协议端 ws_url",
    )
    unified.set_defaults(handler=run_unified)

    shard = run_sub.add_parser("shard", help="分片 hub + worker")
    shard.add_argument("--hub-only", action="store_true")
    shard.add_argument("--workers-only", action="store_true")
    shard.add_argument("--workers", metavar="N")
    shard.add_argument("--worker-base", metavar="PORT")
    shard.add_argument("--skip-port-sync", action="store_true")
    shard.set_defaults(handler=run_shard)


def register_lifecycle(sub: argparse._SubParsersAction) -> None:
    for name, help_text in (
        ("stop", "停止当前编排的 Bot 进程"),
        ("status", "查看运行状态"),
        ("restart", "停止后重新启动"),
    ):
        parser = sub.add_parser(name, help=help_text)
        add_mode_argument(parser)
        if name == "restart":
            parser.add_argument("--workers-only", action="store_true", help="分片：仅重启 worker")
            parser.add_argument("--hub-only", action="store_true", help="分片：仅重启 hub")
            parser.add_argument("--skip-port-sync", action="store_true")
        parser.set_defaults(handler=lambda args, action=name: run_lifecycle(action, args))


def run_unified(args: argparse.Namespace) -> int:
    extra: list[str] = []
    if args.skip_port_sync:
        extra.append("--skip-port-sync")
    return run_bot_lifecycle("start", mode="unified", extra_args=extra)


def run_shard(args: argparse.Namespace) -> int:
    extra: list[str] = []
    if args.hub_only:
        extra.append("--hub-only")
    if args.workers_only:
        extra.append("--workers-only")
    if args.workers:
        extra.extend(["--workers", str(args.workers)])
    if args.worker_base:
        extra.extend(["--worker-base", str(args.worker_base)])
    if args.skip_port_sync:
        extra.append("--skip-port-sync")
    return run_bot_lifecycle("start", mode="shard", extra_args=extra)


def run_lifecycle(action: str, args: argparse.Namespace) -> int:
    if not bot_lifecycle_available():
        print("缺少 run_unified_bot.sh 或 run_sharded_bot.sh", file=sys.stderr)
        return 1
    extra: list[str] = []
    if action == "restart":
        if getattr(args, "workers_only", False):
            extra.append("--workers-only")
        if getattr(args, "hub_only", False):
            extra.append("--hub-only")
        if getattr(args, "skip_port_sync", False):
            extra.append("--skip-port-sync")
    return run_bot_lifecycle(action, mode=args.mode, extra_args=extra or None)
