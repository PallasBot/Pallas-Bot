"""跨 worker 群级短占位。"""

from __future__ import annotations

import time
from typing import Any

from src.platform.shard.coord.coord_redis_store import (
    coord_key,
    mutate_json_sync,
    read_json_sync,
)


def _gate_key(kind: str, plugin: str, group_id: int) -> str:
    return coord_key("group_gate", kind, plugin, group_id)


def _gate_ttl(data: dict[str, Any]) -> int:
    until = float(data.get("until") or 0)
    return max(1, int(until - time.time()) + 5)


def _mutate_gate(kind: str, plugin: str, group_id: int, fn) -> dict[str, Any] | None:
    return mutate_json_sync(_gate_key(kind, plugin, group_id), fn, ttl_sec_fn=_gate_ttl)


def try_acquire_broadcast_slot_sync(plugin: str, group_id: int, *, ttl_sec: float) -> bool:
    """分片：同群短时仅首次占位成功。"""
    now = time.time()
    ttl = max(0.1, float(ttl_sec))
    ok = False

    def claim(data: dict[str, Any]) -> None:
        nonlocal ok
        until = float(data.get("until") or 0)
        if now < until:
            ok = False
            return
        data.update({"plugin": plugin, "group_id": int(group_id), "until": now + ttl, "kind": "broadcast"})
        ok = True

    result = _mutate_gate("broadcast", plugin, group_id, claim)
    if result is None:
        data = read_json_sync(_gate_key("broadcast", plugin, group_id))
        until = float((data or {}).get("until") or 0)
        return until <= now
    return ok


def try_begin_owned_gate_sync(plugin: str, group_id: int, bot_id: int, *, gate_sec: float) -> bool:
    """分片：窗口内仅 owner bot 可通过。"""
    now = time.time()
    ttl = max(1.0, float(gate_sec))
    ok = False

    def claim(data: dict[str, Any]) -> None:
        nonlocal ok
        until = float(data.get("until") or 0)
        owner = int(data.get("owner_bot_id") or 0)
        if now < until:
            ok = owner == int(bot_id)
            return
        data.update({
            "plugin": plugin,
            "group_id": int(group_id),
            "owner_bot_id": int(bot_id),
            "until": now + ttl,
            "kind": "owned",
        })
        ok = True

    result = _mutate_gate("owned", plugin, group_id, claim)
    if result is None:
        data = read_json_sync(_gate_key("owned", plugin, group_id))
        if not data:
            return False
        until = float(data.get("until") or 0)
        if now >= until:
            return True
        return int(data.get("owner_bot_id") or 0) == int(bot_id)
    return ok


def bind_owned_gate_sync(plugin: str, group_id: int, bot_id: int, *, gate_sec: float) -> None:
    """强制绑定主持牛。"""
    now = time.time()
    ttl = max(1.0, float(gate_sec))

    def stamp(data: dict[str, Any]) -> None:
        data.update({
            "plugin": plugin,
            "group_id": int(group_id),
            "owner_bot_id": int(bot_id),
            "until": now + ttl,
            "kind": "owned",
        })

    _mutate_gate("owned", plugin, group_id, stamp)


def read_owned_gate_bot_id_sync(plugin: str, group_id: int) -> int | None:
    """未过期 owned gate 的主持牛 QQ；无占位或已过期时返回 None。"""
    data = read_json_sync(_gate_key("owned", plugin, int(group_id)))
    if not data:
        return None
    until = float(data.get("until") or 0)
    if time.time() >= until:
        return None
    owner = int(data.get("owner_bot_id") or 0)
    return owner or None


def is_owned_gate_holder_sync(plugin: str, group_id: int, bot_id: int) -> bool:
    """是否当前主持牛；无占位或已过期时任意 bot 均可。"""
    data = read_json_sync(_gate_key("owned", plugin, group_id))
    if not data:
        return True
    until = float(data.get("until") or 0)
    if time.time() >= until:
        return True
    return int(data.get("owner_bot_id") or 0) == int(bot_id)


def release_owned_gate_sync(plugin: str, group_id: int) -> None:
    """释放群级 owned gate。"""
    from src.platform.shard.coord.coord_redis_store import delete_key_sync

    delete_key_sync(_gate_key("owned", plugin, int(group_id)))
