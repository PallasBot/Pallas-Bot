"""做梦与醒梦入口明文常量。"""

from __future__ import annotations

_DREAM_FANOUT_TEXTS = frozenset({
    "牛牛做梦",
    "牛牛醒梦",
    "牛牛别做梦",
})


def is_dream_plaintext(text: str) -> bool:
    """做梦与醒梦口令：分片下恒 fanout，各牛独立做梦态。"""
    return (text or "").strip() in _DREAM_FANOUT_TEXTS
