"""牛牛核心：进程/分片/版本摘要。"""

from __future__ import annotations

import time

from pallas.console.cli.bot_process import bot_lifecycle_available
from pallas.console.cli.runtime_mode import detect_running_bot_mode
from pallas.core.foundation.bot_version import get_bot_current_version, get_pallas_bot_version_for_reporting
from pallas.core.platform.shard import context as shard_ctx

_PROCESS_STARTED_AT = time.monotonic()


def _format_uptime(elapsed_sec: float) -> str:
    total = max(0, int(elapsed_sec))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}天")
    if days or hours:
        parts.append(f"{hours}小时")
    if days or hours or minutes:
        parts.append(f"{minutes}分")
    parts.append(f"{seconds}秒")
    return "".join(parts)


def _coord_redis_line() -> str | None:
    if not shard_ctx.sharding_active():
        return None
    from pallas.core.platform.coord.redis_settings import coord_redis_enabled, resolve_coord_redis_url

    if coord_redis_enabled():
        return "协调 Redis：可达"
    if resolve_coord_redis_url():
        return "协调 Redis：已配置但不可达"
    return "协调 Redis：未配置"


def format_runtime_status_text(*, self_id: str | int | None = None) -> str:
    lines: list[str] = ["【牛牛状态】"]
    version = get_pallas_bot_version_for_reporting()
    lines.append(f"版本：{version or 'unknown'}")

    git_info = get_bot_current_version()
    commit = (git_info.get("commit") or "").strip()
    tag = (git_info.get("tag") or "").strip()
    if commit:
        suffix = f"（{tag}）" if tag else ""
        lines.append(f"Git：{commit}{suffix}")

    if self_id is not None and str(self_id).strip():
        lines.append(f"本机 QQ：{self_id}")

    lines.append(f"运行时长：{_format_uptime(time.monotonic() - _PROCESS_STARTED_AT)}")

    if shard_ctx.sharding_active():
        lines.append(f"分片：{shard_ctx.role()} · shard #{shard_ctx.shard_id()}")
    else:
        lines.append("运行模式：单进程 unified")

    redis_line = _coord_redis_line()
    if redis_line:
        lines.append(redis_line)

    detected = detect_running_bot_mode()
    if detected:
        lines.append(f"编排脚本检测：{detected} 运行中")
    elif bot_lifecycle_available():
        lines.append("编排脚本检测：未运行（当前应为 nb 前台或自定义守护）")

    return "\n".join(lines)
