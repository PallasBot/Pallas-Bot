"""默认日志路径（unified+aux 心智；分片为进阶）。"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003

from pallas.console.cli.runtime_mode import resolve_bot_mode
from pallas.core.foundation.paths import PROJECT_ROOT

BOT_LOG_DIR = PROJECT_ROOT / "data" / "bot"
UNIFIED_LAUNCHER_LOG_DIR = PROJECT_ROOT / "data" / "pallas_unified" / "logs"
UNIFIED_BOT_LOG = UNIFIED_LAUNCHER_LOG_DIR / "bot.log"
EMBED_AUX_LOG = PROJECT_ROOT / "data" / "pallas_embed" / "logs" / "embed.log"
SHARD_HUB_LOG = PROJECT_ROOT / "data" / "pallas_shard" / "logs" / "hub.log"
SHARD_LOG_DIR = PROJECT_ROOT / "data" / "pallas_shard" / "logs"


def default_primary_log(*, mode: str = "auto") -> Path:
    resolved = resolve_bot_mode(mode)
    if resolved == "shard":
        return SHARD_HUB_LOG
    return UNIFIED_BOT_LOG


def latest_bot_log() -> Path | None:
    try:
        return max(BOT_LOG_DIR.glob("nonebot_*.log"), key=lambda path: path.stat().st_mtime)
    except (OSError, ValueError):
        return None


def list_default_log_targets(*, mode: str = "auto") -> list[tuple[str, Path]]:
    """返回 (标签, 路径)；优先业务日志，默认不枚举 worker-N。"""
    resolved = resolve_bot_mode(mode)
    bot_log = latest_bot_log()
    bot_targets = [("Bot 业务日志", bot_log)] if bot_log is not None else []
    if resolved == "shard":
        targets: list[tuple[str, Path]] = [*bot_targets, ("hub", SHARD_HUB_LOG), ("embed 辅进程", EMBED_AUX_LOG)]
        return targets
    return [*bot_targets, ("启动器日志目录", UNIFIED_LAUNCHER_LOG_DIR), ("embed 辅进程", EMBED_AUX_LOG)]


def read_log_tail(path: Path, *, lines: int = 40) -> str:
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    parts = text.splitlines()
    if lines <= 0:
        return text
    return "\n".join(parts[-lines:])
