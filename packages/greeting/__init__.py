from nonebot import get_bot
from nonebot.plugin import PluginMetadata

from pallas.core.commands import command_limit_list, command_limit_row, command_perm_list, command_perm_row
from pallas.core.perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)
from pallas.core.perm.metadata_text import SCENE_AUTO, SCENE_GROUP, SCENE_PRIVATE, join_usage, usage_line
from pallas.product.llm.knowledge.declare import knowledge_source_row

from . import commands as _commands  # noqa: F401
from .commands import call_me_message_rule, greeting_plugin_disabled, handle_notice

__plugin_meta__ = PluginMetadata(
    name="牛牛欢迎",
    description="为新好友和新成员发送欢迎内容，并支持自定义。",
    usage=join_usage(
        usage_line("设置好友欢迎 / 清除好友欢迎", "私聊维护新好友欢迎"),
        usage_line("设置群欢迎 / 清除群欢迎", "群内维护入群欢迎"),
    ),
    type="application",
    homepage=PLUGIN_HOMEPAGE,
    supported_adapters={"~onebot.v11"},
    extra={
        "version": PLUGIN_EXTRA_VERSION,
        "menu_template": PLUGIN_MENU_TEMPLATE,
        "reload_policy": "metadata",
        "command_permissions": command_perm_list(
            command_perm_row("greeting.set_friend_welcome", "设置好友欢迎", "bot_moderator"),
            command_perm_row("greeting.clear_friend_welcome", "清除好友欢迎", "bot_moderator"),
            command_perm_row("greeting.set_group_welcome", "设置群欢迎", "group_moderator"),
            command_perm_row("greeting.clear_group_welcome", "清除群欢迎", "group_moderator"),
        ),
        "command_limits": command_limit_list(
            command_limit_row("greeting.set_friend_welcome", 5),
            command_limit_row("greeting.clear_friend_welcome", 5),
            command_limit_row("greeting.set_group_welcome", 5),
            command_limit_row("greeting.clear_group_welcome", 5),
        ),
        "menu_data": [
            {
                "func": "入群欢迎",
                "trigger_method": "on_notice",
                "trigger_scene": SCENE_AUTO,
                "trigger_condition": "新人入群",
                "brief_des": "发送入群欢迎",
                "detail_des": "有人进群时自动欢迎；如果你设置过本群欢迎，就优先使用你自己的内容。",
            },
            {
                "func": "好友欢迎",
                "trigger_method": "on_notice",
                "trigger_scene": SCENE_AUTO,
                "trigger_condition": "新好友添加",
                "brief_des": "发送好友欢迎",
                "detail_des": "有人加好友时自动欢迎；如果你设置过好友欢迎，就优先使用你自己的内容。",
            },
            {
                "func": "设置好友欢迎",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_PRIVATE,
                "trigger_condition": "设置好友欢迎",
                "command_permission": "greeting.set_friend_welcome",
                "brief_des": "自定义新好友欢迎",
                "detail_des": "按提示发送文字、图片，或图文一起发，保存成好友欢迎内容。",
            },
            {
                "func": "清除好友欢迎",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_PRIVATE,
                "trigger_condition": "清除好友欢迎",
                "command_permission": "greeting.clear_friend_welcome",
                "brief_des": "恢复默认好友欢迎",
                "detail_des": "删掉你保存的好友欢迎内容，恢复成默认欢迎。",
            },
            {
                "func": "设置群欢迎",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "设置群欢迎",
                "command_permission": "greeting.set_group_welcome",
                "brief_des": "自定义本群入群欢迎",
                "detail_des": "按提示发送文字、图片，或图文一起发，保存成当前群的欢迎内容。",
            },
            {
                "func": "清除群欢迎",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "清除群欢迎",
                "command_permission": "greeting.clear_group_welcome",
                "brief_des": "恢复默认入群欢迎",
                "detail_des": "删掉当前群保存的欢迎内容，恢复成默认欢迎。",
            },
        ],
        "knowledge_sources": [
            knowledge_source_row(
                source_id="greeting.faq",
                title="牛牛欢迎说明",
                description="入群与加好友欢迎及自定义",
                chunks=[
                    {
                        "title": "自动欢迎",
                        "content": (
                            "新人入群或有人加好友时，牛牛会自动发送欢迎消息；若已设置自定义欢迎则优先使用自定义内容。"
                        ),
                        "keywords": "欢迎,入群,加好友,新人,自动",
                    },
                    {
                        "title": "自定义欢迎",
                        "content": (
                            "私聊发送「设置好友欢迎」可自定义新好友欢迎；"
                            "群内发送「设置群欢迎」可自定义本群入群欢迎，按提示发送文字或图片。"
                        ),
                        "keywords": "设置,自定义,好友欢迎,群欢迎,怎么设",
                    },
                    {
                        "title": "恢复默认欢迎",
                        "content": ("私聊「清除好友欢迎」或群内「清除群欢迎」可删除已保存内容并恢复默认欢迎。"),
                        "keywords": "清除,恢复,默认,删除欢迎",
                    },
                ],
            ),
        ],
    },
)

__all__ = ["call_me_message_rule", "get_bot", "greeting_plugin_disabled", "handle_notice"]
