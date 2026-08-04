from __future__ import annotations

import argparse  # noqa: TC003

from pallas.console.cli.redis_ops import redis_status, start_redis


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("redis", help="检查或创建项目 Redis（分片 / AI 可共用）")
    redis_sub = parser.add_subparsers(dest="redis_command", required=True)
    redis_sub.add_parser("start", help="复用或创建仅回环暴露的 Docker Redis").set_defaults(handler=run_start)
    redis_sub.add_parser("status", help="检查 REDIS_URL 连通性").set_defaults(handler=run_status)


def run_start(_args: argparse.Namespace) -> int:
    return start_redis()


def run_status(_args: argparse.Namespace) -> int:
    return redis_status()
