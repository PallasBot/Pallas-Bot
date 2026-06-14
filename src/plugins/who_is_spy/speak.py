from __future__ import annotations

import re
from typing import Protocol

_WS_RE = re.compile(r"\s+")
_AT_CQ_RE = re.compile(r"\[(?:CQ:)?at[^\]]*\]", re.IGNORECASE)


class SpeechMessageEvent(Protocol):
    message: object


def extract_at_speech_text(event: SpeechMessageEvent) -> str:
    """去掉 @ 段后取文本段拼接（述词正文）。"""
    parts: list[str] = []
    for seg in event.message:
        if seg.type != "text":
            continue
        parts.append(str(seg.data.get("text") or ""))
    text = _WS_RE.sub(" ", "".join(parts)).strip()
    if text:
        return text
    getter = getattr(event, "get_plaintext", None)
    if callable(getter):
        plain = _WS_RE.sub(" ", str(getter() or "")).strip()
        plain = re.sub(r"^@\S+\s*", "", plain).strip()
        if plain:
            return plain
    raw = getattr(event, "raw_message", None) or ""
    text = _AT_CQ_RE.sub("", raw)
    return _WS_RE.sub(" ", text).strip()
