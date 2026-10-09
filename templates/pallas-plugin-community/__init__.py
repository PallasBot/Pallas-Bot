from nonebot.plugin import PluginMetadata
from pallas.api.commands import bind_alias_handlers, group_command
from pallas.api.metadata import SCENE_GROUP, join_usage, usage_line

from .handlers import handle_ping

PLUGIN_ID = "example_plugin"

__plugin_meta__ = PluginMetadata(
    name="示例社区插件",
    description="社区插件模板，演示一条简单命令。",
    usage=join_usage(usage_line("ping", "回复 Pong。")),
    type="application",
    supported_adapters={"~onebot.v11"},
    extra={
        "version": "0.1.0",
        "command_permissions": [
            {"id": "example_plugin.ping", "label": "ping", "default": "everyone"},
        ],
        "command_limits": [{"id": "example_plugin.ping", "cd_sec": 3}],
        "menu_data": [
            {
                "func": "ping",
                "trigger_method": "命令",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "发送 ping",
                "brief_des": "回复 Pong。",
                "detail_des": "群内发送 ping。",
                "command_permission": "example_plugin.ping",
            },
        ],
        "reload_policy": "config_only",
    },
)

cmd = group_command("example_plugin.ping", "ping")
bind_alias_handlers(cmd, handle_ping)
