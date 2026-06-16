from __future__ import annotations

import asyncio
import time

from nonebot import get_driver, logger

from src.features.persona.group_profiler import DEFAULT_WINDOW_HOURS, build_group_style_profile_from_recent_repos
from src.features.persona.loader import invalidate_persona_cache
from src.foundation.db import make_group_config_repository, make_local_context_repository, make_message_repository

_dirty_group_ids: set[int] = set()
_LIFECYCLE_BOUND = False
_DEFAULT_REFRESH_INTERVAL_SEC = 20 * 60
_DEFAULT_REFRESH_BATCH_SIZE = 32


def mark_group_style_dirty(group_id: int) -> None:
    _dirty_group_ids.add(int(group_id))


def pop_dirty_group_style_batch(limit: int) -> list[int]:
    size = max(0, int(limit))
    if size <= 0 or not _dirty_group_ids:
        return []
    batch = sorted(_dirty_group_ids)[:size]
    _dirty_group_ids.difference_update(batch)
    return batch


def clear_group_style_dirty_state() -> None:
    _dirty_group_ids.clear()


async def refresh_dirty_group_style_batch(
    *,
    limit: int = _DEFAULT_REFRESH_BATCH_SIZE,
    window_hours: int = DEFAULT_WINDOW_HOURS,
) -> int:
    refreshed = 0
    for group_id in pop_dirty_group_style_batch(limit):
        try:
            ok = await refresh_group_style_profile(group_id, window_hours=window_hours)
        except Exception as exc:
            logger.warning("group_style_refresh failed group={}: {}", group_id, exc)
            continue
        if ok:
            refreshed += 1
    return refreshed


async def refresh_group_style_profile(group_id: int, *, window_hours: int = DEFAULT_WINDOW_HOURS) -> bool:
    gid = int(group_id)
    now_ts = int(time.time())

    message_repo = make_message_repository()
    context_repo = make_local_context_repository()
    profile = await build_group_style_profile_from_recent_repos(
        group_id=gid,
        message_repo=message_repo,
        context_repo=context_repo,
        now_ts=now_ts,
        window_hours=window_hours,
    )

    repo = make_group_config_repository()
    await repo.upsert_field(gid, "style_profile", profile)
    invalidate_persona_cache()

    from src.features.persona.cross_group_refresh import mark_bots_cross_group_dirty_for_group

    await mark_bots_cross_group_dirty_for_group(gid, window_hours=window_hours)
    return True


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
                    from src.features.persona.cross_group_refresh import refresh_dirty_bot_cross_group_batch

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
