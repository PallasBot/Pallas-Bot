from nonebot.plugin import PluginMetadata

from src.features.cmd_perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)
from src.features.cmd_perm.metadata_text import SCENE_BOTH, SCENE_GROUP, join_usage, usage_line

__plugin_meta__ = PluginMetadata(
    name="随时闲聊",
    description="群内 @牛牛 多轮对话，支持清空会话记忆。",
    usage=join_usage(
        usage_line("群内 @牛牛 + 消息", "与牛牛多轮对话"),
        usage_line("@牛牛 clear", "清空本群当前会话记忆"),
        usage_line("@牛牛 unload", "卸载 Ollama 模型"),
        usage_line("@牛牛 model [模型名]", "查询或热更换 Ollama 模型"),
    ),
    type="application",
    homepage=PLUGIN_HOMEPAGE,
    supported_adapters={"~onebot.v11"},
    extra={
        "version": PLUGIN_EXTRA_VERSION,
        "menu_template": PLUGIN_MENU_TEMPLATE,
        "ingress_route": {"lane": "remote"},
        "help_aliases": ["牛牛聊天"],
        "command_permissions": [
            {"id": "ollama.chat", "label": "随时闲聊", "default": "everyone"},
            {"id": "ollama.clear", "label": "清空会话", "default": "everyone"},
            {"id": "ollama.unload", "label": "卸载模型", "default": "staff"},
            {"id": "ollama.set_model", "label": "更换模型", "default": "superuser"},
        ],
        "menu_data": [
            {
                "func": "随时闲聊",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "群内 @牛牛 发消息",
                "command_permission": "ollama.chat",
                "brief_des": "多轮对话，口癖与人设",
                "detail_des": "像和牛牛发消息一样 @ 即可；会按会话记住上文，话太多时会自动忘远一点的记录。",
            },
            {
                "func": "清空和牛牛的记录",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "@牛牛 clear",
                "command_permission": "ollama.clear",
                "brief_des": "忘掉本轮聊天里说过的话",
                "detail_des": "只清对话内容，牛牛该怎么说话的人设仍会保留。",
            },
            {
                "func": "卸载 Ollama 模型",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "@牛牛 unload",
                "command_permission": "ollama.unload",
                "brief_des": "释放 AI 侧显存",
                "detail_des": "向 Pallas-Bot-AI 请求卸载当前 Ollama 模型；下次对话会重新加载。",
            },
            {
                "func": "更换 Ollama 模型",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_BOTH,
                "trigger_condition": "@牛牛 model [模型名]",
                "command_permission": "ollama.set_model",
                "brief_des": "查询或热更换后端模型",
                "detail_des": "不带模型名时返回当前模型；带上名称时会向 AI 服务请求拉取并切换（如 qwen2.5:7b）。",
            },
        ],
    },
)

from . import chat_message as _chat_message  # noqa: E402, F401
from . import commands as _commands  # noqa: E402, F401
