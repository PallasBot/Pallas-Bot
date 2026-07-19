"""黑名单门禁全量内存快照：周期性批量刷新 DB。"""

from __future__ import annotations

import asyncio
import os
import time

from nonebot import logger

from pallas.core.foundation.db import get_db_backend

_SNAPSHOT_REFRESH_SEC = float(os.getenv("PALLAS_BAN_SNAPSHOT_REFRESH_SEC", "30"))
_SNAPSHOT_STALE_SEC = float(os.getenv("PALLAS_BAN_SNAPSHOT_STALE_SEC", "120"))
_FALLBACK_DB_TIMEOUT_SEC = float(os.getenv("PALLAS_BAN_GATE_DB_TIMEOUT_SEC", "0.8"))
_REDIS_GEN_KEY = "pallas:ban_gate:snapshot_gen"
_REMOTE_GEN_SYNC_TTL_SEC = 2.0

_global_banned: frozenset[int] = frozenset()
_group_blocked: dict[int, frozenset[int]] = {}
_banned_groups: frozenset[int] = frozenset()
_last_refresh_mono: float = 0.0
_ready: bool = False
_lock = asyncio.Lock()
_refresh_task: asyncio.Task[None] | None = None
_synced_redis_gen: int = -1
_remote_gen_checked_at: float = 0.0


def bump_ban_gate_snapshot_remote_generation() -> None:
    try:
        from pallas.core.platform.coord.redis_claim import get_coord_redis_client

        client = get_coord_redis_client()
        if client is not None:
            client.incr(_REDIS_GEN_KEY)
    except Exception:
        pass


def sync_ban_gate_snapshot_remote_generation() -> bool:
    """对比 Redis 世代；变化时返回 True。"""
    global _synced_redis_gen, _remote_gen_checked_at
    now = time.monotonic()
    if _remote_gen_checked_at and now - _remote_gen_checked_at < _REMOTE_GEN_SYNC_TTL_SEC:
        return False
    try:
        from pallas.core.platform.coord.redis_claim import get_coord_redis_client

        client = get_coord_redis_client()
        if client is None:
            _remote_gen_checked_at = now
            return False
        raw = client.get(_REDIS_GEN_KEY)
        _remote_gen_checked_at = now
        remote = int(raw) if raw else 0
        if remote == _synced_redis_gen:
            return False
        _synced_redis_gen = remote
        return True
    except Exception:
        _remote_gen_checked_at = now
        return False


def schedule_ban_gate_snapshot_refresh() -> None:
    bump_ban_gate_snapshot_remote_generation()
    asyncio.create_task(refresh_ban_gate_snapshot())


def snapshot_ready() -> bool:
    if not _ready:
        return False
    return (time.monotonic() - _last_refresh_mono) <= _SNAPSHOT_STALE_SEC


def is_user_globally_banned_fast(user_id: int) -> bool | None:
    """命中快照返回 bool；快照未就绪返回 None。"""
    if not snapshot_ready():
        return None
    return user_id in _global_banned


def is_user_blocked_in_group_fast(group_id: int, user_id: int) -> bool | None:
    if not snapshot_ready():
        return None
    blocked = _group_blocked.get(group_id)
    if blocked is None:
        return False
    return user_id in blocked


def is_group_banned_fast(group_id: int) -> bool | None:
    if not snapshot_ready():
        return None
    return group_id in _banned_groups


def fallback_db_timeout_sec() -> float:
    return _FALLBACK_DB_TIMEOUT_SEC


async def patch_user_banned(user_id: int, banned: bool) -> None:
    async with _lock:
        global _global_banned
        cur = set(_global_banned)
        if banned:
            cur.add(user_id)
        else:
            cur.discard(user_id)
        _global_banned = frozenset(cur)


async def patch_group_blocked_users(group_id: int, user_ids: list[int] | None = None) -> None:
    async with _lock:
        global _group_blocked
        if user_ids is None:
            _group_blocked.pop(group_id, None)
            return
        uids = frozenset(int(u) for u in user_ids)
        if uids:
            _group_blocked[group_id] = uids
        else:
            _group_blocked.pop(group_id, None)


async def patch_group_banned(group_id: int, banned: bool) -> None:
    async with _lock:
        global _banned_groups
        cur = set(_banned_groups)
        if banned:
            cur.add(int(group_id))
        else:
            cur.discard(int(group_id))
        _banned_groups = frozenset(cur)


async def refresh_ban_gate_snapshot() -> None:
    global _global_banned, _group_blocked, _banned_groups, _last_refresh_mono, _ready
    backend = get_db_backend()
    try:
        if backend == "mongodb":
            users, groups, banned_groups = await _load_snapshot_mongodb()
        elif backend in ("postgresql", "postgres", "pg"):
            users, groups, banned_groups = await _load_snapshot_postgresql()
        else:
            logger.warning("ban_gate_snapshot: unsupported backend={}, skip refresh", backend)
            return
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("ban_gate_snapshot: refresh failed")
        return

    async with _lock:
        _global_banned = users
        _group_blocked = groups
        _banned_groups = banned_groups
        _last_refresh_mono = time.monotonic()
        _ready = True
    logger.debug(
        "ban_gate_snapshot refreshed: global_banned={} groups_with_blocks={} banned_groups={}",
        len(users),
        len(groups),
        len(banned_groups),
    )


async def _load_snapshot_mongodb() -> tuple[frozenset[int], dict[int, frozenset[int]], frozenset[int]]:
    from pallas.core.foundation.db.modules import GroupConfigModule, UserConfigModule

    user_docs = await UserConfigModule.find(UserConfigModule.banned == True).to_list()  # noqa: E712
    users = frozenset(int(d.user_id) for d in user_docs)

    group_docs = await GroupConfigModule.find().to_list()
    groups: dict[int, frozenset[int]] = {}
    for doc in group_docs:
        raw = getattr(doc, "blocked_user_ids", None) or []
        uids: list[int] = []
        for x in raw:
            try:
                uids.append(int(x))
            except (TypeError, ValueError):
                continue
        if uids:
            groups[int(doc.group_id)] = frozenset(uids)
    banned_group_docs = await GroupConfigModule.find(GroupConfigModule.banned == True).to_list()  # noqa: E712
    banned_groups = frozenset(int(d.group_id) for d in banned_group_docs)
    return users, groups, banned_groups


async def _load_snapshot_postgresql() -> tuple[frozenset[int], dict[int, frozenset[int]], frozenset[int]]:
    from sqlalchemy import select

    from pallas.core.foundation.db.repository_pg import GroupConfigRow, UserConfigRow, get_session

    async with get_session() as session:
        user_rows = await session.execute(select(UserConfigRow.user_id).where(UserConfigRow.banned.is_(True)))
        users = frozenset(int(r[0]) for r in user_rows.all())

        group_rows = await session.execute(
            select(GroupConfigRow.group_id, GroupConfigRow.blocked_user_ids).where(
                GroupConfigRow.blocked_user_ids != []
            )
        )
        groups: dict[int, frozenset[int]] = {}
        for gid, raw in group_rows.all():
            uids: list[int] = []
            for x in raw or []:
                try:
                    uids.append(int(x))
                except (TypeError, ValueError):
                    continue
            if uids:
                groups[int(gid)] = frozenset(uids)

        banned_group_rows = await session.execute(
            select(GroupConfigRow.group_id).where(GroupConfigRow.banned.is_(True))
        )
        banned_groups = frozenset(int(r[0]) for r in banned_group_rows.all())
    return users, groups, banned_groups


async def _refresh_loop() -> None:
    while True:
        await asyncio.shield(refresh_ban_gate_snapshot())
        waited = 0.0
        while waited < _SNAPSHOT_REFRESH_SEC:
            chunk = min(_REMOTE_GEN_SYNC_TTL_SEC, _SNAPSHOT_REFRESH_SEC - waited)
            await asyncio.sleep(chunk)
            waited += chunk
            if sync_ban_gate_snapshot_remote_generation():
                break


async def start_ban_gate_snapshot() -> None:
    global _refresh_task
    await refresh_ban_gate_snapshot()
    if _refresh_task is None or _refresh_task.done():
        _refresh_task = asyncio.create_task(_refresh_loop(), name="ban_gate_snapshot_refresh")


async def stop_ban_gate_snapshot() -> None:
    global _refresh_task
    if _refresh_task is not None:
        _refresh_task.cancel()
        try:
            await _refresh_task
        except asyncio.CancelledError:
            pass
        _refresh_task = None


async def reset_ban_gate_snapshot_for_tests() -> None:
    """测试用：清空快照并停止后台任务。"""
    global _global_banned, _group_blocked, _banned_groups, _last_refresh_mono, _ready  # noqa: FURB154
    global _synced_redis_gen, _remote_gen_checked_at  # noqa: FURB154
    await stop_ban_gate_snapshot()
    async with _lock:
        _global_banned = frozenset()
        _group_blocked = {}
        _banned_groups = frozenset()
        _last_refresh_mono = 0.0
        _ready = False
    _synced_redis_gen = -1
    _remote_gen_checked_at = 0.0
