"""卧底插件分片同群互斥（namespace=spy_group，实现见 platform spy_activity）。"""

from __future__ import annotations

from src.platform.shard.coord.spy_activity import (
    SPY_ACTIVITY_LOCK,
    clear_spy_room_session,
    end_spy_room_lock,
    mark_spy_prep_room,
    mark_spy_room_session,
    read_spy_prep_room,
    spy_room_coord_live,
)

SPY_GROUP_LOCK = SPY_ACTIVITY_LOCK

__all__ = [
    "SPY_GROUP_LOCK",
    "clear_spy_room_session",
    "end_spy_room_lock",
    "mark_spy_prep_room",
    "mark_spy_room_session",
    "read_spy_prep_room",
    "spy_room_coord_live",
]
