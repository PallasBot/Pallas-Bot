from nonebot import on_request
from nonebot.adapters.onebot.v11 import Bot, GroupRequestEvent

from src.common.config import BotConfig, GroupConfig, UserConfig

request_cmd = on_request(
    priority=14,
    block=False,
)


@request_cmd.handle()
async def handle_group_request(bot: Bot, event: GroupRequestEvent):
    if event.sub_type == "invite":
        if await GroupConfig(event.group_id).is_banned() or await UserConfig(event.user_id).is_banned():
            await event.reject(bot)
            return

        bot_config = BotConfig(event.self_id)
        if await bot_config.auto_accept() or await bot_config.is_admin_of_bot(event.user_id):
            await event.approve(bot)
