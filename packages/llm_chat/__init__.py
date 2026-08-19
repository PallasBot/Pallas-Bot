from nonebot.plugin import PluginMetadata

from pallas.api.commands import command_limit_list, command_limit_row, command_perm_list, command_perm_row
from pallas.api.metadata import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
    SCENE_GROUP,
    SCENE_PRIVATE,
    join_usage,
    usage_line,
)
from pallas.product.llm.runtime_api import knowledge_source_row, llm_command_tool_row
from pallas.product.llm.sticker_followup import bind_outgoing_sticker_followup
from pallas.product.llm.sticker_label_observability import bind_sticker_label_backfill_lifecycle
from pallas.product.llm.sticker_vision import bind_sticker_vision_delivery_dispatcher

from . import admin_commands as _admin_commands  # noqa: F401
from . import chat_message as _chat_message  # noqa: F401
from . import commands as _commands  # noqa: F401
from . import drunk_chat as _drunk_chat  # noqa: F401
from . import status_commands as _status_commands  # noqa: F401
from . import style_commands as _style_commands  # noqa: F401

bind_sticker_vision_delivery_dispatcher()
bind_outgoing_sticker_followup()
bind_sticker_label_backfill_lifecycle()

__plugin_meta__ = PluginMetadata(
    name="智能对话",
    description="群里 @牛牛 就能连续聊天；醉酒时也可以「牛牛 + 文本」搭话，并可清空本轮记忆。",
    usage=join_usage(
        usage_line("群内 @牛牛 + 消息", "和牛牛多轮聊天"),
        usage_line("醉酒时 @牛牛 / 牛牛 + 文本", "酒后搭话"),
        usage_line("@牛牛 clear", "清空本轮聊天记忆"),
        usage_line("@牛牛 重置表达", "清空本牛在本群的表达风格记录"),
    ),
    type="application",
    homepage=PLUGIN_HOMEPAGE,
    supported_adapters={"~onebot.v11"},
    extra={
        "help_tag": "chat",
        "version": PLUGIN_EXTRA_VERSION,
        "menu_template": PLUGIN_MENU_TEMPLATE,
        "reload_policy": "metadata",
        "ingress_route": {"lane": "remote", "passive": True},
        "help_aliases": ["牛牛聊天", "智能闲聊", "随时闲聊", "酒后聊天", "醉酒聊天"],
        "command_permissions": command_perm_list(
            command_perm_row("llm_chat.chat", "智能对话", "everyone"),
            command_perm_row("llm_chat.clear", "清空会话", "everyone"),
            command_perm_row("llm_chat.reset_style", "重置表达风格", "group_moderator"),
            command_perm_row("llm_chat.switch_model", "换模型", "superuser"),
            command_perm_row("llm_chat.unload_model", "卸模型", "superuser"),
            command_perm_row("llm_chat.status", "LLM 状态", "superuser"),
            command_perm_row("llm_chat.sticker_test", "测试缓存/LLM 表情", "superuser"),
        ),
        "command_limits": command_limit_list(
            command_limit_row("llm_chat.chat", 3),
            command_limit_row("llm_chat.clear", 2),
            command_limit_row("llm_chat.reset_style", 10),
            command_limit_row("llm_chat.status", 5),
            command_limit_row("llm_chat.switch_model", 10),
            command_limit_row("llm_chat.unload_model", 10),
            command_limit_row("llm_chat.sticker_test", 5),
        ),
        "llm_tools": [
            llm_command_tool_row(
                name="llm_chat.clear",
                command_id="llm_chat.clear",
                description="清空当前用户与本 bot 的多轮 LLM 会话记忆。用户明确要求忘记聊过的内容时使用。",
                parameters={"type": "object", "properties": {}},
                command_template="clear",
                hints=["忘掉", "清空", "clear", "忘了吧", "清空对话", "忘记刚才"],
                visibility="deferred",
            ),
        ],
        "knowledge_sources": [
            knowledge_source_row(
                source_id="llm_chat.faq",
                title="智能对话说明",
                description="群内智能对话与酒后对话的触发方式与会话管理",
                chunks=[
                    {
                        "title": "如何开始对话",
                        "content": "在群内 @牛牛 并发送消息即可开始多轮对话；牛牛会结合本轮上下文接话。",
                        "keywords": "聊天,闲聊,怎么聊,怎么用,@牛牛,对话,智能对话",
                    },
                    {
                        "title": "酒后对话",
                        "content": (
                            "牛牛须先处于醉酒状态（可先发送「牛牛喝酒」）；"
                            "然后在群内 @牛牛 发消息，或以「牛牛 + 文本」搭话。"
                            "未醉酒时的 @ 走清醒智能对话。"
                        ),
                        "keywords": "酒后,聊天,醉酒,@牛牛,怎么聊,喝酒",
                    },
                    {
                        "title": "清空本轮记录",
                        "content": (
                            "发送 @牛牛 clear 可清空当前群内的多轮会话记忆；也可在对话中明确要求牛牛忘记刚聊的内容。"
                            "醒酒时也会清掉本群酒后会话上下文。"
                        ),
                        "keywords": "清空,clear,忘记,重置,会话,记录,醒酒",
                    },
                    {
                        "title": "与命令工具的分工",
                        "content": (
                            "智能对话走 @牛牛 对话；清空记忆用 clear 命令或由模型调用清空工具，"
                            "不要凭空编造不存在的管理入口。"
                        ),
                        "keywords": "工具,命令,清空,帮助",
                    },
                    {
                        "title": "重置表达风格",
                        "content": (
                            "发送 @牛牛 重置表达 可清空当前这只牛在本群学到的表达风格记录，之后重新学习；"
                            "只影响当前牛与本群，不会改动其他牛或其他群的风格。"
                        ),
                        "keywords": "重置,表达,风格,清空,学习",
                    },
                ],
            ),
        ],
        "menu_data": [
            {
                "func": "智能对话",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "群内 @牛牛 发消息",
                "command_permission": "llm_chat.chat",
                "brief_des": "和牛牛连续聊天。",
                "detail_des": "像平时发消息一样 @ 它就行；它会记住这轮聊过的话，再顺着接下去。",
            },
            {
                "func": "酒后聊天",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "醉酒时 @牛牛 / 牛牛 + 文本",
                "command_permission": "llm_chat.chat",
                "brief_des": "醉酒时和牛牛聊天。",
                "detail_des": (
                    "要先让牛牛喝酒（例如「牛牛喝酒」）；"
                    "醉酒后可 @ 它，或直接「牛牛 + 文本」搭话。"
                    "醒酒后这轮酒后记忆会清掉。"
                ),
            },
            {
                "func": "清空和牛牛的记录",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "@牛牛 clear",
                "command_permission": "llm_chat.clear",
                "brief_des": "清空这轮聊天记忆。",
                "detail_des": "让牛牛忘掉这轮刚聊过的话，不会改掉它平时的说话风格。也可在对话里明确说让它忘记。",
            },
            {
                "func": "重置表达风格",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "@牛牛 重置表达",
                "command_permission": "llm_chat.reset_style",
                "brief_des": "清空本牛在本群的表达风格记录。",
                "detail_des": (
                    "只影响当前这只牛、当前这个群：清掉从群消息里学到的表达风格锚点与例句，"
                    "之后会重新学习；同群其他牛与本牛在其他群的风格不受影响。"
                ),
            },
            {
                "func": "LLM 状态",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_PRIVATE,
                "trigger_condition": "LLM状态 / llm状态",
                "help_audience": "superuser",
                "command_permission": "llm_chat.status",
                "brief_des": "查看聊天服务状态。",
                "detail_des": "私聊查看智能对话是否可用，以及当前大致状态。",
            },
            {
                "func": "测试缓存表情",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "牛牛测试缓存表情",
                "help_audience": "superuser",
                "command_permission": "llm_chat.sticker_test",
                "brief_des": "发送一张缓存表情图验证链路。",
                "detail_des": "仅超级用户可用；无可用缓存图片时不会发送。",
            },
            {
                "func": "测试 LLM 表情",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "牛牛测试LLM表情 + 待匹配文本",
                "help_audience": "superuser",
                "command_permission": "llm_chat.sticker_test",
                "brief_des": "验证 VLM 选择与表情派发。",
                "detail_des": "仅超级用户可用；命令后需附上用于召回候选的文本。",
            },
            {
                "func": "换模型",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_PRIVATE,
                "trigger_condition": "换模型 / 牛牛换模型 [模型名]",
                "help_audience": "superuser",
                "command_permission": "llm_chat.switch_model",
                "brief_des": "切换本地对话模型。",
                "detail_des": "私聊发送可查看当前模型；带模型名则切换，无需重启 Celery，旧权重自动卸载。",
            },
            {
                "func": "卸模型",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_PRIVATE,
                "trigger_condition": "卸模型 / 牛牛卸模型",
                "help_audience": "superuser",
                "command_permission": "llm_chat.unload_model",
                "brief_des": "卸载当前本地模型。",
                "detail_des": "释放当前本地模型权重；下次对话按新配置重新加载。",
            },
        ],
    },
)
