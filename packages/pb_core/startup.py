from nonebot import get_driver
from nonebot.adapters.onebot.v11 import Bot

from .restart_notify import maybe_notify_restart_online

driver = get_driver()


@driver.on_bot_connect
async def pb_core_on_bot_connect(bot: Bot) -> None:
    if bot.type != "OneBot V11" or not bot.self_id.isnumeric():
        return
    await maybe_notify_restart_online(bot)
