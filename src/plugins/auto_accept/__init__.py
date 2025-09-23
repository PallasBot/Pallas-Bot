from nonebot import on_request
from nonebot.adapters.milky import Bot
from nonebot.adapters.milky.event import GroupInvitationEvent
from nonebot.rule import is_type

from src.common.config import BotConfig, GroupConfig, UserConfig

request_cmd = on_request(
    rule=is_type(GroupInvitationEvent),
    priority=14,
    block=False,
)


@request_cmd.handle()
async def handle_group_request(bot: Bot, event: GroupInvitationEvent):
    if await GroupConfig(event.data.group_id).is_banned() or await UserConfig(event.data.initiator_id).is_banned():
        await bot.reject_group_invitation(request_id=event.data.request_id)
        return

    bot_config = BotConfig(event.self_id)
    if await bot_config.auto_accept() or await bot_config.is_admin_of_bot(event.data.initiator_id):
        await bot.accept_group_invitation(request_id=event.data.request_id)
