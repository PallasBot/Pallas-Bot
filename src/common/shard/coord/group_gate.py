"""跨 worker 群级短占位（广播 slot / 插件 owned gate）。"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from src.common.paths import plugin_data_dir

_PLUGIN = "pallas_shard"


def _coord_dir():
    from pathlib import Path

    root = Path(plugin_data_dir(_PLUGIN, create=True)) / "coord" / "group_gate"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _gate_path(kind: str, plugin: str, group_id: int) -> Any:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in f"{kind}_{plugin}_{group_id}")
    return _coord_dir() / f"{safe}.json"


def _lock_path(path) -> Any:
    return path.with_suffix(path.suffix + ".lock")


def _acquire_lock(lock_path, *, timeout: float = 2.0) -> int | None:
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


def try_acquire_broadcast_slot_sync(plugin: str, group_id: int, *, ttl_sec: float) -> bool:
    """分片：同群短时仅首次占位成功。"""
    path = _gate_path("broadcast", plugin, group_id)
    now = time.time()
    ttl = max(0.1, float(ttl_sec))
    ok = False
    lk = _lock_path(path)
    fd = _acquire_lock(lk)
    if fd is None:
        data = _read(path)
        until = float((data or {}).get("until") or 0)
        return until <= now
    try:
        data = _read(path) or {}
        until = float(data.get("until") or 0)
        if now < until:
            ok = False
        else:
            data.update({"plugin": plugin, "group_id": int(group_id), "until": now + ttl, "kind": "broadcast"})
            _write_atomic(path, data)
            ok = True
    finally:
        _release_lock(fd, lk)
    return ok


def try_begin_owned_gate_sync(plugin: str, group_id: int, bot_id: int, *, gate_sec: float) -> bool:
    """分片：窗口内仅 owner bot 可通过。"""
    path = _gate_path("owned", plugin, group_id)
    now = time.time()
    ttl = max(1.0, float(gate_sec))
    ok = False
    lk = _lock_path(path)
    fd = _acquire_lock(lk)
    if fd is None:
        data = _read(path)
        if not data:
            return False
        until = float(data.get("until") or 0)
        if now >= until:
            return True
        return int(data.get("owner_bot_id") or 0) == int(bot_id)
    try:
        data = _read(path) or {}
        until = float(data.get("until") or 0)
        owner = int(data.get("owner_bot_id") or 0)
        if now < until:
            ok = owner == int(bot_id)
        else:
            data.update({
                "plugin": plugin,
                "group_id": int(group_id),
                "owner_bot_id": int(bot_id),
                "until": now + ttl,
                "kind": "owned",
            })
            _write_atomic(path, data)
            ok = True
    finally:
        _release_lock(fd, lk)
    return ok
