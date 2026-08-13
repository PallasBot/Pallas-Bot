from nonebot import get_driver
from nonebot_plugin_apscheduler import scheduler

from pallas.api.logging import register_plugin_startup_ready
from pallas.core.foundation.config import BotConfig

driver = get_driver()


@scheduler.scheduled_job("cron", hour=4)
async def fully_sober_up_all():
    await BotConfig.fully_sober_up()


@driver.on_startup
async def drink_startup() -> None:
    if not scheduler.running:
        scheduler.start()
    register_plugin_startup_ready("drink", detail="每日清醒定时维护已调度")


@driver.on_shutdown
async def drink_shutdown() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
