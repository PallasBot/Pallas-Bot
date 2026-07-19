from nonebot import logger
from nonebot_plugin_apscheduler import scheduler

from .handlers import run_change_name


@scheduler.scheduled_job("cron", minute="*/1")
async def change_name():
    try:
        await run_change_name()
    except Exception:
        logger.exception("take_name: change_name 定时任务失败")
