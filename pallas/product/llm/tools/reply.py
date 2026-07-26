"""可见对白通道：动作工具成功后可选调用，避免自由文本「已派发」套话。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pallas.product.llm.tools.registry import LlmToolSource, LlmToolSpec, register_tool

if TYPE_CHECKING:
    from pallas.product.llm.tools.context import ToolInvokeContext

CHAT_REPLY_NAME = "chat.reply"


def register_reply_tools() -> None:
    register_tool(
        LlmToolSpec(
            name=CHAT_REPLY_NAME,
            description=(
                "向群友发送一条可见口语对白。动作类工具已执行后若需要开口确认才调用；"
                "也可不调用以保持沉默。禁止写「已派发/帮你找找/正在生成」等系统腔。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "极短自然口语，直接可念给群友听",
                    },
                },
                "required": ["text"],
            },
            domains=frozenset({"chat", "meta"}),
            handler=handle_chat_reply,
            source=LlmToolSource.BUILTIN,
            capabilities=frozenset(),
            hints=frozenset(),
        )
    )


async def handle_chat_reply(arguments: dict[str, Any], context: ToolInvokeContext | None = None) -> dict[str, Any]:
    del context
    text = str((arguments or {}).get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "text_required"}
    if text.upper() in {"PASS", "SILENCE", "<SILENCE>", "[SILENCE]"}:
        return {"ok": True, "result": {"text": "", "visible_reply": False, "silent": True}}
    return {"ok": True, "result": {"text": text, "visible_reply": True}}


def extract_chat_reply_text(result: dict[str, Any]) -> str | None:
    """从 chat.reply 工具结果取出可见对白；静默时返回空串；无效返回 None。"""
    if not isinstance(result, dict) or not bool(result.get("ok", True)):
        return None
    payload = result.get("result") if isinstance(result.get("result"), dict) else result
    if not isinstance(payload, dict):
        return None
    if payload.get("silent") or payload.get("visible_reply") is False:
        return ""
    text = str(payload.get("text") or "").strip()
    return text
