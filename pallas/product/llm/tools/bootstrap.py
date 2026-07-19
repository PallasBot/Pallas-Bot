"""统一引导：内置 domain tools + 插件声明 command tools。"""

from __future__ import annotations

from pallas.product.llm.tools.arknights import register_arknights_tools
from pallas.product.llm.tools.mcp_bootstrap import clear_mcp_tools, register_mcp_tools
from pallas.product.llm.tools.memory import register_memory_tools
from pallas.product.llm.tools.plugin_bootstrap import clear_plugin_command_tools, register_plugin_command_tools

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
