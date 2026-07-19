"""从 @对话 话术中解析「记住」类教导。"""

from __future__ import annotations

import re

from .policy import classify_memory_candidate, normalize_episode_note

_TEACH_PREFIXES = (
    "记住：",
    "记住:",
    "请你记住",
    "要记住",
    "帮我记住",
)

_CQ_CODE_RE = re.compile(r"\[CQ:[^\]]+\]", re.IGNORECASE)


def strip_cq_codes(text: str) -> str:
    return _CQ_CODE_RE.sub("", text or "").strip()


def parse_memory_teach(user_text: str) -> str | None:
    plain = strip_cq_codes(user_text)
    if not plain:
        return None
    for prefix in _TEACH_PREFIXES:
        if plain.startswith(prefix):
            body = plain[len(prefix) :].strip()
            if body and classify_memory_candidate(plain) == "episode_note":
                return normalize_episode_note(body, max_len=500)
    return None
