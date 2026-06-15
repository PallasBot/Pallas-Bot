"""入站门控：跳过跨 Bot / unified once-claim 的明文判定。"""

from __future__ import annotations

from src.platform.ingress.plugin_command_plaintext import is_plugin_command_plaintext
from src.platform.ingress.policy_registry import fanout_policy_bypasses_claim
from src.platform.shard.ingress_fanout import is_ingress_fanout_plaintext
from src.platform.shard.registry.config import is_sharding_active


def ingress_fanout_bypasses_claim(plain: str) -> bool:
    text = (plain or "").strip()
    sharding_active = is_sharding_active()

    if is_ingress_fanout_plaintext(text):
        return True

    if fanout_policy_bypasses_claim(text, sharding_active=sharding_active):
        return True

    # unified：插件命令走 fanout，由 help / 各插件 run_preprocessor 内存抢占。
    if is_plugin_command_plaintext(text) and not sharding_active:
        return True

    return False
