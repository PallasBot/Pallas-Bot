"""分片：AI 异步任务登记，供 hub 将 /callback 转发到对应 worker。"""

from __future__ import annotations

import os
import time
from typing import Any

from src.platform.shard.coord.ai_task_registry_redis import (
    read_ai_task_redis_sync,
    remove_ai_task_redis_sync,
    write_ai_task_redis_sync,
)
from src.platform.shard.coord.maa_route_registry import current_worker_port
from src.platform.shard.registry import get_shard_registry, worker_port_for_shard
from src.platform.shard.registry.config import get_shard_registry_settings, is_sharding_active
from src.platform.shard.registry.store import assign_bot_to_shard

_DEFAULT_TTL_SEC = 86400.0


def ai_task_ttl_sec() -> float:
    raw = os.getenv("PALLAS_AI_TASK_TTL_SEC", "").strip()
    try:
        ttl = float(raw) if raw else _DEFAULT_TTL_SEC
    except ValueError:
        ttl = _DEFAULT_TTL_SEC
    return max(600.0, ttl)


def _is_stale(rec: dict[str, Any]) -> bool:
    start = float(rec.get("start_time") or 0)
    return start <= 0 or (time.time() - start) > ai_task_ttl_sec()


def build_ai_task_record(task_id: str, task_status: dict[str, Any]) -> dict[str, Any] | None:
    bot_raw = task_status.get("bot_id")
    if bot_raw is None:
        return None
    bot_id = str(bot_raw).strip()
    if not bot_id.isdigit():
        return None
    reg = get_shard_registry()
    local_port = current_worker_port()
    if local_port is not None:
        sid = int(get_shard_registry_settings().shard_id)
        port = int(local_port)
    else:
        sid = reg.shard_for_bot(bot_id)
        if sid is None:
            sid = assign_bot_to_shard(bot_id, registry=reg)
        port = worker_port_for_shard(int(sid), registry=reg)
    return {
        "task_id": task_id,
        "bot_id": bot_id,
        "group_id": task_status.get("group_id"),
        "shard_id": int(sid),
        "worker_port": int(port),
        "start_time": float(task_status.get("start_time") or time.time()),
    }


def register_ai_task(task_id: str, task_status: dict[str, Any]) -> None:
    if not is_sharding_active():
        return
    rec = build_ai_task_record(task_id, task_status)
    if rec is None:
        return
    ttl = int(ai_task_ttl_sec())
    write_ai_task_redis_sync(rec, ttl_sec=ttl)


def remove_ai_task(task_id: str) -> None:
    if not is_sharding_active():
        return
    remove_ai_task_redis_sync(task_id)


def get_ai_task_record(task_id: str) -> dict[str, Any] | None:
    if not is_sharding_active():
        return None
    rec = read_ai_task_redis_sync(task_id)
    if not rec or _is_stale(rec):
        remove_ai_task(task_id)
        return None
    return rec


def resolve_worker_port_for_task(task_id: str) -> int | None:
    rec = get_ai_task_record(task_id)
    if not rec:
        return None
    try:
        return int(rec["worker_port"])
    except (KeyError, TypeError, ValueError):
        return None
