from nonebot.plugin import PluginMetadata

from pallas.core.commands import command_limit_list, command_limit_row, command_perm_list, command_perm_row
from pallas.core.perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)
from pallas.core.perm.metadata_text import SCENE_BOTH, join_usage, usage_line

from . import commands as _commands  # noqa: F401
from . import gate_block as _gate_block  # noqa: F401
from .ban_gate import (
    apply_group_banned_change,
    apply_group_blocked_users_change,
    apply_user_banned_change,
    invalidate_group_ban_gate_cache,
    invalidate_user_ban_gate_cache,
    query_user_ban_status_for_gate,
    reset_group_ban_gate_cache,
    reset_user_ban_gate_cache,
)
from .commands import (
    blacklist_add_cmd,
    blacklist_add_group_cmd,
    blacklist_list_cmd,
    blacklist_remove_cmd,
    blacklist_remove_group_cmd,
    handle_blacklist_add,
    handle_blacklist_add_group,
    handle_blacklist_list,
    handle_blacklist_remove,
    handle_blacklist_remove_group,
)
from .gate_block import block_globally_banned_users
from .helpers import (
    build_blacklist_view_message,
    can_manage_blacklist,
    collect_target_qqs_from_plain_and_message,
    event_actor_user_id,
    format_id_list,
)

__plugin_meta__ = PluginMetadata(
    name="牛牛黑名单",
    description="屏蔽指定用户或群，不再响应他们的消息。",
    usage=join_usage(
        usage_line("牛牛拉黑 / 牛牛屏蔽 + QQ 或 @", "私聊为全局用户，群内仅本群"),
        usage_line("牛牛拉黑群 / 牛牛屏蔽群 + 群号", "私聊须写群号；群内可省略为本群"),
        usage_line("牛牛解禁 / 牛牛取消拉黑 + 目标", "解除用户拉黑"),
        usage_line("牛牛解禁群 / 牛牛取消拉黑群 + 群号", "解除群拉黑"),
        usage_line("牛牛黑名单 / 牛牛查看黑名单", "查看全局或本群拉黑名单"),
    ),
    type="application",
    homepage=PLUGIN_HOMEPAGE,
    supported_adapters={"~onebot.v11"},
    extra={
        "version": PLUGIN_EXTRA_VERSION,
        "menu_template": PLUGIN_MENU_TEMPLATE,
        "reload_policy": "metadata",
        "command_permissions": command_perm_list(
            command_perm_row("blacklist.add", "牛牛拉黑 / 牛牛屏蔽 / 牛牛拉黑群", "staff"),
            command_perm_row("blacklist.remove", "牛牛解禁 / 牛牛解禁群", "staff"),
            command_perm_row("blacklist.list", "牛牛黑名单 / 牛牛查看黑名单", "staff"),
        ),
        "command_limits": command_limit_list(
            command_limit_row("blacklist.add", 3),
            command_limit_row("blacklist.remove", 3),
            command_limit_row("blacklist.list", 3),
        ),
        "menu_data": [
            {
                "func": "查看名单",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_BOTH,
                "trigger_condition": "牛牛黑名单 / 牛牛查看黑名单",
                "command_permission": "blacklist.list",
                "brief_des": "查看拉黑名单",
                "detail_des": "私聊看全局名单，群里看本群已经屏蔽了谁。",
            },
            {
                "func": "拉黑与解禁",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_BOTH,
                "trigger_condition": "牛牛拉黑 / 牛牛屏蔽 / 牛牛解禁 + QQ 或 @",
                "command_permissions": ["blacklist.add", "blacklist.remove"],
                "brief_des": "屏蔽用户消息",
                "detail_des": "可写 QQ 或 @ 用户；私聊时作用更广，群里时只影响当前群。",
            },
            {
                "func": "群拉黑与解禁",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_BOTH,
                "trigger_condition": "牛牛拉黑群 / 牛牛屏蔽群 / 牛牛解禁群 + 群号",
                "command_permissions": ["blacklist.add", "blacklist.remove"],
                "brief_des": "屏蔽整群消息",
                "detail_des": "可按群号屏蔽或恢复某个群；在群里可直接作用当前群。",
            },
            {
                "func": "事件门禁",
                "trigger_method": "event_preprocessor",
                "help_audience": "superuser",
                "trigger_condition": "被拉黑用户的消息与通知",
                "brief_des": "自动拦截",
                "detail_des": "超管向说明；用户只需使用拉黑/解禁命令。",
            },
        ],
    },
)

__all__ = [
    "apply_group_banned_change",
    "apply_group_blocked_users_change",
    "apply_user_banned_change",
    "blacklist_add_cmd",
    "blacklist_add_group_cmd",
    "blacklist_list_cmd",
    "blacklist_remove_cmd",
    "blacklist_remove_group_cmd",
    "block_globally_banned_users",
    "build_blacklist_view_message",
    "can_manage_blacklist",
    "collect_target_qqs_from_plain_and_message",
    "event_actor_user_id",
    "format_id_list",
    "handle_blacklist_add",
    "handle_blacklist_add_group",
    "handle_blacklist_list",
    "handle_blacklist_remove",
    "handle_blacklist_remove_group",
    "invalidate_group_ban_gate_cache",
    "invalidate_user_ban_gate_cache",
    "query_user_ban_status_for_gate",
    "reset_group_ban_gate_cache",
    "reset_user_ban_gate_cache",
]
