"""分片模式下的八角笼配对与主持牛门控。"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from src.platform.shard import context as shard_ctx
from src.platform.shard.coord.cage_duel import (
    run_shard_cage_duel_coord,
    update_shard_cage_duel_registration,
)
from src.plugins.duel.duel_bots import (
    fleet_bot_confirmed_in_group,
    list_local_fleet_bots_in_group,
    pick_cage_duel_bot_pair,
)

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent


async def resolve_cage_duel_pair(
    bot: Bot,
    event: GroupMessageEvent,
    *,
    plain: str,
) -> tuple[int, int] | None:
    """分片走 coord 登记；单进程走本地配对。返回 (a, b) 或 None。"""
    if not shard_ctx.sharding_active():
        pair = await pick_cage_duel_bot_pair(
            event.group_id,
            int(event.user_id),
            int(event.time),
            plaintext=plain,
        )
        if not pair:
            return None
        return int(pair[0]), int(pair[1])

    self_id = int(bot.self_id)
    if not await fleet_bot_confirmed_in_group(bot, event.group_id):
        return None

    coord_task = asyncio.create_task(
        run_shard_cage_duel_coord(
            group_id=event.group_id,
            user_id=int(event.user_id),
            message_time=int(event.time),
            plaintext=plain,
            self_bot_id=self_id,
        )
    )
    try:
        if shard_ctx.is_local_representative(self_id):
            probed = await list_local_fleet_bots_in_group(event.group_id)
            await update_shard_cage_duel_registration(
                group_id=event.group_id,
                user_id=int(event.user_id),
                message_time=int(event.time),
                plaintext=plain,
                bot_ids=sorted({self_id, *probed}),
            )
        pair = await coord_task
    except asyncio.CancelledError:
        raise
    finally:
        if not coord_task.done():
            coord_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await coord_task
    if not pair:
        return None
    return int(pair[0]), int(pair[1])


def cage_narrator_offline_for_reply(narrator: int) -> bool:
    """分片下主持牛未在本 worker 连线且集群无在线记录时，应向用户提示离线。"""
    if not shard_ctx.sharding_active():
        return False
    from src.platform.shard.presence import bot_has_local_connection, get_cluster_online_bot_ids

    if bot_has_local_connection(narrator):
        return False
    return narrator not in get_cluster_online_bot_ids()
