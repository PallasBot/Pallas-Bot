"""分片：MAA 远控 user → worker 登记，供 hub 转发 getTask / reportStatus。"""

from __future__ import annotations

import hashlib
import time
from typing import Any

from nonebot import logger

from src.platform.shard.coord.coord_redis_store import coord_key, read_json_sync, setex_json_sync
from src.platform.shard.registry.config import get_shard_registry_settings, is_sharding_active
from src.platform.shard.registry.store import get_shard_registry, worker_port_for_shard

_TTL_SEC = 86400.0 * 7


def _user_key(user: str) -> str | None:
    key = (user or "").strip()
    if not key or not key.isdigit():
        return None
    return key


def _route_redis_key(user: str) -> str | None:
    key = _user_key(user)
    if key is None:
        return None
    return coord_key("maa_route", key)


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
    redis_key = _route_redis_key(key)
    if redis_key is None:
        return
    s = get_shard_registry_settings()
    ok = setex_json_sync(
        redis_key,
        {
            "user": key,
            "worker_port": int(port),
            "shard_id": int(s.shard_id) if s.role == "worker" else None,
            "updated_at": time.time(),
        },
        int(_TTL_SEC),
    )
    if not ok:
        logger.warning("maa route register failed user={}", key)


def resolve_worker_port_for_maa_user(user: str) -> int | None:
    if not is_sharding_active():
        return None
    key = _user_key(user)
    if key is None:
        return None
    redis_key = _route_redis_key(key)
    if redis_key is not None:
        rec = read_json_sync(redis_key)
        if rec and not _is_stale(rec):
            try:
                return int(rec["worker_port"])
            except (KeyError, TypeError, ValueError):
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
