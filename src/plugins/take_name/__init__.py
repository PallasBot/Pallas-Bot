import random

from nonebot import get_bot, logger, on_notice, require
from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import NoticeEvent, permission
from nonebot.exception import ActionFailed
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from src.common.config import BotConfig
from src.common.utils import is_bot_admin
from src.plugins.repeater.model import Chat

change_name_sched = require("nonebot_plugin_apscheduler").scheduler

__plugin_meta__ = PluginMetadata(
    name="自动夺舍",
    description="牛牛自动取名和同步群名片的功能",
    usage="""
这个插件会让牛牛自动更换群名片：
1. 牛牛会定期自动更换自己的群名片为群内随机用户的名片
2. 当牛牛醉酒时，有一定概率会"夺舍"其他群友的名片
3. 当被取名的用户修改自己的群名片时，牛牛会同步修改自己的群名片为该用户的新名片
    """.strip(),
    type="application",
    homepage="https://github.com/PallasBot",
    supported_adapters=["~onebot.v11"],
    extra={
        "version": "2.0.0",
        "menu_data": [
            {
                "func": "牛牛夺舍",
                "trigger_method": "scheduler",
                "trigger_condition": "定时任务",
                "brief_des": "牛牛自动更换群名片",
                "detail_des": "牛牛每分钟有约0.2%的概率自动更换自己的群名片为群内随机用户的名片，并戳一戳该用户。",
            },
            {
                "func": "醉酒夺舍",
                "trigger_method": "scheduler",
                "trigger_condition": "醉酒状态",
                "brief_des": "醉酒时随机更换群友名片",
                "detail_des": "当牛牛处于醉酒状态且为群管理员时，更换自己名片的同时有概率将被取名用户的名字改为固定名称（帕拉斯、牛牛等）。",  # noqa: E501
            },
            {
                "func": "名片同步",
                "trigger_method": "on_notice",
                "trigger_condition": "群名片变更",
                "brief_des": "同步被取名用户的群名片",
                "detail_des": "当被牛牛取名的用户修改自己的群名片时，牛牛会自动同步修改自己的群名片为该用户的新名片。",
            },
        ],
        "menu_template": "default",
    },
)


@change_name_sched.scheduled_job("cron", minute="*/1")
async def change_name():
    rand_messages = await Chat.get_random_message_from_each_group()
    if not rand_messages:
        return

    for group_id, target_msg in rand_messages.items():
        if random.random() > 0.002:  # 期望约每8个多小时改一次
            continue

        bot_id = target_msg.bot_id
        config = BotConfig(bot_id, group_id)
        if await config.is_sleep():
            continue

        target_user_id = target_msg.user_id
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
    config = BotConfig(int(bot.self_id), group_id)

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
