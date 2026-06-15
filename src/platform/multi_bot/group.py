"""多 Bot 同群：插件侧统一入口（见 group_message_dedup 实现）。

典型用法::

    from src.platform.multi_bot.group import claim_group_handler

    @matcher.handle()
    async def handler(bot: Bot, event: MessageEvent):
        if not await claim_group_handler("my_plugin", event, int(bot.self_id)):
            return
        ...

协议重复上报用 ``should_skip_duplicate_group_event``。
短时群级占位用 ``try_acquire_group_broadcast_slot`` / ``try_begin_group_owned_gate``。
同群长时独占用 ``begin_group_exclusive_activity``。
"""

from src.platform.multi_bot.dedup import (
    begin_group_exclusive_activity,
    bind_group_owned_gate,
    bind_group_owned_gate_sync,
    claim_group_handler,
    claim_group_message_event,
    cross_bot_group_message_key,
    cross_bot_message_signature,
    is_group_owned_gate_holder,
    needs_group_host_bot_gate,
    normalize_group_plaintext,
    normalize_group_raw_message,
    normalize_message_time,
    release_group_owned_gate,
    release_group_owned_gate_sync,
    should_skip_duplicate_group_event,
    try_acquire_group_broadcast_slot,
    try_begin_group_draw_cheer,
    try_begin_group_owned_gate,
    try_claim_cross_bot_message,
    try_claim_cross_bot_message_memory,
    try_claim_cross_shard_message,
    try_claim_cross_shard_message_memory,
    try_claim_group_message_once,
)

__all__ = [
    "claim_group_handler",
    "claim_group_message_event",
    "cross_bot_group_message_key",
    "cross_bot_message_signature",
    "normalize_group_plaintext",
    "normalize_group_raw_message",
    "normalize_message_time",
    "should_skip_duplicate_group_event",
    "try_acquire_group_broadcast_slot",
    "try_begin_group_draw_cheer",
    "try_begin_group_owned_gate",
    "begin_group_exclusive_activity",
    "bind_group_owned_gate",
    "bind_group_owned_gate_sync",
    "is_group_owned_gate_holder",
    "needs_group_host_bot_gate",
    "release_group_owned_gate",
    "release_group_owned_gate_sync",
    "try_claim_cross_bot_message",
    "try_claim_cross_bot_message_memory",
    "try_claim_group_message_once",
    "try_claim_cross_shard_message",
    "try_claim_cross_shard_message_memory",
]
