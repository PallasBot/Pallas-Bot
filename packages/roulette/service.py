from __future__ import annotations

import asyncio
import random
import time
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot.log import logger

from pallas.api.logging import format_plugin_event
from pallas.core.foundation.config import BotConfig, GroupConfig
from pallas.core.platform.multi_bot.dedup import try_claim_group_message_once

from . import game
from .config import SHOT_CFG
from .game import participate_in_roulette_mode

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from nonebot.adapters.onebot.v11 import GroupMessageEvent

    type SendMessage = Callable[[object], Awaitable[object]]

_ROULETTE_START_PLUGIN = "roulette_start"


async def start_roulette(
    event: GroupMessageEvent,
    send: SendMessage,
    *,
    mode_override: int | None = None,
) -> None:
    if not await try_claim_group_message_once(
        _ROULETTE_START_PLUGIN,
        event.group_id,
        event.user_id,
        event.get_plaintext(),
        event.time,
        include_message_time=True,
    ):
        logger.debug(
            "roulette: start once-claim lost bot={} group={} user={}",
            event.self_id,
            event.group_id,
            event.user_id,
        )
        return
    if mode_override is not None:
        await GroupConfig(event.group_id).set_roulette_mode(mode_override)
    chamber = random.randint(1, 6)
    game.roulette_status[event.group_id] = chamber
    game.roulette_count[event.group_id] = 0
    game.roulette_time[event.group_id] = int(time.time())
    game.ban_players.clear(event.group_id)
    mode = mode_override if mode_override is not None else await GroupConfig(event.group_id).roulette_mode()
    if await participate_in_roulette_mode(event, mode):
        game.roulette_player.append(event.self_id, event.group_id)
    game.roulette_player.append(event.user_id, event.group_id)
    type_msg = "踢出群聊" if mode == 0 else "禁言"
    await send(
        f"这是一把充满荣耀与死亡的左轮手枪，六个弹槽只有一颗子弹，中弹的那个人将会被{type_msg}。勇敢的战士们啊，扣动你们的扳机吧！"
    )
    mode_name = "mute" if mode else "kick"
    logger.info(
        format_plugin_event(
            "start_roulette",
            f"Bot [{event.self_id}] opened a {mode_name} roulette in group [{event.group_id}] with chamber [{chamber}]",
        )
    )


async def join_active_roulette(event: GroupMessageEvent) -> None:
    game.roulette_player.append(event.user_id, event.group_id)


async def fire_roulette(event: GroupMessageEvent, send: SendMessage) -> None:
    penalty = await prepare_fire_roulette(event, send)
    if penalty is not None:
        await penalty()


async def prepare_fire_roulette(
    event: GroupMessageEvent,
    send: SendMessage,
) -> Callable[[], Awaitable[None]] | None:
    async with game.shot_lock:
        game.roulette_status[event.group_id] -= 1
        game.roulette_count[event.group_id] += 1
        shot_count = game.roulette_count[event.group_id]
        game.roulette_time[event.group_id] = int(time.time())
        game.roulette_player.append(event.user_id, event.group_id)
        logger.info(
            format_plugin_event(
                "roulette_shot",
                f"User [{event.user_id}] fired shot [{shot_count}/6] in group [{event.group_id}]",
            )
        )

        if shot_count == 6 and random.random() < 0.125:
            game.roulette_status[event.group_id] = 0
            game.roulette_player.clear(event.group_id)
            await send(SHOT_CFG.misfire_msg)
            return
        if game.roulette_status[event.group_id] > 0:
            await send(SHOT_CFG.miss_texts[shot_count - 1] + f"( {shot_count} / 6 )")
            return

        game.roulette_status[event.group_id] = 0

        async def let_the_bullets_fly() -> None:
            await asyncio.sleep(random.randint(5, 20))

        if await BotConfig(event.self_id, event.group_id).drunkenness() <= 0:
            game.roulette_player.clear(event.group_id)
            shot_awaitable = await game.shot(event.self_id, event.user_id, event.group_id)
            if not shot_awaitable:
                await send("听啊，悲鸣停止了。这是幸福的和平到来前的宁静。")
                return None
            reply_msg = (
                MessageSegment.text(SHOT_CFG.hit_msg.split("{at}")[0])
                + MessageSegment.at(event.user_id)
                + MessageSegment.text(SHOT_CFG.hit_msg.split("{at}")[1])
            )
            await send(reply_msg)
            return lambda: delayed_shot(shot_awaitable, let_the_bullets_fly)

        player_ids = game.roulette_player.get_user_ids(event.group_id)
        rand_list = player_ids[-random.randint(1, min(len(player_ids), 6)) :][::-1]
        game.roulette_player.clear(event.group_id)
        shot_awaitable_list = []
        for user_id in rand_list:
            shot_awaitable = await game.shot(event.self_id, user_id, event.group_id)
            if not shot_awaitable:
                continue
            shot_awaitable_list.append(shot_awaitable)
            drunk_parts = SHOT_CFG.drunk_hit_msg.replace("{count}", str(len(shot_awaitable_list))).split("{at}")
            reply_msg = (
                MessageSegment.text(drunk_parts[0]) + MessageSegment.at(user_id) + MessageSegment.text(drunk_parts[1])
            )
            await send(reply_msg)
        if not shot_awaitable_list:
            return None
        return lambda: delayed_shots(shot_awaitable_list, let_the_bullets_fly)


async def delayed_shot(shot_awaitable: Callable[[], Awaitable[None]], delay: Callable[[], Awaitable[None]]) -> None:
    await delay()
    await shot_awaitable()


async def delayed_shots(
    shot_awaitables: list[Callable[[], Awaitable[None]]],
    delay: Callable[[], Awaitable[None]],
) -> None:
    await delay()
    for shot_awaitable in shot_awaitables:
        await shot_awaitable()
