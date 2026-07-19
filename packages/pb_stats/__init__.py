from nonebot.plugin import PluginMetadata

from pallas.core.perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)

from . import config as _config  # noqa: F401
from . import startup as _startup  # noqa: F401

__plugin_meta__ = PluginMetadata(
    name="在线统计",
    description="把本实例的在线统计信息同步到社区页面。",
    usage="（超管）在 WebUI 插件「在线统计」配置页查看和调整上报与社区展示。",
    type="application",
    homepage=PLUGIN_HOMEPAGE,
    supported_adapters={"~onebot.v11"},
    extra={
        "version": PLUGIN_EXTRA_VERSION,
        "menu_template": PLUGIN_MENU_TEMPLATE,
        "help_audience": "superuser",
        "menu_data": [
            {
                "func": "在线统计上报",
                "trigger_method": "http",
                "help_audience": "superuser",
                "trigger_condition": "WebUI 插件「在线统计」配置页",
                "brief_des": "在线统计同步",
                "detail_des": "在后台持续同步在线统计信息；没有群内口令。",
            },
        ],
    },
)
