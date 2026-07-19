"""插件命令可配置权限。"""

from .acl import (
    ACL_TARGET_ANY,
    ACL_TARGET_GROUP_BAN,
    AclDecision,
    AclSubject,
    acl_admin_bypass,
    clear_acl_cache,
    evaluate_acl,
    group_block_target,
)
from .check import (
    group_message_permission_for_command,
    group_or_private_message_permission_for_command,
    permission_for_command,
    private_message_permission_for_command,
    satisfies_command_permission,
)
from .config import CmdPermConfig, clear_cmd_perm_cache, get_cmd_perm_config
from .declare import command_perm_list, command_perm_row
from .help_menu import (
    help_say_phrase,
    help_scene_text,
    is_user_help_menu_item,
    is_user_help_plugin,
    iter_plugin_detail_menu,
    iter_user_help_menu,
)
from .menu_display import (
    effective_permission_avail_text,
    raw_trigger_condition,
    trigger_condition_with_effective_perm,
)
from .migration import (
    derive_acl_from_legacy,
    migrate_bot_admins_to_admin_members_once,
    run_acl_startup_migrations,
)
from .registry import DEFAULT_COMMAND_PERMISSIONS, VALID_LEVELS, normalize_level, resolved_level
from .runtime_meta import get_command_permission_meta

__all__ = [
    "ACL_TARGET_ANY",
    "ACL_TARGET_GROUP_BAN",
    "AclDecision",
    "AclSubject",
    "acl_admin_bypass",
    "clear_acl_cache",
    "command_perm_list",
    "command_perm_row",
    "CmdPermConfig",
    "DEFAULT_COMMAND_PERMISSIONS",
    "VALID_LEVELS",
    "clear_cmd_perm_cache",
    "derive_acl_from_legacy",
    "evaluate_acl",
    "get_cmd_perm_config",
    "get_command_permission_meta",
    "group_block_target",
    "group_message_permission_for_command",
    "group_or_private_message_permission_for_command",
    "migrate_bot_admins_to_admin_members_once",
    "normalize_level",
    "permission_for_command",
    "private_message_permission_for_command",
    "resolved_level",
    "run_acl_startup_migrations",
    "satisfies_command_permission",
    "effective_permission_avail_text",
    "help_say_phrase",
    "help_scene_text",
    "is_user_help_menu_item",
    "is_user_help_plugin",
    "iter_plugin_detail_menu",
    "iter_user_help_menu",
    "raw_trigger_condition",
    "trigger_condition_with_effective_perm",
]
