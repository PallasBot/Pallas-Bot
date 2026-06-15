from nonebot.plugin import PluginMetadata

from src.features.cmd_perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)
from src.features.cmd_perm.metadata_text import SCENE_GROUP, join_usage, usage_line

__plugin_meta__ = PluginMetadata(
    name="牛牛画画",
    description="群内 AI 生图，支持文字描述或参考图改图。",
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
        "command_permissions": [
            {"id": "draw.draw", "label": "牛牛画画", "default": "everyone"},
            {"id": "draw.gateway", "label": "牛牛网关", "default": "everyone"},
        ],
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
