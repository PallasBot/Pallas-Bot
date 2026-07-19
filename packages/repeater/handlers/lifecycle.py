"""复读插件启动/关闭钩子。"""

from __future__ import annotations

from nonebot import get_driver

from ..model import Chat

driver = get_driver()


@driver.on_startup
async def startup():
    await Chat.update_global_blacklist()


@driver.on_shutdown
async def shutdown():
    try:
        await Chat.sync()
    except Exception:
        pass
