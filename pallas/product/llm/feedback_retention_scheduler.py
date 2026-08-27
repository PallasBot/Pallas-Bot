"""反馈试数据周期归档。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from nonebot import get_driver, logger
from nonebot_plugin_apscheduler import scheduler

from pallas.core.foundation.startup_report import register_startup_scheduled, register_startup_skipped
from pallas.core.platform.bot_runtime.roles import is_sharded_worker
from pallas.product.llm.repeater_feedback import compact_feedback_entries

_JOB_ID = "llm_feedback_retention_compaction"
_LIFECYCLE_BOUND = False


def feedback_retention_scheduled_enabled() -> bool:
    from pallas.product.llm.config import get_llm_config

    return bool(get_llm_config().llm_feedback_retention_scheduled_enabled)


def feedback_retention_days() -> int:
    from pallas.product.llm.config import get_llm_config

    return max(1, int(get_llm_config().llm_feedback_retention_days))


def feedback_retention_interval_sec() -> int:
    from pallas.product.llm.config import get_llm_config

    return max(3600, int(get_llm_config().llm_feedback_retention_interval_sec))


def should_run_feedback_retention_scheduler() -> bool:
    if is_sharded_worker():
        return False
    return feedback_retention_scheduled_enabled()


async def run_feedback_retention_round() -> None:
    if not should_run_feedback_retention_scheduler():
        return
    try:
        report = await asyncio.to_thread(
            compact_feedback_entries,
            retention_days=feedback_retention_days(),
        )
    except Exception:
        logger.exception("LLM feedback retention compaction failed")
        return
    if report.get("archived"):
        logger.info(
            "LLM feedback retention archived [{}] entries, retained [{}] of [{}]",
            report.get("archived"),
            report.get("retained"),
            report.get("total"),
        )


async def start_feedback_retention_job() -> None:
    if not should_run_feedback_retention_scheduler():
        register_startup_skipped("反馈归档", "reason=disabled")
        return
    if scheduler.get_job(_JOB_ID):
        scheduler.remove_job(_JOB_ID)
    interval_sec = feedback_retention_interval_sec()
    retention_days = feedback_retention_days()
    scheduler.add_job(
        run_feedback_retention_round,
        trigger="interval",
        seconds=interval_sec,
        id=_JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=600,
        next_run_time=datetime.now() + timedelta(seconds=300),
    )
    logger.debug("Feedback retention: interval [{}s], retention [{}d]", interval_sec, retention_days)
    register_startup_scheduled("反馈归档", f"间隔 [{interval_sec}s] 保留 [{retention_days}d]")


async def reload_feedback_retention_job() -> None:
    if scheduler.get_job(_JOB_ID):
        scheduler.remove_job(_JOB_ID)
    if should_run_feedback_retention_scheduler():
        await start_feedback_retention_job()


def bind_feedback_retention_lifecycle() -> None:
    global _LIFECYCLE_BOUND
    if _LIFECYCLE_BOUND:
        return
    _LIFECYCLE_BOUND = True
    driver = get_driver()

    @driver.on_startup
    async def _on_startup() -> None:
        await start_feedback_retention_job()
