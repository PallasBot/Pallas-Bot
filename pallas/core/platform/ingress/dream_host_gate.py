"""做梦主持牛 ingress：做梦中仅主持牛接收群消息。"""

from __future__ import annotations

DREAM_HOST_GATE_PLUGIN = "dream"


async def dream_session_ingress_passes(bot_id: int, group_id: int) -> bool:
    from pallas.core.platform.multi_bot.dedup import is_group_owned_gate_holder, needs_group_host_bot_gate

    if not needs_group_host_bot_gate():
        return True
    return await is_group_owned_gate_holder(DREAM_HOST_GATE_PLUGIN, int(group_id), int(bot_id))
