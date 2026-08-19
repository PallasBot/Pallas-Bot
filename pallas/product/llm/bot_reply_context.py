from __future__ import annotations

import time
from collections import OrderedDict

_TTL_SEC = 600.0
_MAX_ENTRIES = 512
_reply_contexts: OrderedDict[tuple[int, int, int], tuple[float, str]] = OrderedDict()


def record_bot_reply_context(*, group_id: int, bot_id: int, message_id: int | None, text: str) -> None:
    content = str(text or "").strip()
    if int(group_id) <= 0 or int(bot_id) <= 0 or not message_id or not content:
        return
    key = (int(group_id), int(bot_id), int(message_id))
    _reply_contexts[key] = (time.monotonic() + _TTL_SEC, content[:500])
    _reply_contexts.move_to_end(key)
    while len(_reply_contexts) > _MAX_ENTRIES:
        _reply_contexts.popitem(last=False)


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
