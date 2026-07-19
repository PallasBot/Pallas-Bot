from nonebot.plugin import PluginMetadata

from pallas.core.commands import command_limit_list, command_limit_row, command_perm_list, command_perm_row
from pallas.core.perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)
from pallas.core.perm.metadata_text import SCENE_GROUP, SCENE_PRIVATE, join_usage, usage_line
from pallas.product.llm.knowledge.declare import knowledge_source_row
from pallas.product.llm.tools.declare import llm_command_tool_row

from . import admin_commands as _admin_commands  # noqa: F401
from . import chat_message as _chat_message  # noqa: F401
from . import commands as _commands  # noqa: F401
from . import status_commands as _status_commands  # noqa: F401

__plugin_meta__ = PluginMetadata(
    name="随时闲聊",
    description="群里随时 @牛牛 聊天，也可以清空这轮聊天记录。",
    usage=join_usage(
        usage_line("群内 @牛牛 + 消息", "与牛牛多轮对话"),
        usage_line("@牛牛 clear", "清空本群当前会话记忆"),
    ),
    type="application",
    homepage=PLUGIN_HOMEPAGE,
    supported_adapters={"~onebot.v11"},
    extra={
        "version": PLUGIN_EXTRA_VERSION,
        "help_audience": "superuser",
        "menu_template": PLUGIN_MENU_TEMPLATE,
        "reload_policy": "metadata",
        "ingress_route": {"lane": "remote"},
        "help_aliases": ["牛牛聊天", "智能闲聊"],
        "command_permissions": command_perm_list(
            command_perm_row("llm_chat.chat", "随时闲聊", "everyone"),
            command_perm_row("llm_chat.clear", "清空会话", "everyone"),
            command_perm_row("llm_chat.switch_model", "换模型", "superuser"),
            command_perm_row("llm_chat.unload_model", "卸模型", "superuser"),
            command_perm_row("llm_chat.status", "LLM 状态", "superuser"),
        ),
        "command_limits": command_limit_list(
            command_limit_row("llm_chat.chat", 3),
            command_limit_row("llm_chat.clear", 2),
            command_limit_row("llm_chat.status", 5),
            command_limit_row("llm_chat.switch_model", 10),
            command_limit_row("llm_chat.unload_model", 10),
        ),
        "llm_tools": [
            llm_command_tool_row(
                name="llm_chat.clear",
                command_id="llm_chat.clear",
                description="清空当前用户与本 bot 的多轮 LLM 会话记忆。用户明确要求忘记聊过的内容时使用。",
                parameters={"type": "object", "properties": {}},
                command_template="clear",
            ),
        ],
        "knowledge_sources": [
            knowledge_source_row(
                source_id="llm_chat.faq",
                title="随时闲聊说明",
                description="群内智能闲聊的触发方式与会话管理",
                chunks=[
                    {
                        "title": "如何开始闲聊",
                        "content": "在群内 @牛牛 并发送消息即可开始多轮对话；牛牛会结合本轮上下文接话。",
                        "keywords": "聊天,闲聊,怎么聊,怎么用,@牛牛,对话",
                    },
                    {
                        "title": "清空本轮记录",
                        "content": (
                            "发送 @牛牛 clear 可清空当前群内的多轮会话记忆；也可在对话中明确要求牛牛忘记刚聊的内容。"
                        ),
                        "keywords": "清空,clear,忘记,重置,会话,记录",
                    },
                    {
                        "title": "与口令工具的分工",
                        "content": (
                            "闲聊走 @牛牛 对话；清空记忆用 clear 口令或由模型调用清空工具，"
                            "不要凭空编造不存在的管理入口。"
                        ),
                        "keywords": "工具,口令,清空,帮助",
                    },
                ],
            ),
        ],
        "menu_data": [
            {
                "func": "LLM 状态",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_PRIVATE,
                "trigger_condition": "LLM状态 / llm状态",
                "help_audience": "superuser",
                "command_permission": "llm_chat.status",
                "brief_des": "查看聊天状态",
                "detail_des": "看看智能对话现在能不能正常用，以及当前的大致状态。",
            },
            {
                "func": "随时闲聊",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "群内 @牛牛 发消息",
                "command_permission": "llm_chat.chat",
                "brief_des": "和牛牛连续聊天",
                "detail_des": "像平时发消息一样 @ 它就行；它会记住这轮聊过的话，再顺着接下去。",
            },
            {
                "func": "清空和牛牛的记录",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "@牛牛 clear",
                "command_permission": "llm_chat.clear",
                "brief_des": "清空这轮聊天记录",
                "detail_des": "让牛牛忘掉这轮刚聊过的话，但不会改掉它本来的说话风格。",
            },
            {
                "func": "换模型",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_PRIVATE,
                "trigger_condition": "换模型 / 牛牛换模型 [模型名]",
                "help_audience": "superuser",
                "command_permission": "llm_chat.switch_model",
                "brief_des": "切换本地对话模型",
                "detail_des": "私聊发送可查看当前模型；带模型名则切换，无需重启 Celery，旧权重自动卸载。",
            },
            {
                "func": "卸模型",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_PRIVATE,
                "trigger_condition": "卸模型 / 牛牛卸模型",
                "help_audience": "superuser",
                "command_permission": "llm_chat.unload_model",
                "brief_des": "卸载当前本地模型",
                "detail_des": "释放当前本地模型权重；下次对话按新配置重新加载。",
            },
        ],
    },
)
