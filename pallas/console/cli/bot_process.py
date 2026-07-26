"""包装 Bot 启停：unified 走 Python；shard 经可解析的 bash 调用脚本。"""

from __future__ import annotations

import sys
import time
from collections.abc import Sequence  # noqa: TC003
from pathlib import Path  # noqa: TC003

from pallas.console.cli.process_util import (
    is_windows,
    resolve_bash,
    run_bash_script,
    spawn_detached,
)
from pallas.console.cli.runtime_mode import resolve_bot_mode
from pallas.console.cli.unified_lifecycle import run_unified_action
from pallas.core.foundation.paths import PROJECT_ROOT

UNIFIED_SCRIPT = PROJECT_ROOT / "scripts" / "run_unified_bot.sh"
SHARD_SCRIPT = PROJECT_ROOT / "scripts" / "run_sharded_bot.sh"


def script_for_mode(mode: str) -> Path:
    return SHARD_SCRIPT if mode == "shard" else UNIFIED_SCRIPT


def bot_lifecycle_available() -> bool:
    """unified 已由 Python 实现；shard 仍需脚本（有 bash 时可跑）。"""
    return True


def shard_lifecycle_available() -> bool:
    return SHARD_SCRIPT.is_file() and resolve_bash() is not None


def run_bot_lifecycle(
    action: str,
    *,
    mode: str = "auto",
    extra_args: Sequence[str] | None = None,
) -> int:
    resolved = resolve_bot_mode(mode)
    extra = list(extra_args or ())
    if resolved == "unified":
        skip_port_sync = "--skip-port-sync" in extra
        return run_unified_action(action, skip_port_sync=skip_port_sync)

    if not SHARD_SCRIPT.is_file():
        print(f"缺少脚本 {SHARD_SCRIPT}", file=sys.stderr)
        return 1
    if resolve_bash() is None:
        print(
            "分片启停仍依赖 bash 脚本。\n"
            + (
                "Windows 请安装 Git for Windows（bash 在 PATH）或使用 WSL；"
                "单进程请用：uv run pallas / uv run pallas run unified。"
                if is_windows()
                else "请安装 bash 或检查 PATH。"
            ),
            file=sys.stderr,
        )
        return 1
    return run_bash_script(
        SHARD_SCRIPT,
        [action, *extra],
        cwd=PROJECT_ROOT,
        purpose="分片启停",
    )


def restart_after_delay(delay_s: float, mode: str, workers_only: bool) -> None:
    time.sleep(delay_s)
    extra: list[str] = []
    if workers_only and mode == "shard":
        extra.append("--workers-only")
    raise SystemExit(run_bot_lifecycle("restart", mode=mode, extra_args=extra))


def schedule_bot_restart(
    *,
    mode: str = "auto",
    workers_only: bool = False,
    delay_s: float = 2.0,
) -> bool:
    try:
        from packages.pb_webui.api import invalidate_health_snapshot
        from packages.pb_webui.restart_state import mark_restart_requested

        mark_restart_requested(workers_only=workers_only)
        invalidate_health_snapshot()
    except Exception:
        pass
    resolved = resolve_bot_mode(mode)
    if resolved == "shard" and resolve_bash() is None:
        return False
    py = (
        "from pallas.console.cli.bot_process import restart_after_delay; "
        f"restart_after_delay({delay_s!r}, {resolved!r}, {workers_only!r})"
    )
    try:
        spawn_detached(
            [sys.executable, "-c", py],
            cwd=PROJECT_ROOT,
        )
    except OSError:
        return False
    return True
