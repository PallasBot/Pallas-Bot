"""按 task_type 解析回调失败文案与会话写入策略。"""

from __future__ import annotations

import re

from pallas.core.platform.ai_callback.task_types import (
    CHAT_DRUNK_TASK_TYPE,
    DEFAULT_FAIL_REPLY,
    DRAW_IMAGE_TASK_TYPE,
    LEGACY_LLM_CHAT_TASK_TYPES,
    LLM_SESSION_TASK_TYPES,
    REPEATER_LLM_TASK_TYPES,
)

_TAIL_FRAGMENT_SPLIT_RE = re.compile(r"[。！？!?~～\n\r]+")


def _normalize_duplicate_compare_text(text: str) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    normalized = re.sub(r"\[[^\[\]]{1,12}\]", "", normalized)
    normalized = re.sub(r"\s+", "", normalized)
    normalized = normalized.strip("。！？!?~～，,、；;：:…")
    return normalized


def _split_tail_fragments(text: str) -> list[str]:
    normalized = str(text or "").strip()
    if not normalized:
        return []
    parts = [part.strip("，,、；;：:… ") for part in _TAIL_FRAGMENT_SPLIT_RE.split(normalized) if part.strip()]
    return [part for part in parts if part]


def should_suppress_llm_duplicate_reply(task: dict, reply_text: str) -> bool:
    if task.get("task_type") not in LEGACY_LLM_CHAT_TASK_TYPES:
        return False
    text = str(reply_text or "").strip()
    if not text:
        return False
    last = str(task.get("last_reply_text") or "").strip()
    if not last:
        return False
    normalized_text = _normalize_duplicate_compare_text(text)
    normalized_last = _normalize_duplicate_compare_text(last)
    if not normalized_text or not normalized_last:
        return False
    if normalized_text == normalized_last:
        return True
    if not normalized_text.startswith(normalized_last):
        return False
    tail = normalized_text[len(normalized_last) :].strip()
    if not tail:
        return True
    tail_fragments = _split_tail_fragments(text)
    if not tail_fragments:
        return False
    if len(tail_fragments) == 1:
        return len(tail_fragments[0]) <= 5
    return all(len(fragment) <= 5 for fragment in tail_fragments[1:]) and len(tail_fragments[-1]) <= 5


def failure_reply_for_task(task: dict) -> str | None:
    """失败时发往群的消息；None 表示静默失败。"""
    task_type = task.get("task_type")
    if (
        task_type in REPEATER_LLM_TASK_TYPES
        or task_type in LEGACY_LLM_CHAT_TASK_TYPES
        or task_type == CHAT_DRUNK_TASK_TYPE
    ):
        return None
    if task_type == DRAW_IMAGE_TASK_TYPE:
        from pallas.core.platform.plugin_runtime.resolve import import_plugin_submodule

        draw_replies = import_plugin_submodule("draw", "replies")
        return draw_replies.DRAW_VAGUE_REPLY
    return DEFAULT_FAIL_REPLY


def should_append_llm_session(task: dict) -> bool:
    return task.get("task_type") in LLM_SESSION_TASK_TYPES
