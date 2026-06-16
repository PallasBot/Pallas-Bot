"""牛牛连通口令，内核模块。"""

from nonebot.plugin import PluginMetadata

from src.features.cmd_perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)
from src.features.cmd_perm.metadata_text import SCENE_BOTH, join_usage, usage_line

__plugin_meta__ = PluginMetadata(
    name="牛牛连通",
    description="群内或私聊检测智能对话、画画、远控与唱歌服务是否通畅。",
    usage=join_usage(
        usage_line("牛牛连通 / 牛牛网关", "并行探测上述服务并回报延迟"),
    ),
    type="application",
    homepage=PLUGIN_HOMEPAGE,
    supported_adapters={"~onebot.v11"},
    extra={
        "version": PLUGIN_EXTRA_VERSION,
        "ingress_route": {"lane": "remote"},
        "menu_template": PLUGIN_MENU_TEMPLATE,
        "exact_plaintexts": ["牛牛连通", "牛牛网关"],
        "command_permissions": [
            {"id": "connectivity.probe", "label": "牛牛连通", "default": "everyone"},
        ],
        "command_limits": [
            {"id": "connectivity.probe", "cd_sec": 3},
        ],
        "menu_data": [
            {
                "func": "牛牛连通",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_BOTH,
                "trigger_condition": "牛牛连通 / 牛牛网关",
                "command_permission": "connectivity.probe",
                "brief_des": "检测外部服务是否通畅",
                "detail_des": "并行检测智能对话、画画、MAA 远控与唱歌服务，并回报延迟。",
            },
        ],
    },
)

from src.features.service_gateways import commands as _connectivity_commands  # noqa: E402, F401
