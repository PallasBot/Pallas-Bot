"""接话 LLM 限流：群冷却、进程内并发与全局限流。"""

import asyncio
import time

from nonebot import logger

from pallas.core.foundation.config import BotConfig
from pallas.core.platform.shard.coord.coord_redis_store import coord_key, redis_client_or_none

from .config import LlmConfig, get_llm_config

REPEATER_LLM_TASKS = frozenset({"repeater_fallback", "repeater_polish", "repeater_polish_lite", "repeater_select"})
_COOLDOWN_ACTION = "llm_repeater"

_repeater_sem: asyncio.Semaphore | None = None
_repeater_sem_limit: int | None = None
_local_rpm_window: int | None = None
_local_rpm_count: int = 0
_skipped_group_cd: int = 0
_skipped_inflight: int = 0
_skipped_global_rpm: int = 0


def clear_repeater_llm_limit_state() -> None:
    global _repeater_sem, _repeater_sem_limit, _local_rpm_window, _local_rpm_count
    _repeater_sem = None
    _repeater_sem_limit = None
    _local_rpm_window = None
    _local_rpm_count = 0


def is_repeater_llm_task(task: str | None) -> bool:
    return str(task or "").strip().lower() in REPEATER_LLM_TASKS


def repeater_max_inflight(cfg: LlmConfig | None = None) -> int:
    c = cfg or get_llm_config()
    return max(1, int(c.llm_repeater_max_inflight))


def repeater_sem() -> asyncio.Semaphore:
    global _repeater_sem, _repeater_sem_limit
    limit = repeater_max_inflight()
    if _repeater_sem is None or _repeater_sem_limit != limit:
        _repeater_sem = asyncio.Semaphore(limit)
        _repeater_sem_limit = limit
    return _repeater_sem


def estimated_production_workers() -> int:
    try:
        from pallas.core.platform.shard.worker_scale import production_worker_count_required

        return max(1, production_worker_count_required())
    except Exception:
        return 8


def per_worker_global_rpm_limit(cfg: LlmConfig | None = None) -> int:
    c = cfg or get_llm_config()
    total = max(1, int(c.llm_repeater_global_rpm))
    workers = estimated_production_workers()
    return max(1, (total + workers - 1) // workers)


def try_consume_local_rpm(cfg: LlmConfig | None = None) -> bool:
    global _local_rpm_window, _local_rpm_count
    limit = per_worker_global_rpm_limit(cfg)
    window = int(time.time()) // 60
    if _local_rpm_window != window:
        _local_rpm_window = window
        _local_rpm_count = 0
    if _local_rpm_count >= limit:
        return False
    _local_rpm_count += 1
    return True


def try_consume_global_rpm(cfg: LlmConfig | None = None) -> bool:
    c = cfg or get_llm_config()
    limit = max(1, int(c.llm_repeater_global_rpm))
    client = redis_client_or_none()
    if client is None:
        return try_consume_local_rpm(c)
    window = int(time.time()) // 60
    key = coord_key("llm_repeater_rpm", window)
    try:
        count = int(client.incr(key))
        if count == 1:
            client.expire(key, 120)
        return count <= limit
    except Exception:
        return try_consume_local_rpm(c)


async def is_repeater_group_cooldown_ready(
    bot_id: int,
    group_id: int,
    *,
    cfg: LlmConfig | None = None,
) -> bool:
    c = cfg or get_llm_config()
    cd_sec = max(0, int(c.llm_repeater_group_cooldown_sec))
    if cd_sec <= 0:
        return True
    config = BotConfig(int(bot_id), int(group_id), cooldown=cd_sec)
    return await config.is_cooldown(_COOLDOWN_ACTION)


async def refresh_repeater_group_cooldown(bot_id: int, group_id: int) -> None:
    c = get_llm_config()
    if int(c.llm_repeater_group_cooldown_sec) <= 0:
        return
    config = BotConfig(int(bot_id), int(group_id), cooldown=int(c.llm_repeater_group_cooldown_sec))
    await config.refresh_cooldown(_COOLDOWN_ACTION)


async def check_repeater_llm_allowed(
    bot_id: int,
    group_id: int,
    *,
    cfg: LlmConfig | None = None,
) -> str | None:
    global _skipped_group_cd, _skipped_global_rpm
    c = cfg or get_llm_config()
    if not c.llm_governance_enabled:
        return None
    if not await is_repeater_group_cooldown_ready(bot_id, group_id, cfg=c):
        _skipped_group_cd += 1
        if _skipped_group_cd == 1 or _skipped_group_cd % 100 == 0:
            logger.debug(
                "repeater llm skipped group cooldown: bot={} group={} count={}",
                bot_id,
                group_id,
                _skipped_group_cd,
            )
        return "repeater_group_cooldown"
    if not try_consume_global_rpm(c):
        _skipped_global_rpm += 1
        if _skipped_global_rpm == 1 or _skipped_global_rpm % 100 == 0:
            logger.debug(
                "repeater llm skipped global rpm: bot={} group={} count={}",
                bot_id,
                group_id,
                _skipped_global_rpm,
            )
        return "repeater_global_rpm"
    return None


class RepeaterLlmSlot:
    __slots__ = ("acquired",)

    def __init__(self) -> None:
        self.acquired = False


async def try_acquire_repeater_llm_slot(*, cfg: LlmConfig | None = None) -> RepeaterLlmSlot | None:
    global _skipped_inflight
    c = cfg or get_llm_config()
    if not c.llm_governance_enabled:
        slot = RepeaterLlmSlot()
        slot.acquired = True
        return slot
    sem = repeater_sem()
    if sem.locked():
        _skipped_inflight += 1
        if _skipped_inflight == 1 or _skipped_inflight % 100 == 0:
            logger.debug("repeater llm skipped inflight busy count={}", _skipped_inflight)
        return None
    await sem.acquire()
    slot = RepeaterLlmSlot()
    slot.acquired = True
    return slot


def release_repeater_llm_slot(slot: RepeaterLlmSlot | None) -> None:
    if slot is None or not slot.acquired:
        return
    c = get_llm_config()
    if not c.llm_governance_enabled:
        slot.acquired = False
        return
    repeater_sem().release()
    slot.acquired = False
