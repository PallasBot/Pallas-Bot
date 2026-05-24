"""曾建立过 WS 连接的牛牛（分片写入共享文件；单进程用 fleet 内存集合）。"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from src.common.paths import plugin_data_dir
from src.common.shard.registry.config import is_sharding_active

_PLUGIN = "pallas_shard"
_SEEN_FILE = "cluster_session_seen.json"


def _seen_path():
    return plugin_data_dir(_PLUGIN, create=True) / _SEEN_FILE


def _lock_path():
    return _seen_path().with_suffix(".json.lock")


def acquire_seen_lock(timeout: float = 3.0) -> int | None:
    _seen_path().parent.mkdir(parents=True, exist_ok=True)
    path = _lock_path()
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            return os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                if time.time() - path.stat().st_mtime > 10.0:
                    path.unlink(missing_ok=True)
            except OSError:
                pass
            time.sleep(0.02)
    return None


def release_seen_lock(fd: int | None) -> None:
    path = _lock_path()
    if fd is not None:
        try:
            os.close(fd)
        except OSError:
            pass
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _read_seen_data() -> dict[str, Any]:
    path = _seen_path()
    if not path.is_file():
        return {"seen": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"seen": []}
    if not isinstance(raw, dict):
        return {"seen": []}
    seen = raw.get("seen")
    if not isinstance(seen, list):
        raw["seen"] = []
    return raw


def _write_seen_atomic(data: dict[str, Any]) -> None:
    path = _seen_path()
    data["updated_at"] = time.time()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _load_cluster_seen_ids() -> set[int]:
    seen = _read_seen_data().get("seen")
    if not isinstance(seen, list):
        return set()
    out: set[int] = set()
    for item in seen:
        if str(item).isdigit():
            out.add(int(item))
    return out


def note_cluster_session_seen_sync(*, qq: int) -> None:
    """分片：任意 worker 连上牛时写入共享名册。"""
    key = str(int(qq))
    fd = acquire_seen_lock()
    if fd is None:
        return
    try:
        data = _read_seen_data()
        seen = data.setdefault("seen", [])
        if not isinstance(seen, list):
            seen = []
            data["seen"] = seen
        if key not in seen:
            seen.append(key)
            seen.sort(key=lambda x: int(x) if str(x).isdigit() else 0)
        _write_seen_atomic(data)
    finally:
        release_seen_lock(fd)


def note_bot_session_seen(qq: int) -> None:
    from src.common.multi_bot.fleet import note_fleet_bot_session_connected

    note_fleet_bot_session_connected(int(qq))
    if is_sharding_active():
        note_cluster_session_seen_sync(qq=int(qq))


def get_session_seen_bot_ids() -> frozenset[int]:
    """全集群/单进程：本次部署以来曾连过 WS 的 QQ（不含 registry 幽灵号）。"""
    from src.common.multi_bot.fleet import get_process_session_connected_ids

    ids = set(get_process_session_connected_ids())
    if is_sharding_active():
        ids.update(_load_cluster_seen_ids())
    return frozenset(ids)
