"""分片 hub：MAA getTask / reportStatus 统一入口。"""

from __future__ import annotations

from nonebot import get_app
from nonebot.plugin import PluginMetadata

from src.features.cmd_perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)
from src.features.cmd_perm.metadata_text import join_usage, usage_line
from src.platform.bot_runtime.roles import is_hub_role
from src.platform.shard.coord.maa_hub_routes import remount_maa_hub_forward_routes

if is_hub_role():
    remount_maa_hub_forward_routes(get_app())

__plugin_meta__ = PluginMetadata(
    name="MAA 远控入口",
    description="分片 hub 上转发 MAA HTTP 至对应 worker。",
    usage=join_usage(
        usage_line("POST /maa/getTask、/maa/reportStatus", "分片时 MAA 对接 hub 基址"),
    ),
    type="application",
    homepage=PLUGIN_HOMEPAGE,
    supported_adapters={"~onebot.v11"},
    extra={
        "version": PLUGIN_EXTRA_VERSION,
        "menu_template": PLUGIN_MENU_TEMPLATE,
        "menu_data": [
            {
                "func": "MAA HTTP 转发",
                "trigger_method": "http",
                "help_audience": "maintainer",
                "trigger_condition": "POST /maa/getTask、/maa/reportStatus（hub）",
                "brief_des": "分片统一 MAA 入口",
                "detail_des": "按 QQ 用户标识符将请求转发至最近登记 worker；maa_public_base_url 填 hub 对外地址。",
            },
        ],
    },
)
