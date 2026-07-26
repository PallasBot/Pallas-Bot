"""群聊历史工具。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pallas.product.llm.session_store import list_group_ambient_messages
from pallas.product.llm.tools.contracts import ToolCapability
from pallas.product.llm.tools.registry import LlmToolSpec, register_tool

if TYPE_CHECKING:
    from pallas.product.llm.tools.context import ToolInvokeContext


def register_history_tools() -> None:
    register_tool(
        LlmToolSpec(
            name="chat.history",
            description="读取当前群最近的环境消息。",
            parameters={"type": "object", "properties": {"limit": {"type": "integer"}}, "required": []},
            domains=frozenset({"chat", "history"}),
            handler=handle_chat_history,
            capabilities=frozenset({ToolCapability.READ_ONLY.value, ToolCapability.REQUIRES_GROUP_CONTEXT.value}),
        )
    )


async def handle_chat_history(arguments: dict[str, Any], context: ToolInvokeContext | None = None) -> dict[str, Any]:
    if context is None or context.group_id is None:
        return {"ok": False, "error": "group_context_required"}
    limit = max(1, min(int((arguments or {}).get("limit") or 20), 50))
    turns = await list_group_ambient_messages(context.bot_id, context.group_id, limit=limit)
    return {
        "ok": True,
        "messages": [turn.model_dump(mode="json") if hasattr(turn, "model_dump") else dict(turn) for turn in turns],
    }
