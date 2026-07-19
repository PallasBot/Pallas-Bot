"""群内 fleet 牛探测；供复读 fanout、报数等复用，与决斗插件解耦。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pallas.core.plugin_coord._lazy import import_symbol_any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

_list_group_online_bot_ids: Callable[[int], Awaitable[list[int]]] | None = None
_list_local_fleet_bots_in_group: Callable[[int], Awaitable[list[int]]] | None = None


def register_fleet_probe(
    *,
    list_group_online_bot_ids: Callable[[int], Awaitable[list[int]]] | None = None,
    list_local_fleet_bots_in_group: Callable[[int], Awaitable[list[int]]] | None = None,
) -> None:
    g = globals()
    if list_group_online_bot_ids is not None:
        g["_list_group_online_bot_ids"] = list_group_online_bot_ids
    if list_local_fleet_bots_in_group is not None:
        g["_list_local_fleet_bots_in_group"] = list_local_fleet_bots_in_group


_DUEL_BOTS = ("pallas_plugin_duel.duel_bots", "packages.duel.duel_bots")


async def list_group_online_bot_ids(group_id: int) -> list[int]:
    if _list_group_online_bot_ids is not None:
        return list(await _list_group_online_bot_ids(group_id))
    fn = import_symbol_any(_DUEL_BOTS, "list_group_online_bot_ids")
    if fn is None:
        return []
    return list(await fn(group_id))


async def list_local_fleet_bots_in_group(group_id: int) -> list[int]:
    if _list_local_fleet_bots_in_group is not None:
        return list(await _list_local_fleet_bots_in_group(group_id))
    fn = import_symbol_any(_DUEL_BOTS, "list_local_fleet_bots_in_group")
    if fn is None:
        return []
    return list(await fn(group_id))
