"""分片：MAA 待拉取任务队列（hub/worker 共享 data，供 getTask / 状态统计）。"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from nonebot import logger

from src.common.paths import plugin_data_dir
from src.plugins.maa.tasks import normalize_device_id

_PLUGIN = "pallas_shard"
_LOCK_RETRIES = 5


def _root() -> Path:
    root = Path(plugin_data_dir(_PLUGIN, create=True)) / "coord" / "maa_pending"
    root.mkdir(parents=True, exist_ok=True)
    (root / "queues").mkdir(parents=True, exist_ok=True)
    (root / "task_index").mkdir(parents=True, exist_ok=True)
    return root


def _queue_path(user: str, device: str) -> Path | None:
    u = (user or "").strip()
    norm = normalize_device_id(device)
    if not u or not norm:
        return None
    return _root() / "queues" / f"{u}_{norm}.json"


def _index_path(task_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in task_id)
    return _root() / "task_index" / f"{safe}.json"


def _lock_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".lock")


def _acquire_lock(lock_path: Path, *, timeout: float = 3.0) -> int | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            return os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                if time.time() - lock_path.stat().st_mtime > 10.0:
                    lock_path.unlink(missing_ok=True)
            except OSError:
                pass
            time.sleep(0.02)
    return None


def _release_lock(fd: int | None, lock_path: Path) -> None:
    if fd is not None:
        try:
            os.close(fd)
        except OSError:
            pass
    try:
        lock_path.unlink(missing_ok=True)
    except OSError:
        pass


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _write_atomic(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _mutate_queue(path: Path, fn) -> dict[str, Any]:
    lk = _lock_path(path)
    fd = _acquire_lock(lk)
    if fd is None:
        raise TimeoutError(f"failed to acquire lock for pending queue: {path}")
    try:
        data = _read_json(path) or {"tasks": {}}
        tasks = data.get("tasks")
        if not isinstance(tasks, dict):
            data["tasks"] = {}
        fn(data)
        _write_atomic(path, data)
        return data
    finally:
        _release_lock(fd, lk)


def _mutate_queue_retry(path: Path, fn) -> dict[str, Any] | None:
    last: TimeoutError | None = None
    for attempt in range(_LOCK_RETRIES):
        try:
            return _mutate_queue(path, fn)
        except TimeoutError as err:
            last = err
            if attempt + 1 < _LOCK_RETRIES:
                time.sleep(0.05 * (attempt + 1))
    logger.warning(
        "maa pending queue lock timeout after {} tries: {}",
        _LOCK_RETRIES,
        path,
    )
    if last is not None:
        logger.debug("maa pending queue lock last error: {}", last)
    return None


def enqueue_task_sync(task: dict[str, Any]) -> None:
    """task 须含 task_id、user、device 等字段。"""
    user = str(task.get("user") or "").strip()
    device = str(task.get("device") or "")
    path = _queue_path(user, device)
    if path is None:
        return
    task_id = str(task.get("task_id") or "")
    if not task_id:
        return

    def add(data: dict[str, Any]) -> None:
        data["tasks"][task_id] = task

    if _mutate_queue_retry(path, add) is None:
        return
    idx = _index_path(task_id)
    _write_atomic(
        idx,
        {"task_id": task_id, "user": user, "device": normalize_device_id(device) or device},
    )


def list_pending_sync(user: str, device: str) -> list[dict[str, Any]]:
    path = _queue_path(user, device)
    if path is None:
        return []
    data = _read_json(path)
    if not data:
        return []
    tasks = data.get("tasks")
    if not isinstance(tasks, dict):
        return []
    out = [t for t in tasks.values() if isinstance(t, dict) and not t.get("reported")]
    out.sort(key=lambda x: float(x.get("created_at") or 0))
    return out


def mark_reported_sync(task_id: str) -> dict[str, Any] | None:
    idx = _read_json(_index_path(task_id))
    if not idx:
        return None
    user = str(idx.get("user") or "")
    device = str(idx.get("device") or "")
    path = _queue_path(user, device)
    if path is None:
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

    if _mutate_queue_retry(path, mark) is None:
        return None
    try:
        _index_path(task_id).unlink(missing_ok=True)
    except OSError:
        pass
    return found


def pending_count_for_user_sync(user: str) -> int:
    u = (user or "").strip()
    if not u:
        return 0
    total = 0
    queues = _root() / "queues"
    prefix = f"{u}_"
    for path in queues.glob(f"{prefix}*.json"):
        data = _read_json(path)
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
    queues = _root() / "queues"
    if device is not None:
        path = _queue_path(u, device)
        paths = [path] if path is not None else []
    else:
        paths = list(queues.glob(f"{u}_*.json"))

    for path in paths:
        if path is None or not path.is_file():
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
                    try:
                        _index_path(str(tid)).unlink(missing_ok=True)
                    except OSError:
                        pass

        _mutate_queue_retry(path, clear)
    return removed


def pending_type_counts_sync(user: str, *, device: str | None = None) -> dict[str, int]:
    u = (user or "").strip()
    if not u:
        return {}
    counts: dict[str, int] = {}
    queues = _root() / "queues"
    if device is not None:
        path = _queue_path(u, device)
        paths = [path] if path is not None else []
    else:
        paths = list(queues.glob(f"{u}_*.json"))
    for path in paths:
        if path is None or not path.is_file():
            continue
        data = _read_json(path)
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
    root = _root()
    now = time.time()
    for sub in ("queues", "task_index"):
        dir_path = root / sub
        if not dir_path.is_dir():
            continue
        for path in dir_path.glob("*.json"):
            try:
                if now - path.stat().st_mtime > max_age_sec:
                    path.unlink(missing_ok=True)
            except OSError:
                pass
