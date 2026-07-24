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


def _is_short_echo_of_prior(normalized_text: str, normalized_prior: str) -> bool:
    """短回复复读上一句全文，或只吐出上一句尾部残片（串台）。"""
    if not normalized_text or not normalized_prior:
        return False
    if normalized_text == normalized_prior:
        return True
    # 新回复是上一句的短后缀/子串：如「都在玩呢」←「原神挺受欢迎的，很多人都在玩呢」
    if len(normalized_text) <= 24 and len(normalized_text) >= 4 and normalized_text in normalized_prior:
        return True
    return False


def _is_parasitic_prefix_extension(text: str, normalized_text: str, normalized_last: str) -> bool:
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


def should_suppress_llm_duplicate_reply(task: dict, reply_text: str) -> bool:
    if task.get("task_type") not in LEGACY_LLM_CHAT_TASK_TYPES:
        return False
    text = str(reply_text or "").strip()
    if not text:
        return False
    normalized_text = _normalize_duplicate_compare_text(text)
    if not normalized_text:
        return False

    last = str(task.get("last_reply_text") or "").strip()
    priors: list[str] = []
    if last:
        priors.append(last)
    recent = task.get("recent_reply_texts")
    if isinstance(recent, list):
        for item in recent:
            sample = str(item or "").strip()
            if sample and sample not in priors:
                priors.append(sample)

    for prior in priors:
        normalized_prior = _normalize_duplicate_compare_text(prior)
        if not normalized_prior:
            continue
        if _is_short_echo_of_prior(normalized_text, normalized_prior):
            return True
    if last:
        normalized_last = _normalize_duplicate_compare_text(last)
        if normalized_last and _is_parasitic_prefix_extension(text, normalized_text, normalized_last):
            return True
    return False


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
