from nonebot.plugin import PluginMetadata

from pallas.api.commands import bind_alias_handlers, group_command
from pallas.api.metadata import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
    SCENE_BOTH,
    join_usage,
    usage_line,
)

from .config import Config
from .handlers import handle_template

__plugin_meta__ = PluginMetadata(
    name="扩展插件模板",
    description="Pallas-Bot 4.0 官方扩展包模板。",
    usage=join_usage(
        usage_line("模板命令", "示例命令，展示命令接入方式。"),
    ),
    type="application",
    homepage=PLUGIN_HOMEPAGE,
    config=Config,
    supported_adapters={"~onebot.v11"},
    extra={
        "help_tag": "tool",
        "version": PLUGIN_EXTRA_VERSION,
        "menu_template": PLUGIN_MENU_TEMPLATE,
        "command_permissions": [
            {"id": "template.main", "label": "模板命令", "default": "everyone"},
        ],
        "command_limits": [
            {"id": "template.main", "cd_sec": 5},
        ],
        "menu_data": [
            {
                "func": "模板命令",
                "group": "示例",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_BOTH,
                "trigger_condition": "模板命令",
                "command_permission": "template.main",
                "brief_des": "一句话说明。",
                "detail_des": "详细说明。",
            },
        ],
        "reload_policy": "config_only",
    },
)

cmd = group_command("template.main", "模板命令")
bind_alias_handlers(cmd, handle_template)
