"""控制台扩展 JSON 读缓存。"""

from __future__ import annotations

import asyncio
import copy
import time
import typing
from typing import Any

from nonebot import logger

_READ_CACHE: dict[str, dict[str, Any]] = {}
_READ_INFLIGHT: dict[str, asyncio.Task[Any]] = {}


def clear_extended_read_cache() -> None:
    """清空控制台扩展 JSON 的进程内读缓存。"""
    _READ_CACHE.clear()
    for task in list(_READ_INFLIGHT.values()):
        if not task.done():
            task.cancel()
    _READ_INFLIGHT.clear()


def cache_value_copy(data: Any) -> Any:
    """避免调用方就地修改 dict/list 污染缓存条目。"""
    if isinstance(data, (dict, list)):
        try:
            return copy.deepcopy(data)
        except Exception:  # noqa: BLE001
            return data
    return data


async def cached_read(
    *,
    key: str,
    loader: typing.Callable[[], typing.Awaitable[Any]],
    ttl_sec: float = 1.0,
    stale_sec: float = 20.0,
) -> Any:
    """短 TTL 读缓存；失败时回退最近成功快照。"""
    now = time.monotonic()
    hit = _READ_CACHE.get(key)
    if hit and now < float(hit["exp"]):
        return cache_value_copy(hit["data"])

    inflight = _READ_INFLIGHT.get(key)
    if inflight is not None and not inflight.done():
        return await inflight

    async def run() -> Any:
        t = time.monotonic()
        stale_hit = _READ_CACHE.get(key)
        try:
            data = await loader()
        except Exception:
            if stale_hit and t < float(stale_hit["stale_exp"]):
                logger.warning("Pallas-Bot 控制台: 使用缓存兜底 key={}", key)
                return cache_value_copy(stale_hit["data"])
            raise
        stored = cache_value_copy(data)
        _READ_CACHE[key] = {
            "data": stored,
            "exp": t + max(0.05, ttl_sec),
            "stale_exp": t + max(ttl_sec, stale_sec),
        }
        return cache_value_copy(stored)

    task = asyncio.create_task(run())
    _READ_INFLIGHT[key] = task
    try:
        return await task
    finally:
        _READ_INFLIGHT.pop(key, None)


def drop_read_cache(prefixes: tuple[str, ...]) -> None:
    if not _READ_CACHE:
        return
    for k in [k for k in _READ_CACHE if any(k.startswith(p) for p in prefixes)]:
        _READ_CACHE.pop(k, None)
