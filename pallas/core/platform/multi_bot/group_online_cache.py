"""按群缓存在线 fleet / 本进程已连接牛，减少 member API 重复调用。"""

from __future__ import annotations

import asyncio
import time

from nonebot import get_bots

GROUP_ONLINE_TTL_SEC = 45.0
GROUP_ONLINE_CACHE_MAX = 512
NS_FLEET = "fleet"
NS_LOCAL_CONNECTED = "local_connected"

_lock = asyncio.Lock()
_caches: dict[str, dict[int, tuple[float, tuple[int, ...]]]] = {
    NS_FLEET: {},
    NS_LOCAL_CONNECTED: {},
}


def clear_group_online_cache(namespace: str | None = None) -> None:
    if namespace is None:
        for bucket in _caches.values():
            bucket.clear()
        return
    bucket = _caches.get(namespace)
    if bucket is not None:
        bucket.clear()


def get_cached_group_bot_ids(group_id: int, *, namespace: str) -> list[int] | None:
    now = time.time()
    bucket = _caches.get(namespace, {})
    cached = bucket.get(int(group_id))
    if cached is not None and cached[0] > now:
        return list(cached[1])
    return None


async def store_cached_group_bot_ids(
    group_id: int,
    ids: tuple[int, ...] | list[int],
    *,
    namespace: str,
) -> None:
    gid = int(group_id)
    now = time.time()
    tup = tuple(int(x) for x in ids)
    async with _lock:
        bucket = _caches.setdefault(namespace, {})
        if len(bucket) >= GROUP_ONLINE_CACHE_MAX:
            expired = [k for k, (exp, _) in bucket.items() if exp <= now]
            for k in expired:
                bucket.pop(k, None)
            if len(bucket) >= GROUP_ONLINE_CACHE_MAX:
                bucket.clear()
        bucket[gid] = (now + GROUP_ONLINE_TTL_SEC, tup)


async def resolve_local_connected_bots_in_group(group_id: int) -> list[int]:
    """本进程已连接且能查到该群成员资料的牛牛 QQ。"""
    gid = int(group_id)
    cached = get_cached_group_bot_ids(gid, namespace=NS_LOCAL_CONNECTED)
    if cached is not None:
        return cached

    bots = get_bots()
    out: list[int] = []
    for key in sorted(bots.keys(), key=lambda x: int(x) if str(x).isdigit() else 0):
        try:
            bid = int(key)
        except ValueError:
            continue
        try:
            await bots[key].get_group_member_info(group_id=gid, user_id=bid)
        except Exception:
            continue
        out.append(bid)

    await store_cached_group_bot_ids(gid, out, namespace=NS_LOCAL_CONNECTED)
    return out
