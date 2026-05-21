"""入站门控：配置、fast lane、群消息分片、Notice 采样。"""

from src.common.ingress.config import IngressConfig, clear_ingress_config_cache, get_ingress_config
from src.common.ingress.dispatch import (
    ingress_handle_event,
    install_ingress_event_dispatch,
    reload_ingress_dispatch_runtime,
    slow_dispatch_queue_capacity,
    slow_dispatch_worker_count,
    start_ingress_slow_dispatch_workers,
    stop_ingress_slow_dispatch_workers,
)
from src.common.ingress.duel_elect import ingress_duel_elected_bot_id, ingress_message_uses_duel_claim
from src.common.ingress.fast_lane import (
    acquire_slow_event_slot,
    clear_ingress_slow_path_runtime_state,
    ingress_fast_lane_enabled,
    is_command_like_plaintext,
    is_duel_ingress_priority_plaintext,
    is_fast_lane_event,
    release_slow_event_slot,
    should_apply_ingress_slow_path,
    should_repeater_skip_group_message,
    slow_event_overflow_held,
    slow_event_slot_held,
)
from src.common.ingress.gate import (
    ingress_group_message_fanout_all_bots,
    ingress_multi_bot_shard_enabled,
    should_this_bot_handle_group_message,
)
from src.common.ingress.matcher_priority import BACKGROUND, FAST_LANE, HIGH, LOW, NORMAL
from src.common.ingress.notice_gate import (
    classify_notice,
    ingress_notice_gate_enabled,
    notice_shard_key,
    should_sample_keep_notice,
    should_this_bot_handle_notice,
)

__all__ = [
    "BACKGROUND",
    "FAST_LANE",
    "HIGH",
    "LOW",
    "NORMAL",
    "IngressConfig",
    "acquire_slow_event_slot",
    "classify_notice",
    "clear_ingress_config_cache",
    "clear_ingress_slow_path_runtime_state",
    "get_ingress_config",
    "ingress_duel_elected_bot_id",
    "ingress_handle_event",
    "ingress_fast_lane_enabled",
    "install_ingress_event_dispatch",
    "ingress_group_message_fanout_all_bots",
    "ingress_message_uses_duel_claim",
    "ingress_multi_bot_shard_enabled",
    "ingress_notice_gate_enabled",
    "is_command_like_plaintext",
    "is_duel_ingress_priority_plaintext",
    "is_fast_lane_event",
    "should_apply_ingress_slow_path",
    "should_repeater_skip_group_message",
    "slow_dispatch_queue_capacity",
    "slow_dispatch_worker_count",
    "start_ingress_slow_dispatch_workers",
    "stop_ingress_slow_dispatch_workers",
    "notice_shard_key",
    "reload_ingress_dispatch_runtime",
    "release_slow_event_slot",
    "slow_event_overflow_held",
    "slow_event_slot_held",
    "should_sample_keep_notice",
    "should_this_bot_handle_group_message",
    "should_this_bot_handle_notice",
]
