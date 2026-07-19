from __future__ import annotations

import asyncio
import time

from nonebot import get_driver, logger

from pallas.core.foundation.db import (
    make_group_config_repository,
    make_local_context_repository,
    make_message_repository,
)
from pallas.product.persona.group_profiler import DEFAULT_WINDOW_HOURS, build_group_style_profile_from_recent_repos
from pallas.product.persona.loader import invalidate_persona_cache

_dirty_group_ids: set[int] = set()
_pending_forced_teach: dict[int, int] = {}
_LIFECYCLE_BOUND = False
_DEFAULT_REFRESH_INTERVAL_SEC = 20 * 60
_DEFAULT_REFRESH_BATCH_SIZE = 32
_FORCED_TEACH_DECAY = 0.85
_FORCED_TEACH_EVENT_WEIGHT = 1.0
_FORCED_TEACH_WEIGHT_CAP = 10.0


def mark_group_style_dirty(group_id: int) -> None:
    _dirty_group_ids.add(int(group_id))


def mark_group_style_forced_teach(group_id: int, *, events: int = 1) -> None:
    gid = int(group_id)
    _dirty_group_ids.add(gid)
    _pending_forced_teach[gid] = int(_pending_forced_teach.get(gid, 0)) + max(1, int(events))


def pop_forced_teach_events(group_id: int) -> int:
    return int(_pending_forced_teach.pop(int(group_id), 0))


def merge_forced_teach_weight(previous_profile: dict | None, pending_events: int) -> float:
    prev = 0.0
    if isinstance(previous_profile, dict):
        sample = previous_profile.get("sample")
        if isinstance(sample, dict):
            prev = float(sample.get("forced_teach_weight") or 0.0)
    decayed = prev * _FORCED_TEACH_DECAY
    added = max(0, int(pending_events)) * _FORCED_TEACH_EVENT_WEIGHT
    return min(_FORCED_TEACH_WEIGHT_CAP, decayed + added)


def pop_dirty_group_style_batch(limit: int) -> list[int]:
    size = max(0, int(limit))
    if size <= 0 or not _dirty_group_ids:
        return []
    batch = sorted(_dirty_group_ids)[:size]
    _dirty_group_ids.difference_update(batch)
    return batch


def clear_group_style_dirty_state() -> None:
    _dirty_group_ids.clear()
    _pending_forced_teach.clear()


async def refresh_dirty_group_style_batch(
    *,
    limit: int = _DEFAULT_REFRESH_BATCH_SIZE,
    window_hours: int = DEFAULT_WINDOW_HOURS,
) -> int:
    from pallas.product.persona.affect_refine import affect_refine_llm_batch_limit

    refreshed = 0
    llm_budget = affect_refine_llm_batch_limit()
    llm_used = 0
    for group_id in pop_dirty_group_style_batch(limit):
        allow_llm = llm_used < llm_budget
        try:
            ok, used_llm = await refresh_group_style_profile(
                group_id,
                window_hours=window_hours,
                allow_llm_refine=allow_llm,
            )
        except Exception as exc:
            logger.warning("group_style_refresh failed group={}: {}", group_id, exc)
            continue
        if ok:
            refreshed += 1
        if used_llm:
            llm_used += 1
            await asyncio.sleep(1.0)
    return refreshed


async def refresh_group_style_profile(
    group_id: int,
    *,
    window_hours: int = DEFAULT_WINDOW_HOURS,
    allow_llm_refine: bool = True,
) -> tuple[bool, bool]:
    gid = int(group_id)
    now_ts = int(time.time())

    repo = make_group_config_repository()
    cfg = await repo.get(gid)
    prev_profile = getattr(cfg, "style_profile", None) if cfg is not None else None
    pending_teach = pop_forced_teach_events(gid)
    forced_teach_weight = merge_forced_teach_weight(
        prev_profile if isinstance(prev_profile, dict) else None,
        pending_teach,
    )

    message_repo = make_message_repository()
    context_repo = make_local_context_repository()
    profile = await build_group_style_profile_from_recent_repos(
        group_id=gid,
        message_repo=message_repo,
        context_repo=context_repo,
        now_ts=now_ts,
        window_hours=window_hours,
        forced_teach_weight=forced_teach_weight,
    )

    from pallas.product.persona.affect_refine import refine_group_style_affect
    from pallas.product.persona.affect_refine_client import collect_affect_refine_samples

    recent_messages = await message_repo.find_recent_in_group(gid, before_time=now_ts + 1, limit=32)
    profile, used_llm = await refine_group_style_affect(
        profile,
        group_id=gid,
        message_samples=collect_affect_refine_samples(list(recent_messages)),
        allow_llm=allow_llm_refine,
        prev_profile=prev_profile if isinstance(prev_profile, dict) else None,
        force_llm=pending_teach > 0,
    )

    await repo.upsert_field(gid, "style_profile", profile)
    invalidate_persona_cache()

    from pallas.product.persona.cross_group_refresh import mark_bots_cross_group_dirty_for_group

    await mark_bots_cross_group_dirty_for_group(gid, window_hours=window_hours)
    return True, used_llm


def bind_group_style_refresh_lifecycle() -> None:
    global _LIFECYCLE_BOUND
    if _LIFECYCLE_BOUND:
        return
    _LIFECYCLE_BOUND = True
    driver = get_driver()

    @driver.on_startup
    async def _start_group_style_refresh_worker() -> None:
        async def _run() -> None:
            while True:
                try:
                    await refresh_dirty_group_style_batch()
                    from pallas.product.persona.cross_group_refresh import refresh_dirty_bot_cross_group_batch

                    await refresh_dirty_bot_cross_group_batch()
                except Exception as exc:
                    logger.warning("group_style_refresh batch loop failed: {}", exc)
                await asyncio.sleep(_DEFAULT_REFRESH_INTERVAL_SEC)

        task = asyncio.create_task(_run(), name="group_style_refresh_worker")
        driver._pallas_group_style_refresh_task = task

    @driver.on_shutdown
    async def _stop_group_style_refresh_worker() -> None:
        task = getattr(driver, "_pallas_group_style_refresh_task", None)
        if task is None:
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        driver._pallas_group_style_refresh_task = None
