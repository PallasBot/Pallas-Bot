"""启动后刷新插件 LLM tools。"""

from __future__ import annotations

from nonebot import get_driver

from pallas.core.foundation.startup_report import register_startup_ready, register_startup_scheduled

_HOOK_REGISTERED = False


def register_llm_tools_startup_hook() -> None:
    global _HOOK_REGISTERED
    if _HOOK_REGISTERED:
        return
    driver = get_driver()

    @driver.on_startup
    async def refresh_plugin_llm_tools() -> None:
        from pallas.product.llm.feedback_embedding_cache import schedule_feedback_trigger_backfill
        from pallas.product.llm.repeater_feedback import schedule_feedback_index_prewarm
        from pallas.product.llm.tools.background import resume_background_tool_tasks
        from pallas.product.llm.tools.bootstrap import ensure_llm_tools_bootstrapped

        ensure_llm_tools_bootstrapped(force=True)
        await resume_background_tool_tasks()
        schedule_feedback_trigger_backfill()
        schedule_feedback_index_prewarm()
        register_startup_ready("LLM 工具")
        register_startup_scheduled("反馈向量回填")

    _HOOK_REGISTERED = True
