"""按群缓存在线 fleet / 本进程已连接牛，减少 member API 重复调用。"""

from __future__ import annotations

import asyncio
import time

from nonebot import get_bots, logger

from pallas.core.foundation.logging import log_rate_limited

GROUP_ONLINE_TTL_SEC = 45.0
GROUP_ONLINE_CACHE_MAX = 512
_GROUP_MEMBER_PROBE_TIMEOUT_SEC = 3.0
NS_FLEET = "fleet"
NS_LOCAL_CONNECTED = "local_connected"

_lock = asyncio.Lock()
_caches: dict[str, dict[int, tuple[float, tuple[int, ...]]]] = {
    NS_FLEET: {},
    NS_LOCAL_CONNECTED: {},
}
_observed_local_group_bots: dict[int, dict[int, float]] = {}


def clear_group_online_cache(namespace: str | None = None) -> None:
    if namespace is None:
        for bucket in _caches.values():
            bucket.clear()
        _observed_local_group_bots.clear()
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
    ttl_sec: float | None = None,
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
        bucket[gid] = (now + (ttl_sec if ttl_sec is not None else GROUP_ONLINE_TTL_SEC), tup)


def remember_local_group_bot(group_id: int, bot_id: int) -> None:
    """记录已实际收到该群消息的本机帐号。"""
    gid = int(group_id)
    bid = int(bot_id)
    now = time.time()
    observed = _observed_local_group_bots.setdefault(gid, {})
    for old_bot_id, expires_at in tuple(observed.items()):
        if expires_at <= now:
            observed.pop(old_bot_id, None)
    observed[bid] = now + GROUP_ONLINE_TTL_SEC


def forget_group_bot(group_id: int, bot_id: int) -> None:
    gid = int(group_id)
    bid = int(bot_id)
    observed = _observed_local_group_bots.get(gid)
    if observed is not None:
        observed.pop(bid, None)
        if not observed:
            _observed_local_group_bots.pop(gid, None)
    for bucket in _caches.values():
        cached = bucket.get(gid)
        if cached is None:
            continue
        expires_at, ids = cached
        bucket[gid] = (expires_at, tuple(value for value in ids if value != bid))


def recent_local_group_bot_ids(group_id: int) -> list[int]:
    gid = int(group_id)
    observed = _observed_local_group_bots.get(gid)
    if not observed:
        return []
    now = time.time()
    for bot_id, expires_at in tuple(observed.items()):
        if expires_at <= now:
            observed.pop(bot_id, None)
    if not observed:
        _observed_local_group_bots.pop(gid, None)
        return []
    return sorted(observed)


async def resolve_local_connected_bots_in_group(group_id: int, *, force_probe: bool = False) -> list[int]:
    """本进程已连接且能查到该群成员资料的牛牛 QQ。"""
    gid = int(group_id)
    if not force_probe:
        observed = recent_local_group_bot_ids(gid)
        if observed:
            return observed
    cached = get_cached_group_bot_ids(gid, namespace=NS_LOCAL_CONNECTED)
    if cached is not None:
        return cached

    bots = get_bots()
    out: list[int] = []
    deadline = time.monotonic() + _GROUP_MEMBER_PROBE_TIMEOUT_SEC
    for key in sorted(bots.keys(), key=lambda x: int(x) if str(x).isdigit() else 0):
        try:
            bid = int(key)
        except ValueError:
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            log_rate_limited(
                logger,
                "warning",
                f"group_online_cache.probe_exhausted.{gid}",
                "group online cache: probe budget exhausted for group [{}]",
                gid,
            )
            break
        try:
            await asyncio.wait_for(
                bots[key].get_group_member_info(group_id=gid, user_id=bid),
                timeout=remaining,
            )
        except TimeoutError:
            log_rate_limited(
                logger,
                "warning",
                f"group_online_cache.probe_exhausted.{gid}",
                "group online cache: probe budget exhausted for group [{}]",
                gid,
            )
            break
        except Exception as e:
            logger.debug("group online cache: probe {} failed for group [{}]: {}", bid, gid, e)
            continue
        out.append(bid)

    await store_cached_group_bot_ids(gid, out, namespace=NS_LOCAL_CONNECTED)
    return out
