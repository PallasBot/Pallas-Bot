"""牛牛连通口令，内核模块。"""

from nonebot.plugin import PluginMetadata

from pallas.core.perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)
from pallas.core.perm.metadata_text import SCENE_BOTH, join_usage, usage_line

__plugin_meta__ = PluginMetadata(
    name="牛牛连通",
    description="检查牛牛常用功能现在是否连得上、用得了。",
    usage=join_usage(
        usage_line("牛牛连通 / 牛牛网关", "查看常用功能是否可用和快不快"),
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
                "brief_des": "查看服务连通情况",
                "detail_des": "看看聊天、画图、唱歌这些常用功能现在能不能用，顺不顺畅。",
            },
        ],
    },
)

from pallas.product.service_gateways import commands as _connectivity_commands  # noqa: E402, F401
