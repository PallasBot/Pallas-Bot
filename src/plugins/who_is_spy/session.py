from __future__ import annotations

from typing import Literal

from src.platform.multi_bot.dedup import (
    begin_group_exclusive_activity,
    needs_group_host_bot_gate,
    release_group_owned_gate_sync,
)
from src.platform.multi_bot.group import is_group_owned_gate_holder

from .coord_store import (
    GAME_SNAPSHOT_KEY,
    clear_game_snapshot,
    game_from_snapshot,
    read_game_snapshot,
    read_prep_players,
    write_game_snapshot,
    write_prep_players,
)
from .group_lock import (
    SPY_GROUP_LOCK,
    clear_spy_room_session,
    end_spy_room_lock,
    mark_spy_room_session,
    read_spy_prep_room,
    spy_room_coord_live,
    spy_session_active,
)
from .logic import games, get_nickname
from .models import Game, Player

PLUGIN_KEY = "who_is_spy"

SPY_HOST_GATE_SEC = 7200.0

SpyRoomGate = Literal["ok", "busy"]


def group_key(group_id: int) -> int:
    return int(group_id)


def bind_local_game(game: Game) -> Game:
    gid = group_key(game.group_id)
    game.group_id = gid
    games[gid] = game
    return game


def persist_prep(game: Game) -> None:
    write_prep_players(game.group_id, game)


def persist_game(game: Game) -> None:
    if game.ready:
        write_game_snapshot(game)
    else:
        persist_prep(game)


def read_active_game_snapshot(group_id: int) -> Game | None:
    """协调层已开局快照；read_game_snapshot 失败时回读 lock 原文。"""
    gid = group_key(group_id)
    snap = read_game_snapshot(gid)
    if snap is not None and snap.ready:
        return snap
    data = SPY_GROUP_LOCK.read(gid)
    if not data:
        return None
    raw = data.get(GAME_SNAPSHOT_KEY)
    if not isinstance(raw, dict):
        return None
    parsed = game_from_snapshot(raw)
    if parsed is not None and parsed.ready:
        return parsed
    return None


def resolve_game_sync(group_id: int) -> Game | None:
    """内存无局或仅有筹备房时，优先用协调层已开局快照（供 Rule / ingress 使用）。"""
    gid = group_key(group_id)
    active = read_active_game_snapshot(gid)
    if active is not None:
        return bind_local_game(active)
    cached = games.get(gid)
    if cached is not None:
        if cached.ready or not spy_session_active(gid):
            return cached
    snap = read_game_snapshot(gid)
    if snap is not None:
        return bind_local_game(snap)
    return None


async def begin_spy_room(group_id: int) -> SpyRoomGate:
    gid = group_key(group_id)
    return await begin_group_exclusive_activity("spy_group", gid, has_local=gid in games)


def close_spy_room(group_id: int) -> None:
    gid = group_key(group_id)
    games.pop(gid, None)
    end_spy_room_lock(gid)
    clear_game_snapshot(gid)
    if needs_group_host_bot_gate():
        release_group_owned_gate_sync("who_is_spy", gid)


def mark_spy_room_active(group_id: int) -> None:
    mark_spy_room_session(group_key(group_id))


def clear_spy_room_active(group_id: int) -> None:
    clear_spy_room_session(group_key(group_id))


async def restore_prep_game(bot, group_id: int) -> Game | None:
    gid = group_key(group_id)
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
    for uid, nickname in read_prep_players(gid):
        game.players[uid] = Player(uid=uid, nickname=nickname)
    if owner_id not in game.players:
        nick = await get_nickname(bot, gid, owner_id)
        game.players[owner_id] = Player(uid=owner_id, nickname=nick)
    return bind_local_game(game)


async def load_local_prep_game(bot, group_id: int) -> Game | None:
    """主持牛 worker 内存无 games 时，从 spy_group 占位恢复筹备房。"""
    gid = group_key(group_id)
    active = read_active_game_snapshot(gid)
    if active is not None:
        return bind_local_game(active)
    cached = games.get(gid)
    if cached is not None:
        return cached
    return await restore_prep_game(bot, gid)


async def load_local_game(bot, group_id: int) -> Game | None:
    """筹备或进行中：优先协调层已开局快照，其次内存 / 筹备名册。"""
    gid = group_key(group_id)
    active = read_active_game_snapshot(gid)
    if active is not None:
        return bind_local_game(active)
    cached = games.get(gid)
    if cached is not None:
        return cached
    return await restore_prep_game(bot, gid)
