"""闭嘴/别回/复话 关键词（reply_gate、behavior 与静默门控共用）。"""

from __future__ import annotations

import re

SHUT_UP_KEYWORDS: tuple[str, ...] = (
    "闭嘴",
    "别说话",
    "不要说话",
    "别回我",
    "别回了",
    "别回复",
    "少说话",
    "别出声",
)

# 说话/复话 关键词：仅当该关键词「不含闭嘴义」时才视为解除
SPEAK_KEYWORDS: tuple[str, ...] = (
    "说话",
    "回话",
    "别沉默",
)

_SHUT_UP_RE = re.compile("|".join(re.escape(item) for item in SHUT_UP_KEYWORDS))
_SPEAK_RE = re.compile("|".join(re.escape(item) for item in SPEAK_KEYWORDS))


def is_shut_up_text(text: str) -> bool:
    plain = str(text or "").strip()
    return bool(plain and _SHUT_UP_RE.search(plain))


def is_speak_request_text(text: str) -> bool:
    """含说话/回话等解除信号，且不能带「别/不」等否定。"""
    plain = str(text or "").strip()
    if not plain:
        return False
    if is_shut_up_text(plain):
        return False
    return bool(_SPEAK_RE.search(plain))
