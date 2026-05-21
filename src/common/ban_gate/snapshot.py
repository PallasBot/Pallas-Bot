"""黑名单门禁全量内存快照：周期性批量刷新 DB。"""

from __future__ import annotations

import asyncio
import os
import time

from nonebot import logger

from src.common.db import get_db_backend

_SNAPSHOT_REFRESH_SEC = float(os.getenv("PALLAS_BAN_SNAPSHOT_REFRESH_SEC", "30"))
_SNAPSHOT_STALE_SEC = float(os.getenv("PALLAS_BAN_SNAPSHOT_STALE_SEC", "120"))
_FALLBACK_DB_TIMEOUT_SEC = float(os.getenv("PALLAS_BAN_GATE_DB_TIMEOUT_SEC", "0.8"))

_global_banned: frozenset[int] = frozenset()
_group_blocked: dict[int, frozenset[int]] = {}
_last_refresh_mono: float = 0.0
_ready: bool = False
_lock = asyncio.Lock()
_refresh_task: asyncio.Task[None] | None = None


def snapshot_ready() -> bool:
    if not _ready:
        return False
    return (time.monotonic() - _last_refresh_mono) <= _SNAPSHOT_STALE_SEC


def is_user_globally_banned_fast(user_id: int) -> bool | None:
    """命中快照返回 bool；快照未就绪返回 None（调用方回退 DB）。"""
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


async def refresh_ban_gate_snapshot() -> None:
    global _global_banned, _group_blocked, _last_refresh_mono, _ready
    backend = get_db_backend()
    try:
        if backend == "mongodb":
            users, groups = await _load_snapshot_mongodb()
        elif backend in ("postgresql", "postgres", "pg"):
            users, groups = await _load_snapshot_postgresql()
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
        _last_refresh_mono = time.monotonic()
        _ready = True
    logger.info(
        "ban_gate_snapshot refreshed: global_banned={} groups_with_blocks={}",
        len(users),
        len(groups),
    )


async def _load_snapshot_mongodb() -> tuple[frozenset[int], dict[int, frozenset[int]]]:
    from src.common.db.modules import GroupConfigModule, UserConfigModule

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
    return users, groups


async def _load_snapshot_postgresql() -> tuple[frozenset[int], dict[int, frozenset[int]]]:
    from sqlalchemy import select

    from src.common.db.repository_pg import GroupConfigRow, UserConfigRow, get_session

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
    return users, groups


async def _refresh_loop() -> None:
    while True:
        await asyncio.shield(refresh_ban_gate_snapshot())
        await asyncio.sleep(_SNAPSHOT_REFRESH_SEC)


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
    global _global_banned, _group_blocked, _last_refresh_mono, _ready
    await stop_ban_gate_snapshot()
    async with _lock:
        _global_banned = frozenset()
        _group_blocked = {}
        _last_refresh_mono = 0.0
        _ready = False
