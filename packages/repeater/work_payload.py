"""复读学习在消息进程与 work aux 之间传递的数据。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_CHAT_FIELDS = ("group_id", "user_id", "bot_id", "raw_message", "plain_text", "time")
_MESSAGE_FIELDS = (*_CHAT_FIELDS, "is_plain_text", "keywords")


def normalize_work_text(value: object) -> str:
    return str(value).replace("\x00", "")


def chat_data_to_dict(chat_data: Any) -> dict[str, int | str | None]:
    return {
        "group_id": int(chat_data.group_id),
        "user_id": int(chat_data.user_id),
        "bot_id": int(chat_data.bot_id),
        "raw_message": normalize_work_text(chat_data.raw_message),
        "plain_text": normalize_work_text(chat_data.plain_text),
        "sender_name": normalize_work_text(getattr(chat_data, "sender_name", "")),
        "message_id": getattr(chat_data, "message_id", None),
        "reply_to_message_id": getattr(chat_data, "reply_to_message_id", None),
        "suppressed_by_rage": bool(getattr(chat_data, "suppressed_by_rage", False)),
        "time": int(chat_data.time),
    }


def chat_data_to_message_dict(chat_data: Any) -> dict[str, int | str | bool | None]:
    """序列化 ChatData 供独立 message 落库 job 使用（含 message 表所需全部字段）。"""
    return {
        "group_id": int(chat_data.group_id),
        "user_id": int(chat_data.user_id),
        "bot_id": int(chat_data.bot_id),
        "raw_message": normalize_work_text(chat_data.raw_message),
        "plain_text": normalize_work_text(chat_data.plain_text),
        "time": int(chat_data.time),
        "is_plain_text": bool(chat_data.is_plain_text),
        "keywords": normalize_work_text(chat_data.keywords),
        "sender_name": normalize_work_text(getattr(chat_data, "sender_name", "")),
        "message_id": getattr(chat_data, "message_id", None),
        "reply_to_message_id": getattr(chat_data, "reply_to_message_id", None),
    }


def message_to_dict(message: Any) -> dict[str, int | str | bool | None]:
    return {
        "group_id": int(message.group_id),
        "user_id": int(message.user_id),
        "bot_id": int(message.bot_id),
        "raw_message": normalize_work_text(message.raw_message),
        "plain_text": normalize_work_text(message.plain_text),
        "time": int(message.time),
        "is_plain_text": bool(message.is_plain_text),
        "keywords": normalize_work_text(message.keywords),
        "sender_name": normalize_work_text(getattr(message, "sender_name", "")),
        "message_id": getattr(message, "message_id", None),
        "reply_to_message_id": getattr(message, "reply_to_message_id", None),
    }


@dataclass(frozen=True, slots=True)
class RepeaterLearnPayload:
    chat: dict[str, int | str | None]
    predecessor: dict[str, int | str | bool | None] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "chat": dict(self.chat),
            "predecessor": dict(self.predecessor) if self.predecessor is not None else None,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> RepeaterLearnPayload:
        chat = value.get("chat")
        if not isinstance(chat, dict) or any(field not in chat for field in _CHAT_FIELDS):
            raise ValueError("invalid repeater learn chat payload")
        predecessor = value.get("predecessor")
        if predecessor is not None and (
            not isinstance(predecessor, dict) or any(field not in predecessor for field in _MESSAGE_FIELDS)
        ):
            raise ValueError("invalid repeater learn predecessor payload")
        return cls(chat=dict(chat), predecessor=dict(predecessor) if predecessor is not None else None)
