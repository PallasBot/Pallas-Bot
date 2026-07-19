import asyncio
import random
import time

from nonebot import on_message, on_notice, on_request
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupAdminNoticeEvent,
    GroupMessageEvent,
    GroupRequestEvent,
    MessageSegment,
    permission,
)
from nonebot.rule import Rule

from pallas.core.foundation.config import BotConfig, GroupConfig
from pallas.core.perm import group_message_permission_for_command

from .config import SHOT_CFG
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
    roulette,
    roulette_count,
    roulette_player,
    roulette_status,
    roulette_time,
    shot,
    shot_lock,
    sync_role_cache,
)

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
    if mode is not None:
        await GroupConfig(event.group_id).set_roulette_mode(mode)

    await roulette(roulette_type_msg, event, mode_override=mode)


roulette_msg = on_message(
    priority=5,
    block=True,
    rule=Rule(is_roulette_msg),
    permission=permission.GROUP,
)


@roulette_msg.handle()
async def _(event: GroupMessageEvent):
    await roulette(roulette_msg, event)


shot_msg = on_message(
    priority=5,
    block=True,
    rule=Rule(is_shot_msg),
    permission=permission.GROUP,
)


@shot_msg.handle()
async def _(event: GroupMessageEvent):
    async with shot_lock:
        roulette_status[event.group_id] -= 1
        roulette_count[event.group_id] += 1
        shot_msg_count = roulette_count[event.group_id]
        roulette_time[event.group_id] = int(time.time())
        roulette_player.append(event.user_id, event.group_id)

        if shot_msg_count == 6 and random.random() < 0.125:
            roulette_status[event.group_id] = 0
            roulette_player.clear(event.group_id)
            await roulette_msg.finish(SHOT_CFG.misfire_msg)

        elif roulette_status[event.group_id] > 0:
            await roulette_msg.finish(SHOT_CFG.miss_texts[shot_msg_count - 1] + f"( {shot_msg_count} / 6 )")

        roulette_status[event.group_id] = 0

        async def let_the_bullets_fly():
            await asyncio.sleep(random.randint(5, 20))

        if await BotConfig(event.self_id, event.group_id).drunkenness() <= 0:
            roulette_player.clear(event.group_id)
            shot_awaitable = await shot(event.self_id, event.user_id, event.group_id)
            if shot_awaitable:
                reply_msg = (
                    MessageSegment.text(SHOT_CFG.hit_msg.split("{at}")[0])
                    + MessageSegment.at(event.user_id)
                    + MessageSegment.text(SHOT_CFG.hit_msg.split("{at}")[1])
                )
                await roulette_msg.send(reply_msg)
                await let_the_bullets_fly()
                await shot_awaitable()
            else:
                reply_msg = "听啊，悲鸣停止了。这是幸福的和平到来前的宁静。"
                await roulette_msg.finish(reply_msg)

        else:
            player_ids = roulette_player.get_user_ids(event.group_id)
            rand_list = player_ids[-random.randint(1, min(len(player_ids), 6)) :][::-1]
            roulette_player.clear(event.group_id)
            shot_awaitable_list = []
            for user_id in rand_list:
                shot_awaitable = await shot(event.self_id, user_id, event.group_id)
                if not shot_awaitable:
                    continue

                shot_awaitable_list.append(shot_awaitable)

                drunk_parts = SHOT_CFG.drunk_hit_msg.replace("{count}", str(len(shot_awaitable_list))).split("{at}")
                reply_msg = (
                    MessageSegment.text(drunk_parts[0])
                    + MessageSegment.at(user_id)
                    + MessageSegment.text(drunk_parts[1])
                )
                await roulette_msg.send(reply_msg)

            if not shot_awaitable_list:
                return

            await let_the_bullets_fly()
            for shot_awaitable in shot_awaitable_list:
                await shot_awaitable()


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
    roulette_player.append(event.user_id, event.group_id)


rescue_or_judgment = on_message(
    priority=4,
    block=False,
    rule=Rule(is_rescue_or_judgment),
    permission=permission.GROUP,
)


@rescue_or_judgment.handle()
async def _(bot: Bot, event: GroupMessageEvent):
    await rescue_or_judgment_handler(bot, event)
