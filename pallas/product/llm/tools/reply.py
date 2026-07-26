"""可见对白通道：动作工具成功后可选调用，避免自由文本「已派发」套话。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from pallas.product.llm.tools.registry import LlmToolSource, LlmToolSpec, register_tool

if TYPE_CHECKING:
    from pallas.product.llm.tools.context import ToolInvokeContext

CHAT_REPLY_NAME = "chat.reply"

# 动作已落地后的元叙述 / 假进度；命中则当作静默
_SIDE_EFFECT_META_REPLY_RE = re.compile(
    r"(已派发|派发指令|帮你找找|正在生成|已经安排|安排上了|等结果|"
    r"整了个|做好了|搜了一下|没有.{0,12}合适|大伙品品|找找.{0,8}模板|"
    r"放一首随机|听听看合不合)"
)


def is_side_effect_meta_reply(text: str) -> bool:
    plain = str(text or "").strip()
    if not plain:
        return False
    return _SIDE_EFFECT_META_REPLY_RE.search(plain) is not None


def register_reply_tools() -> None:
    register_tool(
        LlmToolSpec(
            name=CHAT_REPLY_NAME,
            description=(
                "向群友发送一条可见口语对白。动作类工具成功后默认不调用（沉默）；"
                "仅当必须补充工具未直接给出的信息（如口令、缺素材）才调用。"
                "禁止「整了个/搜了一下/已派发/帮你找找/大伙品品」等复述动作的废话。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "极短自然口语；不要复述工具已做完的事",
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
    if is_side_effect_meta_reply(text):
        return {"ok": True, "result": {"text": "", "visible_reply": False, "silent": True, "meta_suppressed": True}}
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
    if is_side_effect_meta_reply(text):
        return ""
    return text
