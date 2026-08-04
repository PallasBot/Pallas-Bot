"""`pallas logs`：默认看 unified Bot + embed 辅进程，不强迫记 worker-N。"""

from __future__ import annotations

import argparse  # noqa: TC003
import sys

from pallas.console.cli.log_paths import (
    SHARD_LOG_DIR,
    list_default_log_targets,
    read_log_tail,
)
from pallas.console.cli.runtime_mode import resolve_bot_mode, runtime_instance_summary


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "logs",
        help="打印默认日志路径与尾部（unified+aux；分片仅 hub）",
    )
    parser.add_argument(
        "--mode",
        choices=("auto", "unified", "shard"),
        default="auto",
        help="运行编排（默认 auto）",
    )
    parser.add_argument(
        "-n",
        "--lines",
        type=int,
        default=40,
        metavar="N",
        help="每个目标打印末尾行数（0=仅路径）",
    )
    parser.add_argument(
        "--paths-only",
        action="store_true",
        help="只列路径，不读内容",
    )
    parser.set_defaults(handler=run_logs)


def run_logs(args: argparse.Namespace) -> int:
    mode = resolve_bot_mode(args.mode)
    lines = 0 if args.paths_only else max(0, int(args.lines))
    summary = runtime_instance_summary(mode)
    print(f"Pallas · 运行日志 · {summary['label']} · 实例 {summary['running_instances']}")
    for label, path in list_default_log_targets(mode=mode):
        if path.is_dir():
            print(f"  · {label}: {path}")
            continue
        exists = "有" if path.is_file() else "无"
        print(f"  · {label}: {path} [{exists}]")
        if lines <= 0:
            continue
        body = read_log_tail(path, lines=lines)
        if not body:
            print("    (空或不存在)")
            continue
        print("    ---")
        for line in body.splitlines():
            print(f"    {line}")
        print("    ---")
    if mode == "shard":
        print(f"  · 消息实例进阶日志目录: {SHARD_LOG_DIR}/worker-*.log")
        print("    需要账号级排障时再打开对应消息实例日志。", file=sys.stderr)
    return 0
