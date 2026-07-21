"""闭嘴/别回 指令关键词（reply_gate / behavior / situational_rules 共用）。"""

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

_SHUT_UP_RE = re.compile("|".join(re.escape(item) for item in SHUT_UP_KEYWORDS))


def is_shut_up_text(text: str) -> bool:
    plain = str(text or "").strip()
    return bool(plain and _SHUT_UP_RE.search(plain))
