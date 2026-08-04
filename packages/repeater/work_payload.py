"""复读学习在消息进程与 work aux 之间传递的数据。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_CHAT_FIELDS = ("group_id", "user_id", "bot_id", "raw_message", "plain_text", "time")
_MESSAGE_FIELDS = (*_CHAT_FIELDS, "is_plain_text", "keywords")


def chat_data_to_dict(chat_data: Any) -> dict[str, int | str]:
    return {
        "group_id": int(chat_data.group_id),
        "user_id": int(chat_data.user_id),
        "bot_id": int(chat_data.bot_id),
        "raw_message": str(chat_data.raw_message),
        "plain_text": str(chat_data.plain_text),
        "time": int(chat_data.time),
    }


def message_to_dict(message: Any) -> dict[str, int | str | bool]:
    return {
        "group_id": int(message.group_id),
        "user_id": int(message.user_id),
        "bot_id": int(message.bot_id),
        "raw_message": str(message.raw_message),
        "plain_text": str(message.plain_text),
        "time": int(message.time),
        "is_plain_text": bool(message.is_plain_text),
        "keywords": str(message.keywords),
    }


@dataclass(frozen=True, slots=True)
class RepeaterLearnPayload:
    chat: dict[str, int | str]
    predecessor: dict[str, int | str | bool] | None

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
