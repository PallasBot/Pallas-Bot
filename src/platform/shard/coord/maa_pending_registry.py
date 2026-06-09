"""分片：MAA 待拉取任务队列（hub/worker 共享，供 getTask / 状态统计）。"""

from __future__ import annotations

import time
from typing import Any

from nonebot import logger

from src.platform.shard.coord.coord_redis_store import (
    coord_key,
    delete_key_sync,
    mutate_json_sync,
    read_json_sync,
    scan_keys_sync,
    setex_json_sync,
)
from src.plugins.maa.tasks import normalize_device_id

_LOCK_RETRIES = 5
_QUEUE_TTL_SEC = 86400


def _queue_key(user: str, device: str) -> str | None:
    u = (user or "").strip()
    norm = normalize_device_id(device)
    if not u or not norm:
        return None
    return coord_key("maa_pending", "queue", f"{u}_{norm}")


def _index_key(task_id: str) -> str:
    return coord_key("maa_pending", "idx", task_id)


def _queue_ttl(_data: dict[str, Any]) -> int:
    return _QUEUE_TTL_SEC


def _mutate_queue_retry(queue_key: str, fn) -> dict[str, Any] | None:
    last: Exception | None = None
    for attempt in range(_LOCK_RETRIES):
        result = mutate_json_sync(queue_key, fn, ttl_sec_fn=_queue_ttl, retries=3)
        if result is not None:
            return result
        last = TimeoutError(f"failed to mutate pending queue: {queue_key}")
        if attempt + 1 < _LOCK_RETRIES:
            time.sleep(0.05 * (attempt + 1))
    logger.warning("maa pending queue lock timeout after {} tries: {}", _LOCK_RETRIES, queue_key)
    if last is not None:
        logger.debug("maa pending queue lock last error: {}", last)
    return None


def enqueue_task_sync(task: dict[str, Any]) -> None:
    """task 须含 task_id、user、device 等字段。"""
    user = str(task.get("user") or "").strip()
    device = str(task.get("device") or "")
    queue_key = _queue_key(user, device)
    if queue_key is None:
        return
    task_id = str(task.get("task_id") or "")
    if not task_id:
        return

    def add(data: dict[str, Any]) -> None:
        tasks = data.setdefault("tasks", {})
        if not isinstance(tasks, dict):
            data["tasks"] = {}
            tasks = data["tasks"]
        tasks[task_id] = task

    if _mutate_queue_retry(queue_key, add) is None:
        return
    setex_json_sync(
        _index_key(task_id),
        {"task_id": task_id, "user": user, "device": normalize_device_id(device) or device},
        _QUEUE_TTL_SEC,
    )


def list_pending_sync(user: str, device: str) -> list[dict[str, Any]]:
    queue_key = _queue_key(user, device)
    if queue_key is None:
        return []
    data = read_json_sync(queue_key)
    if not data:
        return []
    tasks = data.get("tasks")
    if not isinstance(tasks, dict):
        return []
    out = [t for t in tasks.values() if isinstance(t, dict) and not t.get("reported")]
    out.sort(key=lambda x: float(x.get("created_at") or 0))
    return out


def mark_reported_sync(task_id: str) -> dict[str, Any] | None:
    idx = read_json_sync(_index_key(task_id))
    if not idx:
        return None
    user = str(idx.get("user") or "")
    device = str(idx.get("device") or "")
    queue_key = _queue_key(user, device)
    if queue_key is None:
        return None
    found: dict[str, Any] | None = None

    def mark(data: dict[str, Any]) -> None:
        nonlocal found
        tasks = data.get("tasks")
        if not isinstance(tasks, dict):
            return
        rec = tasks.get(task_id)
        if not isinstance(rec, dict):
            return
        rec["reported"] = True
        found = rec

    if _mutate_queue_retry(queue_key, mark) is None:
        return None
    delete_key_sync(_index_key(task_id))
    return found


def pending_count_for_user_sync(user: str) -> int:
    u = (user or "").strip()
    if not u:
        return 0
    prefix = coord_key("maa_pending", "queue", f"{u}_")
    total = 0
    for key in scan_keys_sync(prefix):
        data = read_json_sync(key)
        if not data:
            continue
        tasks = data.get("tasks")
        if not isinstance(tasks, dict):
            continue
        total += sum(1 for t in tasks.values() if isinstance(t, dict) and not t.get("reported"))
    return total


def pending_count_for_device_sync(user: str, device: str) -> int:
    return len(list_pending_sync(user, device))


def clear_pending_sync(user: str, *, device: str | None = None) -> int:
    u = (user or "").strip()
    if not u:
        return 0
    removed = 0
    if device is not None:
        keys = [_queue_key(u, device)]
    else:
        prefix = coord_key("maa_pending", "queue", f"{u}_")
        keys = scan_keys_sync(prefix)

    for queue_key in keys:
        if queue_key is None:
            continue

        def clear(data: dict[str, Any]) -> None:
            nonlocal removed
            tasks = data.get("tasks")
            if not isinstance(tasks, dict):
                return
            for tid, rec in list(tasks.items()):
                if isinstance(rec, dict) and not rec.get("reported"):
                    del tasks[tid]
                    removed += 1
                    delete_key_sync(_index_key(str(tid)))

        _mutate_queue_retry(queue_key, clear)
    return removed


def pending_type_counts_sync(user: str, *, device: str | None = None) -> dict[str, int]:
    u = (user or "").strip()
    if not u:
        return {}
    counts: dict[str, int] = {}
    if device is not None:
        keys = [_queue_key(u, device)]
    else:
        prefix = coord_key("maa_pending", "queue", f"{u}_")
        keys = scan_keys_sync(prefix)
    for queue_key in keys:
        if queue_key is None:
            continue
        data = read_json_sync(queue_key)
        if not data:
            continue
        tasks = data.get("tasks")
        if not isinstance(tasks, dict):
            continue
        for rec in tasks.values():
            if not isinstance(rec, dict) or rec.get("reported"):
                continue
            name = str(rec.get("task_type") or "")
            if name:
                counts[name] = counts.get(name, 0) + 1
    return counts


async def prune_stale_maa_pending_files(*, max_age_sec: float = 86400.0) -> None:
    """Redis TTL 自动过期。"""
    return None
