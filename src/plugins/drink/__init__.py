import asyncio
import random
from datetime import datetime, timedelta

from nonebot import get_bot, get_driver, logger, on_message
from nonebot.adapters.milky import permission
from nonebot.adapters.milky.event import GroupMessageEvent
from nonebot.exception import ActionFailed
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule
from nonebot_plugin_apscheduler import scheduler

from src.common.config import BotConfig

__plugin_meta__ = PluginMetadata(
    name="牛牛喝酒",
    description="让牛牛喝酒！",
    usage="""
牛牛喝酒 - 让牛牛喝酒，增加聊天概率，有概率睡着zzz...
    """.strip(),
    type="application",
    homepage="https://github.com/PallasBot",
    supported_adapters={"~milky"},
    extra={
        "version": "2.0.0",
        "menu_data": [
            {
                "func": "牛牛喝酒",
                "trigger_method": "on_message",
                "trigger_condition": "牛牛喝酒/牛牛干杯/牛牛继续喝",
                "brief_des": "让牛牛喝酒并产生醉酒效果",
                "detail_des": "触发后牛牛会喝酒，根据醉酒程度可能会发送醉酒消息或直接睡着，一段时间后会自动清醒",
            },
        ],
        "menu_template": "default",
    },
)

driver = get_driver()


async def is_drink_msg(event: GroupMessageEvent) -> bool:
    return event.get_plaintext().strip() in {"牛牛喝酒", "牛牛干杯", "牛牛继续喝"}


drink_msg = on_message(
    rule=Rule(is_drink_msg),
    permission=permission.GROUP,
    priority=5,
    block=True,
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
async def _(event: GroupMessageEvent):
    config = BotConfig(event.self_id, event.data.peer_id, cooldown=3)
    if not await config.is_cooldown("drink"):
        return
    await config.refresh_cooldown("drink")

    drunk_duration = random.randint(60, 600)
    logger.info(
        f"bot [{event.self_id}] ready to drink in group [{event.data.peer_id}], sober up after {drunk_duration} sec"
    )

    await config.drink()
    drunkenness = await config.drunkenness()
    go_to_sleep = random.random() < (0.02 if drunkenness <= 50 else (drunkenness - 50 + 1) * 0.02)
    if go_to_sleep:
        # 35 是期望概率
        sleep_duration = (min(drunkenness, 35) + random.random()) * 800
        logger.info(
            f"bot [{event.self_id}] go to sleep in group [{event.data.peer_id}], wake up after {sleep_duration} sec"
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
        args=(event.self_id, event.data.peer_id),
    )


@scheduler.scheduled_job("cron", hour=4)
async def update_data():
    await BotConfig.fully_sober_up()


@driver.on_startup
async def _startup():
    if not scheduler.running:
        scheduler.start()


@driver.on_shutdown
async def _shutdown():
    if scheduler.running:
        scheduler.shutdown(wait=False)
