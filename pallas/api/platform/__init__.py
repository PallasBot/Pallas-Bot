"""平台级协作钩子：多 Bot 去重/舰队、分片在线态、AI callback 注册、Bot 角色与发送。

仅官方/内置插件使用；社区插件一般不依赖此模块。
"""

# ── AI callback ──
from pallas.core.platform.ai_callback.media_task_hooks import register_media_task_hooks
from pallas.core.platform.ai_callback.task_types import DRAW_IMAGE_TASK_TYPE

# ── Bot 角色 ──
from pallas.core.platform.bot_runtime.roles import (
    bot_role,
    is_hub_role,
    is_sharded_hub,
    is_sharded_worker,
    is_sharding_active,
    is_unified_role,
)

# ── 发送不可用 ──
from pallas.core.platform.bot_runtime.send_unavailable import (
    is_bot_send_unavailable,
    log_bot_send_unavailable,
)

# ── 消息入口策略 ──
from pallas.core.platform.ingress.dream_host_gate import (
    DREAM_HOST_GATE_PLUGIN,
    dream_session_ingress_passes,
)
from pallas.core.platform.ingress.policy_registry import text_matches_plugin_fanout

# ── 多 Bot 去重与舰队 ──
from pallas.core.platform.multi_bot.at_targets import message_at_fleet_bot
from pallas.core.platform.multi_bot.bot_filter import is_fleet_bot_qq
from pallas.core.platform.multi_bot.connected_roster import connected_bot_ids
from pallas.core.platform.multi_bot.dedup import (
    begin_group_exclusive_activity,
    bind_group_owned_gate,
    bind_group_owned_gate_sync,
    claim_group_handler,
    claim_group_message_event,
    is_group_owned_gate_holder,
    needs_group_host_bot_gate,
    normalize_message_time,
    release_group_owned_gate_sync,
    try_acquire_group_broadcast_slot,
    try_begin_group_owned_gate,
    try_claim_group_message_once,
)
from pallas.core.platform.multi_bot.fleet import (
    get_catalog_bot_ids,
    get_fleet_bot_ids,
    invalidate_fleet_bot_cache,
)
from pallas.core.platform.multi_bot.group_fleet_probe import (
    list_local_fleet_bots_in_group,
    register_fleet_probe,
)
from pallas.core.platform.multi_bot.group_online_cache import (
    GROUP_ONLINE_TTL_SEC,
    NS_FLEET,
    NS_LOCAL_CONNECTED,
    clear_group_online_cache,
    get_cached_group_bot_ids,
    resolve_local_connected_bots_in_group,
    store_cached_group_bot_ids,
)
from pallas.core.platform.multi_bot.session_seen import get_session_seen_bot_ids

# ── 插件子模块解析 ──
from pallas.core.platform.plugin_runtime.resolve import import_plugin_submodule

# ── 分片上下文 ──
from pallas.core.platform.shard.context import (
    is_local_representative,
    local_representative_bot_id,
    sharding_active,
)

# ── 跨分片 Bot 操作 ──
from pallas.core.platform.shard.coord.bot_action import (
    get_member_card_as_bot,
    invoke_bot_action,
    send_group_message_as_bot,
    send_private_msg_as_bot,
    set_group_card_as_bot,
)
from pallas.core.platform.shard.coord.bot_count import (
    STAGGER_SEC,
    run_shard_coordinated_bot_count,
    update_shard_bot_count_registration,
)

# ── 分片在线态 ──
from pallas.core.platform.shard.presence import (
    bot_has_local_connection,
    close_local_bot_connection,
    get_cluster_online_bot_ids,
    mark_protocol_bot_offline,
    pick_local_query_bot,
)

# ── 跨插件共享常量 ──
from pallas.core.shared.dream_ban_ack_state import DREAM_BAN_ACK_SENT_STATE_KEY

# ── 产品域 (LLM) ──
from pallas.product.llm.config import get_llm_config, llm_server_base_url
from pallas.product.llm.tools.declare import llm_command_tool_row

__all__ = [
    # AI callback
    "DRAW_IMAGE_TASK_TYPE",
    "register_media_task_hooks",
    # Bot 角色
    "bot_role",
    "is_hub_role",
    "is_sharded_hub",
    "is_sharded_worker",
    "is_sharding_active",
    "is_unified_role",
    # 发送不可用
    "is_bot_send_unavailable",
    "log_bot_send_unavailable",
    # 消息入口
    "DREAM_HOST_GATE_PLUGIN",
    "dream_session_ingress_passes",
    "text_matches_plugin_fanout",
    # 多 Bot 舰队
    "begin_group_exclusive_activity",
    "bind_group_owned_gate",
    "bind_group_owned_gate_sync",
    "claim_group_handler",
    "claim_group_message_event",
    "connected_bot_ids",
    "get_catalog_bot_ids",
    "get_fleet_bot_ids",
    "get_session_seen_bot_ids",
    "invalidate_fleet_bot_cache",
    "is_fleet_bot_qq",
    "is_group_owned_gate_holder",
    "list_local_fleet_bots_in_group",
    "message_at_fleet_bot",
    "needs_group_host_bot_gate",
    "normalize_message_time",
    "register_fleet_probe",
    "release_group_owned_gate_sync",
    "try_acquire_group_broadcast_slot",
    "try_begin_group_owned_gate",
    "try_claim_group_message_once",
    # 群在线态缓存
    "GROUP_ONLINE_TTL_SEC",
    "NS_FLEET",
    "NS_LOCAL_CONNECTED",
    "clear_group_online_cache",
    "get_cached_group_bot_ids",
    "resolve_local_connected_bots_in_group",
    "store_cached_group_bot_ids",
    # 分片在线态
    "bot_has_local_connection",
    "close_local_bot_connection",
    "get_cluster_online_bot_ids",
    "mark_protocol_bot_offline",
    "pick_local_query_bot",
    # 分片上下文
    "is_local_representative",
    "local_representative_bot_id",
    "sharding_active",
    # 跨分片 Bot 操作
    "get_member_card_as_bot",
    "invoke_bot_action",
    "send_group_message_as_bot",
    "send_private_msg_as_bot",
    "set_group_card_as_bot",
    "STAGGER_SEC",
    "run_shard_coordinated_bot_count",
    "update_shard_bot_count_registration",
    # 插件子模块
    "import_plugin_submodule",
    # LLM
    "get_llm_config",
    "llm_command_tool_row",
    "llm_server_base_url",
    # 跨插件常量
    "DREAM_BAN_ACK_SENT_STATE_KEY",
]
