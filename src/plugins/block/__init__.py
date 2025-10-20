from nonebot import get_driver, get_plugin_config, logger, on_message, on_notice
from nonebot.adapters.milky import Bot, permission
from nonebot.adapters.milky.event import GroupMemberIncreaseEvent, GroupMessageEvent, GroupNudgeEvent
from nonebot.rule import Rule

from src.common.config import BotConfig

from .config import Config

plugin_config = get_plugin_config(Config)
driver = get_driver()


@driver.on_bot_connect
async def bot_connect(bot: Bot) -> None:
    if bot.self_id.isnumeric() and bot.type == "Milky":
        logger.info(f"Bot {bot.self_id} connected.")
        plugin_config.bots.add(int(bot.self_id))


@driver.on_bot_disconnect
async def bot_disconnect(bot: Bot) -> None:
    if bot.self_id.isnumeric() and bot.type == "Milky":
        try:
            plugin_config.bots.remove(int(bot.self_id))
        except ValueError:
            pass
        else:
            logger.info(f"Bot {bot.self_id} disconnected.")


async def is_other_bot(event: GroupMessageEvent) -> bool:
    return event.data.sender_id in plugin_config.bots


async def is_sleep(event: GroupMessageEvent | GroupMemberIncreaseEvent | GroupNudgeEvent) -> bool:
    if isinstance(event, GroupMessageEvent):
        group_id = event.data.peer_id
    else:
        group_id = event.data.group_id
    if not group_id:
        return False
    return await BotConfig(event.self_id, group_id).is_sleep()


other_bot_msg = on_message(
    rule=Rule(is_other_bot),
    permission=permission.GROUP,
    priority=1,
    block=True,
)

any_msg = on_message(
    rule=Rule(is_sleep),
    permission=permission.GROUP,
    priority=4,
    block=True,
)

any_notice = on_notice(
    rule=Rule(is_sleep),
    priority=4,
    block=True,
)


@other_bot_msg.handle()
async def _():
    return
