"""LLM @对话冷却期消息队列：合并为一次 completion。"""

from __future__ import annotations

from dataclasses import dataclass

from pallas.product.llm.config import LlmConfig, get_llm_config

_QUEUE: dict[str, str] = {}


@dataclass(frozen=True)
class ChatQueueMergeResult:
    text: str
    merged: bool


def chat_queue_key(bot_id: int, group_id: int | None, user_id: int) -> str:
    gid = int(group_id) if group_id is not None else 0
    return f"{int(bot_id)}:{gid}:{int(user_id)}"


def stash_chat_during_cooldown(
    bot_id: int,
    group_id: int | None,
    user_id: int,
    text: str,
    *,
    cfg: LlmConfig | None = None,
) -> None:
    c = cfg or get_llm_config()
    if not c.llm_chat_queue_merge:
        return
    key = chat_queue_key(bot_id, group_id, user_id)
    _QUEUE[key] = (text or "").strip()


def merge_queued_chat(
    bot_id: int,
    group_id: int | None,
    user_id: int,
    current_text: str,
    *,
    cfg: LlmConfig | None = None,
) -> ChatQueueMergeResult:
    c = cfg or get_llm_config()
    current = (current_text or "").strip()
    if not c.llm_chat_queue_merge:
        return ChatQueueMergeResult(text=current, merged=False)
    key = chat_queue_key(bot_id, group_id, user_id)
    queued = _QUEUE.pop(key, "").strip()
    if not queued:
        return ChatQueueMergeResult(text=current, merged=False)
    if queued == current:
        return ChatQueueMergeResult(text=current, merged=True)
    return ChatQueueMergeResult(text=f"{queued}\n{current}", merged=True)


def clear_chat_queue_for_tests() -> None:
    _QUEUE.clear()


def queue_size_for_tests() -> int:
    return len(_QUEUE)
