"""Learner 上下文：内存近期链不足时从 DB 补齐。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pallas.core.foundation.db import Message as MessageModel

    from .model import ChatData

_GROUP_TAIL_LIMIT = 8


async def group_messages_before(chat_data: ChatData) -> list[MessageModel]:
    from .message_store import MessageStore

    group_id = int(chat_data.group_id)
    before_time = int(chat_data.time)
    mem = [m for m in MessageStore._message_dict.get(group_id, []) if int(m.time) < before_time]
    if mem:
        return mem[-_GROUP_TAIL_LIMIT:]
    return []


async def user_message_before_in_group(chat_data: ChatData, group_msgs: list[MessageModel]) -> MessageModel | None:
    user_id = int(chat_data.user_id)
    for msg in group_msgs[:-3:-1]:
        if int(msg.user_id) == user_id:
            return msg
    return None
