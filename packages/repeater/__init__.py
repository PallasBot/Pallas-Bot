from nonebot.plugin import PluginMetadata

from pallas.api.commands import command_limit_list, command_limit_row, command_perm_list, command_perm_row
from pallas.api.metadata import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
    SCENE_AUTO,
    SCENE_GROUP,
    join_usage,
    usage_line,
)

from . import handlers  # noqa: F401
from .handlers.ban import is_ban_latest_trigger, is_ban_reply_trigger, resolve_ban_reply_raw
from .handlers.helpers import is_shutup, post_proc

__plugin_meta__ = PluginMetadata(
    name="牛牛复读",
    description="学习群里的说话方式，接话、复读和贴表情。",
    usage=join_usage(
        usage_line("群内聊天", "被动学习后回复、跟复读、定时发言"),
        usage_line("@牛牛 回复「不可以」 / 不可以发这个", "禁用指定内容"),
    ),
    type="application",
    homepage=PLUGIN_HOMEPAGE,
    supported_adapters={"~onebot.v11"},
    extra={
        "help_tag": "chat",
        "version": PLUGIN_EXTRA_VERSION,
        "menu_template": PLUGIN_MENU_TEMPLATE,
        "ingress_route": {"lane": "storage", "passive": True},
        "command_permissions": command_perm_list(
            command_perm_row("repeater.ban", "复读「不可以」", "everyone"),
            command_perm_row("repeater.ban_latest", "复读「不可以发这个」", "everyone"),
        ),
        "command_limits": command_limit_list(
            command_limit_row("repeater.ban", 3),
            command_limit_row("repeater.ban_latest", 3),
        ),
        "menu_data": [
            {
                "func": "智能回复",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_AUTO,
                "trigger_condition": "群内正常聊天",
                "brief_des": "学习话题后参与讨论",
                "detail_des": "平时会边学边接话；同一句话反复出现时，也可能跟着一起复读。",
            },
            {
                "func": "主动发言",
                "trigger_method": "scheduler",
                "trigger_scene": SCENE_AUTO,
                "trigger_condition": "定时触发",
                "brief_des": "偶尔主动插话",
                "detail_des": "有时候会自己冒出来说一句，像群里突然插话一样。",
            },
            {
                "func": "表情回应",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_AUTO,
                "trigger_condition": "群内消息或他人贴表情",
                "brief_des": "随机或跟随贴表情",
                "detail_des": "看到消息或表情时，可能会回一个表情，也可能跟着别人一起贴。",
            },
            {
                "func": "不可以",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "@牛牛 回复「不可以」/ 不可以发这个",
                "command_permissions": ["repeater.ban", "repeater.ban_latest"],
                "brief_des": "禁止牛牛再学/再说某内容",
                "detail_des": (
                    "回复某条消息说「不可以」，或对牛牛最近一句话说「不可以发这个」，就能让它别再学、别再说。"
                ),
            },
        ],
    },
)

__all__ = [
    "is_ban_latest_trigger",
    "is_ban_reply_trigger",
    "is_shutup",
    "post_proc",
    "resolve_ban_reply_raw",
]
