"""llm_chat 查询结果为空时的可见提示。"""

from __future__ import annotations

from pallas.core.platform.ai_callback.task_types import LLM_CHAT_TASK_TYPE

# 硬触发：用户明确点名/续聊；ambient 空输出可静默
HARD_SPEAK_TRIGGERS = frozenset({"to_me", "mention", "followup"})
QUERY_EMPTY_FALLBACK = "资料查到了，但这次回答没整理出来，再问我一次吧。"
QUERY_NO_RESULT_FALLBACK = "现有资料里没找到可靠答案。"
QUERY_FAILED_FALLBACK = "资料查询失败了，稍后再试。"


def query_fallback_for_task(task: dict) -> str:
    trace = task.get("agent_trace")
    if not isinstance(trace, dict):
        return ""
    if int(trace.get("successful_query_call_count") or 0) <= 0 and int(trace.get("query_tool_failed_count") or 0) <= 0:
        return ""
    trigger = str(task.get("speak_trigger") or "to_me").strip() or "to_me"
    if trigger not in HARD_SPEAK_TRIGGERS:
        return ""
    if int(trace.get("query_tool_hit_count") or 0) <= 0:
        if int(trace.get("query_tool_failed_count") or 0) > 0:
            return QUERY_FAILED_FALLBACK
        if int(trace.get("query_tool_empty_count") or 0) > 0:
            return QUERY_NO_RESULT_FALLBACK
    return QUERY_EMPTY_FALLBACK


def resolve_llm_chat_empty_fallback(
    task: dict,
    reply_text: str,
    *,
    suppress_empty_fallback: bool = False,
) -> str:
    """有正文则原样返回；仅查询类空结果提供可见提示。"""
    text = str(reply_text or "").strip()
    if text:
        return text
    if str(task.get("task_type") or "").strip() != LLM_CHAT_TASK_TYPE:
        return ""
    query_fallback = query_fallback_for_task(task)
    if query_fallback:
        return query_fallback
    return ""
