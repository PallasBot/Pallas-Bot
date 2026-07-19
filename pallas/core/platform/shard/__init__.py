"""分片运行时：注册表、协调、在线态、日志与数据同步。"""

from pallas.core.platform.shard.context import (
    is_local_representative,
    local_representative_bot_id,
    sharding_active,
)
from pallas.core.platform.shard.coord import (
    is_shard_bot_count_command_plaintext,
    publish_single_qte_request,
    run_shard_coordinated_bot_count,
    schedule_cross_shard_single_qte,
    single_qte_session_id,
    start_duel_qte_coord_watcher,
)
from pallas.core.platform.shard.logs.process import install_shard_process_logging
from pallas.core.platform.shard.registry import (
    ShardRegistry,
    ShardRegistrySettings,
    assign_bot_to_shard,
    clear_shard_registry_cache,
    get_shard_registry,
    get_shard_registry_settings,
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
    "is_local_representative",
    "local_representative_bot_id",
    "sharding_active",
    "install_shard_process_logging",
    "is_shard_bot_count_command_plaintext",
    "publish_single_qte_request",
    "rebalance_hint",
    "resolve_onebot_ws_url_for_bot",
    "run_shard_coordinated_bot_count",
    "schedule_cross_shard_single_qte",
    "single_qte_session_id",
    "start_duel_qte_coord_watcher",
    "worker_port_for_shard",
]
