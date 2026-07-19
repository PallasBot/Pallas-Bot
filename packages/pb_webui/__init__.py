# ruff: noqa: E501
from nonebot.plugin import PluginMetadata

from pallas.core.perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)
from pallas.core.perm.metadata_text import join_usage, usage_line

from . import startup as _startup  # noqa: F401

__plugin_meta__ = PluginMetadata(
    name="Web 控制台",
    description="用浏览器查看和管理牛牛。",
    usage=join_usage(
        usage_line("/pallas/", "控制台页面"),
        usage_line("/pallas/api/*", "实例、日志、数据库与插件统计等接口"),
    ),
    type="application",
    homepage=PLUGIN_HOMEPAGE,
    supported_adapters={"~onebot.v11"},
    extra={
        "version": PLUGIN_EXTRA_VERSION,
        "menu_template": PLUGIN_MENU_TEMPLATE,
        "help_audience": "superuser",
        "reload_policy": "metadata",
        "menu_data": [
            {
                "func": "控制台页面",
                "trigger_method": "http",
                "help_audience": "superuser",
                "trigger_condition": "/pallas/",
                "brief_des": "打开管理页面",
                "detail_des": "在浏览器里查看运行情况、日志和常用管理页面。",
            },
            {
                "func": "扩展状态接口",
                "trigger_method": "http",
                "help_audience": "superuser",
                "trigger_condition": "/pallas/api/*",
                "brief_des": "控制台数据入口",
                "detail_des": "给控制台页面提供它需要的状态与管理数据。",
            },
        ],
    },
)
