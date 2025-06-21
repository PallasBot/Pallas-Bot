import asyncio
import random

from nonebot import logger, on_message, require
from nonebot.adapters.onebot.v11 import GroupMessageEvent, permission
from nonebot.exception import ActionFailed
from nonebot.rule import Rule

from src.common.config import BotConfig


async def is_drink_msg(event: GroupMessageEvent) -> bool:
    return event.get_plaintext().strip() in {"牛牛喝酒", "牛牛干杯", "牛牛继续喝"}


drink_msg = on_message(
    rule=Rule(is_drink_msg),
    priority=5,
    block=True,
    permission=permission.GROUP,
)


@drink_msg.handle()
async def _(event: GroupMessageEvent):
    config = BotConfig(event.self_id, event.group_id, cooldown=3)
    if not await config.is_cooldown("drink"):
        return
    await config.refresh_cooldown("drink")

    drunk_duration = random.randint(60, 600)
    logger.info(
        f"bot [{event.self_id}] ready to drink in group [{event.group_id}], sober up after {drunk_duration} sec"
    )

    await config.drink()
    drunkenness = await config.drunkenness()
    go_to_sleep = random.random() < (0.02 if drunkenness <= 50 else (drunkenness - 50 + 1) * 0.02)
    if go_to_sleep:
        # 35 是期望概率
        sleep_duration = (min(drunkenness, 35) + random.random()) * 800
        logger.info(
            f"bot [{event.self_id}] go to sleep in group [{event.group_id}], wake up after {sleep_duration} sec"
        )
        await config.sleep(sleep_duration)

    try:
        if go_to_sleep:
            await drink_msg.send("呀，博士。你今天走起路来，怎么看着摇…摇……晃…………")
            await asyncio.sleep(1)
            await drink_msg.send("Zzz……")
        else:
            await drink_msg.send("呀，博士。你今天走起路来，怎么看着摇摇晃晃的？")
    except ActionFailed:
        pass

    await asyncio.sleep(drunk_duration)
    if await config.sober_up() and not await config.is_sleep():
        logger.info(f"bot [{event.self_id}] sober up in group [{event.group_id}]")
        await drink_msg.finish("呃......咳嗯，下次不能喝、喝这么多了......")


update_sched = require("nonebot_plugin_apscheduler").scheduler


@update_sched.scheduled_job("cron", hour="4")
async def update_data():
    await BotConfig.fully_sober_up()
