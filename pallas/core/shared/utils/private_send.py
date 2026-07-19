"""群临时会话私聊发送：SnowLuma / NapCat sub_type=group 需带 group_id。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pallas.core.shared.utils.group_temp_context import resolve_inferred_group_id

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Bot
    from nonebot.adapters.onebot.v11.event import Event
    from nonebot.adapters.onebot.v11.message import Message, MessageSegment


def is_group_temp_private_event(event: object) -> bool:
    if getattr(event, "message_type", None) != "private":
        return False
    return getattr(event, "sub_type", None) == "group"


def event_declared_group_id(event: object) -> int | None:
    raw = getattr(event, "group_id", None)
    try:
        gid = int(raw) if raw is not None else 0
    except (TypeError, ValueError):
        gid = 0
    if gid > 0:
        return gid
    sender = getattr(event, "sender", None)
    if sender is None:
        return None
    sraw = getattr(sender, "group_id", None)
    if sraw is None and isinstance(sender, dict):
        sraw = sender.get("group_id")
    try:
        sgid = int(sraw) if sraw is not None else 0
    except (TypeError, ValueError):
        sgid = 0
    return sgid if sgid > 0 else None


def group_temp_private_group_id(event: object) -> int | None:
    if not is_group_temp_private_event(event):
        return None
    gid = event_declared_group_id(event)
    if gid is not None:
        return gid
    uid = getattr(event, "user_id", None)
    sid = getattr(event, "self_id", None)
    if uid is None or sid is None:
        return None
    return resolve_inferred_group_id(str(sid), str(uid))


async def send_private_msg_compat(
    bot: Bot,
    user_id: int,
    message: str | Message | MessageSegment,
    *,
    group_id: int | None = None,
    event: Event | None = None,
) -> Any:
    gid = group_id if group_id is not None else group_temp_private_group_id(event)
    payload: dict[str, Any] = {"user_id": int(user_id), "message": message}
    if gid is not None and int(gid) > 0:
        payload["group_id"] = int(gid)
    return await bot.call_api("send_private_msg", **payload)


async def reply_private_message(
    bot: Bot,
    event: Event,
    message: str | Message | MessageSegment,
) -> Any:
    gid = group_temp_private_group_id(event)
    if gid is not None:
        return await send_private_msg_compat(
            bot,
            int(event.user_id),
            message,
            group_id=gid,
        )
    return await bot.send(event, message)
