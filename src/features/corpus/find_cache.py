"""find_by_keywords 进程内 TTL 缓存，减轻复读热路径远程 HTTP。"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from nonebot import logger

from src.features.corpus.reply_perf_config import find_cache_max_entries, find_cache_ttl_sec
from src.foundation.db.pool_budget import is_pg_pool_timeout_error

if TYPE_CHECKING:
    from src.foundation.db.modules import Context

_find_cache: dict[str, tuple[float, Context | None]] = {}
_reply_find_cache: dict[str, tuple[float, Context | None]] = {}
_find_inflight: dict[str, asyncio.Task[Context | None]] = {}
_reply_find_inflight: dict[str, asyncio.Task[Context | None]] = {}
_find_lock = asyncio.Lock()
_REPLY_DB_FAIL_TTL_SEC = 2.0
_reply_db_fail_until: dict[str, float] = {}


def _reply_db_fail_active(key: str, *, now: float | None = None) -> bool:
    exp = _reply_db_fail_until.get(key)
    if exp is None:
        return False
    cur = time.monotonic() if now is None else now
    if cur < exp:
        return True
    _reply_db_fail_until.pop(key, None)
    return False


def mark_reply_db_fail(keywords: str) -> None:
    key = (keywords or "").strip()
    if key:
        _reply_db_fail_until[key] = time.monotonic() + _REPLY_DB_FAIL_TTL_SEC


def reply_db_fail_active(keywords: str) -> bool:
    key = (keywords or "").strip()
    if not key:
        return False
    return _reply_db_fail_active(key)


async def _cached_find(
    cache: dict[str, tuple[float, Context | None]],
    inflight: dict[str, asyncio.Task[Context | None]],
    keywords: str,
    loader,
    *,
    for_reply: bool = False,
) -> Context | None:
    key = (keywords or "").strip()
    if not key:
        return None
    now = time.monotonic()
    if _reply_db_fail_active(key, now=now):
        if for_reply:
            logger.debug(
                "corpus_find_reply.skip reply_db_fail_cooldown kw_len={}",
                len(key),
            )
        return None
    task: asyncio.Task[Context | None] | None = None
    async with _find_lock:
        hit = cache.get(key)
        if hit is not None:
            exp, val = hit
            if now < exp:
                return val
            cache.pop(key, None)
        task = inflight.get(key)
        if task is None:
            task = asyncio.create_task(loader(key))
            inflight[key] = task
        cache_max = find_cache_max_entries()
        if len(cache) > cache_max:
            stale = [k for k, (e, _) in cache.items() if now >= e]
            for k in stale:
                cache.pop(k, None)
            if len(cache) > cache_max:
                cache.clear()

    try:
        ctx = await asyncio.shield(task)
    except Exception as exc:
        async with _find_lock:
            if inflight.get(key) is task:
                inflight.pop(key, None)
        if is_pg_pool_timeout_error(exc):
            mark_reply_db_fail(key)
            if for_reply:
                logger.debug(
                    "corpus_find_reply.skip db_timeout kw_len={}",
                    len(key),
                )
            return None
        raise

    expire_at = time.monotonic() + find_cache_ttl_sec()
    async with _find_lock:
        if inflight.get(key) is task:
            inflight.pop(key, None)
        cache[key] = (expire_at, ctx)
    return ctx


async def cached_find_by_keywords(
    keywords: str,
    loader,
) -> Context | None:
    return await _cached_find(_find_cache, _find_inflight, keywords, loader)


async def cached_find_by_keywords_for_reply(
    keywords: str,
    loader,
) -> Context | None:
    return await _cached_find(_reply_find_cache, _reply_find_inflight, keywords, loader, for_reply=True)


async def invalidate_find_cache(keywords: str | None = None) -> None:
    async with _find_lock:
        if keywords is None:
            _find_cache.clear()
            _reply_find_cache.clear()
            _find_inflight.clear()
            _reply_find_inflight.clear()
            _reply_db_fail_until.clear()
            return
        key = keywords.strip()
        if key:
            _find_cache.pop(key, None)
            _reply_find_cache.pop(key, None)
            _reply_db_fail_until.pop(key, None)


async def reset_find_cache_for_tests() -> None:
    await invalidate_find_cache(None)
