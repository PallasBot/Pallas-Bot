"""llm_chat 空回复兜底：硬触发后模型空输出时仍回一句，避免已读不回。"""

from __future__ import annotations

from pallas.core.platform.ai_callback.task_types import LLM_CHAT_TASK_TYPE
from pallas.product.persona.soft_agree_fillers import LLM_CHAT_EMPTY_FALLBACK_TEXT

# 硬触发：用户明确点名/续聊；ambient 空输出可静默
HARD_SPEAK_TRIGGERS = frozenset({"to_me", "mention", "followup"})
# 须避开 FILLER_ONLY_REPLIES（如「嗯？」），否则过滤清空后又被填回同一垫词
LLM_CHAT_EMPTY_FALLBACK = LLM_CHAT_EMPTY_FALLBACK_TEXT


def resolve_llm_chat_empty_fallback(
    task: dict,
    reply_text: str,
    *,
    suppress_empty_fallback: bool = False,
) -> str:
    """有正文则原样返回；硬触发且为空时用 fallback / 短兜底。

    本轮已成功走过工具调用时允许静默，避免动作完成后硬塞垫词。
    """
    text = str(reply_text or "").strip()
    if text:
        return text
    if suppress_empty_fallback:
        return ""
    if str(task.get("task_type") or "").strip() != LLM_CHAT_TASK_TYPE:
        return ""
    trace = task.get("agent_trace")
    if isinstance(trace, dict) and int(trace.get("tool_call_count") or 0) > 0:
        return ""
    trigger = str(task.get("speak_trigger") or "to_me").strip() or "to_me"
    if trigger not in HARD_SPEAK_TRIGGERS:
        return ""
    fallback = str(task.get("fallback_text") or "").strip()
    if fallback:
        from pallas.product.llm.corpus_contamination import FILLER_ONLY_REPLIES

        compact = fallback.rstrip("。.!！?？~～…")
        if fallback in FILLER_ONLY_REPLIES or compact in FILLER_ONLY_REPLIES:
            return LLM_CHAT_EMPTY_FALLBACK
        return fallback
    return LLM_CHAT_EMPTY_FALLBACK
