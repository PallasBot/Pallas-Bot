"""做梦/醒梦入口明文（供 ingress 门控与 dream 共用，勿依赖 plugins）。"""

from __future__ import annotations

_DREAM_START_TEXTS = frozenset({"牛牛做梦"})
_DREAM_WAKE_TEXTS = frozenset({"牛牛醒梦", "牛牛别做梦"})


def is_dream_start_plaintext(text: str) -> bool:
    return (text or "").strip() in _DREAM_START_TEXTS


def is_dream_wake_plaintext(text: str) -> bool:
    return (text or "").strip() in _DREAM_WAKE_TEXTS


def is_dream_plaintext(text: str) -> bool:
    plain = (text or "").strip()
    return plain in _DREAM_START_TEXTS or plain in _DREAM_WAKE_TEXTS
