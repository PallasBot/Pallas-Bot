"""OneBot V11 协议扩展事件。"""

from __future__ import annotations

from typing import Any, Literal, override

from nonebot import get_driver
from nonebot.adapters.onebot.v11 import Event  # noqa: TC002 — preprocessor 运行时解析注解需要
from nonebot.adapters.onebot.v11.event import GroupMessageEvent, NoticeEvent, PrivateMessageEvent
from nonebot.compat import model_dump, model_validator
from nonebot.message import event_preprocessor

from pallas.core.shared.utils.group_temp_context import record_user_group_activity
from pallas.core.shared.utils.private_send import (
    group_temp_private_group_id,
    is_group_temp_private_event,
    send_private_msg_compat,
)


class GroupTempPrivateMessageEvent(PrivateMessageEvent):
    """群临时会话私聊：sub_type=group；group_id 可为 0（SnowLuma 常不上报）。"""

    sub_type: Literal["group"]
    group_id: int = 0


class ProfileLikeNotifyEvent(NoticeEvent):
    """名片赞提醒：NapCat 仅上报 operator_id，无 user_id / group_id。"""

    notice_type: Literal["notify"]
    sub_type: Literal["profile_like"]
    operator_id: int
    operator_nick: str = ""
    times: int = 1
    user_id: int = 0
    group_id: int = 0

    @model_validator(mode="before")
    @classmethod
    def fill_compat_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        if out.get("user_id") is None and out.get("operator_id") is not None:
            out["user_id"] = out["operator_id"]
        if out.get("group_id") is None:
            out["group_id"] = 0
        return out

    @override
    def get_user_id(self) -> str:
        return str(self.operator_id)

    @override
    def get_session_id(self) -> str:
        return str(self.operator_id)


_hooks_installed = False


def install_group_temp_private_hooks() -> None:
    global _hooks_installed
    if _hooks_installed:
        return
    _hooks_installed = True

    from nonebot.adapters.onebot.v11 import Bot
    from nonebot.adapters.onebot.v11 import bot as ob_bot
    from nonebot.adapters.onebot.v11.message import Message, MessageSegment

    original_send = ob_bot.send

    async def patched_send(
        bot: Bot,
        event: Event,
        message: str | Message | MessageSegment,
        at_sender: bool = False,
        reply_message: bool = False,
        **params: Any,
    ) -> Any:
        gid = group_temp_private_group_id(event)
        if gid is not None:
            event_dict = model_dump(event)
            user_id = event_dict.get("user_id")
            if user_id is not None:
                full_message: str | Message | MessageSegment = message
                if reply_message and event_dict.get("message_id") is not None:
                    full_message = Message()
                    full_message += MessageSegment.reply(event_dict["message_id"])
                    full_message += message
                return await send_private_msg_compat(
                    bot,
                    int(user_id),
                    full_message,
                    group_id=gid,
                )
        return await original_send(
            bot,
            event,
            message,
            at_sender=at_sender,
            reply_message=reply_message,
            **params,
        )

    ob_bot.send = patched_send

    @event_preprocessor
    async def track_group_temp_private_context(event: Event) -> None:
        if isinstance(event, GroupMessageEvent):
            record_user_group_activity(
                str(event.self_id),
                str(event.user_id),
                int(event.group_id),
            )
            return
        if is_group_temp_private_event(event):
            gid = group_temp_private_group_id(event)
            if gid is not None:
                object.__setattr__(event, "group_id", int(gid))
                record_user_group_activity(
                    str(event.self_id),
                    str(event.user_id),
                    int(gid),
                )


def register_onebot_v11_custom_events() -> None:
    from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter

    OneBotV11Adapter.add_custom_model(GroupTempPrivateMessageEvent, ProfileLikeNotifyEvent)
    install_group_temp_private_hooks()
    # 确保 driver 已创建后再挂 preprocessor（boot 在 nonebot.init 之后调用本函数）
    get_driver()
