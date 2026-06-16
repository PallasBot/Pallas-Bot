"""APScheduler 在 APSCHEDULER_AUTOSTART=false 时仍由进程拉起。"""

from __future__ import annotations

from nonebot import get_driver, logger

_HOOK_REGISTERED = False


def ensure_apscheduler_running() -> None:
    try:
        from nonebot_plugin_apscheduler import scheduler
    except ImportError:
        return
    if scheduler.running:
        return
    scheduler.start()
    logger.info("启动：定时任务调度器已就绪")


def register_apscheduler_startup_hook() -> None:
    """在 nonebot.init() 之后、load_plugin 阶段调用一次即可。"""
    global _HOOK_REGISTERED
    if _HOOK_REGISTERED:
        return
    try:
        import nonebot_plugin_apscheduler  # noqa: F401
    except ImportError:
        return
    try:
        driver = get_driver()
    except ValueError:
        return

    @driver.on_startup
    async def ensure_apscheduler_on_startup() -> None:
        ensure_apscheduler_running()

    _HOOK_REGISTERED = True
