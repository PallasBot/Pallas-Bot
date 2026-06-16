from nonebot.plugin import PluginMetadata

from src.features.cmd_perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)
from src.features.cmd_perm.metadata_text import SCENE_GROUP, join_usage, usage_line

__plugin_meta__ = PluginMetadata(
    name="随时闲聊",
    description="群内 @牛牛 多轮对话，支持清空会话记忆。",
    usage=join_usage(
        usage_line("群内 @牛牛 + 消息", "与牛牛多轮对话"),
        usage_line("@牛牛 clear", "清空本群当前会话记忆"),
    ),
    type="application",
    homepage=PLUGIN_HOMEPAGE,
    supported_adapters={"~onebot.v11"},
    extra={
        "version": PLUGIN_EXTRA_VERSION,
        "menu_template": PLUGIN_MENU_TEMPLATE,
        "ingress_route": {"lane": "remote"},
        "help_aliases": ["牛牛聊天", "智能闲聊"],
        "command_permissions": [
            {"id": "llm_chat.chat", "label": "随时闲聊", "default": "everyone"},
            {"id": "llm_chat.clear", "label": "清空会话", "default": "everyone"},
        ],
        "command_limits": [
            {"id": "llm_chat.chat", "cd_sec": 3},
        ],
        "menu_data": [
            {
                "func": "随时闲聊",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "群内 @牛牛 发消息",
                "command_permission": "llm_chat.chat",
                "brief_des": "多轮对话，口癖与人设",
                "detail_des": "像和牛牛发消息一样 @ 即可；会按会话记住上文，话太多时会自动忘远一点的记录。",
            },
            {
                "func": "清空和牛牛的记录",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "@牛牛 clear",
                "command_permission": "llm_chat.clear",
                "brief_des": "忘掉本轮聊天里说过的话",
                "detail_des": "只清对话内容，牛牛该怎么说话的人设仍会保留。",
            },
        ],
    },
)

from . import chat_message as _chat_message  # noqa: E402, F401
from . import commands as _commands  # noqa: E402, F401
