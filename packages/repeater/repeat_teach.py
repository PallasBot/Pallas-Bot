"""强制复读教学：连续相同消息达到 repeat_threshold 时视为显式教牛说话。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .config import get_repeater_config

if TYPE_CHECKING:
    from pallas.core.foundation.db import Message as MessageModel

    from .model import ChatData


def repeat_ignore_user_ids() -> set[int]:
    from .responder import Responder

    return Responder._repeat_ignore_user_ids()


def human_messages_for_repeat(group_msgs: list[MessageModel]) -> list[MessageModel]:
    ignore = repeat_ignore_user_ids()
    return [m for m in group_msgs if getattr(m, "user_id", None) not in ignore]


def is_forced_repeat_teaching(
    chat_data: ChatData,
    prior_group_msgs: list[MessageModel],
    *,
    repeat_threshold: int | None = None,
) -> bool:
    """当前句与前序人类消息已连续相同，达到跟复读阈值（默认 3 连）。"""
    rt = int(repeat_threshold if repeat_threshold is not None else get_repeater_config().repeat_threshold)
    if rt < 2:
        return False
    if chat_data.user_id in repeat_ignore_user_ids():
        return False
    raw_message = chat_data.raw_message
    if not raw_message.strip():
        return False
    human_msgs = human_messages_for_repeat(prior_group_msgs)
    tail = rt - 1
    if len(human_msgs) < tail:
        return False
    return all(item.raw_message == raw_message for item in human_msgs[-tail:])
