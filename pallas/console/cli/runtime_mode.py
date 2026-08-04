"""检测 unified / 分片运行态。"""

from __future__ import annotations

import os

from pallas.console.cli.process_util import pid_alive, read_pid_file
from pallas.core.foundation.paths import PROJECT_ROOT

UNIFIED_PID_FILE = PROJECT_ROOT / "data" / "pallas_unified" / "run" / "bot.pid"
SHARD_HUB_PID_FILE = PROJECT_ROOT / "data" / "pallas_shard" / "run" / "hub.pid"
SHARD_RUN_DIR = SHARD_HUB_PID_FILE.parent

__all__ = [
    "UNIFIED_PID_FILE",
    "SHARD_HUB_PID_FILE",
    "detect_running_bot_mode",
    "pid_alive",
    "read_pid_file",
    "resolve_bot_mode",
    "runtime_instance_summary",
]


def detect_running_bot_mode() -> str | None:
    shard_pid = read_pid_file(SHARD_HUB_PID_FILE)
    if shard_pid is not None and pid_alive(shard_pid):
        return "shard"
    for path in SHARD_RUN_DIR.glob("worker-*.pid"):
        worker_pid = read_pid_file(path)
        if worker_pid is not None and pid_alive(worker_pid):
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


def runtime_instance_summary(mode: str = "auto") -> dict[str, object]:
    resolved = resolve_bot_mode(mode)
    if resolved == "unified":
        pid = read_pid_file(UNIFIED_PID_FILE)
        running = pid is not None and pid_alive(pid)
        return {
            "mode": "unified",
            "label": "统一运行时（单实例）",
            "running_instances": int(running),
            "instances": [
                {
                    "name": "消息实例",
                    "kind": "message",
                    "running": running,
                    "pid": pid,
                }
            ],
        }

    instances: list[dict[str, object]] = []
    hub_pid = read_pid_file(SHARD_HUB_PID_FILE)
    instances.append({
        "name": "控制台实例",
        "kind": "control",
        "running": hub_pid is not None and pid_alive(hub_pid),
        "pid": hub_pid,
    })
    for path in sorted(SHARD_RUN_DIR.glob("worker-*.pid")):
        suffix = path.stem.removeprefix("worker-")
        if suffix in {"test", "test2"}:
            continue
        pid = read_pid_file(path)
        instances.append({
            "name": f"消息实例 {suffix}",
            "kind": "message",
            "running": pid is not None and pid_alive(pid),
            "pid": pid,
        })
    return {
        "mode": "shard",
        "label": "统一运行时（多实例）",
        "running_instances": sum(1 for item in instances if item["running"] is True),
        "instances": instances,
    }
