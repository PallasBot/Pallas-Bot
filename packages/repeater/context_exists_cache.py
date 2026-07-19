"""复读 context_exists_by_keywords 的进程内 TTL 门禁，减轻每条群消息的学习路径 DB 压力。"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from pallas.core.foundation.db.context_repo_access import context_repo

if TYPE_CHECKING:
    from collections.abc import Iterable

_CONTEXT_EXISTS_CACHE_TTL_SEC = 45.0
_CONTEXT_EXISTS_CACHE_MAX = 100_000
_exists_cache: dict[str, tuple[float, bool]] = {}
_exists_lock = asyncio.Lock()
_exists_generation: dict[str, int] = {}
_fetch_tasks: dict[str, asyncio.Task[bool]] = {}
_fetch_tasks_lock = asyncio.Lock()


async def invalidate_context_exists_cache(keywords: str | Iterable[str] | None = None) -> None:
    """写入或清理语料后使存在性缓存失效；不传参则清空全部。"""
    if keywords is None:
        async with _fetch_tasks_lock:
            for t in list(_fetch_tasks.values()):
                if not t.done():
                    t.cancel()
            _fetch_tasks.clear()
        async with _exists_lock:
            _exists_cache.clear()
            _exists_generation.clear()
        return

    keys = [keywords] if isinstance(keywords, str) else list(keywords)
    if not keys:
        return
    async with _exists_lock:
        for kw in keys:
            k = kw if isinstance(kw, str) else str(kw)
            _exists_cache.pop(k, None)
            _exists_generation[k] = _exists_generation.get(k, 0) + 1


async def reset_context_exists_cache() -> None:
    await invalidate_context_exists_cache(None)


async def note_context_exists(keywords: str) -> None:
    """本地刚写入/确认存在后标记，避免紧接着再次查库。"""
    if not keywords:
        return
    expire_at = time.monotonic() + _CONTEXT_EXISTS_CACHE_TTL_SEC
    async with _exists_lock:
        _exists_cache[keywords] = (expire_at, True)


async def _fetch_exists_db(keywords: str) -> bool:
    repo = context_repo
    local_exists = getattr(repo, "local_context_exists_by_keywords", None)
    if callable(local_exists):
        return await local_exists(keywords)
    return await repo.context_exists_by_keywords(keywords)


async def _await_exists_deduped(keywords: str) -> bool:
    async with _fetch_tasks_lock:
        t = _fetch_tasks.get(keywords)
        if t is not None and not t.done():
            task = t
        else:

            async def _runner() -> bool:
                try:
                    return await _fetch_exists_db(keywords)
                finally:
                    async with _fetch_tasks_lock:
                        cur = asyncio.current_task()
                        if _fetch_tasks.get(keywords) is cur:
                            _fetch_tasks.pop(keywords, None)

            task = asyncio.create_task(_runner())
            _fetch_tasks[keywords] = task
    return await task


async def context_exists_for_learn(keywords: str) -> bool:
    """带 TTL 与并发去重的 context 存在性查询。"""
    if not keywords:
        return False

    while True:
        now = time.monotonic()
        async with _exists_lock:
            hit = _exists_cache.get(keywords)
            if hit is not None:
                exp, val = hit
                if now < exp:
                    return val
                _exists_cache.pop(keywords, None)
            if len(_exists_cache) > _CONTEXT_EXISTS_CACHE_MAX:
                stale = [k for k, (e, _) in _exists_cache.items() if now >= e]
                for k in stale:
                    _exists_cache.pop(k, None)
                if len(_exists_cache) > _CONTEXT_EXISTS_CACHE_MAX:
                    _exists_cache.clear()
            gen_snapshot = _exists_generation.get(keywords, 0)

        exists = await _await_exists_deduped(keywords)

        expire_at = time.monotonic() + _CONTEXT_EXISTS_CACHE_TTL_SEC
        async with _exists_lock:
            if _exists_generation.get(keywords, 0) != gen_snapshot:
                continue
            _exists_cache[keywords] = (expire_at, exists)
        return exists
