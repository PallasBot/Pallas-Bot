from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from types import SimpleNamespace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import GroupMessageEvent

from pallas.core.platform.federate.ingress import (
    claim_federate_group_message_ingress,
    federate_ingress_cached_win,
)
from pallas.core.platform.ingress.fanout_bypass import ingress_fanout_bypasses_claim
from pallas.core.platform.ingress.plugin_command_plaintext import is_plugin_command_plaintext
from pallas.core.platform.ingress.unified_pass import unified_ingress_once_won
from pallas.core.platform.multi_bot.dedup import (
    normalize_group_raw_message,
    should_skip_duplicate_group_event,
    try_claim_cross_bot_message,
    try_claim_group_message_once,
)
from pallas.core.platform.shard import context as shard_ctx
from pallas.core.platform.shard.repeater_ingress_metrics import (
    record_repeater_ingress_claim,
    record_repeater_ingress_early_discard,
    record_repeater_ingress_event,
)

from .fanout_reply import repeater_fanout_enabled
from .shard_opt import repeater_worker_handles_message

message_id_lock = asyncio.Lock()
message_id_dict = defaultdict(lambda: deque(maxlen=100))


async def remember_group_message_id(group_id: int, message_id: int) -> bool:
    """同群同 message_id 在本进程内只放行一次。"""
    async with message_id_lock:
        bucket = message_id_dict[group_id]
        if message_id in bucket:
            return False
        bucket.append(message_id)
        return True


async def build_repeater_event_context(bot_id: int, event: GroupMessageEvent):
    record_repeater_ingress_event()
    if int(event.user_id) == int(bot_id):
        record_repeater_ingress_early_discard("self_sent")
        return None
    if not repeater_worker_handles_message(bot_id):
        record_repeater_ingress_early_discard("worker_gate")
        return None

    try:
        from packages.help.plugin_manager import is_plugin_disabled

        if await is_plugin_disabled("repeater", int(event.group_id), int(bot_id)):
            record_repeater_ingress_early_discard("plugin_disabled")
            return None
    except Exception:
        pass

    plain_body = event.get_plaintext()
    if plain_body and is_plugin_command_plaintext(plain_body):
        record_repeater_ingress_early_discard("plugin_command")
        return None
    if ingress_fanout_bypasses_claim(plain_body):
        record_repeater_ingress_early_discard("fanout_bypass")
        return None

    from pallas.product.message_scrub import is_message_scrub_blocked_sync

    if is_message_scrub_blocked_sync(plain_text=plain_body or "", raw_message=event.raw_message):
        record_repeater_ingress_early_discard("message_scrub")
        return None

    if not await remember_group_message_id(event.group_id, event.message_id):
        record_repeater_ingress_early_discard("message_id_dup")
        return None

    norm_raw = normalize_group_raw_message(event.raw_message)
    if await should_skip_duplicate_group_event(
        event.group_id,
        event.user_id,
        norm_raw,
        event.time,
    ):
        record_repeater_ingress_early_discard("group_event_dup")
        return None

    body = plain_body or event.raw_message
    ingress_once_won = not shard_ctx.sharding_active() and unified_ingress_once_won(
        event,
        plain=plain_body,
        body=body,
    )
    if not ingress_once_won:
        if not federate_ingress_cached_win(event, include_message_time=True, plain=plain_body, body=body):
            won = await claim_federate_group_message_ingress(
                event,
                include_message_time=True,
                plain=plain_body,
                body=body,
            )
            record_repeater_ingress_claim(won=won)
            if not won:
                record_repeater_ingress_early_discard("federate_claim")
                return None

    sharding_active = shard_ctx.sharding_active()
    if ingress_once_won:
        pass
    elif not sharding_active:
        won = await try_claim_group_message_once(
            "repeater_ingress",
            event.group_id,
            event.user_id,
            plain_body,
            event.time,
        )
        record_repeater_ingress_claim(won=won)
        if not won:
            record_repeater_ingress_early_discard("local_claim")
            return None
    elif not repeater_fanout_enabled():
        won = await try_claim_cross_bot_message(
            "repeater_reply",
            event.group_id,
            event.user_id,
            plain_body,
            event.time,
            bot_id,
            use_plaintext=True,
        )
        record_repeater_ingress_claim(won=won)
        if not won:
            record_repeater_ingress_early_discard("cross_bot_claim")
            return None

    return SimpleNamespace(
        plain_body=plain_body,
        norm_raw=norm_raw,
        sharding_active=sharding_active,
    )
