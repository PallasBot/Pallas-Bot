"""启动后按需同步方舟知识库。"""

from __future__ import annotations

from nonebot import get_driver

_HOOK_REGISTERED = False


def register_arknights_kb_startup_hook() -> None:
    global _HOOK_REGISTERED
    if _HOOK_REGISTERED:
        return
    driver = get_driver()

    @driver.on_startup
    async def schedule_arknights_kb_on_startup() -> None:
        from pallas.product.arknights_kb.sync_runtime import schedule_arknights_kb_sync

        schedule_arknights_kb_sync()

    _HOOK_REGISTERED = True
