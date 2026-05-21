"""跨 worker 同群决斗互斥：共享 data 层占用，避免多片同时开战。"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from src.common.paths import plugin_data_dir
from src.common.shard.registry.config import (
    get_shard_registry_settings,
    is_sharding_active,
)

_PLUGIN = "pallas_shard"
_BUSY_TTL_SEC = 7200.0
_local_busy: set[int] = set()


def _coord_dir():
    from pathlib import Path

    root = Path(plugin_data_dir(_PLUGIN, create=True)) / "coord" / "duel_group"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _lock_path(group_id: int):
    return _coord_dir() / f"{int(group_id)}.json"


def _session_lock_path(path) -> Any:
    return path.with_suffix(path.suffix + ".lock")


def _acquire_lock(lock_path, *, timeout: float = 3.0) -> int | None:
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


def _release_lock(fd: int | None, lock_path) -> None:
    if fd is not None:
        try:
            os.close(fd)
        except OSError:
            pass
    try:
        lock_path.unlink(missing_ok=True)
    except OSError:
        pass


def _read(path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _write_atomic(path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _mutate(path, fn) -> dict[str, Any] | None:
    lk = _session_lock_path(path)
    fd = _acquire_lock(lk)
    if fd is None:
        return _read(path)
    try:
        data = _read(path) or {}
        fn(data)
        _write_atomic(path, data)
        return data
    finally:
        _release_lock(fd, lk)


def try_begin_duel_group(group_id: int) -> bool:
    """同群同时进行中的决斗至多一场（分片时跨 worker）。"""
    gid = int(group_id)
    if not is_sharding_active():
        if gid in _local_busy:
            return False
        _local_busy.add(gid)
        return True

    path = _lock_path(gid)
    now = time.time()
    sid = get_shard_registry_settings().shard_id
    acquired = False

    def claim(data: dict[str, Any]) -> None:
        nonlocal acquired
        until = float(data.get("until") or 0)
        if until > now and data.get("busy"):
            acquired = False
            return
        data.update({
            "group_id": gid,
            "busy": True,
            "until": now + _BUSY_TTL_SEC,
            "shard_id": int(sid),
            "acquired_at": now,
        })
        acquired = True

    _mutate(path, claim)
    return acquired


def end_duel_group(group_id: int) -> None:
    gid = int(group_id)
    if not is_sharding_active():
        _local_busy.discard(gid)
        return

    path = _lock_path(gid)

    def release(data: dict[str, Any]) -> None:
        data["busy"] = False
        data["until"] = 0

    _mutate(path, release)
