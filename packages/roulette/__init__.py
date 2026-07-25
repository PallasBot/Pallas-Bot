from nonebot.plugin import PluginMetadata

from pallas.core.commands import command_limit_list, command_limit_row, command_perm_list, command_perm_row
from pallas.core.perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)
from pallas.core.perm.metadata_text import SCENE_GROUP, join_usage, usage_line
from pallas.product.llm.knowledge.declare import knowledge_source_row
from pallas.product.llm.tools.declare import llm_command_tool_row

from . import commands as _commands  # noqa: F401
from .game import parse_roulette_start_command

__plugin_meta__ = PluginMetadata(
    name="牛牛轮盘",
    description="在群里玩踢人或禁言轮盘，也能救人和补一枪。",
    usage=join_usage(
        usage_line("牛牛轮盘 / 牛牛轮盘踢人 / 牛牛轮盘禁言", "启动轮盘（默认禁言模式）"),
        usage_line("牛牛开枪", "参与当前局"),
        usage_line("牛牛救一下 [@用户]", "解除禁言，有概率炸膛"),
        usage_line("牛牛补一枪 [@用户]", "追加禁言，有概率炸膛"),
    ),
    type="application",
    homepage=PLUGIN_HOMEPAGE,
    supported_adapters={"~onebot.v11"},
    extra={
        "help_tag": "fun",
        "version": PLUGIN_EXTRA_VERSION,
        "menu_template": PLUGIN_MENU_TEMPLATE,
        "reload_policy": "metadata",
        "exact_plaintexts": [
            "牛牛轮盘",
            "牛牛轮盘踢人",
            "牛牛轮盘禁言",
            "牛牛踢人轮盘",
            "牛牛禁言轮盘",
            "牛牛开枪",
        ],
        "command_prefixes": ["牛牛救一下", "牛牛补一枪"],
        "ingress_fanout": {
            "scope": "always",
            "plaintexts": [
                "牛牛轮盘",
                "牛牛轮盘踢人",
                "牛牛轮盘禁言",
                "牛牛踢人轮盘",
                "牛牛禁言轮盘",
                "牛牛开枪",
            ],
            "prefixes": ["牛牛救一下", "牛牛补一枪"],
        },
        "command_permissions": command_perm_list(
            command_perm_row("roulette.start", "牛牛轮盘"),
            command_perm_row("roulette.shot", "牛牛开枪"),
            command_perm_row("roulette.rescue", "牛牛救一下"),
            command_perm_row("roulette.punish", "牛牛补一枪"),
            command_perm_row("roulette.mode_switch", "牛牛轮盘切换模式", "staff"),
        ),
        "command_limits": command_limit_list(
            command_limit_row("roulette.start", 5),
            command_limit_row("roulette.shot", 2),
            command_limit_row("roulette.rescue", 5),
            command_limit_row("roulette.punish", 5),
            command_limit_row("roulette.mode_switch", 5),
        ),
        "llm_tools": [
            llm_command_tool_row(
                name="roulette.start",
                command_id="roulette.start",
                description="开始一局牛牛轮盘（默认禁言模式）。用户明确要求玩轮盘、开始轮盘时使用。",
                parameters={"type": "object", "properties": {}},
                command_template="牛牛轮盘",
            ),
            llm_command_tool_row(
                name="roulette.shot",
                command_id="roulette.shot",
                description="在已开始的轮盘局里开枪参与。用户说开枪、参与轮盘时使用。",
                parameters={"type": "object", "properties": {}},
                command_template="牛牛开枪",
            ),
            llm_command_tool_row(
                name="roulette.rescue",
                command_id="roulette.rescue",
                description="尝试解救被禁言的人（不指定对象时帮大家解禁）。用户说救一下、解禁时使用。",
                parameters={"type": "object", "properties": {}},
                command_template="牛牛救一下",
            ),
            llm_command_tool_row(
                name="roulette.punish",
                command_id="roulette.punish",
                description="对已中招者追加惩罚。用户说补一枪、再罚一次时使用。",
                parameters={"type": "object", "properties": {}},
                command_template="牛牛补一枪",
            ),
        ],
        "menu_data": [
            {
                "func": "牛牛轮盘",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "牛牛轮盘 / 牛牛轮盘踢人 / 牛牛轮盘禁言",
                "command_permission": "roulette.start",
                "brief_des": "启动轮盘",
                "detail_des": "可选踢人或禁言模式；轮到谁中弹，就按当前模式执行结果。",
            },
            {
                "func": "切换轮盘模式",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "牛牛轮盘踢人 / 牛牛轮盘禁言 / 牛牛踢人轮盘 / 牛牛禁言轮盘",
                "command_permission": "roulette.mode_switch",
                "brief_des": "切换踢人/禁言模式",
                "detail_des": "用「牛牛轮盘踢人」或「牛牛轮盘禁言」指定本局模式；默认禁言。",
            },
            {
                "func": "参与轮盘",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "牛牛开枪",
                "command_permission": "roulette.shot",
                "brief_des": "参与轮盘",
                "detail_des": "轮盘开始后，发「牛牛开枪」参与本局，结果按当前模式决定。",
            },
            {
                "func": "牛牛救一下",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "牛牛救一下 [@用户]",
                "command_permission": "roulette.rescue",
                "brief_des": "解除被禁言的用户",
                "detail_des": "不带 @ 时帮大家解禁，带 @ 时只救那个人；有时会翻车。",
            },
            {
                "func": "牛牛补一枪",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "牛牛补一枪 [@用户]",
                "command_permission": "roulette.punish",
                "brief_des": "对已禁言玩家追加惩罚",
                "detail_des": "给已经中招的人再补一轮惩罚；可 @ 指定对象，也有翻车概率。",
            },
        ],
        "knowledge_sources": [
            knowledge_source_row(
                source_id="roulette.faq",
                title="牛牛轮盘说明",
                description="群内踢人/禁言轮盘玩法",
                chunks=[
                    {
                        "title": "如何开始轮盘",
                        "content": (
                            "发送「牛牛轮盘」启动默认禁言模式；也可用「牛牛轮盘踢人」或「牛牛轮盘禁言」指定模式。"
                        ),
                        "keywords": "轮盘,怎么玩,开始,踢人,禁言,牛牛轮盘",
                    },
                    {
                        "title": "如何参与轮盘",
                        "content": "轮盘开始后，在群内发送「牛牛开枪」即可参与本局，中弹者按当前模式受罚。",
                        "keywords": "开枪,参与,怎么加入,中弹",
                    },
                    {
                        "title": "救人与补枪",
                        "content": (
                            "「牛牛救一下 [@用户]」可尝试解除禁言，不带 @ 时帮大家解禁；"
                            "「牛牛补一枪 [@用户]」对已中招者追加惩罚；两者均有翻车概率。"
                        ),
                        "keywords": "救一下,补一枪,解禁,追加,翻车",
                    },
                    {
                        "title": "与口令工具的分工",
                        "content": (
                            "闲聊中若用户要玩轮盘，可调用 roulette.start / roulette.shot 等工具；"
                            "效果与对应群口令一致，不要编造其它入口。"
                        ),
                        "keywords": "工具,口令,轮盘,开枪",
                    },
                ],
            ),
        ],
    },
)

__all__ = ["parse_roulette_start_command"]
