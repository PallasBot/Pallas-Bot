"""本机语料 backfill 周期任务。"""

from __future__ import annotations

from datetime import datetime, timedelta

from nonebot import get_driver, logger
from nonebot_plugin_apscheduler import scheduler

from src.features.corpus.backfill import (
    corpus_backfill_interval_sec,
    run_corpus_backfill_round,
    should_run_corpus_backfill,
)

_JOB_ID = "corpus_backfill"
_LIFECYCLE_BOUND = False


async def start_corpus_backfill_job() -> None:
    if not should_run_corpus_backfill():
        return
    if scheduler.get_job(_JOB_ID):
        scheduler.remove_job(_JOB_ID)
    interval_sec = corpus_backfill_interval_sec()
    scheduler.add_job(
        run_corpus_backfill_round,
        trigger="interval",
        seconds=interval_sec,
        id=_JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
        next_run_time=datetime.now() + timedelta(seconds=120),
    )
    logger.info("corpus backfill: scheduled interval_sec={}", interval_sec)


async def reload_corpus_backfill_job() -> None:
    if scheduler.get_job(_JOB_ID):
        scheduler.remove_job(_JOB_ID)
    if should_run_corpus_backfill():
        await start_corpus_backfill_job()


def bind_corpus_backfill_lifecycle() -> None:
    global _LIFECYCLE_BOUND
    if _LIFECYCLE_BOUND:
        return
    _LIFECYCLE_BOUND = True
    driver = get_driver()

    @driver.on_startup
    async def _on_startup() -> None:
        await start_corpus_backfill_job()
