from nonebot.plugin import PluginMetadata

from src.features.cmd_perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)
from src.features.cmd_perm.metadata_text import SCENE_AUTO, SCENE_GROUP, join_usage, usage_line
from src.features.corpus.backfill_scheduler import bind_corpus_backfill_lifecycle
from src.features.corpus.prefetch import bind_corpus_prefetch_lifecycle
from src.features.persona import bind_group_style_refresh_lifecycle

from .handlers.ban import is_ban_latest_trigger, is_ban_reply_trigger, resolve_ban_reply_raw
from .handlers.helpers import is_shutup, post_proc
from .learn_queue import bind_repeater_learn_lifecycle

bind_repeater_learn_lifecycle()
bind_group_style_refresh_lifecycle()
bind_corpus_prefetch_lifecycle()
bind_corpus_backfill_lifecycle()

from . import handlers  # noqa: E402, F401 — 注册 matcher / 调度

__plugin_meta__ = PluginMetadata(
    name="牛牛复读",
    description="学习群聊并智能回复、跟复读与表情回应。",
    usage=join_usage(
        usage_line("群内聊天", "被动学习后回复、跟复读、定时发言"),
        usage_line("@牛牛 回复「不可以」 / 不可以发这个", "禁用指定内容"),
    ),
    type="application",
    homepage=PLUGIN_HOMEPAGE,
    supported_adapters={"~onebot.v11"},
    extra={
        "version": PLUGIN_EXTRA_VERSION,
        "menu_template": PLUGIN_MENU_TEMPLATE,
        "ingress_route": {"lane": "storage", "passive": True},
        "command_permissions": [
            {"id": "repeater.ban", "label": "复读「不可以」", "default": "staff"},
            {"id": "repeater.ban_latest", "label": "复读「不可以发这个」", "default": "staff"},
        ],
        "menu_data": [
            {
                "func": "智能回复",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_AUTO,
                "trigger_condition": "群内正常聊天",
                "brief_des": "学习话题后参与讨论",
                "detail_des": "根据相似度与上下文自动回复；相同句连发多次时会跟复读。",
            },
            {
                "func": "主动发言",
                "trigger_method": "scheduler",
                "trigger_scene": SCENE_AUTO,
                "trigger_condition": "定时触发",
                "brief_des": "偶尔主动插话",
                "detail_des": "按概率用学到的话在群内发言。",
            },
            {
                "func": "表情回应",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_AUTO,
                "trigger_condition": "群内消息或他人贴表情",
                "brief_des": "随机或跟随贴表情",
                "detail_des": "可对消息概率回应、对含表情消息回应，或跟随他人已贴的表情。",
            },
            {
                "func": "不可以",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "@牛牛 回复「不可以」/ 不可以发这个",
                "command_permissions": ["repeater.ban", "repeater.ban_latest"],
                "brief_des": "禁止牛牛再学/再说某内容",
                "detail_des": (
                    "回复目标消息说「不可以」；或「不可以发这个」针对你上一条回复。撤回牛牛消息也会禁用该条。"
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
