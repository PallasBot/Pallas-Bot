"""检测 unified / 分片运行态。"""

from __future__ import annotations

import os

from pallas.console.cli.process_util import pid_alive, read_pid_file
from pallas.core.foundation.paths import PROJECT_ROOT

UNIFIED_PID_FILE = PROJECT_ROOT / "data" / "pallas_unified" / "run" / "bot.pid"
SHARD_HUB_PID_FILE = PROJECT_ROOT / "data" / "pallas_shard" / "run" / "hub.pid"

__all__ = [
    "UNIFIED_PID_FILE",
    "SHARD_HUB_PID_FILE",
    "detect_running_bot_mode",
    "pid_alive",
    "read_pid_file",
    "resolve_bot_mode",
]


def detect_running_bot_mode() -> str | None:
    shard_pid = read_pid_file(SHARD_HUB_PID_FILE)
    if shard_pid is not None and pid_alive(shard_pid):
        return "shard"
    unified_pid = read_pid_file(UNIFIED_PID_FILE)
    if unified_pid is not None and pid_alive(unified_pid):
        return "unified"
    return None


def resolve_bot_mode(mode: str) -> str:
    normalized = (mode or "auto").strip().lower()
    if normalized in ("unified", "shard"):
        return normalized
    detected = detect_running_bot_mode()
    if detected:
        return detected
    shard_env = os.environ.get("PALLAS_SHARD_ENABLED", "").strip().lower()
    if shard_env in ("1", "true", "yes", "on"):
        return "shard"
    return "unified"
