from __future__ import annotations

import argparse  # noqa: TC003
import os
import shutil
import sys

from pallas.console.cli.bot_process import bot_lifecycle_available
from pallas.console.cli.runtime_mode import detect_running_bot_mode, resolve_bot_mode
from pallas.console.cli.shard_redis_check import shard_redis_doctor_lines
from pallas.core.foundation.config.repo_settings import repo_config_path
from pallas.core.foundation.paths import PROJECT_ROOT


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("doctor", help="环境与健康检查")
    parser.set_defaults(handler=run)


def run(_args: argparse.Namespace) -> int:
    issues = 0
    if shutil.which("uv") is None:
        print("未找到 uv（PATH）", file=sys.stderr)
        issues += 1
    else:
        print("uv: ok")

    if not (PROJECT_ROOT / "pyproject.toml").is_file():
        print(f"缺少 {PROJECT_ROOT / 'pyproject.toml'}", file=sys.stderr)
        issues += 1
    else:
        print(f"pyproject.toml: ok ({PROJECT_ROOT})")

    config_path = repo_config_path()
    if not config_path.is_file():
        print(
            f"未找到 {config_path}（可复制 config/pallas.example.toml）",
            file=sys.stderr,
        )
        issues += 1
    else:
        print(f"config: ok ({config_path})")

    if bot_lifecycle_available():
        print("lifecycle scripts: ok")
    else:
        print("lifecycle scripts: 缺少 run_unified_bot.sh 或 run_sharded_bot.sh", file=sys.stderr)
        issues += 1

    running = detect_running_bot_mode()
    if running:
        print(f"bot runtime: 运行中 ({running})")
    else:
        print("bot runtime: 未运行")

    resolved = resolve_bot_mode("auto")
    shard_env = os.environ.get("PALLAS_SHARD_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")
    if resolved == "shard" or running == "shard" or shard_env:
        for line in shard_redis_doctor_lines():
            print(line)
            if "不可达" in line or line.endswith("coord redis: 未配置 REDIS_URL"):
                issues += 1

    return 1 if issues else 0
