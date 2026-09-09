"""LLM @对话会话状态：冷却/后台期消息合并 + 同会话单 worker 门闩。"""

from __future__ import annotations

import time
from dataclasses import dataclass

from pallas.product.llm.config import LlmConfig, get_llm_config

# 单会话积压上限与条目 TTL：防止长时间无人取走导致内存与合并文本无界增长
_MAX_PENDING_PER_KEY = 8
_PENDING_TTL_SEC = 600.0

_QUEUE: dict[str, list[PendingChat]] = {}
_IN_FLIGHT: set[str] = set()


@dataclass(frozen=True)
class ChatQueueMergeResult:
    text: str
    merged: bool


@dataclass(frozen=True)
class PendingChat:
    text: str
    message_id: int
    created_at: float
    is_to_me: bool = False
    speak_trigger: str = ""

    def __iter__(self):
        yield self.text
        yield self.message_id
        yield self.created_at


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


def should_merge_chat(text: str, *, is_to_me: bool, speak_trigger: str) -> bool:
    if is_to_me or str(speak_trigger or "").strip() in {"alias", "mention", "followup"}:
        return False
    from pallas.product.llm.reply_necessity import has_reply_obligation
    from pallas.product.llm.tools.select import infer_tool_domains

    return not (has_reply_obligation(text) or infer_tool_domains(text))


def _fresh_entries(key: str) -> list[PendingChat]:
    now = time.monotonic()
    entries: list[PendingChat] = []
    for raw_entry in _QUEUE.get(key, []):
        entry = raw_entry if isinstance(raw_entry, PendingChat) else PendingChat(*raw_entry)
        if now - entry.created_at <= _PENDING_TTL_SEC:
            entries.append(entry)
    if entries:
        _QUEUE[key] = entries
    else:
        _QUEUE.pop(key, None)
    return entries


def stash_pending_chat(
    bot_id: int,
    group_id: int | None,
    user_id: int,
    text: str,
    *,
    message_id: int = 0,
    is_to_me: bool = False,
    speak_trigger: str = "",
) -> None:
    value = str(text or "").strip()
    if not value:
        return
    entries = _QUEUE.setdefault(chat_queue_key(bot_id, group_id, user_id), [])
    entries.append(
        PendingChat(
            text=value,
            message_id=int(message_id or 0),
            created_at=time.monotonic(),
            is_to_me=bool(is_to_me),
            speak_trigger=str(speak_trigger or "").strip(),
        )
    )
    if len(entries) > _MAX_PENDING_PER_KEY:
        del entries[: len(entries) - _MAX_PENDING_PER_KEY]


def take_pending_chat(bot_id: int, group_id: int | None, user_id: int) -> str:
    entries = _fresh_entries(chat_queue_key(bot_id, group_id, user_id))
    _QUEUE.pop(chat_queue_key(bot_id, group_id, user_id), None)
    return "\n".join(entry.text for entry in entries)


def take_pending_chat_one(bot_id: int, group_id: int | None, user_id: int) -> tuple[str, int]:
    entry = take_pending_chat_one_entry(bot_id, group_id, user_id)
    return (entry.text, entry.message_id) if entry is not None else ("", 0)


def take_pending_chat_one_entry(bot_id: int, group_id: int | None, user_id: int) -> PendingChat | None:
    entries = _fresh_entries(chat_queue_key(bot_id, group_id, user_id))
    if not entries:
        return None
    entry = entries.pop(0)
    if entries:
        _QUEUE[chat_queue_key(bot_id, group_id, user_id)] = entries
    else:
        _QUEUE.pop(chat_queue_key(bot_id, group_id, user_id), None)
    return entry


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
