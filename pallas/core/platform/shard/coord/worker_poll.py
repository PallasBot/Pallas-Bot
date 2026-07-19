"""分片 worker：启动 coord Redis 监听器。"""

from __future__ import annotations

from pallas.core.platform.shard import context as shard_ctx
from pallas.core.platform.shard.coord.listeners import coord_listener_starters
from pallas.core.platform.shard.registry.config import get_shard_registry_settings

_started = False


def start_shard_coord_worker_watcher() -> None:
    global _started
    if _started or not shard_ctx.sharding_active():
        return
    if get_shard_registry_settings().role != "worker":
        return
    _started = True
    for start in coord_listener_starters():
        start()


def start_duel_qte_coord_watcher() -> None:
    """兼容旧入口。"""
    start_shard_coord_worker_watcher()
