"""检测 unified / 分片运行态。"""

from __future__ import annotations

import os
from pathlib import Path  # noqa: TC003

from pallas.core.foundation.paths import PROJECT_ROOT

UNIFIED_PID_FILE = PROJECT_ROOT / "data" / "pallas_unified" / "run" / "bot.pid"
SHARD_HUB_PID_FILE = PROJECT_ROOT / "data" / "pallas_shard" / "run" / "hub.pid"


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def read_pid_file(path: Path) -> int | None:
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw.isdigit():
        return None
    return int(raw)


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
