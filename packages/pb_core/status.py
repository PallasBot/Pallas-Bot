"""牛牛核心：进程/分片/版本摘要。"""

from __future__ import annotations

from nonebot import get_bots

from pallas.console.cli.bot_process import bot_lifecycle_available
from pallas.console.cli.runtime_mode import detect_running_bot_mode
from pallas.core.foundation.bot_version import get_bot_current_version, get_pallas_bot_version_for_reporting
from pallas.core.platform.shard import context as shard_ctx


def format_runtime_status_text() -> str:
    lines: list[str] = []
    version = get_pallas_bot_version_for_reporting()
    lines.append(f"版本：{version or 'unknown'}")

    git_info = get_bot_current_version()
    commit = (git_info.get("commit") or "").strip()
    tag = (git_info.get("tag") or "").strip()
    if commit:
        suffix = f"（{tag}）" if tag else ""
        lines.append(f"Git：{commit}{suffix}")

    if shard_ctx.sharding_active():
        lines.append(f"分片：{shard_ctx.role()} · shard #{shard_ctx.shard_id()}")
    else:
        lines.append("运行模式：单进程 unified")

    detected = detect_running_bot_mode()
    if detected:
        lines.append(f"编排脚本检测：{detected} 运行中")
    elif bot_lifecycle_available():
        lines.append("编排脚本检测：未运行（当前应为 nb 前台或自定义守护）")

    bots = get_bots()
    if bots:
        ids = ", ".join(sorted(bots.keys()))
        lines.append(f"本进程已连接牛牛：{len(bots)}（{ids}）")
    else:
        lines.append("本进程已连接牛牛：0")

    return "\n".join(lines)
