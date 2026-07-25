"""llm_chat 空回复兜底：硬触发后模型空输出时仍回一句，避免已读不回。"""

from __future__ import annotations

from pallas.core.platform.ai_callback.task_types import LLM_CHAT_TASK_TYPE

# 硬触发：用户明确点名/续聊；ambient 空输出可静默
HARD_SPEAK_TRIGGERS = frozenset({"to_me", "mention", "followup"})
LLM_CHAT_EMPTY_FALLBACK = "嗯？"


def resolve_llm_chat_empty_fallback(task: dict, reply_text: str) -> str:
    """有正文则原样返回；硬触发且为空时用 fallback / 短兜底。"""
    text = str(reply_text or "").strip()
    if text:
        return text
    if str(task.get("task_type") or "").strip() != LLM_CHAT_TASK_TYPE:
        return ""
    trigger = str(task.get("speak_trigger") or "to_me").strip() or "to_me"
    if trigger not in HARD_SPEAK_TRIGGERS:
        return ""
    fallback = str(task.get("fallback_text") or "").strip()
    if fallback:
        return fallback
    return LLM_CHAT_EMPTY_FALLBACK
