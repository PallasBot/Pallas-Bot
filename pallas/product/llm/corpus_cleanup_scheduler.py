"""Hub 周期语料扫库。"""

from __future__ import annotations

from datetime import datetime, timedelta

from nonebot import get_driver, logger
from nonebot_plugin_apscheduler import scheduler

from pallas.core.platform.bot_runtime.roles import is_sharded_worker
from pallas.product.llm.corpus_contamination import (
    corpus_cleanup_interval_sec,
    corpus_cleanup_scheduled_enabled,
    run_corpus_contamination_cleanup,
)

_JOB_ID = "corpus_contamination_cleanup"
_LIFECYCLE_BOUND = False


def should_run_corpus_cleanup_scheduler() -> bool:
    if is_sharded_worker():
        return False
    if not corpus_cleanup_scheduled_enabled():
        return False
    from pallas.core.foundation.db import is_mongodb_backend, is_postgresql_backend

    return is_postgresql_backend() or is_mongodb_backend()


async def run_corpus_cleanup_round() -> None:
    if not should_run_corpus_cleanup_scheduler():
        return
    try:
        report = await run_corpus_contamination_cleanup(apply=True, preview_limit=5)
    except Exception:
        logger.exception("语料污染周期扫库失败")
        return
    if report.deleted_answer_messages or report.deleted_message_history:
        logger.info(
            "语料污染周期扫库完成 answer_messages={} empty_answers={} message_history={}",
            report.deleted_answer_messages,
            report.deleted_empty_answers,
            report.deleted_message_history,
        )


async def start_corpus_cleanup_job() -> None:
    if not should_run_corpus_cleanup_scheduler():
        return
    if scheduler.get_job(_JOB_ID):
        scheduler.remove_job(_JOB_ID)
    interval_sec = corpus_cleanup_interval_sec()
    scheduler.add_job(
        run_corpus_cleanup_round,
        trigger="interval",
        seconds=interval_sec,
        id=_JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=600,
        next_run_time=datetime.now() + timedelta(seconds=300),
    )
    logger.debug("语料污染扫库：周期 {}s", interval_sec)


async def reload_corpus_cleanup_job() -> None:
    if scheduler.get_job(_JOB_ID):
        scheduler.remove_job(_JOB_ID)
    if should_run_corpus_cleanup_scheduler():
        await start_corpus_cleanup_job()


def bind_corpus_cleanup_lifecycle() -> None:
    global _LIFECYCLE_BOUND
    if _LIFECYCLE_BOUND:
        return
    _LIFECYCLE_BOUND = True
    driver = get_driver()

    @driver.on_startup
    async def _on_startup() -> None:
        await start_corpus_cleanup_job()
