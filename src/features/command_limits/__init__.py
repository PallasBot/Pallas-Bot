"""插件命令冷却（CD）统一 helper。"""

from .config import CommandLimitsConfig, clear_command_limits_cache, get_command_limits_config
from .cooldown import (
    command_limit_action_key,
    config_for_message_event,
    get_command_cooldown_sec,
    is_command_cooldown_ready,
    refresh_command_cooldown,
)
from .metadata import (
    CommandLimitDecl,
    command_limit_for_id,
    command_limits_from_metadata,
    parse_command_limit_decl,
)
from .schema import (
    build_command_limits_ui,
    clear_merged_command_limits_cache,
    effective_command_limit_for,
    merged_default_command_limits,
)

__all__ = [
    "CommandLimitDecl",
    "CommandLimitsConfig",
    "build_command_limits_ui",
    "clear_command_limits_cache",
    "clear_merged_command_limits_cache",
    "command_limit_action_key",
    "command_limit_for_id",
    "command_limits_from_metadata",
    "config_for_message_event",
    "effective_command_limit_for",
    "get_command_cooldown_sec",
    "get_command_limits_config",
    "is_command_cooldown_ready",
    "merged_default_command_limits",
    "parse_command_limit_decl",
    "refresh_command_cooldown",
]
