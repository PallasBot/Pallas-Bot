"""闲聊身份问句识别：避免「你是谁」误触干员查询工具。"""

from __future__ import annotations

import re

_CQ_CODE_RE = re.compile(r"\[CQ:[^\]]+\]", re.IGNORECASE)
_MENTION_RE = re.compile(r"@\S+")

_SELF_IDENTITY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^你是?谁[吗嘛呀呐]?$"),
    re.compile(r"^我(?:又)?是谁[吗嘛呀呐]?$"),
    re.compile(r"^你知道你是?谁[吗嘛呀呐]?$"),
    re.compile(r"^你知道我(?:又)?是谁[吗嘛呀呐]?$"),
)


def normalize_identity_user_text(user_text: str) -> str:
    text = _CQ_CODE_RE.sub("", user_text or "")
    text = _MENTION_RE.sub("", text)
    return re.sub(r"\s+", "", text).strip("，,。！？!? ")


def is_self_identity_question(user_text: str) -> bool:
    text = normalize_identity_user_text(user_text)
    if not text:
        return False
    return any(pattern.fullmatch(text) for pattern in _SELF_IDENTITY_PATTERNS)
