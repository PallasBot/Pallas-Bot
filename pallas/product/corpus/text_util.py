from __future__ import annotations

import re

_CQ_SEGMENT_RE = re.compile(r"\[CQ:[^\]]*]", re.IGNORECASE)


def plain_message_text(text: str) -> str:
    raw = (text or "").replace("\x00", "")
    if not raw:
        return ""
    cleaned = _CQ_SEGMENT_RE.sub("", raw)
    return " ".join(cleaned.split()).strip()
