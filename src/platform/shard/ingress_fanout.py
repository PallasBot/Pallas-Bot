"""入站门控：全员同响类明文。"""

from __future__ import annotations

_GREETING_ONLY = frozenset({"牛牛", "帕拉斯"})


def _fanout_set() -> frozenset[str]:
    from src.platform.ingress.config import get_ingress_fanout_config

    return get_ingress_fanout_config().fanout_set


def is_ingress_fanout_plaintext(plain: str) -> bool:
    return (plain or "").strip() in _fanout_set()


def is_greeting_fanout_plaintext(plain: str) -> bool:
    text = (plain or "").strip()
    return text in _GREETING_ONLY and text in _fanout_set()
