"""跨 worker 同群决斗互斥。"""

from __future__ import annotations

from typing import Any

from src.platform.shard.coord.group_activity import (
    get_group_activity_lock,
    session_live_by_pair,
)

_LOCK = get_group_activity_lock(
    "duel_group",
    session_extra_keys=frozenset({"session_pair"}),
    is_live_session=session_live_by_pair,
)

_local_busy = _LOCK.local_busy
_ORPHAN_BUSY_MIN_AGE_SEC = _LOCK.orphan_min_age_sec


def _group_key(group_id: int) -> str:
    return _LOCK.key(group_id)


def _lock_path(group_id: int) -> str:
    return _group_key(group_id)


def _read(path_or_gid: str | int) -> dict[str, Any] | None:
    if isinstance(path_or_gid, int):
        return _LOCK.read(path_or_gid)
    from src.platform.shard.coord.coord_redis_store import read_json_sync

    return read_json_sync(str(path_or_gid))


def _write_atomic(path_or_gid: str | int, data: dict[str, Any]) -> None:
    gid = int(data.get("group_id") or path_or_gid)
    _LOCK.store(gid, data)


def is_orphan_duel_group_lock(data: dict[str, Any] | None) -> bool:
    return _LOCK.is_orphan_lock(data)


def mark_duel_group_session(group_id: int, bot_a: int, bot_b: int) -> None:
    _LOCK.mark_session(group_id, session_pair=[int(bot_a), int(bot_b)])


def try_begin_duel_group(group_id: int) -> bool:
    return _LOCK.try_begin(group_id)


def end_duel_group(group_id: int) -> None:
    _LOCK.end(group_id)


async def try_reclaim_orphan_duel_group(group_id: int) -> bool:
    from src.plugins.duel.duel_session import get_duel_pair

    return await _LOCK.try_reclaim_orphan(
        group_id,
        local_alive=lambda: get_duel_pair(int(group_id)),
    )
