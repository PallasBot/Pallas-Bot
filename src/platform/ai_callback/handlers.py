"""按 task_type 解析回调失败文案与会话写入策略。"""

from __future__ import annotations

from src.platform.ai_callback.task_types import (
    DEFAULT_FAIL_REPLY,
    LEGACY_LLM_CHAT_TASK_TYPES,
    LLM_SESSION_TASK_TYPES,
    REPEATER_FALLBACK_TASK_TYPE,
    REPEATER_POLISH_TASK_TYPE,
)


def failure_reply_for_task(task: dict) -> str | None:
    """失败时发往群的消息；None 表示静默失败。"""
    task_type = task.get("task_type")
    if task_type == REPEATER_FALLBACK_TASK_TYPE:
        return None
    if task_type in LEGACY_LLM_CHAT_TASK_TYPES:
        from src.plugins.llm_chat.replies import LLM_CHAT_FAILED_REPLY

        return LLM_CHAT_FAILED_REPLY
    if task_type == REPEATER_POLISH_TASK_TYPE:
        fallback = str(task.get("fallback_text") or "").strip()
        return fallback or DEFAULT_FAIL_REPLY
    return DEFAULT_FAIL_REPLY


def should_append_llm_session(task: dict) -> bool:
    return task.get("task_type") in LLM_SESSION_TASK_TYPES
