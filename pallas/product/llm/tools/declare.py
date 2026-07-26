"""在 PluginMetadata.extra 中声明 LLM 可调用的插件命令。"""

from __future__ import annotations

from typing import Any, Literal

ToolVisibility = Literal["visible", "deferred"]
SourceSegmentsMode = Literal["none", "media"]


def llm_command_tool_row(
    *,
    name: str,
    command_id: str,
    description: str,
    parameters: dict[str, Any],
    command_template: str,
    default: bool = True,
    hints: list[str] | None = None,
    visibility: ToolVisibility = "visible",
    source_segments: SourceSegmentsMode = "none",
) -> dict[str, Any]:
    """单条 ``extra['llm_tools']`` 项：意图识别后按模板拼口令并派发。

    hints: 口语触发词；硬域未命中时参与 soft_recall 工具级打分。
    visibility: visible 随域注入；deferred 仅在自身 hints 命中或经 tools.find 激活后注入。
    source_segments: media 时透传原消息的图片 / @ /「自己」；其余口令不附加素材。
    """
    tool_name = (name or "").strip()
    cid = (command_id or "").strip()
    if not tool_name or not cid:
        raise ValueError("name 与 command_id 不能为空")
    template = (command_template or "").strip()
    if not template:
        raise ValueError("command_template 不能为空")
    vis = (visibility or "visible").strip().lower()
    if vis not in {"visible", "deferred"}:
        vis = "visible"
    segment_mode = (source_segments or "none").strip().lower()
    if segment_mode not in {"none", "media"}:
        segment_mode = "none"
    hint_list = [str(item).strip() for item in (hints or []) if str(item).strip()]
    row: dict[str, Any] = {
        "name": tool_name,
        "command_id": cid,
        "description": (description or tool_name).strip(),
        "parameters": parameters if isinstance(parameters, dict) else {},
        "command_template": template,
        "default": bool(default),
        "visibility": vis,
        "source_segments": segment_mode,
    }
    if hint_list:
        row["hints"] = hint_list
    return row
