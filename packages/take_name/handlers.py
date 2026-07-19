import random

from nonebot import get_bots, logger, on_notice
from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import NoticeEvent, permission
from nonebot.exception import ActionFailed
from nonebot.rule import Rule

from packages.repeater.message_store import MessageStore
from pallas.core.foundation.config import BotConfig
from pallas.core.shared.utils import is_bot_admin


async def run_change_name():
    rand_messages = await MessageStore.get_random_message_from_each_group()
    if not rand_messages:
        return

    for group_id, target_msg in rand_messages.items():
        if random.random() > 0.002:
            continue

        bot_id = target_msg.bot_id
        config = BotConfig(bot_id, group_id)
        if await config.is_sleep():
            continue

        target_user_id = target_msg.user_id
        logger.info(f"bot [{bot_id}] ready to change name by using [{target_user_id}] in group [{group_id}]")

        bot_key = str(bot_id)
        local_bots = get_bots()
        if bot_key not in local_bots:
            continue
        bot = local_bots[bot_key]

        try:
            info = await bot.call_api(
                "get_group_member_info",
                **{
                    "group_id": group_id,
                    "user_id": target_user_id,
                    "no_cache": True,
                },
            )
        except ActionFailed:
            continue

        card = info["card"] or info["nickname"]
        logger.info(f"bot [{bot_id}] ready to change name to [{card}] in group [{group_id}]")
        try:
            await bot.call_api(
                "set_group_card",
                **{
                    "group_id": group_id,
                    "user_id": bot_id,
                    "card": card,
                },
            )

            if await config.drunkenness() and await is_bot_admin(bot_id, group_id, True):
                await bot.call_api(
                    "set_group_card",
                    **{
                        "group_id": group_id,
                        "user_id": target_user_id,
                        "card": random.choice(["帕拉斯", "牛牛", "牛牛喝酒", "牛牛干杯", "牛牛继续喝"]),
                    },
                )

            await bot.call_api(
                "group_poke",
                **{
                    "user_id": target_user_id,
                    "group_id": group_id,
                },
            )

            await config.update_taken_name(target_user_id)

        except ActionFailed:
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
