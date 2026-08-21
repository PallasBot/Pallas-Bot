"""Observe and cache group-admin capability for locally connected Bots."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Collection, Mapping
from typing import TYPE_CHECKING, Any

from nonebot import get_bots, logger

if TYPE_CHECKING:
    from nonebot.adapters import Bot

GROUP_ADMIN_CAPABILITY = "group_admin"
GROUP_ADMIN_CACHE_MAX = 512
_DEFAULT_CACHE_MAX = GROUP_ADMIN_CACHE_MAX
_cache: OrderedDict[tuple[int, int], bool] = OrderedDict()
_inflight: dict[tuple[int, int], asyncio.Task[bool | None]] = {}


def clear_group_admin_capability_cache() -> None:
    """Clear local observations, normally used by tests or a full reload."""
    _cache.clear()
    for task in _inflight.values():
        task.cancel()
    _inflight.clear()
    global GROUP_ADMIN_CACHE_MAX
    GROUP_ADMIN_CACHE_MAX = _DEFAULT_CACHE_MAX


def set_group_admin_capability_cache_capacity(capacity: int) -> None:
    if capacity < 1:
        raise ValueError("capacity must be positive")
    global GROUP_ADMIN_CACHE_MAX
    GROUP_ADMIN_CACHE_MAX = capacity
    while len(_cache) > GROUP_ADMIN_CACHE_MAX:
        _cache.popitem(last=False)


def _cache_get(key: tuple[int, int]) -> bool | None:
    value = _cache.get(key)
    if value is not None:
        _cache.move_to_end(key)
    return value


def _cache_contains(key: tuple[int, int]) -> bool:
    return key in _cache


def _cache_set(key: tuple[int, int], value: bool) -> None:
    _cache[key] = value
    _cache.move_to_end(key)
    while len(_cache) > GROUP_ADMIN_CACHE_MAX:
        _cache.popitem(last=False)


def _role_is_admin(role: Any) -> bool | None:
    if isinstance(role, Mapping):
        role = role.get("role")
    if not isinstance(role, str):
        return None
    normalized = role.strip().lower()
    if normalized in {"admin", "owner"}:
        return True
    if normalized in {"member", "unknown", ""}:
        return False
    return None


async def _fetch_role_from_bot(bot: Bot, group_id: int, bot_id: int) -> Any:
    return await bot.get_group_member_info(group_id=group_id, user_id=bot_id)


async def _resolve_uncached(
    group_id: int,
    bot_id: int,
    *,
    bot: Bot | None,
    fetch_role: Callable[[int, int], Awaitable[Any]] | None,
) -> bool | None:
    try:
        if fetch_role is not None:
            role = await fetch_role(group_id, bot_id)
        else:
            if bot is None:
                bot = get_bots().get(str(bot_id))
            if bot is None:
                return None
            role = await _fetch_role_from_bot(bot, group_id, bot_id)
        return _role_is_admin(role)
    except Exception as exc:
        logger.debug(
            "group admin capability lookup failed for group [{}], Bot [{}]: {}",
            group_id,
            bot_id,
            exc,
        )
        return None


async def resolve_group_admin_capability(
    group_id: int,
    bot_id: int,
    *,
    bot: Bot | None = None,
    fetch_role: Callable[[int, int], Awaitable[Any]] | None = None,
) -> bool | None:
    key = (int(group_id), int(bot_id))
    if _cache_contains(key):
        return _cache_get(key)

    task = _inflight.get(key)
    if task is None:
        task = asyncio.create_task(
            _resolve_uncached(key[0], key[1], bot=bot, fetch_role=fetch_role),
            name=f"group_admin_capability:{key[0]}:{key[1]}",
        )
        _inflight[key] = task
    try:
        result = await task
    finally:
        if task.done() and _inflight.get(key) is task:
            _inflight.pop(key, None)
    if result is not None:
        _cache_set(key, result)
    return result


def record_group_admin_notice(*, group_id: int, bot_id: int, role: str) -> None:
    value = _role_is_admin(role)
    key = (int(group_id), int(bot_id))
    if value is None:
        _cache.pop(key, None)
        return
    _cache_set(key, value)


def invalidate_group_admin_capability(*, group_id: int, bot_id: int) -> None:
    _cache.pop((int(group_id), int(bot_id)), None)


def invalidate_bot_group_admin_capabilities(bot_id: int) -> None:
    bid = int(bot_id)
    for key in tuple(_cache):
        if key[1] == bid:
            _cache.pop(key, None)


def local_group_admin_bot_ids(group_id: int) -> frozenset[int]:
    gid = int(group_id)
    return frozenset(bot_id for (cached_gid, bot_id), value in _cache.items() if cached_gid == gid and value)


def local_group_admin_observation_complete(
    group_id: int,
    bot_ids: Collection[int],
) -> bool:
    gid = int(group_id)
    ids = {int(bot_id) for bot_id in bot_ids}
    return bool(ids) and all(_cache_contains((gid, bot_id)) for bot_id in ids)


async def warm_local_group_admin_observations(
    group_id: int,
    bot_ids: Collection[int],
) -> None:
    await asyncio.gather(*(resolve_group_admin_capability(group_id, int(bot_id)) for bot_id in bot_ids))
