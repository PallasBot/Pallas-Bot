"""「不可以」禁用与撤回联动。"""

# ruff: noqa: TC002

from __future__ import annotations

import re

from nonebot import logger, on_message, on_notice
from nonebot.adapters import Bot  # noqa: TC002
from nonebot.adapters.onebot.v11 import GroupMessageEvent, GroupRecallNoticeEvent, Message
from nonebot.exception import ActionFailed
from nonebot.rule import Rule
from nonebot.typing import T_State  # noqa: TC002

from pallas.api.logging import format_plugin_event
from pallas.api.perm import group_message_permission_for_command
from pallas.core.foundation.logging.bridge import format_business_event
from pallas.core.shared.dream_ban_ack_state import DREAM_BAN_ACK_SENT_STATE_KEY
from pallas.core.shared.reply_command_rule import (
    event_has_reply_target,
    event_targets_self,
    extract_reply_id_from_raw_message,
)
from pallas.core.shared.utils.array2cqcode import try_convert_to_cqcode

from ..ban_state import REPEATER_BAN_ACK_SENT_STATE_KEY
from ..model import Chat

_CQ_URL_STRIP_RE = re.compile(r"(\[CQ\:.+)(?:,url=*)(\])")
_RECALL_TOKEN_RE = re.compile(r"\[[^\]]*\]|\w+")
_BAN_ACK_TEXT = "这对角可能会不小心撞倒些家具，我会尽量小心。"


async def finish_ban_ack(finish, event: GroupMessageEvent | GroupRecallNoticeEvent) -> None:
    """回执发送失败（如 QQ result=120）不影响已完成的 ban。"""
    try:
        await finish(_BAN_ACK_TEXT)
    except ActionFailed as e:
        logger.warning(
            "bot [{}] ban ack send failed group [{}]: {}",
            event.self_id,
            event.group_id,
            e,
        )


def normalize_cq_ban_token(token: str) -> str:
    return _CQ_URL_STRIP_RE.sub(r"\1\2", str(token))


def extract_ban_reply_raw_from_message(message: Message | str) -> str:
    if isinstance(message, str):
        return message

    raw_message = "".join(normalize_cq_ban_token(str(item)) for item in message)
    if not raw_message.strip():
        raw_message = message.extract_plain_text()
    return raw_message


def ban_raw_from_recalled_api_payload(message_payload: str) -> str:
    return "".join(
        normalize_cq_ban_token(item) for item in _RECALL_TOKEN_RE.findall(try_convert_to_cqcode(message_payload))
    )


async def resolve_ban_reply_raw(bot: Bot, event: GroupMessageEvent) -> str:
    if event.reply and getattr(event.reply, "message", None):
        return extract_ban_reply_raw_from_message(event.reply.message)

    reply_id = extract_reply_id_from_raw_message(event.raw_message)
    if reply_id is None:
        return ""

    try:
        msg = await bot.get_msg(message_id=reply_id)
    except ActionFailed:
        logger.warning(
            format_business_event("禁言目标读取", "失败", bot=event.self_id, group=event.group_id, message_id=reply_id)
        )
        return ""

    return extract_ban_reply_raw_from_message(Message(msg["message"]))


async def is_reply(event: GroupMessageEvent) -> bool:
    return event_has_reply_target(event)


async def is_ban_reply_trigger(event: GroupMessageEvent) -> bool:
    if "不可以" not in event.get_plaintext():
        return False
    if not await is_reply(event):
        return False
    return event_targets_self(event)


async def is_admin_recall_self_msg(bot: Bot, event: GroupRecallNoticeEvent):
    self_id = event.self_id
    user_id = event.user_id
    group_id = event.group_id
    operator_id = event.operator_id
    if self_id != user_id:
        return False
    if operator_id == self_id:
        return False
    operator_info = await bot.get_group_member_info(group_id=group_id, user_id=operator_id)
    return operator_info["role"] == "owner" or operator_info["role"] == "admin"


async def message_is_ban(bot: Bot, event: GroupMessageEvent, state: T_State) -> bool:
    return event.get_plaintext().strip() == "不可以发这个"


async def is_ban_latest_trigger(bot: Bot, event: GroupMessageEvent, state: T_State) -> bool:
    if not await message_is_ban(bot, event, state):
        return False
    return event_targets_self(event)


ban_msg = on_message(
    rule=Rule(is_ban_reply_trigger),
    priority=5,
    block=True,
    permission=group_message_permission_for_command("repeater.ban"),
)

ban_recalled_msg = on_notice(
    rule=Rule(is_admin_recall_self_msg),
    priority=5,
    block=True,
)

ban_msg_latest = on_message(
    rule=Rule(is_ban_latest_trigger),
    priority=5,
    block=True,
    permission=group_message_permission_for_command("repeater.ban_latest"),
)


@ban_msg.handle()
async def handle_ban_reply(bot: Bot, event: GroupMessageEvent, state: T_State):
    raw_message = await resolve_ban_reply_raw(bot, event)
    if not raw_message.strip():
        logger.debug(
            format_business_event("复读禁言", "已跳过", bot=event.self_id, group=event.group_id, reason="empty_target")
        )
        return

    logger.debug(
        format_business_event(
            "复读禁言", "已准备", bot=event.self_id, group=event.group_id, content_len=len(raw_message)
        )
    )

    if event.reply:
        try:
            await bot.delete_msg(message_id=event.reply.message_id)  # type: ignore
        except ActionFailed:
            logger.warning(
                format_business_event(
                    "禁言目标撤回", "失败", bot=event.self_id, group=event.group_id, content_len=len(raw_message)
                )
            )

    banned = await Chat.ban(event.group_id, event.self_id, raw_message, str(event.user_id))
    if banned:
        logger.info(
            format_plugin_event(
                "ban",
                f"Bot [{event.self_id}] banned a repeater reply in group [{event.group_id}] "
                f"at user [{event.user_id}]'s request",
            )
        )
        if not state.get(DREAM_BAN_ACK_SENT_STATE_KEY):
            state[REPEATER_BAN_ACK_SENT_STATE_KEY] = True
            await finish_ban_ack(ban_msg.finish, event)
    else:
        logger.debug(
            format_business_event("复读禁言", "未命中", bot=event.self_id, group=event.group_id, user=event.user_id)
        )


@ban_recalled_msg.handle()
async def handle_ban_recalled(bot: Bot, event: GroupRecallNoticeEvent, state: T_State):
    try:
        msg = await bot.get_msg(message_id=event.message_id)
    except ActionFailed:
        logger.warning(
            "[Repeater] Failed to read mute target for bot [{}] and message [{}]", event.self_id, event.message_id
        )
        return

    raw_message = ban_raw_from_recalled_api_payload(msg["message"])

    logger.debug(
        format_business_event(
            "复读禁言", "已准备", bot=event.self_id, group=event.group_id, content_len=len(raw_message)
        )
    )

    banned = await Chat.ban(event.group_id, event.self_id, raw_message, str(f"recall by {event.operator_id}"))
    if banned:
        logger.info(
            format_plugin_event(
                "ban",
                f"Bot [{event.self_id}] banned a recalled repeater reply in group [{event.group_id}] "
                f"at operator [{event.operator_id}]'s request",
            )
        )
        if not state.get(DREAM_BAN_ACK_SENT_STATE_KEY):
            state[REPEATER_BAN_ACK_SENT_STATE_KEY] = True
            await finish_ban_ack(ban_recalled_msg.finish, event)
    elif not state.get(DREAM_BAN_ACK_SENT_STATE_KEY):
        pass


@ban_msg_latest.handle()
async def handle_ban_latest(bot: Bot, event: GroupMessageEvent, state: T_State):
    logger.debug(
        format_business_event("复读禁言", "已准备", bot=event.self_id, group=event.group_id, target="latest_reply")
    )

    try:
        await bot.delete_msg(message_id=event.reply.message_id)  # type: ignore
    except ActionFailed:
        logger.warning(
            "[Repeater] Failed to recall mute target for bot [{}] in group [{}]", event.self_id, event.group_id
        )

    if await Chat.ban(event.group_id, event.self_id, "", str(event.user_id)):
        logger.info(
            format_plugin_event(
                "ban",
                f"Bot [{event.self_id}] banned its latest repeater reply in group [{event.group_id}] "
                f"at user [{event.user_id}]'s request",
            )
        )
        await finish_ban_ack(ban_msg_latest.finish, event)
