import random

from nonebot import get_bot, logger, on_notice, require
from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import NoticeEvent, permission
from nonebot.exception import ActionFailed
from nonebot.rule import Rule

from src.common.config import BotConfig
from src.common.utils import is_bot_admin
from src.plugins.repeater.model import Chat

change_name_sched = require("nonebot_plugin_apscheduler").scheduler


@change_name_sched.scheduled_job("cron", minute="*/1")
async def change_name():
    rand_messages = await Chat.get_random_message_from_each_group()
    if not rand_messages:
        return

    for group_id, target_msg in rand_messages.items():
        if random.random() > 0.002:  # 期望约每8个多小时改一次
            continue

        bot_id = target_msg["bot_id"]
        config = BotConfig(bot_id, group_id)
        if await config.is_sleep():
            continue

        target_user_id = target_msg["user_id"]
        logger.info(f"bot [{bot_id}] ready to change name by using [{target_user_id}] in group [{group_id}]")

        bot = get_bot(str(bot_id))
        if not bot:
            logger.error("no bot: " + str(bot_id))
            continue

        try:
            # 获取群友昵称
            info = await bot.call_api(
                "get_group_member_info",
                **{
                    "group_id": group_id,
                    "user_id": target_user_id,
                    "no_cache": True,
                },
            )
        except ActionFailed:
            # 可能这人退群了
            continue

        card = info["card"] or info["nickname"]
        logger.info(f"bot [{bot_id}] ready to change name to[{card}] in group [{group_id}]")
        try:
            # 改牛牛自己的群名片
            await bot.call_api(
                "set_group_card",
                **{
                    "group_id": group_id,
                    "user_id": bot_id,
                    "card": card,
                },
            )

            # 酒后夺舍！改群友的！
            if await config.drunkenness() and await is_bot_admin(bot_id, group_id, True):
                await bot.call_api(
                    "set_group_card",
                    **{
                        "group_id": group_id,
                        "user_id": target_user_id,
                        "card": random.choice(["帕拉斯", "牛牛", "牛牛喝酒", "牛牛干杯", "牛牛继续喝"]),
                    },
                )

            # 戳一戳
            await bot.call_api(
                "group_poke",
                **{
                    "user_id": target_user_id,
                    "group_id": group_id,
                },
            )

            await config.update_taken_name(target_user_id)

        except ActionFailed:
            # 可能牛牛退群了
            continue


async def is_change_name_notice(event: NoticeEvent) -> bool:
    if event.notice_type == "group_card":
        config = BotConfig(event.self_id, event.group_id)
        if event.user_id == await config.taken_name():
            return True
    return False


watch_name = on_notice(
    rule=Rule(is_change_name_notice),
    permission=permission.GROUP,
    priority=4,
)


@watch_name.handle()
async def watch_name_handle(bot: Bot, event: NoticeEvent):
    group_id = event.group_id
    user_id = event.user_id
    bot_id = event.self_id

    try:
        info = await bot.call_api(
            "get_group_member_info",
            **{
                "group_id": group_id,
                "user_id": user_id,
                "no_cache": True,
            },
        )
    except ActionFailed:
        return
    card = info["card"] or info["nickname"]
    logger.info(f"bot [{bot.self_id}] watch name change by [{user_id}] in group [{group_id}]")
    config = BotConfig(bot.self_id, group_id)

    try:
        await bot.call_api(
            "set_group_card",
            **{
                "group_id": group_id,
                "user_id": bot_id,
                "card": card,
            },
        )
        await config.update_taken_name(user_id)
    except ActionFailed:
        return
