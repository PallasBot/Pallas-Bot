from nonebot.plugin import PluginMetadata

from pallas.api.commands import (
    bind_alias_handlers,
    command_limit_list,
    command_limit_row,
    command_perm_list,
    command_perm_row,
    message_command,
)
from pallas.api.metadata import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
    SCENE_BOTH,
    SCENE_PRIVATE,
    join_usage,
    usage_line,
)

from . import config as _config  # noqa: F401
from . import startup as _startup  # noqa: F401
from .handlers import (
    handle_add_bot_admin,
    handle_console,
    handle_plugins,
    handle_restart,
    handle_status,
    handle_update_check,
)

__plugin_meta__ = PluginMetadata(
    name="牛牛核心",
    description="查看牛牛运行状态；另含控制台、更新与重启等管理入口。",
    usage=join_usage(
        usage_line("#pallas", "群内或私聊查看当前运行状态"),
    ),
    type="application",
    homepage=PLUGIN_HOMEPAGE,
    supported_adapters={"~onebot.v11"},
    extra={
        "help_tag": "core",
        "version": PLUGIN_EXTRA_VERSION,
        "menu_template": PLUGIN_MENU_TEMPLATE,
        "command_permissions": command_perm_list(
            command_perm_row("pb_core.status", "运行状态", "bot_moderator"),
            command_perm_row("pb_core.console", "牛牛控制台", "superuser"),
            command_perm_row("pb_core.plugins", "牛牛插件", "superuser"),
            command_perm_row("pb_core.update_check", "牛牛更新", "superuser"),
            command_perm_row("pb_core.restart", "牛牛重启", "superuser"),
            command_perm_row("pb_core.add_bot_admin", "牛牛添加号主", "superuser"),
        ),
        "command_limits": command_limit_list(
            command_limit_row("pb_core.status", 10),
            command_limit_row("pb_core.console", 10),
            command_limit_row("pb_core.plugins", 15),
            command_limit_row("pb_core.update_check", 60),
            command_limit_row("pb_core.restart", 120),
            command_limit_row("pb_core.add_bot_admin", 30),
        ),
        "menu_data": [
            {
                "func": "运行状态",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_BOTH,
                "trigger_condition": "#pallas",
                "command_permission": "pb_core.status",
                "brief_des": "群内/私聊发 #pallas，查看进程与分片信息",
                "detail_des": (
                    "群内或私聊发送 #pallas。"
                    "会返回当前牛 QQ、运行时长，以及分片环境下的协调信息，方便排查是否正常在线。"
                ),
            },
            {
                "func": "牛牛控制台",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_BOTH,
                "trigger_condition": "牛牛控制台",
                "help_audience": "superuser",
                "command_permission": "pb_core.console",
                "brief_des": "返回网页管理入口地址",
                "detail_des": "发送「牛牛控制台」，直接拿到网页管理入口，方便打开后继续操作。",
            },
            {
                "func": "牛牛插件",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_BOTH,
                "trigger_condition": "牛牛插件",
                "help_audience": "superuser",
                "command_permission": "pb_core.plugins",
                "brief_des": "列出当前进程已加载插件",
                "detail_des": "发送「牛牛插件」，看看这只牛现在加载了哪些插件和功能。",
            },
            {
                "func": "牛牛更新",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_PRIVATE,
                "trigger_condition": "牛牛更新",
                "help_audience": "superuser",
                "command_permission": "pb_core.update_check",
                "brief_des": "检查 / 应用更新；可开关自动更新与汇报",
                "detail_des": (
                    "仅超管私聊。发「牛牛更新」检查；"
                    "「应用」或 bot/webui/插件 应用更新；"
                    "「自动 … 开|关」「汇报 开|关」「汇报号 QQ」改配置。"
                    "完整用法发「牛牛更新 帮助」。"
                ),
            },
            {
                "func": "牛牛重启",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_BOTH,
                "trigger_condition": "牛牛重启",
                "help_audience": "superuser",
                "command_permission": "pb_core.restart",
                "brief_des": "安排重启；连上后会私聊通知你",
                "detail_des": ("发送「牛牛重启」。在当前环境支持时安排重新启动；接收命令的牛重新连上后会私聊通知你。"),
            },
            {
                "func": "牛牛添加号主",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_PRIVATE,
                "trigger_condition": "牛牛添加号主",
                "help_audience": "superuser",
                "command_permission": "pb_core.add_bot_admin",
                "brief_des": "牛牛添加号主 号主QQ… [牛 目标牛QQ]",
                "detail_des": (
                    "仅超管私聊。例：「牛牛添加号主 123456」把 QQ 加为当前私聊牛的号主；"
                    "可一次多个号主 QQ；要配置别的牛时用「牛 目标牛QQ」，会自动写入/合并其 bot_config。"
                    "也可 @ 号主。"
                ),
            },
        ],
    },
)

status_cmd = message_command("pb_core.status", "#pallas", cd_sec=10)
console_cmd = message_command("pb_core.console", "牛牛控制台", cd_sec=10)
plugins_cmd = message_command("pb_core.plugins", "牛牛插件", cd_sec=15)
update_cmd = message_command("pb_core.update_check", "牛牛更新", cd_sec=60, scene="private")
restart_cmd = message_command("pb_core.restart", "牛牛重启", cd_sec=120)
add_bot_admin_cmd = message_command("pb_core.add_bot_admin", "牛牛添加号主", cd_sec=30, scene="private")

bind_alias_handlers(status_cmd, handle_status)
bind_alias_handlers(console_cmd, handle_console)
bind_alias_handlers(plugins_cmd, handle_plugins)
bind_alias_handlers(update_cmd, handle_update_check)
bind_alias_handlers(restart_cmd, handle_restart)
bind_alias_handlers(add_bot_admin_cmd, handle_add_bot_admin)
