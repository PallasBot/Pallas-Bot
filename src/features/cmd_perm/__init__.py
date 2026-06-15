"""插件命令可配置权限。"""

from .check import (
    group_message_permission_for_command,
    group_or_private_message_permission_for_command,
    permission_for_command,
    private_message_permission_for_command,
    satisfies_command_permission,
)
from .config import CmdPermConfig, clear_cmd_perm_cache, get_cmd_perm_config
from .declare import command_perm_list, command_perm_row
from .help_menu import help_say_phrase, help_scene_text, is_user_help_menu_item, iter_user_help_menu
from .menu_display import (
    effective_permission_avail_text,
    raw_trigger_condition,
    trigger_condition_with_effective_perm,
)
from .registry import DEFAULT_COMMAND_PERMISSIONS, VALID_LEVELS, normalize_level, resolved_level

__all__ = [
    "command_perm_list",
    "command_perm_row",
    "CmdPermConfig",
    "DEFAULT_COMMAND_PERMISSIONS",
    "VALID_LEVELS",
    "clear_cmd_perm_cache",
    "get_cmd_perm_config",
    "group_message_permission_for_command",
    "group_or_private_message_permission_for_command",
    "normalize_level",
    "permission_for_command",
    "private_message_permission_for_command",
    "resolved_level",
    "satisfies_command_permission",
    "effective_permission_avail_text",
    "help_say_phrase",
    "help_scene_text",
    "is_user_help_menu_item",
    "iter_user_help_menu",
    "raw_trigger_condition",
    "trigger_condition_with_effective_perm",
]
