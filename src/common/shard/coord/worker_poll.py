"""分片 worker：统一轮询 coord 目录（QTE、代发动作等）。"""

from __future__ import annotations

import asyncio

from nonebot import logger

from src.common.shard.registry.config import get_shard_registry_settings, is_sharding_active

_WATCH_SEC = 0.12
_started = False


async def shard_coord_worker_poll_loop() -> None:
    from nonebot import get_bots

    from src.common.shard.coord.bot_action import poll_bot_action_pending, prune_stale_bot_action_files
    from src.common.shard.coord.cage_duel import prune_stale_cage_duel_files
    from src.common.shard.coord.duel_qte import poll_duel_qte_pending, prune_stale_duel_qte_files
    from src.common.shard.coord.maa_seen_registry import prune_stale_maa_seen_files

    while True:
        try:
            if is_sharding_active():
                local_ids = frozenset(get_bots().keys())
                if local_ids:
                    await poll_duel_qte_pending(local_ids)
                    await poll_bot_action_pending(local_ids)
                await prune_stale_duel_qte_files()
                await prune_stale_bot_action_files()
                await prune_stale_cage_duel_files()
                await prune_stale_maa_seen_files()
        except Exception as err:
            logger.debug(f"shard_coord worker poll: {err}")
        await asyncio.sleep(_WATCH_SEC)


def start_shard_coord_worker_watcher() -> None:
    global _started
    if _started or not is_sharding_active():
        return
    if get_shard_registry_settings().role != "worker":
        return
    _started = True
    asyncio.create_task(shard_coord_worker_poll_loop())


def start_duel_qte_coord_watcher() -> None:
    """兼容旧入口。"""
    start_shard_coord_worker_watcher()
