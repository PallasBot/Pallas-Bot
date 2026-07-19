"""启动后刷新插件 LLM tools。"""

from __future__ import annotations

from nonebot import get_driver

_HOOK_REGISTERED = False


def register_llm_tools_startup_hook() -> None:
    global _HOOK_REGISTERED
    if _HOOK_REGISTERED:
        return
    driver = get_driver()

    @driver.on_startup
    async def refresh_plugin_llm_tools() -> None:
        from pallas.product.llm.tools.bootstrap import ensure_llm_tools_bootstrapped

        ensure_llm_tools_bootstrapped(force=True)

    _HOOK_REGISTERED = True
