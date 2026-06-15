from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import TYPE_CHECKING

from nonebot import get_loaded_plugins
from nonebot.log import logger

from src.foundation.config.repo_settings import repo_env_raw_value
from src.foundation.db.pool_budget import pg_pool_capacity, pg_pool_under_pressure
from src.platform.ingress.fleet_dispatch_scale import scaled_dispatch_int
from src.platform.ingress.matcher_activation import iter_matcher_checker_calls, matcher_is_command_only
from src.platform.ingress.route_index import matcher_module_key, plugin_module_key_from_plugin

if TYPE_CHECKING:
    from nonebot.adapters import Bot, Event
    from nonebot.matcher import Matcher

_COMMAND_CHECKER_NAMES = frozenset({"CommandRule", "ShellCommandRule"})
_LANE_BUSY_REPLY = "我习惯了站着不动思考。有时候啊，也会被大家突然戳一戳，看看睡着了没有"
_LANE_ALIASES: dict[str, str] = {
    "command_exact": "command",
    "command_regex": "command",
    "passive_light": "chat",
    "passive_db": "storage",
    "passive_http": "remote",
    "passive_ai": "remote",
    "passive_render": "remote",
}
_LANES: dict[str, LaneController] | None = None
_PLUGIN_LANE_CACHE: dict[str, str | None] | None = None


class DispatchLane(StrEnum):
    COMMAND = "command"
    CHAT = "chat"
    STORAGE = "storage"
    REMOTE = "remote"


@dataclass(frozen=True, slots=True)
class MatcherLaneResult:
    acquired: bool
    lane_busy: bool


class LaneController:
    def __init__(self, lane: str, base_limit: int) -> None:
        self.lane = lane
        self.base_limit = max(1, int(base_limit))
        self.in_use = 0
        self._cond = asyncio.Condition()

    def effective_limit(self) -> int:
        limit = self.base_limit
        if self.lane == DispatchLane.STORAGE and pg_pool_under_pressure(threshold=0.75):
            return max(1, limit // 2)
        return limit

    async def acquire(self, wait_budget_sec: float) -> tuple[bool, float]:
        start = time.monotonic()
        async with self._cond:
            while self.in_use >= self.effective_limit():
                remaining = wait_budget_sec - (time.monotonic() - start)
                if remaining <= 0:
                    return False, (time.monotonic() - start) * 1000.0
                try:
                    await asyncio.wait_for(self._cond.wait(), timeout=remaining)
                except TimeoutError:
                    return False, (time.monotonic() - start) * 1000.0
            self.in_use += 1
            return True, (time.monotonic() - start) * 1000.0

    async def release(self) -> None:
        async with self._cond:
            self.in_use = max(0, self.in_use - 1)
            self._cond.notify(1)


def normalize_lane(raw: str | None) -> str | None:
    text = (raw or "").strip().lower()
    if not text:
        return None
    if text in _LANE_ALIASES:
        return _LANE_ALIASES[text]
    try:
        return str(DispatchLane(text))
    except ValueError:
        return text


def dispatch_lanes_enabled() -> bool:
    raw = repo_env_raw_value("PALLAS_DISPATCH_LANES_ENABLED")
    if raw is None:
        return True
    text = str(raw).strip().lower()
    if text in ("0", "false", "no", "off"):
        return False
    return True


def lane_acquire_timeout_sec() -> float:
    raw = repo_env_raw_value("PALLAS_LANE_ACQUIRE_TIMEOUT_SEC")
    if raw is None:
        return 1.0
    try:
        return max(0.0, float(str(raw).strip()))
    except ValueError:
        return 1.0


def lane_busy_reply_enabled() -> bool:
    raw = repo_env_raw_value("PALLAS_LANE_BUSY_REPLY")
    if raw is None:
        return True
    text = str(raw).strip().lower()
    if text in ("0", "false", "no", "off"):
        return False
    return True


def _env_lane_limit(*keys: str, default: int) -> int:
    for key in keys:
        raw = repo_env_raw_value(key)
        if raw is None:
            continue
        try:
            return max(1, int(str(raw).strip()))
        except ValueError:
            continue
    return default


def default_lane_limits() -> dict[str, int]:
    pool_size_raw = repo_env_raw_value("PG_POOL_SIZE")
    try:
        pool_size = max(1, int(str(pool_size_raw if pool_size_raw is not None else "10").strip()))
    except ValueError:
        pool_size = 10
    storage_default = min(8, pool_size)
    command_default = scaled_dispatch_int(16, per_bot=2, cap=64)
    chat_default = scaled_dispatch_int(32, per_bot=1, cap=48)
    remote_default = scaled_dispatch_int(4, per_bot=1, cap=16)
    return {
        DispatchLane.COMMAND: _env_lane_limit(
            "PALLAS_LANE_COMMAND", "PALLAS_LANE_COMMAND_EXACT", default=command_default
        ),
        DispatchLane.CHAT: _env_lane_limit("PALLAS_LANE_CHAT", "PALLAS_LANE_PASSIVE_LIGHT", default=chat_default),
        DispatchLane.STORAGE: _env_lane_limit("PALLAS_LANE_STORAGE", "PALLAS_LANE_PASSIVE_DB", default=storage_default),
        DispatchLane.REMOTE: _env_lane_limit(
            "PALLAS_LANE_REMOTE",
            "PALLAS_LANE_PASSIVE_AI",
            "PALLAS_LANE_PASSIVE_RENDER",
            "PALLAS_LANE_PASSIVE_HTTP",
            default=remote_default,
        ),
    }


def clear_dispatch_lanes_cache() -> None:
    global _LANES, _PLUGIN_LANE_CACHE
    _LANES = None
    _PLUGIN_LANE_CACHE = None
    lane_for_matcher.cache_clear()


def plugin_lane_override(module_key: str) -> str | None:
    global _PLUGIN_LANE_CACHE
    if _PLUGIN_LANE_CACHE is None:
        mapping: dict[str, str | None] = {}
        for plugin in get_loaded_plugins():
            key = plugin_module_key_from_plugin(plugin)
            meta = getattr(plugin, "metadata", None)
            extra = getattr(meta, "extra", None) if meta is not None else None
            lane: str | None = None
            if isinstance(extra, dict):
                ingress_route = extra.get("ingress_route")
                if isinstance(ingress_route, dict):
                    lane = normalize_lane(str(ingress_route.get("lane") or ""))
            mapping[key] = lane or None
        _PLUGIN_LANE_CACHE = mapping
    return _PLUGIN_LANE_CACHE.get(module_key)


def _checker_name(checker: object) -> str:
    return type(checker).__name__


@lru_cache(maxsize=512)
def lane_for_matcher(matcher: type[Matcher]) -> str:
    module_key = matcher_module_key(matcher)
    override = plugin_lane_override(module_key)
    if override:
        return override

    calls = tuple(iter_matcher_checker_calls(matcher))
    if matcher_is_command_only(matcher) or any(_checker_name(call) in _COMMAND_CHECKER_NAMES for call in calls):
        return DispatchLane.COMMAND

    return DispatchLane.CHAT


def install_dispatch_lanes() -> None:
    global _LANES
    if _LANES is not None or not dispatch_lanes_enabled():
        return
    limits = default_lane_limits()
    _LANES = {lane: LaneController(lane, limit) for lane, limit in limits.items()}
    logger.info(
        "dispatch_lanes: installed command={} chat={} storage={} remote={} pool_capacity={}",
        limits[DispatchLane.COMMAND],
        limits[DispatchLane.CHAT],
        limits[DispatchLane.STORAGE],
        limits[DispatchLane.REMOTE],
        pg_pool_capacity(),
    )


def uninstall_dispatch_lanes() -> None:
    global _LANES
    _LANES = None


def lane_controller(lane: str) -> LaneController | None:
    if _LANES is None:
        return None
    normalized = normalize_lane(lane)
    if normalized is None:
        return None
    return _LANES.get(normalized)


async def acquire_lane(lane: str, *, wait_budget_sec: float | None = None) -> tuple[bool, float]:
    normalized = normalize_lane(lane) or lane
    controller = lane_controller(normalized)
    if controller is None:
        return True, 0.0
    budget = lane_acquire_timeout_sec() if wait_budget_sec is None else max(0.0, wait_budget_sec)
    if normalized == DispatchLane.STORAGE and pg_pool_under_pressure(threshold=0.80) and budget > 0:
        budget = min(budget, 0.05)
    return await controller.acquire(budget)


async def release_lane(lane: str) -> None:
    normalized = normalize_lane(lane) or lane
    controller = lane_controller(normalized)
    if controller is None:
        return
    await controller.release()


async def maybe_send_lane_busy_reply(
    bot: Bot,
    event: Event,
    *,
    command_traffic: bool,
    already_sent: bool,
) -> bool:
    if already_sent or not command_traffic or not lane_busy_reply_enabled():
        return already_sent
    from nonebot.adapters.onebot.v11 import GroupMessageEvent

    if not isinstance(event, GroupMessageEvent):
        return already_sent
    try:
        await bot.send(event, _LANE_BUSY_REPLY)
    except Exception as exc:
        logger.debug("dispatch_lanes: busy reply failed: {}", exc)
        return already_sent
    return True


async def check_and_run_matcher_with_lane(
    matcher: type[Matcher],
    bot: Bot,
    event: Event,
    state: dict,
    stack,
    dependency_cache: dict,
    *,
    command_traffic: bool,
) -> MatcherLaneResult:
    import nonebot.message as nb_message

    from src.platform.ingress.message_load import record_lane_wait

    if not dispatch_lanes_enabled():
        await nb_message.check_and_run_matcher(matcher, bot, event, state, stack, dependency_cache)
        return MatcherLaneResult(acquired=True, lane_busy=False)

    lane = lane_for_matcher(matcher)
    acquired, wait_ms = await acquire_lane(lane)
    record_lane_wait(wait_ms, busy=not acquired)
    if not acquired:
        return MatcherLaneResult(acquired=False, lane_busy=command_traffic)
    try:
        await nb_message.check_and_run_matcher(matcher, bot, event, state, stack, dependency_cache)
    finally:
        await release_lane(lane)
    return MatcherLaneResult(acquired=True, lane_busy=False)
