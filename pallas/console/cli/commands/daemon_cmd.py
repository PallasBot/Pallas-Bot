from __future__ import annotations

import argparse  # noqa: TC003

from pallas.console.cli.daemon import run_daemon


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("daemon", help="守护 unified Bot，探活失败时自动重启")
    parser.add_argument("--interval", type=float, default=15.0, help="探活间隔（秒），默认 15")
    parser.add_argument("--timeout", type=float, default=5.0, help="单次探活超时（秒），默认 5")
    parser.add_argument("--fail-threshold", type=int, default=3, help="连续失败多少次后重启，默认 3")
    parser.add_argument("--cooldown", type=float, default=5.0, help="重启后等待秒数，默认 5")
    parser.add_argument("--port", type=int, help="覆盖 Bot 控制台端口，默认读取配置")
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    return run_daemon(
        interval=args.interval,
        timeout=args.timeout,
        fail_threshold=args.fail_threshold,
        cooldown=args.cooldown,
        port=args.port,
    )
