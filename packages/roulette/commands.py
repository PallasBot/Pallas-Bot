from nonebot import on_message, on_notice, on_request
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupAdminNoticeEvent,
    GroupMessageEvent,
    GroupRequestEvent,
    permission,
)
from nonebot.rule import Rule

from pallas.api.perm import group_message_permission_for_command

from .game import (
    is_drink_msg,
    is_rescue_or_judgment,
    is_roulette_msg,
    is_roulette_type_msg,
    is_set_group_admin,
    is_shot_msg,
    kicked_users,
    parse_roulette_start_command,
    rescue_or_judgment_handler,
    sync_role_cache,
)
from .service import fire_roulette, join_active_roulette, start_roulette

set_group_admin = on_notice(
    rule=Rule(is_set_group_admin),
    permission=permission.GROUP,
    priority=3,
    block=False,
)


@set_group_admin.handle()
async def _(bot: Bot, event: GroupAdminNoticeEvent):
    await sync_role_cache(bot, event)


roulette_type_msg = on_message(
    priority=5,
    block=True,
    rule=Rule(is_roulette_type_msg),
    permission=group_message_permission_for_command("roulette.mode_switch"),
)


@roulette_type_msg.handle()
async def _(event: GroupMessageEvent):
    _, mode = parse_roulette_start_command(event.get_plaintext())
    await start_roulette(event, roulette_type_msg.send, mode_override=mode)
    await roulette_type_msg.finish()


roulette_msg = on_message(
    priority=5,
    block=True,
    rule=Rule(is_roulette_msg),
    permission=permission.GROUP,
)


@roulette_msg.handle()
async def _(event: GroupMessageEvent):
    await start_roulette(event, roulette_msg.send)
    await roulette_msg.finish()


shot_msg = on_message(
    priority=5,
    block=True,
    rule=Rule(is_shot_msg),
    permission=permission.GROUP,
)


@shot_msg.handle()
async def _(event: GroupMessageEvent):
    await fire_roulette(event, roulette_msg.send)
    await shot_msg.finish()


request_cmd = on_request(
    priority=15,
    block=False,
)


@request_cmd.handle()
async def _(bot: Bot, event: GroupRequestEvent):
    if event.sub_type == "add" and event.user_id in kicked_users[event.group_id]:
        kicked_users[event.group_id].remove(event.user_id)
        await event.approve(bot)


drink_msg = on_message(
    priority=4,
    block=False,
    rule=Rule(is_drink_msg),
    permission=permission.GROUP,
)


@drink_msg.handle()
async def _(event: GroupMessageEvent):
    await join_active_roulette(event)


rescue_or_judgment = on_message(
    priority=4,
    block=False,
    rule=Rule(is_rescue_or_judgment),
    permission=permission.GROUP,
)


@rescue_or_judgment.handle()
async def _(bot: Bot, event: GroupMessageEvent):
    await rescue_or_judgment_handler(bot, event)
