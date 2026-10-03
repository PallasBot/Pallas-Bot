from __future__ import annotations

import re

from nonebot.adapters.onebot.v11 import Message


def parse_replayable_message(raw_message: str) -> Message | None:
    message = Message(raw_message)
    for segment in message:
        if segment.type == "markdown":
            content = segment.data.get("content")
            if content is None or not str(content).strip():
                return None
        if segment.type in {"mface", "image"}:
            raw_emoji_id = segment.data.get("emoji_id")
            emoji_id = "" if raw_emoji_id is None else str(raw_emoji_id).strip()
            if segment.type == "mface" or emoji_id:
                if not re.fullmatch(r"[0-9a-fA-F]{32}", emoji_id):
                    return None
    return message
