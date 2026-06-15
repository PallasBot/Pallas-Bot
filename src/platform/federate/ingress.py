"""ingress / repeater 共用的联邦群消息抢占入口。"""

from __future__ import annotations

import asyncio
import os
import time
from typing import TYPE_CHECKING

from src.features.community_stats.store import load_or_create_deployment_id
from src.platform.federate.config import (
    federate_ingress_active,
    federate_ingress_bypass_unified,
)
from src.platform.observability import SlowPathTimer, slow_path_threshold_ms
from src.platform.shard import context as shard_ctx

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import GroupMessageEvent
from src.platform.federate.dedup import try_claim_cross_federate_message
from src.platform.multi_bot.dedup import cross_bot_message_signature

FEDERATE_INGRESS_CLAIM_PLUGIN = "federate_ingress"
_WIN_CACHE_TTL_SEC = float(os.getenv("PALLAS_FEDERATE_WIN_CACHE_SEC", "8"))
_WIN_CACHE_MAX = 20_000
_win_cache: dict[tuple[str, tuple[int, int, str] | tuple[int, int, str, int], str], float] = {}
_inflight_claims: dict[
    tuple[str, tuple[int, int, str] | tuple[int, int, str, int], str],
    asyncio.Future[bool],
] = {}
_win_lock = asyncio.Lock()


def reset_federate_ingress_win_cache_for_tests() -> None:
    _win_cache.clear()
    _inflight_claims.clear()


def bypass_federate_ingress_for_current_mode() -> bool:
    return federate_ingress_bypass_unified() and not shard_ctx.sharding_active()


def federate_ingress_cached_win(
    event: GroupMessageEvent,
    *,
    plugin: str = FEDERATE_INGRESS_CLAIM_PLUGIN,
    include_message_time: bool = True,
    plain: str | None = None,
    body: str | None = None,
) -> bool:
    """本进程是否已缓存赢得联邦 ingress。"""
    if bypass_federate_ingress_for_current_mode():
        return True
    if not federate_ingress_active():
        return True
    plain = (plain if plain is not None else event.get_plaintext() or "").strip()
    body = body if body is not None else (plain or event.raw_message)
    deployment_id = load_or_create_deployment_id().strip().lower()
    if not deployment_id:
        return False
    sig = cross_bot_message_signature(
        int(event.group_id),
        int(event.user_id),
        body,
        event.time,
        use_plaintext=True,
        include_message_time=include_message_time,
    )
    cache_key = (plugin, sig, deployment_id)
    now = time.monotonic()
    exp = _win_cache.get(cache_key)
    return exp is not None and now < exp


async def claim_federate_group_message_ingress(
    event: GroupMessageEvent,
    *,
    plugin: str = FEDERATE_INGRESS_CLAIM_PLUGIN,
    include_message_time: bool = True,
    plain: str | None = None,
    body: str | None = None,
) -> bool:
    """未启用联邦 ingress 或本 deployment 抢占成功时返回 True。"""
    timer = SlowPathTimer(
        "federate_ingress",
        threshold_ms=slow_path_threshold_ms("PALLAS_SLOW_FEDERATE_INGRESS_MS", 12.0),
        log_level="debug",
    )
    if bypass_federate_ingress_for_current_mode():
        timer.finish(outcome="unified_bypass")
        return True
    if not federate_ingress_active():
        timer.finish(outcome="disabled")
        return True
    plain = (plain if plain is not None else event.get_plaintext() or "").strip()
    body = body if body is not None else (plain or event.raw_message)
    deployment_id = load_or_create_deployment_id().strip().lower()
    if not deployment_id:
        timer.finish(outcome="missing_deployment_id", group_id=int(event.group_id), user_id=int(event.user_id))
        return False
    sig = cross_bot_message_signature(
        int(event.group_id),
        int(event.user_id),
        body,
        event.time,
        use_plaintext=True,
        include_message_time=include_message_time,
    )
    cache_key = (plugin, sig, deployment_id)
    now = time.monotonic()
    wait_for: asyncio.Future[bool] | None = None
    claim_owner = False
    async with _win_lock:
        exp = _win_cache.get(cache_key)
        if exp is not None and now < exp:
            timer.mark("cache_hit")
            timer.finish(outcome="cached_win", cache_hit=True, group_id=int(event.group_id), user_id=int(event.user_id))
            return True
        inflight = _inflight_claims.get(cache_key)
        if inflight is not None:
            wait_for = inflight
        else:
            wait_for = asyncio.get_running_loop().create_future()
            _inflight_claims[cache_key] = wait_for
            claim_owner = True
        if len(_win_cache) > _WIN_CACHE_MAX:
            stale = [k for k, e in _win_cache.items() if now >= e]
            for k in stale:
                _win_cache.pop(k, None)
            if len(_win_cache) > _WIN_CACHE_MAX:
                _win_cache.clear()

    if not claim_owner:
        won = await wait_for
        timer.mark("inflight_wait")
        timer.finish(
            outcome="won" if won else "lost",
            cache_hit=False,
            shared_result=True,
            group_id=int(event.group_id),
            user_id=int(event.user_id),
        )
        return won

    try:
        won = await try_claim_cross_federate_message(
            plugin,
            int(event.group_id),
            int(event.user_id),
            body,
            event.time,
            deployment_id,
            use_plaintext=True,
            include_message_time=include_message_time,
        )
    except Exception as exc:
        async with _win_lock:
            future = _inflight_claims.pop(cache_key, None)
        if future is not None and not future.done():
            future.set_exception(exc)
        raise

    timer.mark("redis_claim")
    if won:
        expire_at = time.monotonic() + _WIN_CACHE_TTL_SEC
        async with _win_lock:
            _win_cache[cache_key] = expire_at
    async with _win_lock:
        future = _inflight_claims.pop(cache_key, None)
    if future is not None and not future.done():
        future.set_result(won)
    timer.finish(
        outcome="won" if won else "lost",
        cache_hit=False,
        group_id=int(event.group_id),
        user_id=int(event.user_id),
    )
    return won
