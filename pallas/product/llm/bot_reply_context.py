from __future__ import annotations

import time
from collections import OrderedDict

_TTL_SEC = 600.0
_MAX_ENTRIES = 512
_reply_contexts: OrderedDict[tuple[int, int, int], tuple[float, str]] = OrderedDict()
# 群内最近成功发言的本地 Bot：供昵称定向协议判定「最近 3 分钟最后说话者」。
_RECENT_SPEAKER_TTL_SEC = 180.0
_recent_speakers: dict[int, tuple[float, int]] = {}


def record_bot_reply_context(*, group_id: int, bot_id: int, message_id: int | None, text: str) -> None:
    content = str(text or "").strip()
    if int(group_id) <= 0 or int(bot_id) <= 0 or not message_id or not content:
        return
    key = (int(group_id), int(bot_id), int(message_id))
    _reply_contexts[key] = (time.monotonic() + _TTL_SEC, content[:500])
    _reply_contexts.move_to_end(key)
    while len(_reply_contexts) > _MAX_ENTRIES:
        _reply_contexts.popitem(last=False)
    _recent_speakers[int(group_id)] = (time.monotonic() + _RECENT_SPEAKER_TTL_SEC, int(bot_id))


def recent_group_bot_speaker(*, group_id: int) -> int | None:
    """最近 3 分钟内该群最后成功发言的本地 Bot；无记录或已过期返回 None。"""
    gid = int(group_id)
    if gid <= 0:
        return None
    record = _recent_speakers.get(gid)
    if record is None:
        return None
    expires_at, bot_id = record
    if expires_at <= time.monotonic():
        _recent_speakers.pop(gid, None)
        return None
    return bot_id


def lookup_bot_reply_context(*, group_id: int, bot_id: int, message_id: int | None) -> str | None:
    if int(group_id) <= 0 or int(bot_id) <= 0 or not message_id:
        return None
    key = (int(group_id), int(bot_id), int(message_id))
    record = _reply_contexts.get(key)
    if record is None:
        return None
    expires_at, content = record
    if expires_at <= time.monotonic():
        _reply_contexts.pop(key, None)
        return None
    _reply_contexts.move_to_end(key)
    return content


def clear_bot_reply_context_for_tests() -> None:
    _reply_contexts.clear()
    _recent_speakers.clear()
