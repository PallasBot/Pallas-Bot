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
from pallas.product.llm.runtime_api import knowledge_source_row
from pallas.product.llm.sticker_followup import bind_outgoing_sticker_followup
from pallas.product.llm.sticker_habit import bind_sticker_habit_lifecycle
from pallas.product.llm.sticker_label_observability import bind_sticker_label_backfill_lifecycle
from pallas.product.llm.sticker_vision import bind_sticker_vision_delivery_dispatcher

from . import admin_commands as _admin_commands  # noqa: F401
from . import commands as _commands  # noqa: F401
from . import status_commands as _status_commands  # noqa: F401
from . import style_commands as _style_commands  # noqa: F401

bind_sticker_vision_delivery_dispatcher()
bind_outgoing_sticker_followup()
bind_sticker_label_backfill_lifecycle()
bind_sticker_habit_lifecycle()

__plugin_meta__ = PluginMetadata(
    name="智能对话",
    description="本插件的 @牛牛 智能对话与酒后对话已停用；保留会话清理、表达风格重置与模型状态查询等显式命令。",
    usage=join_usage(
        usage_line("@牛牛 clear", "清空 Pallas 侧历史会话记录（不影响 MaiBot）"),
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
        "knowledge_sources": [
            knowledge_source_row(
                source_id="llm_chat.faq",
                title="智能对话说明",
                description="会话清理、表达风格重置与状态查询",
                chunks=[
                    {
                        "title": "智能对话已停用",
                        "content": "本插件不再提供 @牛牛 的多轮智能对话与酒后对话。",
                        "keywords": "聊天,闲聊,智能对话,停用",
                    },
                    {
                        "title": "清空历史会话记录",
                        "content": (
                            "发送 @牛牛 clear 可清空 Pallas 侧保存的历史会话记录；"
                            "不影响 MaiBot 的记忆，也不删除其他数据。"
                        ),
                        "keywords": "清空,clear,忘记,重置,会话,记录",
                    },
                    {
                        "title": "重置表达风格",
                        "content": (
                            "发送 @牛牛 重置表达 可清空当前这只牛在本群学到的表达风格记录，之后重新学习；"
                            "只影响当前牛与本群，不会改动其他牛或其他群的风格。"
                        ),
                        "keywords": "重置,表达,风格,清空,学习",
                    },
                    {
                        "title": "邀请牛牛进群",
                        "content": (
                            "普通群友想拉牛牛进群，一般先加牛牛为好友，再发出群邀请；"
                            "牛牛同不同意、什么时候同意，由牛牛账号的主人按自己的设置处理，不一定会马上通过。"
                            "这里只说明大致流程，没法确认某一次邀请有没有收到或批准；不清楚时牛牛会直说不知道。"
                        ),
                        "keywords": "邀请牛牛,拉牛牛进群,能来我们群,进我们群,加牛牛好友",
                    },
                ],
            ),
        ],
        "menu_data": [
            {
                "func": "清空和牛牛的记录",
                "group": "聊天与会话",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "@牛牛 clear",
                "command_permission": "llm_chat.clear",
                "brief_des": "清空 Pallas 侧历史会话记录。",
                "detail_des": "只清空 Pallas 侧保存的历史会话记录；不影响 MaiBot 的记忆，也不删除其他数据。",
            },
            {
                "func": "重置表达风格",
                "group": "聊天与会话",
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
                "group": "管理与测试",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_PRIVATE,
                "trigger_condition": "LLM状态 / llm状态",
                "help_audience": "superuser",
                "command_permission": "llm_chat.status",
                "brief_des": "查看 Pallas 共享模型与本地推理状态。",
                "detail_des": "私聊查看 Pallas 共享模型与本地推理状态；LLM 对话由 MaiBot 承担，不在此显示。",
            },
            {
                "func": "测试缓存表情",
                "group": "管理与测试",
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
                "group": "管理与测试",
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
                "group": "管理与测试",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_PRIVATE,
                "trigger_condition": "换模型 / 牛牛换模型 [模型名]",
                "help_audience": "superuser",
                "command_permission": "llm_chat.switch_model",
                "brief_des": "切换 Pallas 本地推理模型。",
                "detail_des": (
                    "私聊发送可查看当前 Pallas 本地推理模型；带模型名则切换，无需重启 Celery，旧权重自动卸载；"
                    "只管理 Pallas 本地模型，不影响 MaiBot 的模型。"
                ),
            },
            {
                "func": "卸模型",
                "group": "管理与测试",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_PRIVATE,
                "trigger_condition": "卸模型 / 牛牛卸模型",
                "help_audience": "superuser",
                "command_permission": "llm_chat.unload_model",
                "brief_des": "卸载 Pallas 本地推理模型。",
                "detail_des": "释放 Pallas 本地推理模型权重，下次本地调用按新配置重新加载；不影响 MaiBot。",
            },
        ],
    },
)
