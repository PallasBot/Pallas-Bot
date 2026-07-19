from __future__ import annotations

import json
from typing import TYPE_CHECKING

from nonebot.exception import IgnoredException

from pallas.core.platform.ingress.claim_gate import ingress_gate_runtime_active
from pallas.core.platform.multi_bot.dedup import (
    normalize_message_time,
    try_claim_group_message_once,
)

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Bot, NoticeEvent

INGRESS_NOTICE_PLUGIN = "ingress_notice"

_DISCARD_NOTICE_TYPES = frozenset({"group_msg_emoji_like"})
_ONCE_NOTICE_TYPES = frozenset({"group_recall"})


def notice_once_body(event: NoticeEvent) -> str | None:
    notice_type = getattr(event, "notice_type", None)
    if notice_type in _DISCARD_NOTICE_TYPES:
        return str(notice_type)
    if notice_type not in _ONCE_NOTICE_TYPES:
        return None
    if notice_type == "group_recall":
        operator_id = int(getattr(event, "operator_id", 0) or 0)
        user_id = int(getattr(event, "user_id", 0) or 0)
        return f"group_recall:{operator_id}:{user_id}"
    return notice_type


def notice_once_group_id(event: NoticeEvent) -> int:
    return int(getattr(event, "group_id", 0) or 0)


def notice_once_user_id(event: NoticeEvent) -> int:
    return int(getattr(event, "user_id", 0) or 0)


async def ingress_notice_gate(bot: Bot, event: NoticeEvent) -> None:
    if not ingress_gate_runtime_active():
        return
    if getattr(event, "post_type", None) != "notice":
        return

    notice_type = getattr(event, "notice_type", None)
    if notice_type in _DISCARD_NOTICE_TYPES:
        raise IgnoredException("ingress notice discard")

    if notice_type == "notify" and getattr(event, "sub_type", None) == "poke":
        target_id = int(getattr(event, "target_id", 0) or 0)
        if target_id != int(bot.self_id):
            raise IgnoredException("poke not for this bot")
        return

    body = notice_once_body(event)
    if body is None:
        return

    group_id = notice_once_group_id(event)
    user_id = notice_once_user_id(event)
    message_time = normalize_message_time(int(getattr(event, "time", 0) or 0))
    if not await try_claim_group_message_once(
        INGRESS_NOTICE_PLUGIN,
        group_id,
        user_id,
        body,
        message_time,
        use_plaintext=False,
        include_message_time=True,
    ):
        raise IgnoredException("ingress notice once claim lost")


def notice_gate_debug_payload(event: NoticeEvent) -> str:
    data = {
        "notice_type": getattr(event, "notice_type", None),
        "sub_type": getattr(event, "sub_type", None),
        "group_id": getattr(event, "group_id", None),
        "user_id": getattr(event, "user_id", None),
    }
    return json.dumps(data, ensure_ascii=False, sort_keys=True)
