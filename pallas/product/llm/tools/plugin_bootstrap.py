"""扫描已加载插件，将 extra['llm_tools'] 注册进 registry。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pallas.product.llm.tools.command_invoke import (
    CommandTemplateError,
    dispatch_group_command_text,
    render_command_template,
)
from pallas.product.llm.tools.contracts import ToolCapability
from pallas.product.llm.tools.metadata import LlmCommandToolDecl, iter_loaded_plugin_llm_tools
from pallas.product.llm.tools.registry import LlmToolSource, LlmToolSpec, register_tool

if TYPE_CHECKING:
    from pallas.product.llm.tools.context import ToolInvokeContext

_PLUGIN_TOOL_NAMES: set[str] = set()


def clear_plugin_command_tools() -> None:
    _PLUGIN_TOOL_NAMES.clear()


def register_plugin_command_tools() -> int:
    count = 0
    for plugin_name, plugin_title, decl in iter_loaded_plugin_llm_tools():
        if decl.name in _PLUGIN_TOOL_NAMES:
            continue
        register_tool(build_command_tool_spec(decl, plugin_name=plugin_name, plugin_title=plugin_title))
        _PLUGIN_TOOL_NAMES.add(decl.name)
        count += 1
    return count


def build_command_tool_spec(
    decl: LlmCommandToolDecl,
    *,
    plugin_name: str,
    plugin_title: str,
) -> LlmToolSpec:
    description = f"{decl.description}（插件：{plugin_title}）"

    async def handler(args: dict, ctx: ToolInvokeContext | None) -> dict:
        if ctx is None:
            return {"ok": False, "error": "missing_invoke_context"}
        try:
            command_text = render_command_template(decl.command_template, args)
        except CommandTemplateError as exc:
            return {"ok": False, "error": str(exc)}
        result = await dispatch_group_command_text(
            ctx,
            command_id=decl.command_id,
            command_text=command_text,
        )
        return {
            "plugin": plugin_name,
            "tool": decl.name,
            **result,
        }

    return LlmToolSpec(
        name=decl.name,
        description=description,
        parameters=decl.parameters or {"type": "object", "properties": {}},
        domains=frozenset({"command", plugin_name}),
        handler=handler,
        source=LlmToolSource.PLUGIN_COMMAND,
        command_id=decl.command_id,
        plugin_name=plugin_name,
        capabilities=frozenset({
            ToolCapability.SIDE_EFFECTING.value,
            ToolCapability.REQUIRES_GROUP_CONTEXT.value,
        }),
    )
