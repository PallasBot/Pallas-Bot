"""分片 worker：启动 coord Redis 监听器（无文件轮询）。"""

from __future__ import annotations

from src.platform.shard.registry.config import get_shard_registry_settings, is_sharding_active

_started = False


def start_shard_coord_worker_watcher() -> None:
    global _started
    if _started or not is_sharding_active():
        return
    if get_shard_registry_settings().role != "worker":
        return
    from src.platform.shard.coord.bot_action import start_bot_action_redis_listener
    from src.platform.shard.coord.dream_drift import start_dream_drift_redis_listener
    from src.platform.shard.coord.duel_qte_redis import start_duel_qte_redis_listeners
    from src.platform.shard.coord.repeater_buffer import start_repeater_buffer_redis_listener
    from src.platform.shard.coord.repeater_reply_buffer import start_repeater_reply_buffer_redis_listener

    _started = True
    start_repeater_buffer_redis_listener()
    start_repeater_reply_buffer_redis_listener()
    start_dream_drift_redis_listener()
    start_duel_qte_redis_listeners()
    start_bot_action_redis_listener()


def start_duel_qte_coord_watcher() -> None:
    """兼容旧入口。"""
    start_shard_coord_worker_watcher()
