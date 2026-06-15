"""分片模式下的牛牛报数协调。"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from nonebot import logger

from src.platform.shard import context as shard_ctx
from src.platform.shard.coord.bot_count import (
    STAGGER_SEC,
    run_shard_coordinated_bot_count,
    update_shard_bot_count_registration,
)
from src.plugins.duel.duel_bots import list_local_fleet_bots_in_group

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent


async def handle_shard_bot_count(
    bot: Bot,
    event: GroupMessageEvent,
    *,
    finish: Callable[[str], Awaitable[None]],
) -> None:
    self_id = int(bot.self_id)
    plain = (event.get_plaintext() or "").strip()
    local_ids = [self_id]
    if shard_ctx.is_local_representative(self_id):
        probed = await list_local_fleet_bots_in_group(event.group_id)
        local_ids = sorted({self_id, *probed})

    coord_task = asyncio.create_task(
        run_shard_coordinated_bot_count(
            group_id=event.group_id,
            user_id=int(event.user_id),
            plaintext=plain,
            message_time=event.time,
            self_bot_id=self_id,
            local_bot_ids=local_ids,
        )
    )
    try:
        if shard_ctx.is_local_representative(self_id) and local_ids:
            await update_shard_bot_count_registration(
                group_id=event.group_id,
                user_id=int(event.user_id),
                plaintext=plain,
                message_time=event.time,
                bot_ids=local_ids,
            )
        coord = await coord_task
    except asyncio.CancelledError:
        raise
    finally:
        if not coord_task.done():
            coord_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await coord_task
    if coord is None:
        return
    index, total = coord
    await asyncio.sleep((index - 1) * STAGGER_SEC)
    try:
        await bot.send_group_msg(group_id=event.group_id, message=f"牛牛{index}号报到！")
    except Exception as e:
        logger.warning(f"bot [{self_id}] shard bot_count send failed in group [{event.group_id}]: {e}")
        return
    if index == total:
        await asyncio.sleep(0.3)
        await finish("牛牛们报数完毕！")
