"""多进程分片注册表：5 牛/进程，协议端 / WebUI / relogin 走 hub，牛牛走 worker。"""

from pallas.core.platform.shard.registry.config import ShardRegistrySettings, get_shard_registry_settings
from pallas.core.platform.shard.registry.store import (
    ShardRegistry,
    TestShardConfig,
    assign_bot_to_shard,
    assign_bot_to_test_shard,
    clear_shard_registry_cache,
    get_shard_registry,
    get_test_config,
    get_test_shard_id,
    init_test_shard,
    list_test_shard_bots,
    rebalance_hint,
    remove_bot_from_test_shard,
    resolve_onebot_ws_url_for_bot,
    resolve_test_port,
    worker_port_for_shard,
)

__all__ = [
    "ShardRegistry",
    "ShardRegistrySettings",
    "TestShardConfig",
    "assign_bot_to_shard",
    "assign_bot_to_test_shard",
    "clear_shard_registry_cache",
    "get_shard_registry",
    "get_shard_registry_settings",
    "get_test_config",
    "init_test_shard",
    "list_test_shard_bots",
    "rebalance_hint",
    "remove_bot_from_test_shard",
    "resolve_onebot_ws_url_for_bot",
    "resolve_test_port",
    "get_test_shard_id",
    "worker_port_for_shard",
]
