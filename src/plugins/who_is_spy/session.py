from __future__ import annotations

from typing import Literal

from src.platform.multi_bot.dedup import (
    begin_group_exclusive_activity,
    needs_group_host_bot_gate,
    release_group_owned_gate_sync,
)
from src.platform.multi_bot.group import is_group_owned_gate_holder

from .group_lock import (
    clear_spy_room_session,
    end_spy_room_lock,
    mark_spy_room_session,
    read_spy_prep_room,
    spy_room_coord_live,
)
from .logic import games, get_nickname
from .models import Game, Player

PLUGIN_KEY = "who_is_spy"

SPY_HOST_GATE_SEC = 7200.0

SpyRoomGate = Literal["ok", "busy"]


async def begin_spy_room(group_id: int) -> SpyRoomGate:
    gid = int(group_id)
    return await begin_group_exclusive_activity("spy_group", gid, has_local=gid in games)


def close_spy_room(group_id: int) -> None:
    gid = int(group_id)
    games.pop(gid, None)
    end_spy_room_lock(gid)
    if needs_group_host_bot_gate():
        release_group_owned_gate_sync("who_is_spy", gid)


def mark_spy_room_active(group_id: int) -> None:
    mark_spy_room_session(int(group_id))


def clear_spy_room_active(group_id: int) -> None:
    clear_spy_room_session(int(group_id))


async def load_local_prep_game(bot, group_id: int) -> Game | None:
    """主持牛 worker 内存无 games 时，从 spy_group 占位恢复筹备房。"""
    gid = int(group_id)
    if gid in games:
        return games[gid]
    if not spy_room_coord_live(gid):
        return None
    bot_id = int(bot.self_id)
    if not await is_group_owned_gate_holder(PLUGIN_KEY, gid, bot_id):
        return None
    prep = read_spy_prep_room(gid)
    if prep is None:
        return None
    owner_id, _host = prep
    game = Game(group_id=gid, owner_id=owner_id)
    nick = await get_nickname(bot, gid, owner_id)
    game.players[owner_id] = Player(uid=owner_id, nickname=nick)
    games[gid] = game
    return game
