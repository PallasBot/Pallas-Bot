"""BotConfig.admins 的进程内 TTL 门禁，减轻命令权限校验的 DB 压力。"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from pallas.core.foundation.db import make_bot_config_repository

if TYPE_CHECKING:
    from collections.abc import Iterable

_BOT_ADMINS_CACHE_TTL_SEC = 45.0
_BOT_ADMINS_CACHE_MAX = 10_000
_BOT_ADMINS_DB_FAIL_TTL_SEC = 2.0
_admins_cache: dict[int, tuple[float, list[int]]] = {}
_admins_db_fail_until: dict[int, float] = {}
_admins_lock = asyncio.Lock()
_admins_generation: dict[int, int] = {}
_fetch_tasks: dict[int, asyncio.Task[list[int]]] = {}
_fetch_tasks_lock = asyncio.Lock()

_any_bot_admin_cache: tuple[float, frozenset[int]] | None = None
_any_bot_admin_generation = 0
_any_bot_admin_fetch_task: asyncio.Task[frozenset[int]] | None = None
_any_bot_admin_fetch_lock = asyncio.Lock()
_any_bot_admin_db_fail_until: float = 0.0

_repo = make_bot_config_repository()


def mark_bot_admins_db_fail(bot_id: int) -> None:
    _admins_db_fail_until[int(bot_id)] = time.monotonic() + _BOT_ADMINS_DB_FAIL_TTL_SEC


def bot_admins_db_fail_active(bot_id: int) -> bool:
    exp = _admins_db_fail_until.get(int(bot_id))
    if exp is None:
        return False
    if time.monotonic() < exp:
        return True
    _admins_db_fail_until.pop(int(bot_id), None)
    return False


def _pg_not_ready() -> bool:
    from pallas.core.foundation.db.repository_pg import is_pg_initialized
    from pallas.core.foundation.db.runtime import is_postgresql_backend

    return is_postgresql_backend() and not is_pg_initialized()


async def invalidate_bot_admins_cache(bot_ids: int | Iterable[int] | None = None) -> None:
    """admins 字段变更后调用；不传参则清空全部 bot 与跨 bot 缓存。"""
    global _any_bot_admin_cache, _any_bot_admin_generation, _any_bot_admin_fetch_task

    if bot_ids is None:
        async with _any_bot_admin_fetch_lock:
            if _any_bot_admin_fetch_task is not None and not _any_bot_admin_fetch_task.done():
                _any_bot_admin_fetch_task.cancel()
            _any_bot_admin_fetch_task = None
        async with _fetch_tasks_lock:
            for t in list(_fetch_tasks.values()):
                if not t.done():
                    t.cancel()
            _fetch_tasks.clear()
        async with _admins_lock:
            _admins_cache.clear()
            _admins_generation.clear()
            _admins_db_fail_until.clear()
            _any_bot_admin_cache = None
            _any_bot_admin_generation += 1
        return

    ids = [bot_ids] if isinstance(bot_ids, int) else list(bot_ids)
    if not ids:
        return
    async with _admins_lock:
        for bid in ids:
            b = int(bid)
            _admins_cache.pop(b, None)
            _admins_generation[b] = _admins_generation.get(b, 0) + 1
        _any_bot_admin_cache = None
        _any_bot_admin_generation += 1


async def reset_bot_admins_cache() -> None:
    await invalidate_bot_admins_cache(None)


async def _load_admins_db(bot_id: int) -> list[int]:
    from pallas.core.foundation.db.pool_budget import is_pg_pool_timeout_error, pg_pool_under_pressure

    if pg_pool_under_pressure(threshold=0.55):
        return []
    try:
        doc = await _repo.get(bot_id)
    except Exception as exc:
        if is_pg_pool_timeout_error(exc):
            mark_bot_admins_db_fail(bot_id)
            return []
        raise
    if doc is None:
        return []
    raw = doc.admins or []
    return list(raw)


async def _await_admins_deduped(bot_id: int) -> list[int]:
    async with _fetch_tasks_lock:
        t = _fetch_tasks.get(bot_id)
        if t is not None and not t.done():
            task = t
        else:

            async def _runner() -> list[int]:
                try:
                    return await _load_admins_db(bot_id)
                finally:
                    async with _fetch_tasks_lock:
                        cur = asyncio.current_task()
                        if _fetch_tasks.get(bot_id) is cur:
                            _fetch_tasks.pop(bot_id, None)

            task = asyncio.create_task(_runner())
            _fetch_tasks[bot_id] = task
    return await task


async def get_bot_admins_cached(bot_id: int) -> list[int]:
    if _pg_not_ready():
        return []
    bot_id = int(bot_id)
    if bot_admins_db_fail_active(bot_id):
        return []
    while True:
        now = time.monotonic()
        async with _admins_lock:
            hit = _admins_cache.get(bot_id)
            if hit is not None:
                exp, val = hit
                if now < exp:
                    return list(val)
                _admins_cache.pop(bot_id, None)
            if len(_admins_cache) > _BOT_ADMINS_CACHE_MAX:
                stale = [k for k, (e, _) in _admins_cache.items() if now >= e]
                for k in stale:
                    _admins_cache.pop(k, None)
                if len(_admins_cache) > _BOT_ADMINS_CACHE_MAX:
                    _admins_cache.clear()
            gen_snapshot = _admins_generation.get(bot_id, 0)

        admins = await _await_admins_deduped(bot_id)

        expire_at = time.monotonic() + _BOT_ADMINS_CACHE_TTL_SEC
        async with _admins_lock:
            if _admins_generation.get(bot_id, 0) != gen_snapshot:
                continue
            _admins_cache[bot_id] = (expire_at, list(admins))
        return list(admins)


async def _load_any_bot_admin_user_ids() -> frozenset[int]:
    from pallas.core.foundation.db.pallas_console_data import list_all_bot_configs_public
    from pallas.core.foundation.db.pool_budget import is_pg_pool_timeout_error, pg_pool_under_pressure

    if pg_pool_under_pressure(threshold=0.55):
        return frozenset()
    try:
        configs = await list_all_bot_configs_public()
    except Exception as exc:
        if is_pg_pool_timeout_error(exc):
            mark_any_bot_admin_db_fail()
            return frozenset()
        return frozenset()

    uids: set[int] = set()
    for cfg in configs:
        for uid in cfg.get("admins") or []:
            try:
                uids.add(int(uid))
            except (TypeError, ValueError):
                continue
    return frozenset(uids)


def mark_any_bot_admin_db_fail() -> None:
    global _any_bot_admin_db_fail_until
    _any_bot_admin_db_fail_until = time.monotonic() + _BOT_ADMINS_DB_FAIL_TTL_SEC


def any_bot_admin_db_fail_active() -> bool:
    global _any_bot_admin_db_fail_until
    if _any_bot_admin_db_fail_until <= 0:
        return False
    if time.monotonic() < _any_bot_admin_db_fail_until:
        return True
    _any_bot_admin_db_fail_until = 0.0
    return False


async def _await_any_bot_admin_user_ids_deduped() -> frozenset[int]:
    global _any_bot_admin_fetch_task
    async with _any_bot_admin_fetch_lock:
        t = _any_bot_admin_fetch_task
        if t is not None and not t.done():
            task = t
        else:

            async def _runner() -> frozenset[int]:
                global _any_bot_admin_fetch_task
                try:
                    return await _load_any_bot_admin_user_ids()
                finally:
                    async with _any_bot_admin_fetch_lock:
                        cur = asyncio.current_task()
                        if _any_bot_admin_fetch_task is cur:
                            _any_bot_admin_fetch_task = None

            task = asyncio.create_task(_runner())
            _any_bot_admin_fetch_task = task
    return await task


async def any_bot_admin_user_ids_cached() -> frozenset[int]:
    """跨 Bot 管理员判定用；列表变更后由 invalidate 整体失效。"""
    global _any_bot_admin_cache

    if _pg_not_ready():
        return frozenset()
    if any_bot_admin_db_fail_active():
        return frozenset()

    while True:
        now = time.monotonic()
        async with _admins_lock:
            gen_snapshot = _any_bot_admin_generation
            hit = _any_bot_admin_cache
            if hit is not None:
                exp, val = hit
                if now < exp:
                    return val

        fs = await _await_any_bot_admin_user_ids_deduped()

        expire_at = time.monotonic() + _BOT_ADMINS_CACHE_TTL_SEC
        async with _admins_lock:
            if _any_bot_admin_generation != gen_snapshot:
                continue
            _any_bot_admin_cache = (expire_at, fs)
        return fs
