from nonebot.plugin import PluginMetadata

from src.features.cmd_perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)
from src.features.cmd_perm.metadata_text import SCENE_GROUP, join_usage, usage_line
from src.features.llm.tools.declare import llm_command_tool_row
from src.features.plugin_storage.declare import plugin_storage_list, plugin_storage_row
from src.features.plugin_storage.startup import register_plugin_storage_startup_hook

register_plugin_storage_startup_hook()

__plugin_meta__ = PluginMetadata(
    name="牛牛画画",
    description="群内按文字描述生图，支持参考图改图。",
    usage=join_usage(
        usage_line("牛牛画画 …", "按描述生图"),
        usage_line("牛牛画画 + 附图 / 回复图片", "以参考图改图，可多图"),
    ),
    type="application",
    homepage=PLUGIN_HOMEPAGE,
    supported_adapters={"~onebot.v11"},
    extra={
        "version": PLUGIN_EXTRA_VERSION,
        "menu_template": PLUGIN_MENU_TEMPLATE,
        "ingress_route": {"lane": "remote"},
        "command_prefixes": ["牛牛画画"],
        "command_permissions": [
            {"id": "draw.draw", "label": "牛牛画画", "default": "everyone"},
            {"id": "draw.gateway", "label": "牛牛网关", "default": "everyone"},
        ],
        "command_limits": [
            {"id": "draw.draw", "cd_sec": 3},
        ],
        "llm_tools": [
            llm_command_tool_row(
                name="draw.image",
                command_id="draw.draw",
                description="根据文字描述生成或修改图片。用户想画画、生图、画图、改图时使用。",
                parameters={
                    "type": "object",
                    "properties": {
                        "prompt": {
                            "type": "string",
                            "description": "画面描述，尽量保留用户原话",
                        },
                    },
                    "required": ["prompt"],
                },
                command_template="牛牛画画 {prompt}",
            ),
        ],
        "plugin_storage": plugin_storage_list(
            plugin_storage_row("daily_usage", scope="deploy", label="群内日用量"),
        ),
        "menu_data": [
            {
                "func": "牛牛画画",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "牛牛画画 …",
                "command_permission": "draw.draw",
                "brief_des": "生图或改图",
                "detail_des": "可纯文字，也可附图或回复图片作参考；次数用尽时会提示。",
            },
        ],
    },
)

from . import draw as _pallas_draw  # noqa: E402, F401
