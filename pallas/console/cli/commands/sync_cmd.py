from __future__ import annotations

import argparse  # noqa: TC003
import asyncio

from pallas.console.cli.sync_ops import run_sync_cli


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("sync", help="同步依赖（包装 uv sync）")
    parser.add_argument(
        "--extra",
        action="append",
        default=[],
        metavar="NAME",
        help="pyproject optional-extra，可重复；deploy-full / deploy-all 仅保留迁移提示",
    )
    parser.add_argument("--dev", action="store_true", help="包含 dev 依赖组（默认 --no-dev）")
    parser.add_argument("--deploy-full", action="store_true", help="提示改用 pallas ext 安装官方扩展")
    parser.add_argument("--deploy-all", action="store_true", help="提示改用 pallas ext 安装官方扩展")
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    return asyncio.run(
        run_sync_cli(
            extras=list(args.extra or []),
            no_dev=not args.dev,
            deploy_full=bool(args.deploy_full),
            deploy_all=bool(args.deploy_all),
        ),
    )
