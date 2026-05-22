"""分片：MAA 远控 user → worker 登记，供 hub 转发 getTask / reportStatus。"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from nonebot import logger

from src.common.paths import plugin_data_dir
from src.common.shard.registry.config import get_shard_registry_settings, is_sharding_active
from src.common.shard.registry.store import get_shard_registry, worker_port_for_shard

_PLUGIN = "pallas_shard"
_TTL_SEC = 86400.0 * 7


def _routes_dir() -> Path:
    root = Path(plugin_data_dir(_PLUGIN, create=True)) / "coord" / "maa_route"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _user_key(user: str) -> str | None:
    key = (user or "").strip()
    if not key or not key.isdigit():
        return None
    return key


def _route_path(user: str) -> Path | None:
    key = _user_key(user)
    if key is None:
        return None
    return _routes_dir() / f"user_{key}.json"


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
    updated = float(rec.get("updated_at") or 0)
    return updated <= 0 or (time.time() - updated) > _TTL_SEC


def current_worker_port() -> int | None:
    if not is_sharding_active():
        return None
    s = get_shard_registry_settings()
    if s.role != "worker":
        return None
    return int(worker_port_for_shard(int(s.shard_id)))


def register_maa_user_route(user: str, *, worker_port: int | None = None) -> None:
    if not is_sharding_active():
        return
    key = _user_key(user)
    if key is None:
        return
    port = worker_port if worker_port is not None else current_worker_port()
    if port is None:
        return
    path = _route_path(key)
    assert path is not None
    lk = _lock_path(path)
    fd = _acquire_lock(lk)
    if fd is None:
        logger.warning("maa route register lock timeout user={}", key)
        return
    s = get_shard_registry_settings()
    try:
        _write_atomic(
            path,
            {
                "user": key,
                "worker_port": int(port),
                "shard_id": int(s.shard_id) if s.role == "worker" else None,
                "updated_at": time.time(),
            },
        )
    finally:
        _release_lock(fd, lk)


def resolve_worker_port_for_maa_user(user: str) -> int | None:
    if not is_sharding_active():
        return None
    key = _user_key(user)
    if key is None:
        return None
    path = _route_path(key)
    if path is not None:
        rec = _read(path)
        if rec and not _is_stale(rec):
            try:
                return int(rec["worker_port"])
            except (KeyError, TypeError, ValueError):
                pass
        else:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
    reg = get_shard_registry()
    sid = reg.shard_for_bot(key)
    shards = getattr(reg, "shards", None) or ()
    if sid is None and shards:
        ordered = sorted(s.id for s in shards)
        pick = int(hashlib.sha256(key.encode()).hexdigest()[:12], 16) % len(ordered)
        sid = ordered[pick]
    if sid is None:
        return None
    return int(worker_port_for_shard(int(sid), registry=reg))
