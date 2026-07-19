"""方舟知识库后台同步（kb_sync_plan）。"""

from __future__ import annotations

import asyncio

from nonebot import logger

from packages.repeater.shard_opt import repeater_maintenance_runs_on_worker
from pallas.core.domain.arknights.sync import kb_sync_plan, run_arknights_sync
from pallas.product.arknights_kb.config import get_arknights_kb_config
from pallas.product.arknights_kb.readiness import kb_sync_gaps

_sync_lock = asyncio.Lock()
_background_sync_task: asyncio.Task[None] | None = None


def kb_sync_runs_on_worker() -> bool:
    return repeater_maintenance_runs_on_worker()


def needs_background_kb_sync() -> bool:
    cfg = get_arknights_kb_config()
    if not cfg.arknights_kb_enabled or not cfg.arknights_kb_auto_sync:
        return False
    if not kb_sync_runs_on_worker():
        return False
    return bool(kb_sync_gaps())


async def sync_kb_data_async() -> bool:
    gaps = kb_sync_gaps()
    if not gaps:
        return True
    async with _sync_lock:
        gaps = kb_sync_gaps()
        if not gaps:
            return True
        logger.info("arknights kb: background sync start gaps={}", gaps)
        plan = kb_sync_plan(avatars=False)
        result = await asyncio.to_thread(run_arknights_sync, plan)
        for line in result.messages:
            logger.info("arknights kb: {}", line)
        ready = not kb_sync_gaps()
        logger.info(
            "arknights kb: background sync done ready={} operators={} enemies={}",
            ready,
            result.operators_count,
            result.enemies_count,
        )
        return ready


async def run_background_kb_sync() -> None:
    try:
        await sync_kb_data_async()
    except Exception as err:
        logger.error("arknights kb: background sync failed: {}", err)


def schedule_arknights_kb_sync() -> None:
    global _background_sync_task
    if not needs_background_kb_sync():
        return
    if _background_sync_task is not None and not _background_sync_task.done():
        logger.debug("arknights kb: background sync already running, skip")
        return
    loop = asyncio.get_running_loop()
    _background_sync_task = loop.create_task(
        run_background_kb_sync(),
        name="arknights_kb_sync",
    )
