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
_MEDIA_TOOL_PREFIXES = frozenset({"draw", "memes"})


def command_dispatch_result_summary(command_text: str) -> str:
    """口令派发成功后写入 tool result.summary，约束后续确认语气。"""
    text = str(command_text or "").strip() or "（空口令）"
    return (
        f"已执行「{text}」。若需开口：用极短口语 ack 即可，也可不说话（PASS/空）；"
        "禁止「已派发/帮你找找/正在生成」等系统腔；禁止编造未发生的结果；"
        "勿把「随机」「随便」等占位词当歌名念出来；有明确歌名或玩法口令时才可点到。"
    )


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
    source_segments_mode = str(decl.source_segments or "none").strip().lower()
    if source_segments_mode not in {"none", "media"}:
        source_segments_mode = "none"
    # 兼容已发布的画图 / 表情插件声明；后续声明应显式标记 source_segments="media"。
    if source_segments_mode == "none" and decl.name.split(".", 1)[0] in _MEDIA_TOOL_PREFIXES:
        source_segments_mode = "media"

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
            source_segments_mode=source_segments_mode,
        )
        if not bool(result.get("ok")):
            return {
                "ok": False,
                "error": str(result.get("error") or "dispatch_failed"),
                "result": {
                    "plugin": plugin_name,
                    "tool": decl.name,
                    "command_id": decl.command_id,
                    "command_text": command_text,
                    "arguments": {key: str(value) for key, value in args.items()},
                },
            }
        summary = command_dispatch_result_summary(command_text)
        return {
            "ok": True,
            "result": {
                "plugin": plugin_name,
                "tool": decl.name,
                "command_id": decl.command_id,
                "command_text": command_text,
                "dispatched": True,
                "arguments": {key: str(value) for key, value in args.items()},
                "summary": summary,
            },
        }

    hints = frozenset(str(item).strip() for item in (decl.hints or []) if str(item).strip())
    visibility = str(decl.visibility or "visible").strip().lower() or "visible"
    if visibility not in {"visible", "deferred"}:
        visibility = "visible"
    return LlmToolSpec(
        name=decl.name,
        description=description,
        parameters=decl.parameters or {"type": "object", "properties": {}},
        domains=_command_tool_domains(plugin_name=plugin_name, decl=decl),
        handler=handler,
        source=LlmToolSource.PLUGIN_COMMAND,
        command_id=decl.command_id,
        plugin_name=plugin_name,
        capabilities=frozenset({
            ToolCapability.SIDE_EFFECTING.value,
            ToolCapability.REQUIRES_GROUP_CONTEXT.value,
        }),
        hints=hints,
        visibility=visibility,
    )


def _command_tool_domains(*, plugin_name: str, decl: LlmCommandToolDecl) -> frozenset[str]:
    """command + 插件名 + 口令/工具名前缀，便于 selective 命中 draw/sing 等短域名。"""
    domains = {"command", str(plugin_name or "").strip()}
    for raw in (decl.command_id, decl.name):
        prefix = str(raw or "").strip().split(".", 1)[0].strip().lower()
        if prefix:
            domains.add(prefix)
    return frozenset(d for d in domains if d)
