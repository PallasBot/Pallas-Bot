from __future__ import annotations

from typing import Literal

LIST_FRIEND_COMMAND = "查看好友申请"
LIST_FRIEND_ALIASES = ("查看好友请求",)
LIST_GROUP_COMMAND = "查看入群申请"
LIST_GROUP_ALIASES = ("查看入群邀请",)

APPROVE_LATEST_COMMAND = "同意"
REJECT_LATEST_COMMAND = "拒绝"
APPROVE_FRIEND_COMMAND = "同意好友"
REJECT_FRIEND_COMMAND = "拒绝好友"
APPROVE_ALL_FRIENDS_COMMAND = "同意所有好友"
REJECT_ALL_FRIENDS_COMMAND = "拒绝所有好友"
APPROVE_GROUP_COMMAND = "同意入群"
REJECT_GROUP_COMMAND = "拒绝入群"
APPROVE_ALL_GROUPS_COMMAND = "同意所有入群"
REJECT_ALL_GROUPS_COMMAND = "拒绝所有入群"
APPROVE_ALL_GROUPS_ALIASES = ("同意所有入群申请", "同意所有入群邀请")
REJECT_ALL_GROUPS_ALIASES = ("拒绝所有入群申请", "拒绝所有入群邀请")
AUTO_ACCEPT_STATUS_COMMAND = "查看自动同意"
AUTO_ACCEPT_STATUS_ALIASES = ("查看自动同意状态", "自动同意状态")
ENABLE_AUTO_FRIEND_COMMAND = "开启自动同意好友"
DISABLE_AUTO_FRIEND_COMMAND = "关闭自动同意好友"
ENABLE_AUTO_GROUP_COMMAND = "开启自动同意入群"
DISABLE_AUTO_GROUP_COMMAND = "关闭自动同意入群"

REQUEST_HANDLER_HELP_CMD = "牛牛帮助 申请管理"
REQUEST_HANDLER_HELP_HINT = f"帮助：{REQUEST_HANDLER_HELP_CMD}"
QUICK_APPROVE_ACTIONS = (APPROVE_LATEST_COMMAND, REJECT_LATEST_COMMAND)

REQUEST_HANDLER_USAGE_LINES = (
    f"{LIST_FRIEND_COMMAND} / {LIST_GROUP_COMMAND} — 查看当前待处理申请",
    f"{APPROVE_LATEST_COMMAND} / {REJECT_LATEST_COMMAND} — 处理最新提醒，或引用某条提醒后只处理该条",
    f"{APPROVE_FRIEND_COMMAND} / {REJECT_FRIEND_COMMAND} 〈QQ号〉；"
    f"{APPROVE_GROUP_COMMAND} / {REJECT_GROUP_COMMAND} 〈群号〉 — 按号码处理单条申请",
    f"{APPROVE_ALL_FRIENDS_COMMAND} / {REJECT_ALL_FRIENDS_COMMAND}；"
    f"{APPROVE_ALL_GROUPS_COMMAND} / {REJECT_ALL_GROUPS_COMMAND} — 批量处理当前列表",
    f"{AUTO_ACCEPT_STATUS_COMMAND}；开启 / 关闭自动同意好友；开启 / 关闭自动同意入群 — 查看或切换自动同意",
)


def build_list_tail(kind: Literal["friend", "group"]) -> str:
    if kind == "friend":
        return (
            "可直接继续：\n"
            f"• 先发「{LIST_FRIEND_COMMAND}」重新查看当前列表；\n"
            f"• 发送「{APPROVE_LATEST_COMMAND}」/「{REJECT_LATEST_COMMAND}」处理最新提醒；\n"
            f"• 引用某条审批提醒后再发「{APPROVE_LATEST_COMMAND}」或「{REJECT_LATEST_COMMAND}」，只处理该条；\n"
            f"• 发送「{APPROVE_FRIEND_COMMAND} <QQ号>」或「{REJECT_FRIEND_COMMAND} <QQ号>」处理指定好友申请；\n"
            f"• 发送「{APPROVE_ALL_FRIENDS_COMMAND}」或「{REJECT_ALL_FRIENDS_COMMAND}」批量处理当前好友申请；\n"
            f"• 更多说明见「{REQUEST_HANDLER_HELP_CMD}」。"
        )
    return (
        "可直接继续：\n"
        f"• 先发「{LIST_GROUP_COMMAND}」重新查看当前列表；\n"
        f"• 发送「{APPROVE_LATEST_COMMAND}」/「{REJECT_LATEST_COMMAND}」处理最新提醒；\n"
        f"• 引用某条审批提醒后再发「{APPROVE_LATEST_COMMAND}」或「{REJECT_LATEST_COMMAND}」，只处理该条；\n"
        f"• 发送「{APPROVE_GROUP_COMMAND} <群号>」或「{REJECT_GROUP_COMMAND} <群号>」处理指定入群申请；\n"
        f"• 发送「{APPROVE_ALL_GROUPS_COMMAND}」或「{REJECT_ALL_GROUPS_COMMAND}」批量处理当前入群申请；\n"
        f"• 更多说明见「{REQUEST_HANDLER_HELP_CMD}」。"
    )


def build_quick_action_arg_hint(action: str) -> str:
    return (
        f"单独发送「{action}」时不要跟其它内容；"
        f"带 QQ 号请用「{action}好友 <QQ号>」，带群号请用「{action}入群 <群号>」。"
        f"若要处理较早一条提醒，请引用那条提醒后再发送「{action}」。"
    )


def build_quick_action_missing_hint(action: str) -> str:
    return (
        "没有可直接处理的最新申请提醒；"
        f"请先发送「{LIST_FRIEND_COMMAND}」或「{LIST_GROUP_COMMAND}」，"
        f"或直接使用「{action}好友 <QQ号>」「{action}入群 <群号>」处理指定申请。"
    )
