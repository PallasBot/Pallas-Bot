import asyncio
import random
from datetime import datetime, timedelta

from nonebot import get_bot, get_driver, logger, on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent, permission
from nonebot.exception import ActionFailed
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule
from nonebot_plugin_apscheduler import scheduler

from src.features.cmd_perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)
from src.features.cmd_perm.metadata_text import SCENE_GROUP, join_usage, usage_line
from src.foundation.config import BotConfig
from src.plugins.dream.runtime import send_dream_wake_text, stop_dream_worker

__plugin_meta__ = PluginMetadata(
    name="牛牛喝酒",
    description="群内饮酒与醒酒，影响醉酒度及关联玩法。",
    usage=join_usage(
        usage_line("牛牛喝酒 / 牛牛干杯 / 牛牛继续喝", "增加醉酒度，可能睡着"),
        usage_line("牛牛醒一醒 / 牛牛别喝了", "立即醒酒；本群在做梦时一并醒梦"),
    ),
    type="application",
    homepage=PLUGIN_HOMEPAGE,
    supported_adapters={"~onebot.v11"},
    extra={
        "version": PLUGIN_EXTRA_VERSION,
        "menu_template": PLUGIN_MENU_TEMPLATE,
        "ingress_fanout": {
            "scope": "always",
            "plaintexts": [
                "牛牛喝酒",
                "牛牛干杯",
                "牛牛继续喝",
                "牛牛醒一醒",
                "牛牛别喝了",
            ],
        },
        "menu_data": [
            {
                "func": "牛牛喝酒",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "牛牛喝酒 / 牛牛干杯 / 牛牛继续喝",
                "brief_des": "饮酒并进入醉酒",
                "detail_des": "醉酒会影响聊天、轮盘、夺舍等；程度过高可能睡着，之后会自动清醒。",
            },
            {
                "func": "牛牛醒一醒",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "牛牛醒一醒 / 牛牛别喝了",
                "brief_des": "立即醒酒",
                "detail_des": "清除醉酒；若本群正在「牛牛做梦」则同时结束做梦。",
            },
        ],
    },
)

driver = get_driver()


async def is_drink_msg(event: GroupMessageEvent) -> bool:
    return event.get_plaintext().strip() in {"牛牛喝酒", "牛牛干杯", "牛牛继续喝"}


drink_msg = on_message(
    rule=Rule(is_drink_msg),
    priority=5,
    block=True,
    permission=permission.GROUP,
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
    permission=permission.GROUP,
)


@sober_up_msg.handle()
async def _(event: GroupMessageEvent):
    config = BotConfig(event.self_id, event.group_id)
    had_drunk = await config.drunkenness() > 0
    had_dream = await config.is_dreaming()
    if not had_drunk and not had_dream:
        return
    if had_drunk:
        await config.fully_sober_up_now()
    if had_dream:
        await config.stop_dream()
        await stop_dream_worker(event.self_id, event.group_id)
    if had_drunk:
        try:
            await sober_up_msg.send("呃......咳嗯，下次不能喝、喝这么多了......")
        except ActionFailed:
            pass
    if had_dream:
        await send_dream_wake_text(event.self_id, event.group_id)


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
