from nonebot.plugin import PluginMetadata

from src.features.cmd_perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)
from src.features.cmd_perm.metadata_text import SCENE_GROUP, SCENE_PRIVATE, join_usage, usage_line

from .commands import CMD_END, CMD_JOIN, CMD_OPEN, CMD_QUIT, CMD_START, CMD_STATUS, SPY_GROUP_COMMAND_PREFIXES
from .config import Config
from .store import init_store

init_store()

from . import handlers as _handlers  # noqa: E402, F401

__plugin_meta__ = PluginMetadata(
    name="牛牛卧底",
    description=(
        "谁是卧底：房主开房、玩家加入，发词后按顺序 @牛牛 述词，"
        "全员述毕私聊匿名投票，直至平民或卧底一方获胜。"
    ),
    usage=join_usage(
        usage_line(CMD_OPEN, "房主开房间"),
        usage_line("牛牛谁是卧底", "同「牛牛卧底」"),
        usage_line(f"{CMD_JOIN} / {CMD_QUIT}", "加入或退出筹备中的房间"),
        usage_line(f"{CMD_START} / 牛牛开始 [潜藏人数]", "房主发词牌并开始"),
        usage_line("按顺序 @牛牛", "述"),
        usage_line("私聊回复数字或 0", "投票"),
        usage_line(f"{CMD_STATUS} / {CMD_END}", "察看局势或结束房间"),
    ),
    type="application",
    homepage=PLUGIN_HOMEPAGE,
    config=Config,
    supported_adapters={"~onebot.v11"},
    extra={
        "version": PLUGIN_EXTRA_VERSION,
        "menu_template": PLUGIN_MENU_TEMPLATE,
        "command_permissions": [
            {"id": "who_is_spy.open", "label": CMD_OPEN, "default": "everyone"},
            {"id": "who_is_spy.join", "label": f"{CMD_JOIN}/{CMD_QUIT}", "default": "everyone"},
            {"id": "who_is_spy.start", "label": CMD_START, "default": "everyone"},
            {"id": "who_is_spy.status", "label": CMD_STATUS, "default": "everyone"},
            {"id": "who_is_spy.end", "label": CMD_END, "default": "everyone"},
        ],
        "hosted_activity_ingress": {
            "plugin_key": "who_is_spy",
            "activity_namespace": "spy_group",
            "command_prefixes": list(SPY_GROUP_COMMAND_PREFIXES),
            "always_pass_prefixes": [CMD_OPEN, "牛牛谁是卧底", CMD_END],
            "session_flag": "session_active",
            "speak_at_fleet_bot_only": True,
        },
        "menu_data": [
            {
                "func": CMD_OPEN,
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": f"{CMD_OPEN} / 牛牛谁是卧底",
                "command_permission": "who_is_spy.open",
                "brief_des": "房主开房间",
                "detail_des": (
                    f"房主开房后自动加入名册；其他人发「{CMD_JOIN}」加入、"
                    f"「{CMD_QUIT}」退出。人数达下限后，房主发「{CMD_START}」或「牛牛开始」开局。"
                ),
            },
            {
                "func": f"{CMD_JOIN} / {CMD_QUIT}",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": f"{CMD_JOIN} / {CMD_QUIT}",
                "command_permission": "who_is_spy.join",
                "brief_des": "加入或退出筹备中的房间",
                "detail_des": (
                    "仅筹备阶段可用；词牌发出后不可再加入或退出（除被投票出局）。"
                    f"房主不可「{CMD_QUIT}」，须用「{CMD_END}」结束。"
                ),
            },
            {
                "func": CMD_START,
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": f"{CMD_START} / 牛牛开始 [潜藏人数]",
                "command_permission": "who_is_spy.start",
                "brief_des": "房主发词牌并开始",
                "detail_des": (
                    "须为房主且人数达本局下限。词牌私聊发送（好友优先，否则临时会话或邮箱）。"
                    "开局后会 @ 第一位玩家；按名册顺序轮流 @牛牛 述词，群内可自由聊天。"
                    "全员述毕后私聊投票；票型公布含弃权数。卧底尽退则平民胜，存活卧底不少于平民则卧底胜。"
                ),
            },
            {
                "func": "述词",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "述词阶段按顺序 @牛牛",
                "brief_des": "轮到顺序时 @牛牛 述词",
                "detail_des": (
                    "仅 @牛牛 的消息计入述词，须轮到你的顺序；普通群聊不计入。"
                    "牛牛会 @ 下一位提醒。每人每轮一次，不可重复述词。"
                ),
            },
            {
                "func": CMD_STATUS,
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": CMD_STATUS,
                "command_permission": "who_is_spy.status",
                "brief_des": "察看局势与序次",
                "detail_des": (
                    "显示轮次、在场人数与带序次的名单。"
                    "述词阶段提示按顺序 @牛牛；投票阶段提示私聊数字与 0 弃权。"
                ),
            },
            {
                "func": CMD_END,
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": CMD_END,
                "command_permission": "who_is_spy.end",
                "brief_des": "结束房间",
                "detail_des": (
                    f"房主或群管可发「{CMD_END}」结束对局或清理占位房间。"
                    "空房间一段时间后会自动清理。"
                ),
            },
            {
                "func": "私聊投票",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_PRIVATE,
                "trigger_condition": "投票阶段私聊回复数字序次（0=弃权）",
                "brief_des": "匿名投票",
                "detail_des": (
                    f"述词结束后牛牛私聊序次列表；回复数字投对应玩家，0 为弃权。"
                    f"全员投毕后群内公布票型（含弃权）。序次见「{CMD_STATUS}」。"
                ),
            },
        ],
    },
)
