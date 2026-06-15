"""同群独占活动只读协调"""

from __future__ import annotations

import time

from src.platform.shard import context as shard_ctx
from src.platform.shard.coord.group_activity import (
    get_group_activity_lock,
    session_live_by_flag,
)
from src.platform.shard.coord.group_gate import read_owned_gate_bot_id_sync


def coord_room_live(activity_namespace: str, group_id: int) -> bool:
    gid = int(group_id)
    lock = get_group_activity_lock(activity_namespace)
    if not shard_ctx.sharding_active():
        return gid in lock.local_busy
    data = lock.read(gid)
    if not data or not data.get("busy"):
        return False
    until = float(data.get("until") or 0)
    return until > time.time()


def coord_session_active(
    activity_namespace: str,
    group_id: int,
    *,
    session_flag: str = "session_active",
) -> bool:
    if not coord_room_live(activity_namespace, group_id):
        return False
    data = get_group_activity_lock(activity_namespace).read(int(group_id))
    if not data:
        return False
    return session_live_by_flag(data, flag_key=session_flag)


def hosted_activity_live(
    *,
    activity_namespace: str,
    plugin_key: str,
    group_id: int,
) -> bool:
    if coord_room_live(activity_namespace, group_id):
        return True
    return read_owned_gate_bot_id_sync(plugin_key, int(group_id)) is not None
