"""默认日志路径（unified+aux 心智；分片为进阶）。"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003

from pallas.console.cli.runtime_mode import resolve_bot_mode
from pallas.core.foundation.paths import PROJECT_ROOT

UNIFIED_BOT_LOG = PROJECT_ROOT / "data" / "pallas_unified" / "logs" / "bot.log"
EMBED_AUX_LOG = PROJECT_ROOT / "data" / "pallas_embed" / "logs" / "embed.log"
SHARD_HUB_LOG = PROJECT_ROOT / "data" / "pallas_shard" / "logs" / "hub.log"
SHARD_LOG_DIR = PROJECT_ROOT / "data" / "pallas_shard" / "logs"


def default_primary_log(*, mode: str = "auto") -> Path:
    resolved = resolve_bot_mode(mode)
    if resolved == "shard":
        return SHARD_HUB_LOG
    return UNIFIED_BOT_LOG


def list_default_log_targets(*, mode: str = "auto") -> list[tuple[str, Path]]:
    """返回 (标签, 路径)；默认不枚举 worker-N，分片只给 hub + 目录提示。"""
    resolved = resolve_bot_mode(mode)
    if resolved == "shard":
        targets: list[tuple[str, Path]] = [
            ("hub", SHARD_HUB_LOG),
            ("embed 辅进程", EMBED_AUX_LOG),
        ]
        return targets
    return [
        ("Bot (unified)", UNIFIED_BOT_LOG),
        ("embed 辅进程", EMBED_AUX_LOG),
    ]


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
