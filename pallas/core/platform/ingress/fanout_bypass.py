"""入站门控：跳过跨 Bot / unified once-claim 的明文判定。"""

from __future__ import annotations

from pallas.core.platform.ingress.config import get_ingress_fanout_config
from pallas.core.platform.ingress.policy_registry import fanout_policy_bypasses_claim
from pallas.core.platform.shard import context as shard_ctx

_GREETING_ONLY = frozenset({"牛牛", "帕拉斯"})


def is_ingress_fanout_plaintext(plain: str) -> bool:
    return (plain or "").strip() in get_ingress_fanout_config().fanout_set


def is_greeting_fanout_plaintext(plain: str) -> bool:
    text = (plain or "").strip()
    return text in _GREETING_ONLY and text in get_ingress_fanout_config().fanout_set


def ingress_fanout_bypasses_claim(plain: str) -> bool:
    text = (plain or "").strip()
    sharding_active = shard_ctx.sharding_active()

    if is_ingress_fanout_plaintext(text):
        return True

    if fanout_policy_bypasses_claim(text, sharding_active=sharding_active):
        return True

    return False
