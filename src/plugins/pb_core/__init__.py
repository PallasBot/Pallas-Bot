from nonebot.plugin import PluginMetadata

from src.features.cmd_perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)
from src.features.cmd_perm.metadata_text import SCENE_BOTH, join_usage, usage_line
from src.features.plugin_sdk import (
    bind_alias_handlers,
    command_limit_list,
    command_limit_row,
    command_perm_list,
    command_perm_row,
    message_command,
)

from .handlers import (
    handle_console,
    handle_plugins,
    handle_restart,
    handle_status,
    handle_update_check,
)

__plugin_meta__ = PluginMetadata(
    name="牛牛核心",
    description="进程状态、控制台入口、插件概览与本体更新检查。",
    usage=join_usage(
        usage_line("牛牛状态", "查看版本、分片与连接摘要"),
        usage_line("牛牛控制台", "回显 WebUI 地址"),
        usage_line("牛牛插件", "已加载 core/extra 插件概览"),
        usage_line("牛牛更新", "检查本体 release 是否有更新"),
        usage_line("牛牛重启", "调度优雅重启"),
    ),
    type="application",
    homepage=PLUGIN_HOMEPAGE,
    supported_adapters={"~onebot.v11"},
    extra={
        "version": PLUGIN_EXTRA_VERSION,
        "menu_template": PLUGIN_MENU_TEMPLATE,
        "command_permissions": command_perm_list(
            command_perm_row("pb_core.status", "牛牛状态", "staff"),
            command_perm_row("pb_core.console", "牛牛控制台", "staff"),
            command_perm_row("pb_core.plugins", "牛牛插件", "staff"),
            command_perm_row("pb_core.update_check", "牛牛更新", "superuser"),
            command_perm_row("pb_core.restart", "牛牛重启", "superuser"),
        ),
        "command_limits": command_limit_list(
            command_limit_row("pb_core.status", 10),
            command_limit_row("pb_core.console", 10),
            command_limit_row("pb_core.plugins", 15),
            command_limit_row("pb_core.update_check", 60),
            command_limit_row("pb_core.restart", 120),
        ),
        "menu_data": [
            {
                "func": "牛牛状态",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_BOTH,
                "trigger_condition": "牛牛状态",
                "command_permission": "pb_core.status",
                "brief_des": "进程与分片摘要",
                "detail_des": "版本、Git、分片角色、编排脚本与本进程已连接牛牛。",
            },
            {
                "func": "牛牛控制台",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_BOTH,
                "trigger_condition": "牛牛控制台",
                "command_permission": "pb_core.console",
                "brief_des": "WebUI 地址",
                "detail_des": "回显控制台 URL；完整管理仍建议在浏览器打开 WebUI。",
            },
            {
                "func": "牛牛插件",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_BOTH,
                "trigger_condition": "牛牛插件",
                "command_permission": "pb_core.plugins",
                "brief_des": "插件加载概览",
                "detail_des": "列出已加载 core/extra 插件与扩展包提示。",
            },
            {
                "func": "牛牛更新",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_BOTH,
                "trigger_condition": "牛牛更新",
                "command_permission": "pb_core.update_check",
                "brief_des": "检查本体 release",
                "detail_des": "只读对比 GitHub 最新发布；应用更新请用 WebUI 或 pallas update bot。",
            },
            {
                "func": "牛牛重启",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_BOTH,
                "trigger_condition": "牛牛重启",
                "command_permission": "pb_core.restart",
                "brief_des": "调度优雅重启",
                "detail_des": "约 3 秒后按当前 unified/分片编排重启；需环境存在 run_*_bot.sh。",
            },
        ],
    },
)

status_cmd = message_command("pb_core.status", "牛牛状态", cd_sec=10)
console_cmd = message_command("pb_core.console", "牛牛控制台", cd_sec=10)
plugins_cmd = message_command("pb_core.plugins", "牛牛插件", cd_sec=15)
update_cmd = message_command("pb_core.update_check", "牛牛更新", cd_sec=60)
restart_cmd = message_command("pb_core.restart", "牛牛重启", cd_sec=120)

bind_alias_handlers(status_cmd, handle_status)
bind_alias_handlers(console_cmd, handle_console)
bind_alias_handlers(plugins_cmd, handle_plugins)
bind_alias_handlers(update_cmd, handle_update_check)
bind_alias_handlers(restart_cmd, handle_restart)
