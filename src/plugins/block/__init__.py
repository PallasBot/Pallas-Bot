from nonebot import get_driver, get_plugin_config, logger, on_message, on_notice
from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import GroupIncreaseNoticeEvent, GroupMessageEvent, PokeNotifyEvent, permission
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from src.common.config import BotConfig

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="其他牛牛消息拦截",
    description="拦截其他牛牛的消息与通知。",
    usage="""
功能说明：
将拦截其他牛牛的群消息与群通知事件。
""".strip(),
    type="application",
    homepage="https://github.com/PallasBot/Pallas-Bot",
    supported_adapters={"~onebot.v11"},
    extra={
        "version": "3.0.0",
        "menu_data": [
            {
                "func": "消息拦截",
                "trigger_method": "on_message/on_notice",
                "trigger_condition": "",
                "brief_des": "拦截群事件",
                "detail_des": "阻断群消息与通知，避免触发后续插件逻辑。",
            },
        ],
    },
)

plugin_config = get_plugin_config(Config)
driver = get_driver()


@driver.on_bot_connect
async def bot_connect(bot: Bot) -> None:
    if bot.self_id.isnumeric() and bot.type == "OneBot V11":
        logger.info(f"Bot {bot.self_id} connected.")
        plugin_config.bots.add(int(bot.self_id))


@driver.on_bot_disconnect
async def bot_disconnect(bot: Bot) -> None:
    if bot.self_id.isnumeric() and bot.type == "OneBot V11":
        try:
            plugin_config.bots.remove(int(bot.self_id))
        except ValueError:
            pass
        else:
            logger.info(f"Bot {bot.self_id} disconnected.")


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
