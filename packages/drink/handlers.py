import asyncio
import random
from datetime import datetime, timedelta

from nonebot import get_bot, logger, on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.exception import ActionFailed
from nonebot.rule import Rule
from nonebot_plugin_apscheduler import scheduler

from pallas.core.foundation.config import BotConfig
from pallas.core.limits import is_command_cooldown_ready, refresh_command_cooldown
from pallas.core.perm import group_message_permission_for_command
from pallas.core.plugin_coord import dream as dream_coord


async def is_drink_msg(event: GroupMessageEvent) -> bool:
    return event.get_plaintext().strip() in {"牛牛喝酒", "牛牛干杯", "牛牛继续喝"}


drink_msg = on_message(
    rule=Rule(is_drink_msg),
    priority=5,
    block=True,
    permission=group_message_permission_for_command("drink.drink"),
)


async def sober_up_later(bot_id: int, group_id: int):
    config = BotConfig(bot_id, group_id)
    if await config.sober_up() and not await config.is_sleep():
        logger.info(f"bot [{bot_id}] sober up in group [{group_id}]")
        await get_bot(str(bot_id)).call_api(
            "send_group_msg",
            **{
                "message": "呃......咳嗯，下次不能喝、喝这么多了......",
                "group_id": group_id,
            },
        )


@drink_msg.handle()
async def handle_drink(event: GroupMessageEvent):
    if not await is_command_cooldown_ready(event, "drink.drink"):
        return
    await refresh_command_cooldown(event, "drink.drink")
    config = BotConfig(event.self_id, event.group_id)

    drunk_duration = random.randint(60, 600)
    logger.info(
        f"bot [{event.self_id}] ready to drink in group [{event.group_id}], sober up after {drunk_duration} sec"
    )

    await config.drink()
    drunkenness = await config.drunkenness()
    go_to_sleep = random.random() < (0.02 if drunkenness <= 50 else (drunkenness - 50 + 1) * 0.02)
    if go_to_sleep:
        sleep_duration = (min(drunkenness, 35) + random.random()) * 800
        logger.info(
            f"bot [{event.self_id}] go to sleep in group [{event.group_id}], wake up after {sleep_duration} sec"
        )
        await config.sleep(int(sleep_duration))

    try:
        if go_to_sleep:
            await drink_msg.send("呀，博士。你今天走起路来，怎么看着摇…摇……晃…………")
            await asyncio.sleep(1)
            await drink_msg.send("Zzz……")
        else:
            await drink_msg.send("呀，博士。你今天走起路来，怎么看着摇摇晃晃的？")
    except ActionFailed:
        pass

    sober_up_date = datetime.now() + timedelta(seconds=drunk_duration)
    scheduler.add_job(
        sober_up_later,
        trigger="date",
        run_date=sober_up_date,
        args=(event.self_id, event.group_id),
    )


async def is_sober_up_msg(event: GroupMessageEvent) -> bool:
    return event.get_plaintext().strip() in {"牛牛醒一醒", "牛牛别喝了"}


sober_up_msg = on_message(
    rule=Rule(is_sober_up_msg),
    priority=5,
    block=True,
    permission=group_message_permission_for_command("drink.sober_up"),
)


@sober_up_msg.handle()
async def handle_sober_up(event: GroupMessageEvent):
    config = BotConfig(event.self_id, event.group_id)
    had_drunk = await config.drunkenness() > 0
    had_dream = await config.is_dreaming()
    if not had_drunk and not had_dream:
        return
    if had_drunk:
        await config.fully_sober_up_now()
    if had_dream:
        await config.stop_dream()
        await dream_coord.stop_dream_worker(event.self_id, event.group_id)
    if had_drunk:
        try:
            await sober_up_msg.send("呃......咳嗯，下次不能喝、喝这么多了......")
        except ActionFailed:
            pass
    if had_dream:
        await dream_coord.send_dream_wake_text(event.self_id, event.group_id)
