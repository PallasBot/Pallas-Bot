"""统一引导：内置 domain tools + 插件声明 command tools。"""

from __future__ import annotations

from pallas.product.llm.tools.arknights import register_arknights_tools
from pallas.product.llm.tools.discovery import register_discovery_tools
from pallas.product.llm.tools.history import register_history_tools
from pallas.product.llm.tools.mcp_bootstrap import clear_mcp_tools, register_mcp_tools
from pallas.product.llm.tools.memory import register_memory_tools
from pallas.product.llm.tools.person import register_person_tools
from pallas.product.llm.tools.plugin_bootstrap import clear_plugin_command_tools, register_plugin_command_tools
from pallas.product.llm.tools.reply import register_reply_tools
from pallas.product.llm.tools.social import register_social_tools
from pallas.product.llm.tools.tasks import register_task_tools
from pallas.product.llm.tools.time_now import register_time_tools
from pallas.product.llm.tools.web import register_web_tools

_BOOTSTRAPPED = False


def ensure_llm_tools_bootstrapped(*, force: bool = False) -> None:
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED and not force:
        return
    if force:
        from pallas.product.llm.tools.registry import clear_tool_registry

        clear_tool_registry()
        clear_plugin_command_tools()
        clear_mcp_tools()
    register_arknights_tools()
    register_memory_tools()
    register_discovery_tools()
    register_reply_tools()
    register_web_tools()
    register_history_tools()
    register_person_tools()
    register_social_tools()
    register_task_tools()
    register_time_tools()
    register_plugin_command_tools()
    register_mcp_tools()
    _BOOTSTRAPPED = True


def reset_llm_tools_bootstrap_for_tests() -> None:
    global _BOOTSTRAPPED
    _BOOTSTRAPPED = False
    clear_plugin_command_tools()
    clear_mcp_tools()
    from pallas.product.llm.tools.registry import clear_tool_registry

    clear_tool_registry()
