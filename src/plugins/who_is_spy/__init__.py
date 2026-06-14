from nonebot.plugin import PluginMetadata

from src.features.cmd_perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)
from src.features.cmd_perm.metadata_text import SCENE_GROUP, SCENE_PRIVATE, join_usage, usage_line

from .commands import CMD_END, CMD_JOIN, CMD_OPEN, CMD_QUIT, CMD_START, CMD_STATUS, CMD_VOTE, SPY_GROUP_COMMAND_PREFIXES
from .config import Config
from .store import init_store

init_store()

from . import handlers as _handlers  # noqa: E402, F401

__plugin_meta__ = PluginMetadata(
    name="牛牛卧底",
    description=("谁是卧底：房主开房、玩家 @牛牛 述词，全员述完自动或房主发起私聊投票，直至平民或卧底一方获胜。"),
    usage=join_usage(
        usage_line(CMD_OPEN, "房主开房间"),
        usage_line("牛牛谁是卧底", "同「牛牛卧底」"),
        usage_line(f"{CMD_JOIN} / {CMD_QUIT}", "加入或退出筹备中的房间"),
        usage_line(f"{CMD_START} / 牛牛开始 [潜藏人数] [白板] [暗牌|明牌]", "房主发词牌并开始"),
        usage_line("@牛牛 + 描述", "讨论阶段记为述词"),
        usage_line(CMD_VOTE, "房主提前开始投票"),
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
            {"id": "who_is_spy.start", "label": f"{CMD_START}/{CMD_VOTE}", "default": "everyone"},
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
                    f"「{CMD_QUIT}」退出。至少满下限人数（默认 4 人）后，房主发「{CMD_START}」或「牛牛开始」开局。"
                    f"示例：①「{CMD_OPEN}」开房 ②「{CMD_JOIN}」加入 ③满员后「{CMD_START}」发词。"
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
                "trigger_condition": f"{CMD_START} / 牛牛开始 [潜藏人数] [白板] [暗牌|明牌]",
                "command_permission": "who_is_spy.start",
                "brief_des": "房主发词牌并开始",
                "detail_des": (
                    "须为房主且人数达本局下限。词牌私聊发送（好友优先，否则临时会话或邮箱）。"
                    "每人都会收到词库词语，或白板身份（无词、不计入平民/卧底胜负计数）。"
                    "私聊默认暗牌（例：「你的词：可乐」）；白板例：「你没有词语（白板）」；明牌会附带身份。"
                    "WebUI 可设默认白板数；本局口令可加「白板」「白板2」「无白板」，以及「暗牌」「明牌」。"
                    "示例：①「牛牛发身份」②「牛牛发身份 2 白板」③「牛牛发身份 明牌」④「牛牛开始 1 白板 暗牌」。"
                    "若私聊只见「你的词：」后没有字，是消息未送达，请加好友或查 QQ 邮箱。"
                    "开局后 @牛牛 发描述记为述词；默认全员述完后自动投票并先发复盘，也可房主发「牛牛投票」提前开投。"
                    "卧底尽退则平民胜，存活卧底不少于平民则卧底胜（白板不计入该比较）。"
                ),
            },
            {
                "func": "@牛牛 述词",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "讨论阶段 @牛牛 并附带描述文本",
                "brief_des": "记为本轮正式述词",
                "detail_des": (
                    "仅讨论阶段、在场玩家可用；每人每轮一次，@牛牛 后须有描述正文。"
                    "全员 @牛牛 述词后默认自动进入私聊投票，并在群内先发本轮述词复盘。"
                    "示例：「@牛牛 是一种红色的水果」；未 @ 的普通聊天不会记入复盘。"
                    "WebUI 可关闭自动投票；关闭后须房主发「牛牛投票」。"
                ),
            },
            {
                "func": CMD_VOTE,
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": CMD_VOTE,
                "command_permission": "who_is_spy.start",
                "brief_des": "房主提前开始投票",
                "detail_des": (
                    "讨论阶段由房主发「牛牛投票」可提前开投；若已有 @牛牛 述词会先公布复盘。"
                    "牛牛私聊序次列表，全员投毕后群内公布票型。"
                    "全员弃权或最高票相同时重新 @牛牛 述词，再由房主发「牛牛投票」。"
                    "示例：讨论中途发「牛牛投票」；私聊收到列表后回复「2」投 2 号，「0」弃权。"
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
                    "显示轮次、在场人数与带序次的名单。讨论阶段提示 @牛牛 述词；投票阶段提示私聊数字与 0 弃权。"
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
                    f"房主或群管可发「{CMD_END}」结束对局或清理占位房间。已开局的局会公布本局词对；"
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
                    f"房主发「{CMD_VOTE}」后牛牛私聊序次列表；回复数字投对应玩家，0 为弃权。"
                    f"全员投毕后群内公布票型（含弃权）。序次见「{CMD_STATUS}」。"
                    "示例：列表为「1. 甲 2. 乙」时，私聊「1」投甲，「0」弃权。"
                ),
            },
        ],
    },
)
