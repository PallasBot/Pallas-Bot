"""跨 worker 同群决斗互斥：Redis 占用，避免多片同时开战。"""

from __future__ import annotations

import time
from typing import Any

from src.platform.shard.coord.coord_redis_store import (
    coord_key,
    mutate_json_sync,
    read_json_sync,
    setex_json_sync,
)
from src.platform.shard.registry.config import (
    get_shard_registry_settings,
    is_sharding_active,
)

_BUSY_TTL_SEC = 7200.0
_ORPHAN_BUSY_MIN_AGE_SEC = 30.0
_local_busy: set[int] = set()


def _group_key(group_id: int) -> str:
    return coord_key("duel_group", group_id)


def _group_ttl(data: dict[str, Any]) -> int:
    until = float(data.get("until") or 0)
    if until > time.time():
        return max(60, int(until - time.time()) + 60)
    return int(_BUSY_TTL_SEC)


def _read_group(group_id: int) -> dict[str, Any] | None:
    return read_json_sync(_group_key(group_id))


def _lock_path(group_id: int) -> str:
    """测试兼容：返回 Redis 键。"""
    return _group_key(group_id)


def _read(path_or_gid: str | int) -> dict[str, Any] | None:
    if isinstance(path_or_gid, int):
        return _read_group(path_or_gid)
    return read_json_sync(str(path_or_gid))


def _write_atomic(path_or_gid: str | int, data: dict[str, Any]) -> None:
    gid = int(data.get("group_id") or path_or_gid)
    _store_group(gid, data)


def _mutate_group(group_id: int, fn, *, retries: int = 8) -> dict[str, Any] | None:
    return mutate_json_sync(
        _group_key(group_id),
        fn,
        ttl_sec_fn=_group_ttl,
        retries=retries,
    )


def _store_group(group_id: int, data: dict[str, Any]) -> None:
    setex_json_sync(_group_key(group_id), data, _group_ttl(data))


def _has_live_session(data: dict[str, Any]) -> bool:
    pair = data.get("session_pair")
    if not isinstance(pair, (list, tuple)) or len(pair) != 2:
        return False
    until = float(data.get("session_until") or 0)
    return until > time.time()


def is_orphan_duel_group_lock(data: dict[str, Any] | None) -> bool:
    """busy 但无有效 session：多为非主持牛开团后未 end 的泄漏。"""
    if not data or not data.get("busy"):
        return False
    acquired = float(data.get("acquired_at") or 0)
    if acquired <= 0 or time.time() < acquired + _ORPHAN_BUSY_MIN_AGE_SEC:
        return False
    return not _has_live_session(data)


def mark_duel_group_session(group_id: int, bot_a: int, bot_b: int) -> None:
    """双牛对局已开始：写入共享状态，供跨 worker 孤儿锁判断。"""
    gid = int(group_id)
    if not is_sharding_active():
        return
    now = time.time()

    def stamp(data: dict[str, Any]) -> None:
        data["session_pair"] = [int(bot_a), int(bot_b)]
        data["session_until"] = now + _BUSY_TTL_SEC

    _mutate_group(gid, stamp)


def try_begin_duel_group(group_id: int) -> bool:
    """同群同时进行中的决斗至多一场（分片时跨 worker）。"""
    gid = int(group_id)
    if not is_sharding_active():
        if gid in _local_busy:
            return False
        _local_busy.add(gid)
        return True

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

    _mutate_group(gid, claim)
    return acquired


def end_duel_group(group_id: int) -> None:
    gid = int(group_id)
    if not is_sharding_active():
        _local_busy.discard(gid)
        return

    def release(data: dict[str, Any]) -> None:
        data["busy"] = False
        data["until"] = 0
        data.pop("session_pair", None)
        data.pop("session_until", None)

    _mutate_group(gid, release)


async def prune_stale_duel_group_files(*, max_age_sec: float = 3600.0) -> int:
    """Redis TTL 自动过期。"""
    return 0


async def try_reclaim_orphan_duel_group(group_id: int) -> bool:
    """
    回收泄漏的群决斗占用：busy 较久且协调层无有效 session_pair。
    不依赖本 worker 内存 duel_pair，避免分片下误判/漏判。
    """
    gid = int(group_id)
    if not is_sharding_active():
        if gid not in _local_busy:
            return False
        from src.plugins.duel.duel_session import get_duel_pair

        if await get_duel_pair(gid) is not None:
            return False
        _local_busy.discard(gid)
        return True

    data = _read_group(gid)
    if not is_orphan_duel_group_lock(data):
        return False
    end_duel_group(gid)
    return True
