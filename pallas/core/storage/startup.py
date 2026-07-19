"""启动后刷新 plugin_storage 声明缓存。"""

from __future__ import annotations

from nonebot import get_driver

_HOOK_REGISTERED = False


def register_plugin_storage_startup_hook() -> None:
    global _HOOK_REGISTERED
    if _HOOK_REGISTERED:
        return
    driver = get_driver()

    @driver.on_startup
    async def refresh_plugin_storage_registry() -> None:
        from pallas.core.storage.schema import clear_plugin_storage_registry_cache

        clear_plugin_storage_registry_cache()

    _HOOK_REGISTERED = True
