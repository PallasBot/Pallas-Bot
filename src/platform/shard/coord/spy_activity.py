"""卧底同群 activity 协调。"""

from __future__ import annotations

from typing import Any

from src.platform.shard.coord.group_activity import (
    get_group_activity_lock,
    session_live_by_flag,
)
from src.platform.shard.coord.group_gate import read_owned_gate_bot_id_sync
from src.platform.shard.coord.hosted_activity_coord import (
    coord_room_live,
    coord_session_active,
    hosted_activity_live,
)

SPY_OWNED_PLUGIN = "who_is_spy"
SPY_ACTIVITY_NS = "spy_group"

SPY_ACTIVITY_LOCK = get_group_activity_lock(
    SPY_ACTIVITY_NS,
    session_extra_keys=frozenset({
        "session_active",
        "prep_owner_id",
        "prep_host_bot_id",
        "prep_players",
        "game_snapshot",
    }),
    is_live_session=lambda data: session_live_by_flag(data, flag_key="session_active"),
)


def spy_room_coord_live(group_id: int) -> bool:
    return coord_room_live(SPY_ACTIVITY_NS, group_id)


def spy_session_active(group_id: int) -> bool:
    return coord_session_active(SPY_ACTIVITY_NS, group_id, session_flag="session_active")


def spy_owned_gate_live(group_id: int) -> bool:
    return read_owned_gate_bot_id_sync(SPY_OWNED_PLUGIN, int(group_id)) is not None


def spy_activity_live(group_id: int) -> bool:
    return hosted_activity_live(
        activity_namespace=SPY_ACTIVITY_NS,
        plugin_key=SPY_OWNED_PLUGIN,
        group_id=group_id,
    )


def mark_spy_prep_room(group_id: int, *, owner_id: int, host_bot_id: int) -> None:
    gid = int(group_id)

    def stamp(data: dict[str, Any]) -> None:
        data["prep_owner_id"] = int(owner_id)
        data["prep_host_bot_id"] = int(host_bot_id)

    SPY_ACTIVITY_LOCK._mutate(gid, stamp)


def read_spy_prep_room(group_id: int) -> tuple[int, int] | None:
    data = SPY_ACTIVITY_LOCK.read(int(group_id))
    if not data or not data.get("busy"):
        return None
    owner = data.get("prep_owner_id")
    host = data.get("prep_host_bot_id")
    if owner is None or host is None:
        return None
    return int(owner), int(host)


def mark_spy_room_session(group_id: int) -> None:
    SPY_ACTIVITY_LOCK.mark_session(int(group_id), session_active=True)


def clear_spy_room_session(group_id: int) -> None:
    SPY_ACTIVITY_LOCK.clear_session(int(group_id))


def end_spy_room_lock(group_id: int) -> None:
    SPY_ACTIVITY_LOCK.end(int(group_id))
