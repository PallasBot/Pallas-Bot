"""多进程分片注册表：5 牛/进程，协议端 / WebUI / relogin 走 hub，牛牛走 worker。"""

from src.common.shard.registry.config import ShardRegistrySettings, get_shard_registry_settings
from src.common.shard.registry.store import (
    ShardRegistry,
    assign_bot_to_shard,
    clear_shard_registry_cache,
    get_shard_registry,
    rebalance_hint,
    resolve_onebot_ws_url_for_bot,
    worker_port_for_shard,
)

__all__ = [
    "ShardRegistry",
    "ShardRegistrySettings",
    "assign_bot_to_shard",
    "clear_shard_registry_cache",
    "get_shard_registry",
    "get_shard_registry_settings",
    "rebalance_hint",
    "resolve_onebot_ws_url_for_bot",
    "worker_port_for_shard",
]
