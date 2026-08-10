"""Daily database lifecycle maintenance registration."""

from __future__ import annotations

from nonebot import logger
from nonebot_plugin_apscheduler import scheduler

from .db_lifecycle_api import get_lifecycle_service

_SCHEDULE_JOB_ID = "pallas_database_lifecycle_daily"


async def run_database_lifecycle_maintenance() -> None:
    try:
        jobs = await get_lifecycle_service().run_enabled_policies(exclude=frozenset({"image_cache"}))
    except Exception:  # noqa: BLE001
        logger.exception("database lifecycle maintenance failed")
        return
    if jobs:
        logger.info(
            "database lifecycle maintenance completed jobs={} deleted_rows={}",
            len(jobs),
            sum(job.deleted_rows for job in jobs),
        )


def install_database_lifecycle_schedule() -> None:
    scheduler.add_job(
        run_database_lifecycle_maintenance,
        "cron",
        hour=4,
        minute=45,
        id=_SCHEDULE_JOB_ID,
        replace_existing=True,
    )
