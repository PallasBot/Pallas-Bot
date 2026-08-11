"""LLM @对话会话状态：冷却/后台期消息合并 + 同会话单 worker 门闩。"""

from __future__ import annotations

from dataclasses import dataclass

from pallas.product.llm.config import LlmConfig, get_llm_config

_QUEUE: dict[str, list[tuple[str, int]]] = {}
_IN_FLIGHT: set[str] = set()


@dataclass(frozen=True)
class ChatQueueMergeResult:
    text: str
    merged: bool


def chat_queue_key(bot_id: int, group_id: int | None, user_id: int) -> str:
    gid = int(group_id) if group_id is not None else 0
    return f"{int(bot_id)}:{gid}:{int(user_id)}"


def begin_chat_turn(bot_id: int, group_id: int | None, user_id: int) -> bool:
    key = chat_queue_key(bot_id, group_id, user_id)
    if key in _IN_FLIGHT:
        return False
    _IN_FLIGHT.add(key)
    return True


def finish_chat_turn(bot_id: int, group_id: int | None, user_id: int) -> None:
    _IN_FLIGHT.discard(chat_queue_key(bot_id, group_id, user_id))


def stash_pending_chat(
    bot_id: int,
    group_id: int | None,
    user_id: int,
    text: str,
    *,
    message_id: int = 0,
) -> None:
    value = str(text or "").strip()
    if value:
        _QUEUE.setdefault(chat_queue_key(bot_id, group_id, user_id), []).append((value, int(message_id or 0)))


def take_pending_chat(bot_id: int, group_id: int | None, user_id: int) -> str:
    return "\n".join(text for text, _message_id in _QUEUE.pop(chat_queue_key(bot_id, group_id, user_id), []))


def take_pending_chat_one(bot_id: int, group_id: int | None, user_id: int) -> tuple[str, int]:
    key = chat_queue_key(bot_id, group_id, user_id)
    entries = _QUEUE.get(key)
    if not entries:
        return "", 0
    text, message_id = entries.pop(0)
    if not entries:
        _QUEUE.pop(key, None)
    return text, message_id


def stash_chat_during_cooldown(
    bot_id: int,
    group_id: int | None,
    user_id: int,
    text: str,
    *,
    cfg: LlmConfig | None = None,
    message_id: int = 0,
) -> None:
    c = cfg or get_llm_config()
    if not c.llm_chat_queue_merge:
        return
    stash_pending_chat(bot_id, group_id, user_id, text, message_id=message_id)


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
    queued = take_pending_chat(bot_id, group_id, user_id)
    if not queued:
        return ChatQueueMergeResult(text=current, merged=False)
    if queued == current:
        return ChatQueueMergeResult(text=current, merged=True)
    return ChatQueueMergeResult(text=f"{queued}\n{current}", merged=True)


def clear_chat_queue_for_tests() -> None:
    _QUEUE.clear()
    _IN_FLIGHT.clear()


def queue_size_for_tests() -> int:
    return len(_QUEUE)
