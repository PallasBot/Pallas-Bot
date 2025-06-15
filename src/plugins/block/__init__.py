from nonebot import get_driver, get_plugin_config, on_message, on_notice
from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import GroupIncreaseNoticeEvent, GroupMessageEvent, PokeNotifyEvent, permission
from nonebot.rule import Rule

from src.common.config import BotConfig

from .config import Config

plugin_config = get_plugin_config(Config)
driver = get_driver()


@driver.on_bot_connect
async def bot_connect(bot: Bot) -> None:
    if bot.self_id.isnumeric() and bot.type == "OneBot V11":
        plugin_config.bots.add(int(bot.self_id))


@driver.on_bot_disconnect
async def bot_disconnect(bot: Bot) -> None:
    if bot.self_id.isnumeric() and bot.type == "OneBot V11":
        try:
            plugin_config.bots.remove(int(bot.self_id))
        except ValueError:
            pass


async def is_other_bot(event: GroupMessageEvent) -> bool:
    return event.user_id in plugin_config.bots


async def is_sleep(event: GroupMessageEvent | GroupIncreaseNoticeEvent | PokeNotifyEvent) -> bool:
    if not event.group_id:
        return False
    return await BotConfig(event.self_id, event.group_id).is_sleep()


other_bot_msg = on_message(
    priority=1,
    block=True,
    rule=Rule(is_other_bot),
    permission=permission.GROUP,
)

any_msg = on_message(
    priority=4,
    block=True,
    rule=Rule(is_sleep),
    permission=permission.GROUP,
)

any_notice = on_notice(
    priority=4,
    block=True,
    rule=Rule(is_sleep),
)


@other_bot_msg.handle()
async def _():
    return
