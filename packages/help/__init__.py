from nonebot.plugin import PluginMetadata

from pallas.core.commands import command_limit_list, command_limit_row, command_perm_list, command_perm_row
from pallas.core.perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)
from pallas.core.perm.metadata_text import SCENE_BOTH, SCENE_GROUP, join_usage, usage_line
from pallas.core.storage.declare import plugin_storage_list, plugin_storage_row
from pallas.product.llm.knowledge.declare import knowledge_source_row

from . import commands as _commands  # noqa: F401
from .style_cache import refresh_style_cache

__plugin_meta__ = PluginMetadata(
    name="牛牛帮助",
    description="查看功能说明，并管理本群常用插件开关。",
    usage=join_usage(
        usage_line("牛牛帮助", "插件总览与开关状态"),
        usage_line("牛牛帮助 〈插件名或序号〉", "单插件功能表"),
        usage_line("牛牛帮助 〈插件〉 〈功能序号或名称〉", "单条功能详情"),
        usage_line("牛牛开启 / 牛牛关闭 〈插件名或序号〉", "本群开关某插件"),
        usage_line("牛牛开启全部功能 / 牛牛关闭全部功能", "本群批量开关"),
    ),
    type="application",
    homepage=PLUGIN_HOMEPAGE,
    supported_adapters={"~onebot.v11"},
    extra={
        "version": PLUGIN_EXTRA_VERSION,
        "menu_template": PLUGIN_MENU_TEMPLATE,
        "reload_policy": "metadata",
        "command_prefixes": [
            "牛牛帮助",
            "牛牛开启",
            "牛牛关闭",
            "牛牛开启全部功能",
            "牛牛关闭全部功能",
        ],
        "ingress_fanout": {
            "scope": "unified_only",
            "prefixes": [
                "牛牛帮助",
                "牛牛开启",
                "牛牛关闭",
                "牛牛开启全部功能",
                "牛牛关闭全部功能",
            ],
        },
        "command_permissions": command_perm_list(
            command_perm_row("help.help", "牛牛帮助", "everyone"),
            command_perm_row("help.plugin_enable", "牛牛开启（单插件）", "staff"),
            command_perm_row("help.plugin_disable", "牛牛关闭（单插件）", "staff"),
            command_perm_row("help.plugin_enable_all", "牛牛开启全部功能", "staff"),
            command_perm_row("help.plugin_disable_all", "牛牛关闭全部功能", "staff"),
        ),
        "command_limits": command_limit_list(
            command_limit_row("help.help", 3),
            command_limit_row("help.plugin_enable", 5),
            command_limit_row("help.plugin_disable", 5),
            command_limit_row("help.plugin_enable_all", 15),
            command_limit_row("help.plugin_disable_all", 15),
        ),
        "menu_data": [
            {
                "func": "总列表",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_BOTH,
                "trigger_condition": "牛牛帮助",
                "command_permission": "help.help",
                "brief_des": "查看功能总览",
                "detail_des": "先看本群有哪些功能，再按序号或名字继续查看。",
            },
            {
                "func": "插件详情",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_BOTH,
                "trigger_condition": "牛牛帮助 〈插件名或序号〉",
                "command_permission": "help.help",
                "brief_des": "查看单个功能页",
                "detail_des": "打开某个功能的用法列表，再继续看具体条目。",
            },
            {
                "func": "功能详情",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_BOTH,
                "trigger_condition": "牛牛帮助 〈插件〉 〈功能序号或名称〉 或 牛牛帮助 〈口令〉",
                "command_permission": "help.help",
                "brief_des": "查看单条说明",
                "detail_des": "查看某一条功能该怎么用、在哪用、谁能用；也可直接发口令如「牛牛帮助 牛牛喝酒」。",
            },
            {
                "func": "插件开关",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "牛牛开启 / 牛牛关闭 〈插件名或序号〉",
                "command_permissions": ["help.plugin_enable", "help.plugin_disable"],
                "brief_des": "开关本群功能",
                "detail_des": "按插件名或序号打开、关闭本群里的某个功能。",
            },
            {
                "func": "批量开关",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "牛牛开启全部功能 / 牛牛关闭全部功能",
                "command_permissions": ["help.plugin_enable_all", "help.plugin_disable_all"],
                "brief_des": "本群一键开关",
                "detail_des": "把帮助总览里能看到的功能一次性全部开启或关闭。",
            },
        ],
        "plugin_storage": plugin_storage_list(
            plugin_storage_row("hidden_plugins", scope="deploy", label="帮助总览隐藏名单"),
            plugin_storage_row("global_disabled_plugins", scope="deploy", label="全实例禁用名单"),
        ),
        "knowledge_sources": [
            knowledge_source_row(
                source_id="help.faq",
                title="牛牛帮助说明",
                description="查看功能说明与本群插件开关",
                chunks=[
                    {
                        "title": "查看功能总览",
                        "content": (
                            "发送「牛牛帮助」可查看本群可用功能总览；"
                            "「牛牛帮助 插件名或序号」查看单个插件；"
                            "「牛牛帮助 插件 功能序号或名称」查看单条详情。"
                        ),
                        "keywords": "帮助,功能,怎么用,牛牛帮助,总览,说明",
                    },
                    {
                        "title": "本群开关插件",
                        "content": (
                            "群管理可用「牛牛开启 / 牛牛关闭 插件名或序号」开关本群某功能；"
                            "「牛牛开启全部功能 / 牛牛关闭全部功能」可批量开关。"
                            "具体谁能操作以当前群设置为准。"
                        ),
                        "keywords": "开启,关闭,开关,插件,全部功能,禁用,启用",
                    },
                    {
                        "title": "与闲聊的分工",
                        "content": (
                            "功能用法与开关状态以「牛牛帮助」口令为准；"
                            "向 @牛牛 提问时若不确定口令，应引导用户发送牛牛帮助，不要编造不存在的命令。"
                        ),
                        "keywords": "口令,帮助,闲聊,怎么查",
                    },
                ],
            ),
        ],
    },
)

__all__ = ["refresh_style_cache"]
