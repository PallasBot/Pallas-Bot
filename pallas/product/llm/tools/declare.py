"""在 PluginMetadata.extra 中声明 LLM 可调用的插件命令。"""

from __future__ import annotations

from typing import Any


def llm_command_tool_row(
    *,
    name: str,
    command_id: str,
    description: str,
    parameters: dict[str, Any],
    command_template: str,
    default: bool = True,
) -> dict[str, Any]:
    """单条 ``extra['llm_tools']`` 项：意图识别后按模板拼口令并派发。"""
    tool_name = (name or "").strip()
    cid = (command_id or "").strip()
    if not tool_name or not cid:
        raise ValueError("name 与 command_id 不能为空")
    template = (command_template or "").strip()
    if not template:
        raise ValueError("command_template 不能为空")
    return {
        "name": tool_name,
        "command_id": cid,
        "description": (description or tool_name).strip(),
        "parameters": parameters if isinstance(parameters, dict) else {},
        "command_template": template,
        "default": bool(default),
    }
