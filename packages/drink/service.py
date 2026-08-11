from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from nonebot import get_bot, logger
from nonebot.exception import ActionFailed
from nonebot_plugin_apscheduler import scheduler

from pallas.api.limits import is_command_cooldown_ready, refresh_command_cooldown
from pallas.api.logging import format_plugin_event
from pallas.core.foundation.config import BotConfig
from pallas.core.plugin_coord import dream as dream_coord

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import GroupMessageEvent

type SendMessage = Callable[[str], Awaitable[object]]


def now() -> datetime:
    return datetime.now()


async def sober_up_later(bot_id: int, group_id: int) -> None:
    config = BotConfig(bot_id, group_id)
    if await config.sober_up() and not await config.is_sleep():
        logger.info(format_plugin_event("sober_up", f"Bot [{bot_id}] sobered up in group [{group_id}]"))
        await get_bot(str(bot_id)).call_api(
            "send_group_msg",
            message="呃......咳嗯，下次不能喝、喝这么多了......",
            group_id=group_id,
        )


async def drink(event: GroupMessageEvent, send: SendMessage) -> None:
    if not await is_command_cooldown_ready(event, "drink.drink"):
        return
    await refresh_command_cooldown(event, "drink.drink")
    config = BotConfig(event.self_id, event.group_id)

    drunk_duration = random.randint(60, 600)
    await config.drink()
    logger.info(
        format_plugin_event(
            "drink",
            f"Bot [{event.self_id}] started drinking in group [{event.group_id}]; sober up in [{drunk_duration}s]",
        )
    )
    drunkenness = await config.drunkenness()
    go_to_sleep = random.random() < (0.02 if drunkenness <= 50 else (drunkenness - 50 + 1) * 0.02)
    if go_to_sleep:
        sleep_duration = (min(drunkenness, 35) + random.random()) * 800
        logger.info(
            format_plugin_event(
                "sleep",
                f"Bot [{event.self_id}] fell asleep in group [{event.group_id}]; wake up in [{int(sleep_duration)}s]",
            )
        )
        await config.sleep(int(sleep_duration))

    try:
        if go_to_sleep:
            await send("呀，博士。你今天走起路来，怎么看着摇…摇……晃…………")
            await asyncio.sleep(1)
            await send("Zzz……")
        else:
            await send("呀，博士。你今天走起路来，怎么看着摇摇晃晃的？")
    except ActionFailed:
        pass

    scheduler.add_job(
        sober_up_later,
        trigger="date",
        run_date=now() + timedelta(seconds=drunk_duration),
        args=(event.self_id, event.group_id),
    )


async def sober_up(event: GroupMessageEvent, send: SendMessage) -> None:
    config = BotConfig(event.self_id, event.group_id)
    had_drunk = await config.drunkenness() > 0
    had_dream = await config.is_dreaming()
    if not had_drunk and not had_dream:
        return
    if had_drunk:
        await config.fully_sober_up_now()
        logger.info(format_plugin_event("sober_up", f"Bot [{event.self_id}] sobered up in group [{event.group_id}]"))
    if had_dream:
        await config.stop_dream()
        await dream_coord.stop_dream_worker(event.self_id, event.group_id)
    if had_drunk:
        try:
            await send("呃......咳嗯，下次不能喝、喝这么多了......")
        except ActionFailed:
            pass
    if had_dream:
        await dream_coord.send_dream_wake_text(event.self_id, event.group_id)
