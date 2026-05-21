"""多牛牛号群消息入站分片、全员同响豁免、决斗主持牛对齐。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.common.ingress.config import get_ingress_config
from src.common.ingress.duel_elect import ingress_duel_elected_bot_id, ingress_message_uses_duel_claim
from src.common.multi_bot import claim_group_message_event, try_claim_cross_bot_message_memory

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import GroupMessageEvent

_INGRESS_PLUGIN = "ingress"
_DUEL_PLUGIN = "duel"


def ingress_group_message_fanout_all_bots(event: GroupMessageEvent) -> bool:
    """是否应对所有在线牛牛连接各处理一次（仅 greeting：牛牛/帕拉斯，豁免 ingress 抢占）。"""
    cfg = get_ingress_config()
    plain = event.get_plaintext().strip()
    if plain in cfg.greeting_fanout_set:
        return True
    raw = (getattr(event, "raw_message", None) or "").strip()
    return raw in cfg.greeting_fanout_set


def ingress_multi_bot_shard_enabled() -> bool:
    return get_ingress_config().ingress_multi_bot_shard_enabled


async def should_this_bot_handle_group_message(
    self_id: int,
    event: GroupMessageEvent,
    *,
    memory_only: bool = False,
) -> bool:
    if not ingress_multi_bot_shard_enabled():
        return True
    if ingress_group_message_fanout_all_bots(event):
        return True

    elected = await ingress_duel_elected_bot_id(event)
    if elected is not None:
        return int(self_id) == int(elected)

    plugin = _DUEL_PLUGIN if ingress_message_uses_duel_claim(event) else _INGRESS_PLUGIN
    if memory_only:
        return await try_claim_cross_bot_message_memory(
            plugin,
            event.group_id,
            event.user_id,
            event.get_plaintext(),
            event.time,
            self_id,
        )
    return await claim_group_message_event(plugin, event, self_id)


async def should_skip_ingress_dispatch_for_bot(self_id: int, event: GroupMessageEvent) -> bool:
    """dispatch 入口丢弃非赢家 bot，避免 N 牛同群重复跑整条 handle_event。"""
    if not ingress_multi_bot_shard_enabled():
        return False
    if int(self_id) == int(getattr(event, "user_id", 0) or 0):
        return False
    if ingress_group_message_fanout_all_bots(event):
        return False
    return not await should_this_bot_handle_group_message(self_id, event, memory_only=True)
