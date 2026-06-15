"""分片 worker：启动 coord Redis 监听器。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.platform.shard.registry.config import get_shard_registry_settings, is_sharding_active

if TYPE_CHECKING:
    from collections.abc import Callable

_started = False


def coord_listener_starters() -> tuple[Callable[[], None], ...]:
    """各 coord 模块注册的 listener 启动函数。"""
    from src.platform.shard.coord.bot_action import start_bot_action_redis_listener
    from src.platform.shard.coord.dream_drift import start_dream_drift_redis_listener
    from src.platform.shard.coord.duel_qte_redis import start_duel_qte_redis_listeners
    from src.platform.shard.coord.repeater_buffer import start_repeater_buffer_redis_listener
    from src.platform.shard.coord.repeater_reply_buffer import start_repeater_reply_buffer_redis_listener

    return (
        start_repeater_buffer_redis_listener,
        start_repeater_reply_buffer_redis_listener,
        start_dream_drift_redis_listener,
        start_duel_qte_redis_listeners,
        start_bot_action_redis_listener,
    )


def start_shard_coord_worker_watcher() -> None:
    global _started
    if _started or not is_sharding_active():
        return
    if get_shard_registry_settings().role != "worker":
        return
    _started = True
    for start in coord_listener_starters():
        start()


def start_duel_qte_coord_watcher() -> None:
    """兼容旧入口。"""
    start_shard_coord_worker_watcher()
