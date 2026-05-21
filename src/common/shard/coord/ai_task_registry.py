"""分片：AI 异步任务登记，供 hub 将 /callback 转发到对应 worker。"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from src.common.paths import plugin_data_dir
from src.common.shard.registry import get_shard_registry, worker_port_for_shard
from src.common.shard.registry.config import is_sharding_active
from src.common.shard.registry.store import assign_bot_to_shard

_PLUGIN = "pallas_shard"
_TTL_SEC = 600.0


def _tasks_dir() -> Path:
    root = Path(plugin_data_dir(_PLUGIN, create=True)) / "coord" / "ai_tasks"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _task_path(task_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in task_id)
    return _tasks_dir() / f"{safe}.json"


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


def _read(path: Path) -> dict[str, Any] | None:
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


def _is_stale(rec: dict[str, Any]) -> bool:
    start = float(rec.get("start_time") or 0)
    return start <= 0 or (time.time() - start) > _TTL_SEC


def register_ai_task(task_id: str, task_status: dict[str, Any]) -> None:
    if not is_sharding_active():
        return
    bot_raw = task_status.get("bot_id")
    if bot_raw is None:
        return
    bot_id = str(bot_raw).strip()
    if not bot_id.isdigit():
        return
    reg = get_shard_registry()
    sid = reg.shard_for_bot(bot_id)
    if sid is None:
        sid = assign_bot_to_shard(bot_id, registry=reg)
    port = worker_port_for_shard(int(sid), registry=reg)
    path = _task_path(task_id)
    lk = _lock_path(path)
    fd = _acquire_lock(lk)
    if fd is None:
        return
    try:
        _write_atomic(
            path,
            {
                "task_id": task_id,
                "bot_id": bot_id,
                "group_id": task_status.get("group_id"),
                "shard_id": int(sid),
                "worker_port": int(port),
                "start_time": float(task_status.get("start_time") or time.time()),
            },
        )
    finally:
        _release_lock(fd, lk)


def remove_ai_task(task_id: str) -> None:
    if not is_sharding_active():
        return
    path = _task_path(task_id)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def resolve_worker_port_for_task(task_id: str) -> int | None:
    if not is_sharding_active():
        return None
    path = _task_path(task_id)
    rec = _read(path)
    if not rec or _is_stale(rec):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    try:
        return int(rec["worker_port"])
    except (KeyError, TypeError, ValueError):
        return None
