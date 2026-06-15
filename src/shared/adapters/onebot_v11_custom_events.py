"""OneBot V11 协议扩展事件。"""

from __future__ import annotations

from typing import Any, Literal, override

from nonebot.adapters.onebot.v11.event import NoticeEvent
from nonebot.compat import model_validator


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


def register_onebot_v11_custom_events() -> None:
    from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter

    OneBotV11Adapter.add_custom_model(ProfileLikeNotifyEvent)
