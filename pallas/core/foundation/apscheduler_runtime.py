"""APScheduler 在 APSCHEDULER_AUTOSTART=false 时仍由进程拉起。"""

from __future__ import annotations

from nonebot import get_driver
from nonebot.plugin import get_plugin

from pallas.core.foundation.startup_report import register_startup_fact

_APSCHEDULER_PLUGIN_ID = "nonebot_plugin_apscheduler"

_HOOK_REGISTERED = False


def ensure_apscheduler_running() -> None:
    try:
        from nonebot_plugin_apscheduler import scheduler
    except ImportError:
        return
    if scheduler.running:
        return
    scheduler.start()
    register_startup_fact("scheduler", "ready")


def register_apscheduler_startup_hook() -> None:
    """在 nonebot.init() 之后、load_plugin 阶段调用一次即可。"""
    global _HOOK_REGISTERED
    if _HOOK_REGISTERED:
        return
    if get_plugin(_APSCHEDULER_PLUGIN_ID) is None:
        return
    try:
        driver = get_driver()
    except ValueError:
        return

    @driver.on_startup
    async def ensure_apscheduler_on_startup() -> None:
        ensure_apscheduler_running()

    _HOOK_REGISTERED = True
