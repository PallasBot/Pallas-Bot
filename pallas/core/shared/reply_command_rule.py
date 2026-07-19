from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import GroupMessageEvent

_RAW_REPLY_RE = re.compile(r"\[reply:id=(\d+)\]|\[CQ:reply,id=(\d+)[^\]]*\]")


def extract_reply_id_from_raw_message(raw_message: str) -> int | None:
    match = _RAW_REPLY_RE.search(raw_message or "")
    if not match:
        return None
    reply_id = match.group(1) or match.group(2)
    if reply_id is None:
        return None
    try:
        return int(reply_id)
    except ValueError:
        return None


def raw_message_mentions_self(event: GroupMessageEvent) -> bool:
    self_id = str(event.self_id)
    raw_message = event.raw_message or ""
    return f"[at:qq={self_id}]" in raw_message or f"[CQ:at,qq={self_id}" in raw_message


def event_targets_self(event: GroupMessageEvent) -> bool:
    return event.is_tome() or raw_message_mentions_self(event)


def event_has_reply_target(event: GroupMessageEvent) -> bool:
    return bool(event.reply) or extract_reply_id_from_raw_message(event.raw_message) is not None
