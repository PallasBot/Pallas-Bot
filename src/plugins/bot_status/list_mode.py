"""牛牛在吗：名册与在线判定模式（session / fleet / connected / auto）。"""

from __future__ import annotations

from typing import Literal

from nonebot import get_bots

from src.common.multi_bot.fleet import get_fleet_bot_ids
from src.common.multi_bot.session_seen import get_session_seen_bot_ids
from src.common.shard.registry.config import is_sharding_active

from .config import get_bot_status_config

StatusListMode = Literal["session", "fleet", "connected"]
ResolvedListMode = StatusListMode


def resolve_status_list_mode() -> ResolvedListMode:
    raw = (get_bot_status_config().bot_status_list_mode or "auto").strip().lower()
    if raw == "auto":
        return "fleet" if is_sharding_active() else "session"
    if raw in ("session", "fleet", "connected"):
        return raw  # type: ignore[return-value]
    return "fleet" if is_sharding_active() else "session"


def status_inventory_bot_ids(*, list_mode: ResolvedListMode | None = None) -> frozenset[int]:
    """名册 QQ：session=本进程；connected=曾连 WS；fleet=协议端 enabled（分片含 registry）。"""
    mode = list_mode or resolve_status_list_mode()
    if mode == "fleet":
        return get_fleet_bot_ids()
    if mode == "connected":
        return get_session_seen_bot_ids()
    try:
        from src.plugins.block import plugin_config as block_cfg

        ids = {int(x) for x in block_cfg.bots}
    except Exception:
        ids = set()
    if is_sharding_active():
        for key in get_bots():
            try:
                ids.add(int(key))
            except ValueError:
                continue
    return frozenset(ids)


def cluster_online_bot_ids_for_status(
    current_bots: dict | None = None,
    *,
    list_mode: ResolvedListMode | None = None,
) -> set[int]:
    """在线集合：分片 fleet/connected 用 presence；其余用本进程 get_bots。"""
    from nonebot import get_bots as nb_get_bots

    mode = list_mode or resolve_status_list_mode()
    bots = current_bots if current_bots is not None else nb_get_bots()
    if is_sharding_active() and mode in ("fleet", "connected"):
        from src.common.shard.presence import get_cluster_online_bot_ids

        return set(get_cluster_online_bot_ids())
    out: set[int] = set()
    for key in bots:
        try:
            out.add(int(key))
        except ValueError:
            continue
    return out
